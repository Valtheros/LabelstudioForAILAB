import hashlib

from data_manager.actions import register_action
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import PermissionDenied

from .models import Workspace
from .security import owns


def automatic_split(sha256, ratios, seed):
    value = int.from_bytes(hashlib.sha256(f'{seed}:{sha256}'.encode()).digest()[:8], 'big') / 2**64 * 100
    return 'train' if value < ratios[0] else ('val' if value < ratios[0] + ratios[1] else 'test')


def update_images(project, queryset, request, field, value):
    if not owns(request.user, project):
        raise PermissionDenied()
    with transaction.atomic():
        workspace = Workspace.objects.select_for_update().get(project=project)
        count = 0
        for task in queryset.filter(project=project).select_related('ailab_image').iterator(chunk_size=100):
            data = dict(task.data)
            if field == 'split':
                data['split'] = value
                data['split_source'] = 'manual'
            elif field == 'auto':
                data['split'] = automatic_split(task.ailab_image.sha256, workspace.ratios, workspace.seed)
                data['split_source'] = 'auto'
            else:
                data['excluded'] = value
            task.data = data
            task.save(update_fields=['data'])
            count += 1
        Workspace.objects.filter(pk=workspace.pk).update(revision=F('revision') + 1)
    return {'processed_items': count, 'detail': f'Updated {count} images', 'reload': True}


def register(name, title, field, value, order):
    def action(project, queryset, **kwargs):
        return update_images(project, queryset, kwargs['request'], field, value)
    action.__name__ = name
    register_action(action, title, order, permission='tasks.change')


for index, (name, title, field, value) in enumerate([
    ('ailab_train', 'Move to Train', 'split', 'train'),
    ('ailab_val', 'Move to Validation', 'split', 'val'),
    ('ailab_test', 'Move to Test', 'split', 'test'),
    ('ailab_auto', 'Restore automatic split', 'auto', None),
    ('ailab_exclude', 'Exclude from dataset', 'excluded', True),
    ('ailab_include', 'Include in dataset', 'excluded', False),
]):
    register(name, title, field, value, index)


def check_action_permission(user, action, project):
    return owns(user, project) and action['id'] in {
        'ailab_train', 'ailab_val', 'ailab_test', 'ailab_auto', 'ailab_exclude', 'ailab_include',
        'delete_tasks_annotations',
        'next_task',
    }
