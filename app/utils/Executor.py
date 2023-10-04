# coding=utf-8

import shlex
import shutil
import subprocess
import threading
from threading import Timer, Thread
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Union
import psutil
from app.models import Patch, Run, Project
import tempfile
import os
import datetime
from app import db
from pathlib import Path


class _RaiiTempDir:
    def __init__(self, prefix="mutate_cpp"):
        self.path = Path(tempfile.mkdtemp(prefix=prefix))

    def __del__(self):
        shutil.rmtree(self.path)


class _ThreadLocal:
    workspace: _RaiiTempDir
    last_project_id: Optional[int]


_thread_local: Union[_ThreadLocal, threading.local] = threading.local()


def _thread_initializer():
    _thread_local.workspace = _RaiiTempDir()
    _thread_local.last_project_id = None


class _ProjectRecord:
    def __init__(self, project: Project):
        self.workdir = project.workdir
        self.quickcheck_timeout = project.quickcheck_timeout
        self.quickcheck_command = project.quickcheck_command
        self.test_timeout = project.test_timeout
        self.test_command = project.test_command
        self.build_command = project.build_command
        self.clean_command = project.clean_command


class _PatchRecord:
    def __init__(self, patch: Patch):
        self.id = patch.id
        self.state = patch.state
        self.file_id = patch.file_id
        self.file_filename = patch.file.filename
        self.project_id = patch.project_id
        self.project = _ProjectRecord(patch.project)
        self.patch = patch.patch


class _RunRecord:
    def __init__(self):
        self.command = None
        self.patch_id = None
        self.project_id = None
        self.timestamp_start = None
        self.output = None
        self.timestamp_end = None
        self.duration = None
        self.log = None
        self.success = None

    def model(self):
        m = Run()
        m.command = self.command
        m.patch_id = self.patch_id
        m.project_id = self.project_id
        m.timestamp_start = self.timestamp_start
        m.output = self.output
        m.timestamp_end = self.timestamp_end
        m.duration = self.duration
        m.log = self.log
        m.success = self.success
        return m


class _ExecutionResult:
    def __init__(self, patch_id: int):
        self.patch_id: int = patch_id
        self.run_records: list[_RunRecord] = []
        self.state: str = "incomplete"


class Executor:
    def __init__(self, app):
        self.running = False
        self.app = app

    def start(self):
        if self.running is False:
            self.running = True
            Thread(target=self.main).start()

    def stop(self):
        self.running = False

    @property
    def count(self):
        return Patch.query.filter(Patch.state == 'incomplete').count()

    def main(self):
        with self.app.app_context():
            while self.running:
                with ThreadPoolExecutor(initializer=_thread_initializer) as executor:
                    patches = Patch.query.filter(Patch.state == 'incomplete').all()
                    patches = map(_PatchRecord, patches)
                    for result in executor.map(Executor.workflow, patches):
                        for run_record in result.run_records:
                            db.session.add(run_record.model())
                        Patch.query.get(result.patch_id).state = result.state
                        db.session.commit()
                        if not self.running:
                            break
                    executor.shutdown(cancel_futures=True)
                self.stop()

    @staticmethod
    def workflow(patch: _PatchRecord) -> _ExecutionResult:
        result = _ExecutionResult(patch.id)
        if patch.file_filename is None:
            return result

        # step 0: prepare workspace and file path
        if patch.project_id != _thread_local.last_project_id:
            shutil.rmtree(_thread_local.workspace.path)
            shutil.copytree(patch.project.workdir, _thread_local.workspace.path)
            _thread_local.last_project_id = patch.project_id
        relative_path = Path(patch.file_filename).relative_to(Path(patch.project.workdir))
        file_path = _thread_local.workspace.path / relative_path

        # step 1: write patch to temp file
        patchfile = tempfile.NamedTemporaryFile(delete=False, mode='w')
        patchfile.write(patch.patch)
        patchfile.close()

        # step 2: apply patch
        Executor.__execute_command_timeout(
            'patch --ignore-whitespace -p1 --input={patchfile} {inputfile}'.format(
                patchfile=patchfile.name, inputfile=file_path),
            cwd='/'
        )

        # step 3: command pipeline
        success = (Executor.__apply_command(result, patch, 'build_command') and
                   Executor.__apply_command(result, patch, 'quickcheck_command') and
                   Executor.__apply_command(result, patch, 'test_command'))

        Executor.__apply_command(result, patch, 'clean_command')

        if success:
            result.state = 'survived'
        else:
            result.state = 'killed'

        # step 4: revert patch
        Executor.__execute_command_timeout(
            'patch --ignore-whitespace -p1 --reverse --input={patchfile} {inputfile}'.format(
                patchfile=patchfile.name, inputfile=file_path),
            cwd='/'
        )

        # step 6: delete patch file
        os.remove(patchfile.name)

        return result

    @staticmethod
    def __execute_command_timeout(command, timeout=None, cwd=None, stdin=None):
        proc = subprocess.Popen(shlex.split(command), stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=cwd)

        def killer(process):
            parent = psutil.Process(process.pid)
            for child in parent.children(recursive=True):  # or parent.children() for recursive=False
                child.kill()
            parent.kill()

        timer = Timer(timeout, killer, (proc,))
        try:
            timer.start()
            stdout, stderr = proc.communicate()
            errcode = proc.returncode
            cancelled = not timer.is_alive()
        finally:
            timer.cancel()

        if cancelled:
            raise subprocess.TimeoutExpired(command, timeout, stdout)

        if errcode != 0:
            raise subprocess.CalledProcessError(errcode, command, stdout)

        return stdout

    @staticmethod
    def __apply_command(result: _ExecutionResult, patch: _PatchRecord, step: str) -> bool:
        print(patch.id, step)
        project = patch.project

        if step == 'quickcheck_command':
            timeout = project.quickcheck_timeout
            command = project.quickcheck_command
        elif step == 'test_command':
            timeout = project.test_timeout
            command = project.test_command
        elif step == 'build_command':
            timeout = None
            command = project.build_command
        elif step == 'clean_command':
            timeout = None
            command = project.clean_command
        else:
            raise NotImplementedError

        # if no command is provided, return without creating a run; True means: next command must be executed
        if not command:
            return True

        run = _RunRecord()
        run.command = step
        run.patch_id = patch.id
        run.project_id = patch.project_id
        run.timestamp_start = datetime.datetime.now()

        # execute command
        try:
            output = Executor.__execute_command_timeout(command, cwd=_thread_local.workspace.path, timeout=timeout)
            timeout = False
            success = True
            nochange = False
        except subprocess.CalledProcessError as e:
            output = e.output
            timeout = False
            success = False
            nochange = e.returncode == 77
        except subprocess.TimeoutExpired as e:
            output = e.output
            timeout = True
            success = False
            nochange = False

        run.output = str(output, encoding='utf-8', errors='ignore')

        run.timestamp_end = datetime.datetime.now()
        run.duration = (run.timestamp_end - run.timestamp_start).total_seconds()

        # determine log message
        if success:
            log = 'success'
        elif timeout:
            log = 'timeout'
        elif nochange:
            log = 'nochange'
        else:
            log = 'failure'

        run.log = log
        run.success = success

        result.run_records.append(run)

        if not success:
            result.state = 'killed'

        return success
