"""Keep the upstream project UI; constrain its writes to a private image workspace."""
import os
import json
import re
import tempfile
import uuid
import zipfile
from xml.etree import ElementTree as ET

import requests
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseRedirect
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from projects.api import ProjectListAPI, ProjectAPI, TemplateListAPI
from tasks.models import Annotation, AnnotationDraft

from .models import Workspace
from .views import label_config, create_tabs, project_config


def parse_config(config, previous=None):
    try:
        root = ET.fromstring(config)
    except ET.ParseError as exc:
        raise ValidationError('Invalid labeling configuration.') from exc
    images = list(root.iter('Image'))
    if len(images) != 1 or images[0].get('value') != '$image':
        raise ValidationError('Use one Image with value="$image" for an AILAB dataset.')
    controls = [e for e in root.iter() if e.tag in {'Choices', 'RectangleLabels', 'PolygonLabels', 'BrushLabels'}]
    types = {e.tag for e in controls}
    if types == {'Choices'} and len(controls) == 1:
        kind = 'image_classification'
        if controls[0].get('choice', 'single') != 'single':
            raise ValidationError('Image classification requires one class per image.')
    elif types == {'RectangleLabels'} and len(controls) == 1:
        kind = 'object_detection'
    elif types and types <= {'PolygonLabels', 'BrushLabels'}:
        marker = re.search(r'<!-- AILAB task: (semantic_segmentation|instance_segmentation) -->', config)
        kind = marker[1] if marker else (previous if previous in {'semantic_segmentation', 'instance_segmentation'} else 'instance_segmentation')
    else:
        raise ValidationError('Use Image Classification, Object Detection, Semantic or Instance Segmentation.')
    allowed = {'View', 'Header', 'Image', 'Choices', 'Choice', 'RectangleLabels', 'PolygonLabels', 'BrushLabels', 'Label', 'Collapse', 'Panel', 'Style'}
    if any(e.tag not in allowed for e in root.iter()):
        raise ValidationError('This labeling control is not supported for an AILAB image dataset.')
    classes = []
    for control in controls:
        if control.get('toName') != images[0].get('name'):
            raise ValidationError('All labels must target the image.')
        current = [{'name': e.get('value', ''), 'color': e.get('background', '#22c55e')} for e in control if e.tag in {'Label', 'Choice'}]
        if classes and [c['name'] for c in classes] != [c['name'] for c in current]:
            raise ValidationError('Polygon and Brush must use the same classes in the same order.')
        classes = current
    try:
        project_config({'name': 'validate', 'kind': kind, 'classes': classes})
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return kind, classes


class Projects(ProjectListAPI):
    def get_queryset(self):
        return super().get_queryset().filter(ailab_workspace__identity=self.request.user.ailab_identity, ailab_workspace__deleted=False)

    @transaction.atomic
    def perform_create(self, serializer):
        config = serializer.validated_data.get('label_config')
        # The upstream wizard creates the project before selecting a template.
        if not config or config in ('<View></View>', '<View />'):
            config = label_config('object_detection', [{'name': 'Object', 'color': '#22c55e'}])
        kind, classes = parse_config(config)
        project = serializer.save(created_by=self.request.user, organization=self.request.user.active_organization,
                                  label_config=config, maximum_annotations=1)
        Workspace.objects.create(project=project, identity=self.request.user.ailab_identity, external_id=uuid.uuid4(), kind=kind, classes=classes)
        create_tabs(project, self.request.user)


class ProjectSettings(ProjectAPI):
    def get_queryset(self):
        return super().get_queryset().filter(ailab_workspace__identity=self.request.user.ailab_identity, ailab_workspace__deleted=False)

    @transaction.atomic
    def perform_update(self, serializer):
        project = serializer.instance
        workspace = Workspace.objects.select_for_update().get(project=project)
        kind, classes = parse_config(serializer.validated_data.get('label_config', project.label_config), workspace.kind)
        answers = Annotation.objects.filter(task__project=project)
        drafts = AnnotationDraft.objects.filter(task__project=project)
        if (answers.exists() or drafts.exists()) and kind != workspace.kind:
            raise ValidationError('Create a new project to change task type after labeling.')
        removed = {c['name'] for c in workspace.classes} - {c['name'] for c in classes}
        for queryset in (answers, drafts):
            if removed and any(removed.intersection(r.get('value', {}).get(r.get('type'), [])) for result in queryset.values_list('result', flat=True).iterator(chunk_size=100) for r in result or []):
                raise ValidationError('A class used in annotations or drafts cannot be removed or renamed.')
        serializer.save(maximum_annotations=1)
        workspace.kind, workspace.classes = kind, classes
        workspace.revision += 1
        workspace.save()

    def perform_destroy(self, instance):
        Workspace.objects.filter(project=instance).update(deleted=True)


