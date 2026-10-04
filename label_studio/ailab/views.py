import hashlib
import io
import json
import math
import os
import re
import secrets
import tempfile
import uuid
from datetime import timedelta
from xml.etree import ElementTree as ET

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import PasswordResetView
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files import File
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import FileResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods
from PIL import Image
from rest_framework.exceptions import ValidationError as APIValidationError

from .actions import automatic_split
from .models import Identity, Workspace, ImageRecord, Snapshot, SnapshotImage
from .signals import validate_result


KINDS = {'image_classification', 'object_detection', 'semantic_segmentation', 'instance_segmentation'}


def limited(request, purpose, limit):
    identifier = request.POST.get('username', request.POST.get('email', '')).strip().casefold()
    key = 'ailab:' + hashlib.sha256(f'{purpose}:{identifier}:{request.META.get("REMOTE_ADDR", "")}'.encode()).hexdigest()
    try:
        cache.add(key, 0, timeout=600)
        return cache.incr(key) > limit
    except Exception:
        return True


@csrf_protect
def user_login(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST':
        if limited(request, 'login', 30):
            return render(request, 'ailab/form.html', {'form': form, 'title': 'Sign in to Label Studio', 'error': 'Too many attempts. Try again in 10 minutes.'}, status=429)
        if form.is_valid():
            user = form.get_user()
            identity = Identity.objects.filter(user=user, activated=True, disabled=False).first()
            if identity:
                login(request, user)
                target = request.GET.get('next', '')
                if not target.startswith('/projects/') or not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
                    target = '/projects/'
                return HttpResponseRedirect(target)
            form.add_error(None, 'This account is not active. Open Annotation in AILAB.')
    return render(request, 'ailab/form.html', {'form': form, 'title': 'Sign in to Label Studio', 'login': True})


@csrf_protect
def activate(request):
    context = {'title': 'Set your Label Studio password', 'activation': True, 'ticket': request.POST.get('ticket', '')}
    if request.method == 'POST':
        if limited(request, 'activation', 30):
            return JsonResponse({'detail': 'Too many attempts. Try again later.'}, status=429)
        token = request.POST.get('ticket', '')
        with transaction.atomic():
            identity = Identity.objects.select_for_update().filter(
                ticket_hash=hashlib.sha256(token.encode()).hexdigest(), ticket_expires__gt=timezone.now(),
                activated=False, disabled=False,
            ).first() if len(token) >= 40 else None
            if identity:
                form = SetPasswordForm(identity.user, request.POST)
                context['form'] = form
                if form.is_valid():
                    user = form.save()
                    identity.activated = True
                    identity.ticket_hash = ''
                    identity.ticket_expires = None
                    identity.save()
                    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                    return HttpResponseRedirect('/projects/')
            else:
                context['error'] = 'This link expired or was already used. Request a new link from AILAB.'
    if 'form' not in context:
        from users.models import User
        context['form'] = SetPasswordForm(User())
    return render(request, 'ailab/form.html', context)


class PasswordReset(PasswordResetView):
    def post(self, request, *args, **kwargs):
        if limited(request, 'password-reset', 5):
            return JsonResponse({'detail': 'Too many attempts. Try again in 10 minutes.'}, status=429)
        return super().post(request, *args, **kwargs)


def project_config(payload):
    name = str(payload.get('name', '')).strip()
    kind = payload.get('kind')
    classes = payload.get('classes')
    ratios = payload.get('ratios', [80, 10, 10])
    seed = payload.get('seed', 0)
    if not name or len(name) > 100 or kind not in KINDS:
        raise ValueError('Provide a project name and supported task type.')
    if not isinstance(classes, list) or not 1 <= len(classes) <= 254:
        raise ValueError('Provide between 1 and 254 classes.')
    names = []
    for item in classes:
        if not isinstance(item, dict):
            raise ValueError('Invalid class.')
        label = str(item.get('name', '')).strip()
        color = item.get('color', '')
        if not label or len(label) > 100 or label.casefold() in names or any(ord(c) < 32 for c in label):
            raise ValueError('Class names must be nonempty and unique.')
        if not isinstance(color, str) or not re.fullmatch('#[0-9a-fA-F]{6}', color):
            raise ValueError('Invalid class color.')
        item['name'] = label
        names.append(label.casefold())
    if kind == 'image_classification' and len(classes) < 2:
        raise ValueError('Classification requires at least two classes.')
    if not isinstance(ratios, list) or len(ratios) != 3 or any(type(v) is not int or not 0 <= v <= 100 for v in ratios) or sum(ratios) != 100 or ratios[0] == 0:
        raise ValueError('Split percentages must total 100 and include Train.')
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError('Seed must be a nonnegative integer.')
    return name, kind, classes, ratios, seed


def label_config(kind, classes):
    root = ET.Element('View')
    ET.SubElement(root, 'Image', name='image', value='$image', zoom='true', rotateControl='false')
    if kind == 'image_classification':
        choices = ET.SubElement(root, 'Choices', name='class', toName='image', choice='single', showInLine='true')
        for item in classes:
            ET.SubElement(choices, 'Choice', value=item['name'])
    else:
        tags = ['RectangleLabels'] if kind == 'object_detection' else ['PolygonLabels', 'BrushLabels']
        tools = ET.SubElement(root, 'Collapse', accordion='true') if len(tags) > 1 else root
        for tag in tags:
            parent = ET.SubElement(tools, 'Panel', value='Polygon' if tag == 'PolygonLabels' else 'Brush', open='true' if tag == 'PolygonLabels' else 'false') if len(tags) > 1 else tools
            control = ET.SubElement(parent, tag, name=tag.lower(), toName='image', **({'canRotate': 'false'} if tag == 'RectangleLabels' else {}))
            for item in classes:
                ET.SubElement(control, 'Label', value=item['name'], background=item['color'])
    return ET.tostring(root, encoding='unicode')


def workspace_for(identity, payload, lock=False):
    queryset = Workspace.objects.select_for_update() if lock else Workspace.objects
    return queryset.select_related('project').get(project_id=int(payload['project']), identity=identity, deleted=False)


def describe(workspace):
    from tasks.models import Annotation
    tasks = workspace.project.tasks
    labeled = Annotation.objects.filter(project=workspace.project, was_cancelled=False).values('task_id').distinct().count()
    return {'id': workspace.project_id, 'external_id': str(workspace.external_id), 'name': workspace.project.title, 'kind': workspace.kind,
            'classes': workspace.classes, 'ratios': workspace.ratios, 'seed': workspace.seed,
            'revision': workspace.revision, 'image_count': tasks.count(), 'labeled_count': labeled,
            'excluded_count': tasks.filter(data__excluded=True).count(),
            'splits': {key: tasks.filter(data__split=key).count() for key in ('train', 'val', 'test')},
            'url': f'{settings.LABEL_PUBLIC_URL}/projects/{workspace.project_id}/data/'}


def create_tabs(project, user):
    from data_manager.models import View, FilterGroup, Filter
    for index, (title, value) in enumerate([('All', None), ('Train', 'train'), ('Validation', 'val'), ('Test', 'test')]):
        group = FilterGroup.objects.create(conjunction='and')
        if value:
            group.filters.add(Filter.objects.create(index=0, column='filter:tasks:data.split', type='String', operator='equal', value=value))
        View.objects.create(project=project, user=user, order=index, filter_group=group,
                            data={'title': title, 'type': 'grid', 'target': 'tasks'}, ordering=['id'])


@csrf_exempt
@require_http_methods(['POST'])
def internal(request, action):
    secret = os.environ.get('LABEL_STUDIO_BRIDGE_SECRET', '')
    if not secret or not secrets.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + secret):
        return JsonResponse({'detail': 'Unauthorized bridge request.'}, status=401)
    subject = request.headers.get('X-AILAB-User', '')
    if not subject or len(subject) > 255:
        return JsonResponse({'detail': 'An AILAB identity is required.'}, status=400)
    try:
        payload = dict(request.GET.items()) if action == 'image-upload' else json.loads(request.body or '{}')
        if not isinstance(payload, dict):
            raise ValueError('JSON object required.')
        if action in {'account', 'activate-link'}:
            return account_action(subject, payload, action)
        identity = Identity.objects.select_related('user').get(subject=subject, activated=True, disabled=False)
        if action == 'image-upload':
            return image_upload(request, identity, payload)
        if action in {'snapshot-page', 'image-download', 'mask-download', 'release-snapshot'}:
            if action == 'release-snapshot':
                Snapshot.objects.filter(pk=payload['snapshot'], workspace__identity=identity).delete()
                return JsonResponse({'released': True})
            snapshot = Snapshot.objects.get(pk=payload['snapshot'], workspace__identity=identity)
            if action == 'image-download':
                item = snapshot.images.select_related('image__upload').get(image_id=int(payload['image']))
                return FileResponse(item.image.upload.file.open('rb'), content_type='image/png')
            if action == 'mask-download':
                from label_studio_sdk.converter.brush import decode_rle
                item = snapshot.images.get(image_id=int(payload['image']))
                region = next(r for r in item.data['result'] if r.get('id') == payload['region'] and r['type'] == 'brushlabels')
                width, height = item.data['width'], item.data['height']
                alpha = decode_rle(region['value']['rle']).reshape(height, width, 4)[:, :, 3]
                output = io.BytesIO()
                Image.fromarray(alpha).save(output, format='PNG')
                output.seek(0)
                return FileResponse(output, content_type='image/png')
            offset = int(payload.get('offset', 0))
            if offset < 0:
                raise ValueError('Invalid offset.')
            item = snapshot.images.order_by('id')[offset:offset + 1]
            return JsonResponse({'items': [row.data for row in item], 'config': snapshot.config, 'total': snapshot.images.count()})
        if action == 'project':
            return JsonResponse(describe(workspace_for(identity, payload)))
        if action == 'snapshot':
            with transaction.atomic():
                return make_snapshot(workspace_for(identity, payload, lock=True), payload)
        raise ValueError('Unsupported bridge action.')
    except ObjectDoesNotExist:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    except IntegrityError:
        return JsonResponse({'detail': 'This operation conflicts with existing data. Refresh and retry.'}, status=409)
    except (ValueError, TypeError, KeyError, StopIteration, SyntaxError, ValidationError, APIValidationError) as exc:
        return JsonResponse({'detail': str(exc)[:300]}, status=400)


