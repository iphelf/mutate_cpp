# coding=utf-8

from threading import Thread
from app.models import Patch, Project, File
import tempfile
import os
from app import db
from .Executor import Executor


class SeqExecutor(Executor):
    def __init__(self, app):
        super().__init__(app)
        self.__current_patch = None

    def start(self):
        if self.__current_patch is None:
            self.running = True
            Thread(target=self.main).start()

    @property
    def current_patch(self):
        return self.__current_patch

    def main(self):
        with self.app.app_context():
            while self.running:
                for patch in Patch.query.filter(Patch.state == 'incomplete').all():
                    if self.running:
                        self.workflow(patch)
                self.stop()

    def is_parallel(self):
        return False

    def workflow(self, patch: Patch):
        assert self.__current_patch is None, 'no auto-concurrency!'

        file: File = File.query.get(patch.file_id)

        if file is not None:
            self.__current_patch = patch

            # step 1: write patch to temp file
            patchfile = tempfile.NamedTemporaryFile(delete=False, mode='w')
            patchfile.write(patch.patch)
            patchfile.close()

            # step 2: apply patch
            Executor._apply_patch(patchfile.name, file.filename)

            # step 3: command pipeline
            success = (SeqExecutor.__apply_command(patch, 'build_command') and
                       SeqExecutor.__apply_command(patch, 'quickcheck_command') and
                       SeqExecutor.__apply_command(patch, 'test_command'))

            SeqExecutor.__apply_command(patch, 'clean_command')

            if success:
                patch.state = 'survived'
                db.session.commit()

            # step 4: revert patch
            Executor._revert_patch(patchfile.name, file.filename)

            # step 6: delete patch file
            os.remove(patchfile.name)

            self.__current_patch = None

    @staticmethod
    def __apply_command(patch: Patch, step: str):
        print(patch, step)
        # noinspection PyUnresolvedReferences
        project: Project = patch.project

        command, timeout = Executor._get_command_and_timeout(project, step)

        # if no command is provided, return without creating a run; True means: next command must be executed
        if not command:
            return True

        run = Executor._run_command(patch.id, patch.project_id, step, command, project.workdir, timeout)

        db.session.add(run.model())

        if not run.success:
            patch.state = 'killed'

        db.session.commit()

        return run.success