class Templates(TemplateListAPI):
    def list(self, request, *args, **kwargs):
        templates = []
        for kind, title, image in [('image_classification', 'Image Classification', 'image-classification'),
                                  ('object_detection', 'Object Detection', 'image-classification'),
                                  ('semantic_segmentation', 'Semantic Segmentation', 'semantic-segmentation-with-polygons'),
                                  ('instance_segmentation', 'Instance Segmentation', 'semantic-segmentation-with-polygons')]:
            config = label_config(kind, [{'name': 'Class A', 'color': '#22c55e'}, {'name': 'Class B', 'color': '#3b82f6'}])
            config = f'<!-- AILAB task: {kind} -->\n' + config
            templates.append({'title': title, 'type': 'community', 'group': 'Computer Vision',
                              'image': f'{settings.FORCE_SCRIPT_NAME or ""}/static/templates/{image}.png', 'config': config, 'details': ''})
        return Response({'templates': templates, 'groups': ['Computer Vision']})


def gateway(request, pk, *, content=None, action=None, operation_id=None):
    suffix = f'operations/{operation_id}/{action}' if action else ('imports' if content else 'operations')
    url = f'http://backend:8000/internal/label-studio/projects/{pk}/' + suffix
    headers = {'Authorization': 'Bearer ' + os.environ['LABEL_STUDIO_BRIDGE_SECRET'], 'X-User-Id': request.user.ailab_identity.subject}
    workspace = Workspace.objects.select_related('project').get(project_id=pk, identity=request.user.ailab_identity, deleted=False)
    headers['X-Label-Project'] = json.dumps({'id': pk, 'external_id': str(workspace.external_id), 'name': workspace.project.title, 'kind': workspace.kind})
    try:
        if action:
            response = requests.post(url, headers=headers, timeout=(5, 15))
        elif content:
            response = requests.post(url, headers={**headers, 'Content-Type': 'application/zip'}, data=content, timeout=(5, 300))
        else:
            response = requests.get(url, headers=headers, timeout=(5, 15))
        data = response.json()
        if not response.ok:
            raise ValidationError(data.get('detail', 'Import failed.'))
        return data
    except (requests.RequestException, ValueError) as exc:
        raise ValidationError('AILAB is unavailable. Retry after the service recovers.') from exc


class ImportImages(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        files = [f for key in request.FILES for f in request.FILES.getlist(key)]
        if not files or sum(f.size for f in files) > 2 * 1024**3:
            raise ValidationError('Select image files or an image ZIP, up to 2 GB.')
        if len(files) == 1 and files[0].name.lower().endswith('.zip'):
            result = gateway(request, pk, content=files[0])
        else:
            with tempfile.TemporaryFile(dir=settings.FILE_UPLOAD_TEMP_DIR) as zipped:
                with zipfile.ZipFile(zipped, 'w') as archive:
                    for index, file in enumerate(files):
                        if not file.name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                            raise ValidationError('Only JPEG, PNG, WebP or an image ZIP is supported.')
                        with archive.open(f'{index}-{os.path.basename(file.name)}', 'w') as output:
                            for chunk in file.chunks():
                                output.write(chunk)
                zipped.seek(0)
                result = gateway(request, pk, content=zipped)
        return Response({'task_count': 0, 'annotation_count': 0, 'prediction_count': 0, 'file_upload_ids': [],
                         'could_be_tasks_list': False, 'found_formats': {}, 'data_columns': ['image'],
                         'ailab_operation': str(result['operation']['id'])}, status=201)


class ImportStatus(APIView):
    def get(self, request, pk):
        return Response(gateway(request, pk))


class ImportAction(APIView):
    def post(self, request, pk, operation_id, action):
        if action not in {'retry', 'cancel'}:
            raise ValidationError('Invalid operation action.')
        return Response(gateway(request, pk, operation_id=operation_id, action=action))


def send_to_ailab(request, pk):
    return HttpResponseRedirect(f'{settings.AILAB_URL}/annotate?project={pk}&transfer={uuid.uuid4()}')
