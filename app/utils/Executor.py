# coding=utf-8

import shlex
import subprocess
from threading import Timer, Thread
import psutil
from app.models import Patch, Run
import datetime
from abc import ABC, abstractmethod


class Executor(ABC):
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

    @abstractmethod
    def main(self):
        ...

    @abstractmethod
    def is_parallel(self):
        ...

    @staticmethod
    def _execute_command_timeout(command, timeout=None, cwd=None, stdin=None):
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

    @staticmethod
    def _apply_patch(patch_file_path, input_file_path):
        Executor._execute_command_timeout(
            'patch --ignore-whitespace -p1 --input={patchfile} {inputfile}'.format(
                patchfile=patch_file_path, inputfile=input_file_path),
            cwd='/'
        )

    @staticmethod
    def _revert_patch(patch_file_path, input_file_path):
        Executor._execute_command_timeout(
            'patch --ignore-whitespace -p1 --reverse --input={patchfile} {inputfile}'.format(
                patchfile=patch_file_path, inputfile=input_file_path),
            cwd='/'
        )

    @staticmethod
    def _get_command_and_timeout(project, step):
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
        return command, timeout

    @staticmethod
    def _run_command(patch_id, project_id, step, command, cwd, timeout) -> _RunRecord:
        run = Executor._RunRecord()
        run.command = step
        run.patch_id = patch_id
        run.project_id = project_id
        run.timestamp_start = datetime.datetime.now()

        # execute command
        try:
            output = Executor._execute_command_timeout(command, cwd=cwd, timeout=timeout)
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

        return run
