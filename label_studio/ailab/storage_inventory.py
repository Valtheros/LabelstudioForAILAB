"""Read-only ownership export for the offline AILAB quota backfill."""
import json
import os
from pathlib import PurePosixPath


def inventory():
    from .models import Workspace
    from data_import.models import FileUpload
    projects, issues = [], []
    mapping = {}
    for workspace in Workspace.objects.select_related('identity').all():
        mapping[workspace.project_id] = workspace
        projects.append({'id': workspace.project_id, 'owner': workspace.identity.subject})
    for upload in FileUpload.objects.all().iterator():
        workspace = mapping.get(upload.project_id)
        path = PurePosixPath(str(upload.file.name))
        if (not workspace or upload.user_id != workspace.identity.user_id
                or path.is_absolute() or '..' in path.parts or path.parts[:2] != ('upload', str(upload.project_id))):
            issues.append({'uploadId': upload.pk, 'reason': 'Upload ownership or path is not verified'})
    return {'projects': projects, 'issues': issues}


if __name__ == '__main__':
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ailab.settings')
    django.setup()
    print(json.dumps(inventory()))
