"""Closed public route surface plus object checks; UI hiding is not authorization."""
import json
import re
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse


def owns(user, project):
    if not user or not user.is_authenticated or not project:
        return False
    try:
        identity = user.ailab_identity
        workspace = project.ailab_workspace
        return (identity.activated and not identity.disabled and not workspace.deleted
                and workspace.identity_id == identity.pk
                and project.organization_id == user.active_organization_id
                and project.organization.created_by_id == user.pk)
    except ObjectDoesNotExist:
        return False


class PrivateWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith(('/static/', '/react-app/', '/dm/', '/label-studio-frontend/', '/ailab/internal/')) or path in {
            '/health/', '/favicon.ico', '/user/login/', '/ailab/activate/', '/ailab/reset/', '/ailab/reset/done/',
            '/ailab/reset/complete/',
        } or path.startswith('/ailab/reset/confirm/'):
            return self.get_response(request)
        if not request.user.is_authenticated:
            if path.startswith(('/api/', '/data/', '/storage-data/')):
                return JsonResponse({'detail': 'Authentication required.'}, status=401)
            return HttpResponseRedirect(reverse('ailab_login') + '?' + urlencode({'next': request.get_full_path()}))
        try:
            identity = request.user.ailab_identity
            if not identity.activated or identity.disabled:
                raise ObjectDoesNotExist
        except ObjectDoesNotExist:
            return JsonResponse({'detail': 'Account is not active.'}, status=403)
        request.session['organization_pk'] = request.user.active_organization_id
        if path == '/':
            return HttpResponseRedirect(reverse('projects:project-index'))
        if path in {'/projects/', '/api/templates/', '/api/projects/validate/', '/heidi-tips', '/heidi-tips/'}:
            return self.get_response(request)
        if path == '/api/projects/':
            if request.method not in {'GET', 'HEAD', 'POST'}:
                return JsonResponse({'detail': 'Method not allowed.'}, status=405)
            if request.method == 'POST':
                try:
                    body = json.loads(request.body)
                    if not isinstance(body, dict) or any(k in body for k in ('created_by', 'organization', 'organization_id', 'members')):
                        raise ValueError()
                except (ValueError, TypeError):
                    return JsonResponse({'detail': 'Invalid project request.'}, status=400)
            return self.get_response(request)
        if path in {'/logout/', '/logout', '/api/current-user/whoami', '/api/current-user/product-tour',
                    '/api/current-user/hotkeys/', '/api/version/', '/version/', '/feature-flags/'}:
            return self.get_response(request)
        if path.startswith('/user/account'):
            return HttpResponseRedirect(reverse('ailab_account'))
        if path == '/ailab/account/':
            return self.get_response(request)
        try:
            project = self.resolve_project(request)
            if not project or not owns(request.user, project):
                return JsonResponse({'detail': 'Not found.'}, status=404)
            self.check_body(request, project)
            # Serialize annotation changes and snapshots on the same project row.
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not path.endswith('/import'):
                from .models import Workspace
                with transaction.atomic():
                    Workspace.objects.select_for_update().get(project=project)
                    return self.get_response(request)
            return self.get_response(request)
        except (ValueError, TypeError, KeyError, ObjectDoesNotExist):
            return JsonResponse({'detail': 'Not found or invalid project reference.'}, status=404)

    @staticmethod
    def resolve_project(request):
        from projects.models import Project
        from tasks.models import Task, Annotation, AnnotationDraft, Prediction
        from data_manager.models import View
        from data_import.models import FileUpload
        path = request.path_info
        match = re.fullmatch(r'/ailab/projects/(\d+)/operations/[0-9a-f-]{36}/(?:retry|cancel)/', path)
        if match and request.method == 'POST':
            return Project.objects.get(pk=match[1])
        match = re.fullmatch(r'/ailab/projects/(\d+)/(?:send|operations)/', path)
        if match and request.method == 'GET':
            return Project.objects.get(pk=match[1])
        if path.rstrip('/') in {'/api/users', '/api/ml', '/api/label_links'} and request.method in {'GET', 'HEAD'}:
            pk = request.GET.get('project')
            return Project.objects.get(pk=int(pk)) if pk else None
        match = re.fullmatch(r'/projects/(\d+)/(?:data/?|settings/(?:[^/]+)?)?', path)
        if match:
            return Project.objects.get(pk=match[1])
        match = re.fullmatch(r'/api/projects/(\d+)/(?:import|validate/|sample-task/)?', path)
        if match:
            return Project.objects.get(pk=match[1])
        match = re.fullmatch(r'/api/projects/(\d+)/(?:next/|tasks/|summary/|label-stream-history/|annotators/|model-versions/|file-uploads)?', path)
        if match and request.method in {'GET', 'HEAD'}:
            return Project.objects.get(pk=match[1])
        match = re.fullmatch(r'/api/tasks/(\d+)/(?:annotations/|drafts|annotations/(\d+)/drafts|agreement/)?', path)
        if match:
            if request.method not in {'GET', 'HEAD'} and path.rstrip('/').endswith(match[1]):
                return None  # No task reassignment or raw data mutation through upstream API.
            task = Task.objects.get(pk=match[1])
            if match[2] and not Annotation.objects.filter(pk=match[2], task=task).exists():
                return None
            return task.project
        match = re.fullmatch(r'/api/(annotations|drafts)/(\d+)/(?:convert-to-draft)?', path)
        if match:
            model = Annotation if match[1] == 'annotations' else AnnotationDraft
            return model.objects.select_related('task__project').get(pk=match[2]).task.project
        match = re.fullmatch(r'/api/dm/views/(\d+)/', path)
        if match:
            return View.objects.get(pk=match[1]).project
        if path in {'/api/tasks/', '/api/dm/views/', '/api/dm/views/order/', '/api/dm/views/reset/',
                    '/api/dm/columns/', '/api/dm/project/', '/api/dm/actions/'}:
            body = json.loads(request.body) if request.content_type == 'application/json' and request.body else {}
            pk = request.GET.get('project') or body.get('project')
            if pk:
                return Project.objects.get(pk=int(pk))
            view = request.GET.get('view')
            if view:
                return View.objects.get(pk=int(view)).project
            return None
        if path.startswith('/data/upload/') and request.method in {'GET', 'HEAD'}:
            return FileUpload.objects.get(file=path.removeprefix('/data/').rstrip('/')).project
        if path == '/storage-data/uploaded/' and request.method in {'GET', 'HEAD'}:
            return FileUpload.objects.get(file=request.GET.get('filepath', '')).project
        return None

    @staticmethod
    def check_body(request, project):
        from tasks.models import Task, Annotation, AnnotationDraft, Prediction
        from data_manager.models import View
        params = dict(request.GET.items())
        if request.content_type == 'application/json' and request.body:
            body = json.loads(request.body)
            if not isinstance(body, dict):
                raise ValueError('Object required')
            params.update(body)
        for key in ('project', 'project_id'):
            if key in params and int(params[key]) != project.pk:
                raise ValueError('Project mismatch')
        for key, model in [('task', Task), ('task_id', Task), ('annotation', Annotation), ('view', View), ('draft', AnnotationDraft),
                           ('draft_id', AnnotationDraft), ('parent_annotation', Annotation), ('parent_prediction', Prediction)]:
            if params.get(key) not in (None, 0, '0'):
                obj = model.objects.get(pk=int(params[key]))
                parent = obj.task.project_id if model in (AnnotationDraft, Annotation) else obj.project_id
                if parent != project.pk:
                    raise ValueError('Cross-project reference')
        for key in ('completed_by', 'created_by', 'members', 'user', 'user_id', 'updated_by', 'organization', 'organization_id'):
            if key in params:
                raise ValueError('Identity fields are server-owned')
