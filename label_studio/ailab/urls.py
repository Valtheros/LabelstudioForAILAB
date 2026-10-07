from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from . import views, native


urlpatterns = [
    path('api/projects/', native.Projects.as_view()),
    path('api/projects/<int:pk>/', native.ProjectSettings.as_view()),
    path('api/projects/<int:pk>/import', native.ImportImages.as_view()),
    path('api/templates/', native.Templates.as_view()),
    path('ailab/projects/<int:pk>/operations/', native.ImportStatus.as_view()),
    path('ailab/projects/<int:pk>/operations/<uuid:operation_id>/<str:action>/', native.ImportAction.as_view()),
    path('ailab/projects/<int:pk>/send/', native.send_to_ailab),
    path('user/login/', views.user_login, name='ailab_login'),
    path('ailab/activate/', views.activate),
    path('ailab/internal/<str:action>/', views.internal),
    path('ailab/account/', views.PasswordChange.as_view(template_name='ailab/form.html', extra_context={'title': 'Change password'}), name='ailab_account'),
    path('ailab/reset/', views.PasswordReset.as_view(template_name='ailab/form.html', email_template_name='ailab/reset_email.txt', subject_template_name='ailab/reset_subject.txt', success_url=reverse_lazy('ailab_reset_done'), extra_context={'title': 'Reset password'}), name='ailab_reset'),
    path('ailab/reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='ailab/form.html', extra_context={'title': 'Check your email'}), name='ailab_reset_done'),
    path('ailab/reset/confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='ailab/form.html', success_url=reverse_lazy('ailab_reset_complete'), extra_context={'title': 'Set a new password'}), name='password_reset_confirm'),
    path('ailab/reset/complete/', auth_views.PasswordResetCompleteView.as_view(template_name='ailab/form.html', extra_context={'title': 'Password updated'}), name='ailab_reset_complete'),
    path('', include('core.urls')),
]