def account_action(subject, payload, action):
    from users.models import User
    from organizations.models import Organization
    with transaction.atomic():
        identity = Identity.objects.select_for_update().filter(subject=subject).first()
        if identity is None:
            email = str(payload.get('email', '')).strip().lower()
            from django.core.validators import validate_email
            validate_email(email)
            if User.objects.filter(email=email).exists():
                raise ValueError('This email already belongs to another Label Studio account.')
            user = User.objects.create_user(email=email, password=None, username=email, is_staff=False, is_superuser=False)
            org = Organization.create_organization(created_by=user, title='Personal workspace')
            user.active_organization = org
            user.save(update_fields=['active_organization'])
            identity = Identity.objects.create(user=user, subject=subject)
        result = {'user_id': identity.user_id, 'activated': identity.activated, 'disabled': identity.disabled,
                  'url': settings.LABEL_PUBLIC_URL + '/user/login/'}
        if action == 'activate-link' and not identity.activated and not identity.disabled:
            ticket = secrets.token_urlsafe(48)
            identity.ticket_hash = hashlib.sha256(ticket.encode()).hexdigest()
            identity.ticket_expires = timezone.now() + timedelta(minutes=10)
            identity.save(update_fields=['ticket_hash', 'ticket_expires'])
            result['url'] = settings.LABEL_PUBLIC_URL + '/ailab/activate/#' + ticket
        return JsonResponse(result)


