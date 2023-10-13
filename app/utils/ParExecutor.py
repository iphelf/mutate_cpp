# coding=utf-8

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Union
from app.models import Patch, Project
import tempfile
import os
from app import db
from pathlib import Path
from .Executor import Executor


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
        # noinspection PyUnresolvedReferences
        self.file_filename = patch.file.filename
        self.project_id = patch.project_id
        # noinspection PyUnresolvedReferences
        self.project = _ProjectRecord(patch.project)
        self.patch = patch.patch


class ParExecutor(Executor):
    def __init__(self, app):
        super().__init__(app)

    def main(self):
        with self.app.app_context():
            while self.running:
                with ThreadPoolExecutor(initializer=_thread_initializer) as executor:
                    patches = Patch.query.filter(Patch.state == 'incomplete').all()
                    patches = map(_PatchRecord, patches)
                    for result in executor.map(ParExecutor.workflow, patches):
                        for run_record in result.run_records:
                            db.session.add(run_record.model())
                        Patch.query.get(result.patch_id).state = result.state
                        db.session.commit()
                        if not self.running:
                            break
                    executor.shutdown(cancel_futures=True)
                self.stop()

    def is_parallel(self):
        return True

    class _ExecutionResult:
        def __init__(self, patch_id: int):
            self.patch_id: int = patch_id
            self.run_records: list[Executor._RunRecord] = []
            self.state: str = "incomplete"

    @staticmethod
    def workflow(patch: _PatchRecord) -> _ExecutionResult:
        result = ParExecutor._ExecutionResult(patch.id)
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
        Executor._apply_patch(patchfile.name, file_path)

        # step 3: command pipeline
        success = (ParExecutor.__apply_command(result, patch, 'build_command') and
                   ParExecutor.__apply_command(result, patch, 'quickcheck_command') and
                   ParExecutor.__apply_command(result, patch, 'test_command'))

        ParExecutor.__apply_command(result, patch, 'clean_command')

        if success:
            result.state = 'survived'
        else:
            result.state = 'killed'

        # step 4: revert patch
        Executor._revert_patch(patchfile.name, file_path)

        # step 6: delete patch file
        os.remove(patchfile.name)

        return result

    @staticmethod
    def __apply_command(result: _ExecutionResult, patch: _PatchRecord, step: str) -> bool:
        print(patch.id, step)
        project = patch.project

        command, timeout = Executor._get_command_and_timeout(project, step)

        # if no command is provided, return without creating a run; True means: next command must be executed
        if not command:
            return True

        run = Executor._run_command(patch.id, patch.project_id, step, command, _thread_local.workspace.path, timeout)

        result.run_records.append(run)

        if not run.success:
            result.state = 'killed'

        return run.success
