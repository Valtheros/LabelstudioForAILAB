"""Per-request upload space, charged to the AILAB owner before parsing files."""
import errno
import fcntl
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

import requests
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.http import JsonResponse
from django.core.exceptions import ObjectDoesNotExist


log = logging.getLogger(__name__)
MAX_BODY = 2 * 1024**3 + 1024**2


def enabled():
    return os.environ.get('STORAGE_ENFORCEMENT', '').lower() == 'true'


class StorageError(Exception):
    def __init__(self, detail, code='STORAGE_UNAVAILABLE', status=503):
        super().__init__(detail)
        self.code, self.status = code, status

    def response(self):
        return JsonResponse({'detail': str(self), 'code': self.code}, status=self.status)


def quota_error(exc):
    if isinstance(exc, OSError) and exc.errno in {errno.EDQUOT, errno.ENOSPC}:
        raise StorageError('Storage is full. Remove unused files or contact your administrator.',
                           'STORAGE_QUOTA_EXCEEDED', 409) from exc


class UploadLease:
    def __init__(self, workspace, required_bytes):
        self.workspace, self.required_bytes = workspace, required_bytes
        self.id = uuid.uuid4().hex
        self.owner = workspace.identity.subject
        key = hashlib.sha256(self.owner.encode()).hexdigest()[:32]
        self.directory = Path(settings.BASE_DATA_DIR) / '.uploads' / key / self.id
        self.file = Path(os.environ.get('STORAGE_LEASE_DIR', '/storage-leases')) / f'label-{self.id}'
        self.fd = None

    def call(self, action):
        payload = {'requiredBytes': self.required_bytes, 'project': self.workspace.project_id,
                   'externalId': str(self.workspace.external_id), 'name': self.workspace.project.title,
                   'kind': self.workspace.kind}
        try:
            response = requests.post(f'http://backend:8000/internal/label-studio/storage/{self.id}/{action}',
                headers={'Authorization': 'Bearer ' + os.environ['LABEL_STUDIO_BRIDGE_SECRET'],
                         'X-User-Id': self.owner}, json=payload, timeout=(5, 30))
            data = response.json()
            if not response.ok:
                raise StorageError(str(data.get('detail', 'Storage is unavailable.')),
                                   data.get('code', 'STORAGE_UNAVAILABLE'), response.status_code)
            return data
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise StorageError('Storage is unavailable. Your saved annotations have not been removed.') from exc

    def __enter__(self):
        if not enabled():
            self.directory = Path(settings.FILE_UPLOAD_TEMP_DIR)
            return self
        registry = os.open(self.file.parent / '.registry.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fcntl.flock(registry, fcntl.LOCK_EX)
            self.fd = os.open(self.file, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        finally:
            os.close(registry)
        try:
            self.call('reserve')
            if not self.directory.is_dir() or self.directory.is_symlink():
                raise StorageError('Upload storage is not ready.')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, kind, exc, traceback):
        if self.fd is not None:
            try:
                if self.directory.exists():
                    shutil.rmtree(self.directory)
                self.call('release')
                self.file.unlink(missing_ok=True)
            except Exception:
                log.exception('Upload lease retained for confirmed-dead-process recovery: %s', self.id)
            finally:
                os.close(self.fd)
                self.fd = None
        quota_error(exc)


class OwnerUploadHandler(FileUploadHandler):
    """Keep every parser spool on the owner's quota project, including small files."""
    def __init__(self, request, lease):
        super().__init__(request)
        self.lease, self.open_files, self.total = lease, [], 0

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.stream = tempfile.TemporaryFile(dir=self.lease.directory)
        self.open_files.append(self.stream)

    def receive_data_chunk(self, raw_data, start):
        self.total += len(raw_data)
        if self.total > MAX_BODY:
            raise StorageError('Image uploads must not exceed 2 GB.', 'UPLOAD_TOO_LARGE', 413)
        try:
            self.stream.write(raw_data)
        except OSError as exc:
            quota_error(exc)
            raise

    def file_complete(self, file_size):
        self.stream.seek(0)
        return UploadedFile(self.stream, self.file_name, self.content_type, file_size, self.charset, self.content_type_extra)


class StorageUploadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = re.fullmatch(r'/api/projects/(\d+)/import', request.path_info)
        if not enabled() or request.method != 'POST' or not match:
            return self.get_response(request)
        from .models import Workspace
        from .security import owns
        try:
            if not request.user.is_authenticated:
                return JsonResponse({'detail': 'Authentication required.'}, status=401)
            workspace = Workspace.objects.select_related('identity', 'project__organization').get(project_id=match[1])
            if not owns(request.user, workspace.project):
                return JsonResponse({'detail': 'Not found.'}, status=404)
            length = request.META.get('CONTENT_LENGTH', '')
            if not length.isascii() or not length.isdigit() or len(length) > 12 or int(length) > MAX_BODY:
                raise StorageError('Image uploads must have a valid length of at most 2 GB.', 'UPLOAD_TOO_LARGE', 413)
            with UploadLease(workspace, 2 * int(length) + 2 * 1024**2) as lease:
                handler = OwnerUploadHandler(request, lease)
                request.upload_handlers = [handler]
                request.ailab_upload_directory = lease.directory
                try:
                    return self.get_response(request)
                finally:
                    # Django normally closes uploads after middleware returns; release only after closing them.
                    for file in handler.open_files:
                        file.close()
        except ObjectDoesNotExist:
            return JsonResponse({'detail': 'Not found.'}, status=404)
        except StorageError as exc:
            return exc.response()

    def process_exception(self, request, exception):
        if isinstance(exception, StorageError):
            return exception.response()
        try:
            quota_error(exception)
        except StorageError as exc:
            return exc.response()
