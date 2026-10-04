import hashlib
import io
import json
import os
import uuid
from unittest.mock import patch

from django.test import TestCase
from PIL import Image

from .models import Identity, Workspace, ImageRecord


class WorkspaceIsolationTests(TestCase):
    def test_account_has_navigation_back_to_label_projects(self):
        self.client.force_login(self.users['alice'])
        response = self.client.get('/ailab/account/')
        self.assertContains(response, 'href="/projects/"')
        self.assertContains(response, 'Change password')

    def test_send_opens_ailab_preview_without_registering_a_dataset(self):
        from urllib.parse import parse_qs, urlsplit
        self.client.force_login(self.users['alice'])
        project_id = self.projects['alice']
        response = self.client.get(f'/ailab/projects/{project_id}/send/')
        self.assertEqual(response.status_code, 302)
        url = urlsplit(response['Location'])
        self.assertEqual(url.path, '/annotate')
        query = parse_qs(url.query)
        self.assertEqual(query['project'], [str(project_id)])
        uuid.UUID(query['transfer'][0])
        self.assertTrue(Workspace.objects.filter(project_id=project_id, deleted=False).exists())

    def test_native_projects_are_private_and_editable(self):
        from .views import label_config
        self.client.force_login(self.users['alice'])
        response = self.client.post('/api/projects/', json.dumps({'title': 'Native project'}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        pk = response.json()['id']
        response = self.client.patch(f'/api/projects/{pk}/', json.dumps({'label_config': label_config('image_classification', [{'name': 'one', 'color': '#22aa44'}, {'name': 'two', 'color': '#334455'}])}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Workspace.objects.get(project_id=pk).kind, 'image_classification')
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn(self.projects['bob'], [p['id'] for p in response.json()['results']])
        for path in (f'/api/projects/{self.projects["bob"]}/', f'/projects/{self.projects["bob"]}/settings/', f'/ailab/projects/{self.projects["bob"]}/send/', f'/ailab/projects/{self.projects["bob"]}/operations/'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post(f'/api/projects/{self.projects["bob"]}/import').status_code, 404)
        self.assertEqual(self.client.post(f'/ailab/projects/{self.projects["bob"]}/operations/{uuid.uuid4()}/retry/').status_code, 404)
        self.assertEqual(self.client.get('/projects/').status_code, 200)
        self.assertEqual(self.client.get('/api/templates/').status_code, 200)

    def test_native_templates_and_segmentation_identity(self):
        from .native import parse_config
        from .views import label_config
        classes = [{'name': 'one', 'color': '#22aa44'}, {'name': 'two', 'color': '#112233'}]
        for kind in ('image_classification', 'object_detection', 'semantic_segmentation', 'instance_segmentation'):
            config = f'<!-- AILAB task: {kind} -->' + label_config(kind, classes)
            parsed_kind, parsed_classes = parse_config(config)
            self.assertEqual(parsed_kind, kind)
            self.assertEqual([c['name'] for c in parsed_classes], ['one', 'two'])
            if kind != 'image_classification':
                self.assertEqual(parsed_classes, classes)
        self.assertEqual(parse_config(label_config('semantic_segmentation', classes), 'semantic_segmentation')[0], 'semantic_segmentation')
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            parse_config('<View><Audio name="audio" value="$audio"/></View>')

    def test_segmentation_tools_keep_existing_control_names(self):
        from xml.etree import ElementTree as ET
        from .views import label_config
        for kind in ('semantic_segmentation', 'instance_segmentation'):
            root = ET.fromstring(label_config(kind, [{'name': 'one', 'color': '#22aa44'}, {'name': 'two', 'color': '#112233'}]))
            panels = root.findall('Collapse/Panel')
            self.assertEqual([p.get('value') for p in panels], ['Polygon', 'Brush'])
            self.assertEqual([p[0].get('name') for p in panels], ['polygonlabels', 'brushlabels'])
            self.assertEqual([label.get('value') for label in panels[1][0]], ['one', 'two'])

    def setUp(self):
        self.secret = patch.dict(os.environ, {'LABEL_STUDIO_BRIDGE_SECRET': 'test-only-bridge-secret'})
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.users = {}
        self.projects = {}
        for subject in ('alice', 'bob'):
            account = self.bridge(subject, 'activate-link', {'email': f'{subject}@example.com'})
            self.assertEqual(account.status_code, 200, account.content)
            identity = Identity.objects.get(subject=subject)
            identity.activated = True
            identity.save()
            self.users[subject] = identity.user
            self.projects[subject] = self.create_project(subject, 'object_detection')

    def create_project(self, subject, kind):
        from .views import label_config
        self.client.force_login(self.users[subject])
        response = self.client.post('/api/projects/', json.dumps({'title': subject}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        project_id = response.json()['id']
        config = f'<!-- AILAB task: {kind} -->' + label_config(kind, [{'name': 'object', 'color': '#22aa44'}])
        response = self.client.patch(f'/api/projects/{project_id}/', json.dumps({'label_config': config}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        Workspace.objects.filter(project_id=project_id).update(ratios=[100, 0, 0])
        return project_id

    def bridge(self, subject, action, payload):
        return self.client.post('/ailab/internal/' + action + '/', json.dumps(payload), content_type='application/json',
                                HTTP_AUTHORIZATION='Bearer test-only-bridge-secret', HTTP_X_AILAB_USER=subject)

    def upload(self, subject):
        from urllib.parse import urlencode
        output = io.BytesIO()
        Image.new('RGB', (16, 12), '#ffaa00').save(output, format='PNG')
        content = output.getvalue()
        query = urlencode({'project': self.projects[subject], 'sha256': hashlib.sha256(content).hexdigest(), 'filename': 'image.png'})
        response = self.client.post('/ailab/internal/image-upload/?' + query, content, content_type='image/png',
                                    HTTP_AUTHORIZATION='Bearer test-only-bridge-secret', HTTP_X_AILAB_USER=subject)
        self.assertEqual(response.status_code, 200, response.content)
        return ImageRecord.objects.get(pk=response.json()['id'])

    def test_project_and_media_isolation(self):
        image = self.upload('bob')
        self.client.force_login(self.users['alice'])
        for path in (f'/projects/{self.projects["bob"]}/data/', f'/api/projects/{self.projects["bob"]}/',
                     f'/api/tasks/{image.task_id}/', image.upload.url,
                     '/api/users/', '/api/organizations/', '/api/storages/localfiles/'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.bridge('alice', 'project', {'project': self.projects['bob']}).status_code, 404)
        self.assertEqual(self.client.get(f'/api/projects/{self.projects["alice"]}/').status_code, 200)

    def test_submit_and_snapshot(self):
        image = self.upload('alice')
        self.client.force_login(self.users['alice'])
        result = [{'id': 'box-1', 'from_name': 'rectanglelabels', 'to_name': 'image', 'type': 'rectanglelabels',
                   'original_width': 16, 'original_height': 12, 'image_rotation': 0,
                   'value': {'x': 10, 'y': 10, 'width': 50, 'height': 50, 'rotation': 0, 'rectanglelabels': ['object']}}]
        response = self.client.post(f'/api/tasks/{image.task_id}/annotations/', json.dumps({'result': result}), content_type='application/json')
        self.assertEqual(response.status_code, 201, response.content)
        snapshot = self.bridge('alice', 'snapshot', {'project': self.projects['alice'], 'operation': str(uuid.uuid4())})
        self.assertEqual(snapshot.status_code, 200, snapshot.content)
        self.assertEqual(snapshot.json()['total'], 1)
        self.assertEqual(self.bridge('bob', 'snapshot-page', {'snapshot': snapshot.json()['snapshot']}).status_code, 404)

    def test_bridge_requires_secret_and_inactive_account_cannot_browse(self):
        self.assertEqual(self.client.post('/ailab/internal/project/', '{}', content_type='application/json').status_code, 401)
        self.client.force_login(self.users['alice'])
        Identity.objects.filter(subject='alice').update(disabled=True)
        self.assertEqual(self.client.get(f'/api/projects/{self.projects["alice"]}/').status_code, 403)

    def test_activation_keeps_authenticated_session_and_cannot_be_replayed(self):
        link = self.bridge('new-user', 'activate-link', {'email': 'new@example.com'}).json()['url']
        ticket = link.split('#')[1]
        payload = {'ticket': ticket, 'new_password1': 'Integration-private-84312!', 'new_password2': 'Integration-private-84312!'}
        self.assertEqual(self.client.post('/ailab/activate/', payload).status_code, 302)
        self.assertEqual(self.client.get('/api/current-user/whoami').status_code, 200)
        replay = self.client.post('/ailab/activate/', payload)
        self.assertContains(replay, 'expired or was already used')

    def test_anonymous_requests_do_not_replace_login_session(self):
        response = self.client.get('/health/')
        self.assertNotIn('ailab_label_session', response.cookies)

    def test_cross_owner_writes_and_references_are_rejected(self):
        from tasks.models import Annotation, AnnotationDraft
        from data_manager.models import View
        own = self.upload('alice')
        other = self.upload('bob')
        annotation = Annotation.objects.create(task=other.task, project=other.task.project,
                                               completed_by=self.users['bob'], result=[])
        draft = AnnotationDraft.objects.create(task=other.task, user=self.users['bob'], result=[])
        view = View.objects.filter(project_id=self.projects['bob']).first()
        self.client.force_login(self.users['alice'])
        for path in (f'/api/tasks/{other.task_id}/annotations/', f'/api/annotations/{annotation.pk}/',
                     f'/api/drafts/{draft.pk}/', f'/api/dm/views/{view.pk}/'):
            for method in ('post', 'patch', 'delete'):
                with self.subTest(path=path, method=method):
                    response = getattr(self.client, method)(path, '{}', content_type='application/json')
                    self.assertEqual(response.status_code, 404)
        for field, value in [('parent_annotation', annotation.pk), ('draft_id', draft.pk), ('view', view.pk)]:
            response = self.client.post(f'/api/tasks/{own.task_id}/annotations/',
                                        json.dumps({'result': [], field: value}), content_type='application/json')
            self.assertEqual(response.status_code, 404)
        self.assertTrue(Annotation.objects.filter(pk=annotation.pk).exists())

    def test_session_write_requires_csrf(self):
        from django.test import Client
        image = self.upload('alice')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.users['alice'])
        response = client.post(f'/api/tasks/{image.task_id}/annotations/', '{"result": []}', content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_invalid_class_value_is_validation_error(self):
        from rest_framework.exceptions import ValidationError
        from .signals import validate_result
        image = self.upload('alice')
        with self.assertRaises(ValidationError):
            validate_result([{'type': 'rectanglelabels', 'value': {'rectanglelabels': [{}]}}], image.workspace, image)

    def test_brush_masks_are_decodable_before_saving(self):
        import numpy as np
        from label_studio_sdk.converter.brush import mask2rle
        from rest_framework.exceptions import ValidationError
        from .signals import validate_result
        image = self.upload('alice')
        workspace = image.workspace
        workspace.kind = 'semantic_segmentation'
        rle = mask2rle(np.full((12, 16), 255, dtype=np.uint8))
        region = {'id': 'brush', 'type': 'brushlabels', 'original_width': 16, 'original_height': 12,
                  'value': {'brushlabels': ['object'], 'rle': rle}}
        validate_result([region], workspace, image)
        region['value']['rle'] = rle[:7]
        with self.assertRaises(ValidationError):
            validate_result([region], workspace, image)

    def test_brush_snapshot_download_preserves_pixels(self):
        import numpy as np
        from label_studio_sdk.converter.brush import mask2rle
        for kind in ('semantic_segmentation', 'instance_segmentation'):
            project_id = self.create_project('alice', kind)
            self.projects['alice'] = project_id
            image = self.upload('alice')
            mask = np.zeros((12, 16), dtype=np.uint8)
            mask[2:8, 3:10] = 255
            result = [{'id': 'brush', 'type': 'brushlabels', 'from_name': 'brushlabels', 'to_name': 'image',
                       'original_width': 16, 'original_height': 12,
                       'value': {'brushlabels': ['object'], 'format': 'rle', 'rle': mask2rle(mask)}}]
            self.client.force_login(self.users['alice'])
            from copy import deepcopy
            from .signals import validate_result
            from rest_framework.exceptions import ValidationError
            draft = deepcopy(result)
            draft[0]['value'].pop('rle')
            draft[0]['value']['touches'] = [{'id': 'stroke', 'type': 'add', 'points': [3, 2, 10, 8],
                'relativePoints': [18.75, 16.67, 62.5, 66.67], 'strokeWidth': 4,
                'relativeStrokeWidth': 25, 'eraserSize': 25}]
            response = self.client.post(f'/api/tasks/{image.task_id}/drafts', json.dumps({'result': draft}), content_type='application/json')
            self.assertEqual(response.status_code, 201, response.content)
            from tasks.models import AnnotationDraft
            self.assertEqual(AnnotationDraft.objects.get(task_id=image.task_id).result, draft)
            with self.assertRaises(ValidationError):
                validate_result(draft, image.workspace, image)
            invalid = deepcopy(draft)
            invalid[0]['value']['touches'][0]['points'] = [float('nan'), 2]
            with self.assertRaises(ValidationError):
                validate_result(invalid, image.workspace, image, draft=True)
            # Existing RLE plus new strokes is also a valid fast autosave.
            draft[0]['value']['rle'] = mask2rle(mask)
            validate_result(draft, image.workspace, image, draft=True)
            AnnotationDraft.objects.filter(task_id=image.task_id).delete()
            response = self.client.post(f'/api/tasks/{image.task_id}/annotations/', json.dumps({'result': result}), content_type='application/json')
            self.assertEqual(response.status_code, 201, response.content)
            snapshot = self.bridge('alice', 'snapshot', {'project': project_id, 'operation': str(uuid.uuid4())}).json()
            response = self.bridge('alice', 'mask-download', {'snapshot': snapshot['snapshot'], 'image': image.pk, 'region': 'brush'})
            self.assertEqual(response.status_code, 200)
            with Image.open(io.BytesIO(b''.join(response.streaming_content))) as decoded:
                self.assertTrue(np.array_equal(np.array(decoded), mask))
