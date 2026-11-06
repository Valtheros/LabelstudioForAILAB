import errno
import fcntl
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, RequestFactory, override_settings
from django.http import JsonResponse

from .storage import OwnerUploadHandler, StorageError, StorageUploadMiddleware, UploadLease


class UploadStorageTests(SimpleTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.control = self.root / 'leases'
        self.control.mkdir()
        (self.control / '.registry.lock').touch()
        self.workspace = SimpleNamespace(identity=SimpleNamespace(subject='alice'), project_id=2,
            project=SimpleNamespace(title='Project'), external_id='681525af-de34-47aa-9d80-0f932a3810ce', kind='object_detection')
        for context in (patch.dict(os.environ, {'STORAGE_ENFORCEMENT': 'true', 'STORAGE_LEASE_DIR': str(self.control)}),
                        override_settings(BASE_DATA_DIR=str(self.root))):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def test_lease_is_locked_before_reserve_and_remains_until_release(self):
        events = []
        def call(lease, action):
            with lease.file.open('r+') as file:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            events.append(action)
            if action == 'reserve':
                lease.directory.mkdir(parents=True)
            else:
                self.assertFalse(lease.directory.exists())
        with patch.object(UploadLease, 'call', call):
            with UploadLease(self.workspace, 1024) as lease:
                (lease.directory / 'temporary').write_bytes(b'owned')
            self.assertFalse(lease.file.exists())
        self.assertEqual(events, ['reserve', 'release'])

    def test_failed_release_keeps_recoverable_unlocked_lease(self):
        def call(lease, action):
            if action == 'reserve':
                lease.directory.mkdir(parents=True)
            else:
                raise StorageError('Disconnected')
        with patch.object(UploadLease, 'call', call), self.assertLogs('ailab.storage', 'ERROR'):
            with UploadLease(self.workspace, 1024) as lease:
                pass
        self.assertTrue(lease.file.exists())
        with lease.file.open('r+') as file:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_upload_parser_spool_stays_in_owner_directory(self):
        handler = OwnerUploadHandler(RequestFactory().post('/'), SimpleNamespace(directory=self.root))
        handler.new_file('file', '../../image.png', 'image/png', 3)
        try:
            handler.receive_data_chunk(b'abc', 0)
            file = handler.file_complete(3)
            self.assertEqual(file.name, 'image.png')
            self.assertEqual(file.read(), b'abc')
            self.assertTrue(os.readlink(f'/proc/self/fd/{file.fileno()}').startswith(str(self.root) + '/'))
            with patch.object(handler.stream, 'write', side_effect=OSError(errno.EDQUOT, 'full')):
                with self.assertRaises(StorageError) as error:
                    handler.receive_data_chunk(b'x', 3)
                self.assertEqual(error.exception.code, 'STORAGE_QUOTA_EXCEEDED')
        finally:
            for file in handler.open_files:
                file.close()

    def test_quota_error_from_zip_writer_is_readable(self):
        response = StorageUploadMiddleware(lambda r: None).process_exception(None, OSError(errno.ENOSPC, 'full'))
        self.assertEqual(response.status_code, 409)
        self.assertIn(b'STORAGE_QUOTA_EXCEEDED', response.content)

    def test_unauthenticated_upload_does_not_reserve_or_parse(self):
        request = RequestFactory().post('/api/projects/2/import')
        request.user = SimpleNamespace(is_authenticated=False)
        with patch.object(UploadLease, '__enter__') as reserve:
            response = StorageUploadMiddleware(lambda r: JsonResponse({}))(request)
        self.assertEqual(response.status_code, 401)
        reserve.assert_not_called()
