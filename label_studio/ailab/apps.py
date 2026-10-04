from django.apps import AppConfig


class AilabConfig(AppConfig):
    name = 'ailab'
    default_auto_field = 'django.db.models.AutoField'

    def ready(self):
        from . import actions, signals  # noqa: F401
