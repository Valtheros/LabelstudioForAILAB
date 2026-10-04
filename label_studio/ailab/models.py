import uuid

from django.conf import settings
from django.db import models


def default_ratios():
    return [80, 10, 10]


class Identity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ailab_identity')
    subject = models.CharField(max_length=255, unique=True)
    ticket_hash = models.CharField(max_length=64, blank=True, db_index=True)
    ticket_expires = models.DateTimeField(null=True)
    activated = models.BooleanField(default=False)
    disabled = models.BooleanField(default=False)


class Workspace(models.Model):
    project = models.OneToOneField('projects.Project', on_delete=models.CASCADE, related_name='ailab_workspace')
    identity = models.ForeignKey(Identity, on_delete=models.PROTECT)
    external_id = models.UUIDField(unique=True)
    kind = models.CharField(max_length=32)
    classes = models.JSONField(default=list)
    ratios = models.JSONField(default=default_ratios)
    seed = models.PositiveIntegerField(default=0)
    revision = models.PositiveBigIntegerField(default=0)
    deleted = models.BooleanField(default=False)


class ImageRecord(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='images')
    task = models.OneToOneField('tasks.Task', on_delete=models.CASCADE, related_name='ailab_image')
    upload = models.OneToOneField('data_import.FileUpload', on_delete=models.PROTECT)
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace', 'sha256'], name='ailab_unique_image_content')]


class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT)
    operation = models.UUIDField(unique=True)
    revision = models.PositiveBigIntegerField()
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class SnapshotImage(models.Model):
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE, related_name='images')
    image = models.ForeignKey(ImageRecord, on_delete=models.PROTECT)
    data = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['snapshot', 'image'], name='ailab_unique_snapshot_image')]
