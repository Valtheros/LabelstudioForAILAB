"""Rebuild owned image URLs from FileUpload; dry-run unless --apply is supplied."""
import argparse
import json
import os


def backfill(*, apply=False):
    from django.db import transaction
    from tasks.models import Task
    from .models import ImageRecord, Workspace

    scanned = changed = 0
    for image in ImageRecord.objects.select_related('upload').iterator(chunk_size=100):
        scanned += 1
        with transaction.atomic():
            Workspace.objects.select_for_update().get(pk=image.workspace_id)
            task = Task.objects.select_for_update().get(pk=image.task_id)
            url = image.upload.url
            if task.data.get('image') != url:
                changed += 1
                if apply:
                    Task.objects.filter(pk=task.pk).update(data={**task.data, 'image': url})
    return {'scanned': scanned, 'changed': changed, 'applied': apply}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ailab.settings')
    import django
    django.setup()
    print(json.dumps(backfill(apply=args.apply)))