def image_upload(request, identity, payload):
    from data_import.models import FileUpload
    from tasks.models import Task
    digest = payload.get('sha256', '')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid image digest.')
    with transaction.atomic():
        workspace = workspace_for(identity, payload, lock=True)
        existing = workspace.images.filter(sha256=digest).first()
        if existing:
            return JsonResponse({'id': existing.pk, 'duplicate': True})
        with tempfile.TemporaryFile(dir=settings.FILE_UPLOAD_TEMP_DIR) as temporary:
            size, hasher = 0, hashlib.sha256()
            while chunk := request.read(1024 * 1024):
                size += len(chunk)
                if size > 150_000_000:
                    raise ValueError('Image file is too large.')
                hasher.update(chunk)
                temporary.write(chunk)
            if hasher.hexdigest() != digest:
                raise ValueError('Image checksum does not match.')
            temporary.seek(0)
            with Image.open(temporary) as image:
                width, height = image.size
                if width * height > 25_000_000 or image.format != 'PNG':
                    raise ValueError('Images must be normalized PNG, up to 25 million pixels.')
                image.verify()
            temporary.seek(0)
            upload = FileUpload(user=identity.user, project=workspace.project)
            upload.file.save(digest + '.png', File(temporary), save=True)
        try:
            task = Task.objects.create(project=workspace.project, file_upload=upload, data={
                'image': upload.url, 'filename': str(payload.get('filename', digest))[:500],
                'split': automatic_split(digest, workspace.ratios, workspace.seed), 'split_source': 'auto', 'excluded': False,
            })
            record = ImageRecord.objects.create(workspace=workspace, task=task, upload=upload, sha256=digest, width=width, height=height)
            workspace.project.summary.update_data_columns([task])
            workspace.project.update_tasks_counters_and_is_labeled(tasks_queryset=[task.pk])
            return JsonResponse({'id': record.pk, 'duplicate': False})
        except Exception:
            upload.file.delete(save=False)
            raise


