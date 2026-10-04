"""AILAB private-workspace deployment of Label Studio 1.23.0."""
import os
from urllib.parse import urlsplit

from core.settings.base import *  # noqa: F403,F401
from core.utils.secret_key import generate_secret_key_if_missing

SECRET_KEY = generate_secret_key_if_missing(BASE_DATA_DIR)
DATABASES = {'default': DATABASES_ALL[get_env('DJANGO_DB', DJANGO_DB_SQLITE)]}
DEBUG = False
DEBUG_PROPAGATE_EXCEPTIONS = False
SENTRY_ENVIRONMENT = 'ailab'
FRONTEND_SENTRY_ENVIRONMENT = 'ailab'
FEATURE_FLAGS_DEFAULT_VALUE = True
FEATURE_FLAGS_OFFLINE = True
FEATURE_FLAGS_FILE = 'feature_flags.json'
FEATURE_FLAGS_FROM_FILE = True
STORAGE_PERSISTENCE = True
ADD_DEFAULT_ML_BACKENDS = False
LOGGING['root']['level'] = 'WARNING'

INSTALLED_APPS = [*INSTALLED_APPS, 'ailab.apps.AilabConfig']
ROOT_URLCONF = 'ailab.urls'
MIDDLEWARE = [m for m in MIDDLEWARE if m not in {
    'organizations.middleware.DummyGetSessionMiddleware',
    'jwt_auth.middleware.JWTAuthenticationMiddleware',
    'core.middleware.ContextLogMiddleware',
    'core.middleware.SetSessionUIDMiddleware',
    'core.middleware.DisableCSRF',
    'core.middleware.XApiKeySupportMiddleware',
}]
MIDDLEWARE.append('ailab.security.PrivateWorkspaceMiddleware')
REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'] = ('rest_framework.authentication.SessionAuthentication',)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'ailab_label_session'
CSRF_COOKIE_NAME = 'ailab_label_csrf'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 86400
CSRF_COOKIE_DOMAIN = None
AILAB_URL = os.environ.get('AILAB_PUBLIC_URL', 'http://172.25.2.135').rstrip('/')
LABEL_PUBLIC_URL = os.environ.get('LABEL_STUDIO_PUBLIC_URL', 'http://172.25.2.135:8080').rstrip('/')
SESSION_COOKIE_SECURE = LABEL_PUBLIC_URL.startswith('https://')
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [LABEL_PUBLIC_URL]
ALLOWED_HOSTS = [urlsplit(LABEL_PUBLIC_URL).hostname, 'label-studio', 'localhost', '127.0.0.1', 'testserver']
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
CORS_ALLOWED_ORIGIN_REGEXES = []
DATA_UPLOAD_MAX_MEMORY_SIZE = 32 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
FILE_UPLOAD_TEMP_DIR = os.path.join(BASE_DATA_DIR, 'tmp')
os.makedirs(FILE_UPLOAD_TEMP_DIR, exist_ok=True)
USE_NGINX_FOR_UPLOADS = False
LOCAL_FILES_SERVING_ENABLED = False
DISABLE_SIGNUP_WITHOUT_LINK = True
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('SMTP_HOST', '')
EMAIL_PORT = int(os.environ.get('SMTP_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('SMTP_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
EMAIL_USE_SSL = os.environ.get('SMTP_SECURE', '').lower() == 'true'
EMAIL_USE_TLS = not EMAIL_USE_SSL and EMAIL_PORT == 587
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.environ.get('AUTH_EMAIL_FROM', EMAIL_HOST_USER)
PASSWORD_RESET_TIMEOUT = 1800
SENTRY_DSN = ''
FRONTEND_SENTRY_DSN = ''
COLLECT_ANALYTICS = False
LATEST_VERSION_CHECK = False
DATA_MANAGER_CHECK_ACTION_PERMISSION = 'ailab.actions.check_action_permission'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                      'LOCATION': os.environ.get('LABEL_STUDIO_REDIS_URL', 'redis://redis:6379/4'),
                      'KEY_PREFIX': 'ailab-label'}}
