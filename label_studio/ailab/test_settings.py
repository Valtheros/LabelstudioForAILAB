from .settings import *  # noqa: F403,F401

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
ALLOWED_HOSTS = [*ALLOWED_HOSTS, 'ailab-label-browser-test']
AILAB_URL = 'http://127.0.0.1:13000'