def make_snapshot(workspace, payload):
    operation = uuid.UUID(str(payload['operation']))
    previous = Snapshot.objects.filter(operation=operation, workspace=workspace).first()
    if previous:
        return JsonResponse({'snapshot': str(previous.pk), 'total': previous.images.count(), 'config': previous.config})
    snapshot = Snapshot.objects.create(workspace=workspace, operation=operation, revision=workspace.revision,
                                       config={'kind': workspace.kind, 'classes': workspace.classes, 'ratios': workspace.ratios,
                                               'seed': workspace.seed, 'revision': workspace.revision, 'name': workspace.project.title})
    count, train = 0, 0
    for image in workspace.images.select_related('task').iterator(chunk_size=100):
        task = image.task
        if task.data.get('excluded'):
            continue
        annotation = task.annotations.filter(was_cancelled=False).order_by('-updated_at', '-id').first()
        if annotation is None or task.drafts.exists():
            raise ValueError(f'Image {task.pk} is unfinished. Submit its annotation or exclude it before publishing.')
        if not annotation.result and workspace.kind == 'image_classification':
            raise ValueError('Classification images require a class or must be excluded.')
        validate_result(annotation.result, workspace, image)
        split = task.data.get('split')
        if split not in ('train', 'val', 'test'):
            raise ValueError('Invalid split.')
        SnapshotImage.objects.create(snapshot=snapshot, image=image, data={
            'id': image.pk, 'task_id': task.pk, 'width': image.width, 'height': image.height,
            'sha256': image.sha256, 'filename': task.data.get('filename'), 'split': split, 'result': annotation.result,
        })
        count += 1
        train += split == 'train'
    if not count or not train:
        raise ValueError('At least one submitted training image is required.')
    return JsonResponse({'snapshot': str(snapshot.pk), 'total': count, 'config': snapshot.config})
