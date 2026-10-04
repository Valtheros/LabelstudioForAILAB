import base64
import binascii
import io
import math

from PIL import Image

from django.db.models import F
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from rest_framework.exceptions import ValidationError
from tasks.models import Annotation, AnnotationDraft, Task

from .models import Workspace


def validate_result(result, workspace, image, *, draft=False):
    if not isinstance(result, list) or len(result) > 5000:
        raise ValidationError('At most 5000 regions are allowed per image.')
    labels = {item['name'] for item in workspace.classes}
    points = 0
    brush_bytes = 0
    brush_pixels = 0
    if any(not isinstance(region, dict) or not isinstance(region.get('value'), dict) for region in result):
        raise ValidationError('Each region must be an object with a value.')
    if workspace.kind == 'image_classification' and result:
        if len(result) != 1:
            raise ValidationError('Select exactly one class.')
    seen = set()
    for region in result:
        kind, value = region.get('type'), region.get('value', {})
        allowed = {'image_classification': {'choices'}, 'object_detection': {'rectanglelabels'},
                   'semantic_segmentation': {'polygonlabels', 'brushlabels'},
                   'instance_segmentation': {'polygonlabels', 'brushlabels'}}[workspace.kind]
        if not isinstance(kind, str) or kind not in allowed or not isinstance(value, dict):
            raise ValidationError('Region type does not match this project.')
        selected = value.get(kind, [])
        if not isinstance(selected, list) or len(selected) != 1 or not isinstance(selected[0], str) or selected[0] not in labels:
            raise ValidationError('Every region must have one project class.')
        if kind == 'choices':
            continue
        region_id = region.get('id')
        if not isinstance(region_id, str) or not region_id or len(region_id) > 128 or region_id in seen:
            raise ValidationError('Region IDs must be unique.')
        seen.add(region_id)
        if (region.get('original_width') != image.width or region.get('original_height') != image.height
                or region.get('image_rotation', 0) != 0):
            raise ValidationError('Region dimensions must match the original image; image rotation is disabled.')
        def number(v, upper=100):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= upper:
                raise ValidationError('Coordinates must be finite and inside the image.')
        if kind == 'rectanglelabels':
            for key in ('x', 'y', 'width', 'height'):
                number(value.get(key))
            if value['width'] <= 0 or value['height'] <= 0 or value['x'] + value['width'] > 100.001 or value['y'] + value['height'] > 100.001 or value.get('rotation', 0) != 0:
                raise ValidationError('Boxes must have positive size, no rotation, and stay inside the image.')
        elif kind == 'polygonlabels':
            polygon = value.get('points', [])
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise ValidationError('A polygon requires at least three points.')
            points += len(polygon)
            if points > 250000:
                raise ValidationError('Too many polygon points in this image.')
            for point in polygon:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValidationError('Invalid polygon point.')
                number(point[0]); number(point[1])
        else:
            rle = value.get('rle')
            # Label Studio fast autosave keeps unflattened strokes alongside an optional base mask.
            if draft:
                touches = value.get('touches', [])
                if not isinstance(touches, list) or len(touches) > 5000:
                    raise ValidationError('Too many brush strokes.')
                for stroke in touches:
                    if not isinstance(stroke, dict) or stroke.get('type') not in ('add', 'eraser'):
                        raise ValidationError('Invalid brush stroke.')
                    for key in ('points', 'relativePoints'):
                        coords = stroke.get(key)
                        if not isinstance(coords, list) or len(coords) % 2:
                            raise ValidationError('Invalid brush stroke points.')
                        points += len(coords) // 2
                        if points > 250000:
                            raise ValidationError('Too many brush points in this image.')
                        # Canvas strokes may cross the image edge; rendering clips them.
                        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1_000_000 for v in coords):
                            raise ValidationError('Invalid brush stroke coordinates.')
                    for key in ('strokeWidth', 'relativeStrokeWidth', 'eraserSize'):
                        number(stroke.get(key, 25), 1_000_000)
                mask = value.get('maskDataURL')
                if mask is not None:
                    if not isinstance(mask, str) or not mask.startswith('data:image/png;base64,') or len(mask) > 11_000_000:
                        raise ValidationError('Invalid draft mask image.')
                    try:
                        raw = base64.b64decode(mask.split(',', 1)[1], validate=True)
                        brush_bytes += len(raw)
                        with Image.open(io.BytesIO(raw)) as png:
                            if png.format != 'PNG' or png.size != (image.width, image.height):
                                raise ValueError('Mask dimensions do not match.')
                            png.verify()
                    except (ValueError, OSError, binascii.Error) as exc:
                        raise ValidationError('Invalid draft mask image.') from exc
                if brush_bytes > 8_000_000:
                    raise ValidationError('Combined brush masks exceed 8 MB.')
                if rle is None and (touches or mask):
                    continue
            elif value.get('touches') or value.get('maskDataURL'):
                raise ValidationError('Submit a flattened brush mask, not draft strokes.')
            if not isinstance(rle, list) or not 7 <= len(rle) <= 8_000_000:
                raise ValidationError('Invalid or oversized brush mask.')
            if any(type(byte) is not int or not 0 <= byte <= 255 for byte in rle):
                raise ValidationError('Invalid brush mask bytes.')
            brush_bytes += len(rle)
            if brush_bytes > 8_000_000 or rle[4] >> 3 != 7:
                raise ValidationError('Brush masks must use 8-bit values and total at most 8 MB per image.')
            if int.from_bytes(bytes(rle[:4]), 'big') != image.width * image.height * 4:
                raise ValidationError('Brush mask dimensions do not match the image.')
            brush_pixels += image.width * image.height
            if brush_pixels > 100_000_000:
                raise ValidationError('Combined brush masks exceed 100 million pixels. Use polygons or smaller images.')
            from label_studio_sdk.converter.brush import decode_rle
            try:
                decode_rle(rle)
            except (ValueError, IndexError, OverflowError) as exc:
                raise ValidationError('The brush mask is incomplete or malformed.') from exc


@receiver(pre_save, sender=Annotation)
@receiver(pre_save, sender=AnnotationDraft)
def check_annotation(sender, instance, **kwargs):
    if not instance.task_id:
        raise ValidationError('A task is required.')
    workspace = Workspace.objects.filter(project_id=instance.task.project_id).first()
    if workspace is None:
        raise ValidationError('This project is not an AILAB workspace.')
    user_id = instance.completed_by_id if sender is Annotation else instance.user_id
    if user_id != workspace.identity.user_id:
        raise ValidationError('Only the owner can annotate this image.')
    validate_result(instance.result, workspace, instance.task.ailab_image, draft=sender is AnnotationDraft)
    if sender is Annotation and Annotation.objects.filter(task_id=instance.task_id).exclude(pk=instance.pk).exists():
        raise ValidationError('Edit the existing annotation instead of creating a second answer.')


@receiver(post_save, sender=Annotation)
@receiver(post_delete, sender=Annotation)
@receiver(post_save, sender=Task)
def bump_revision(sender, instance, **kwargs):
    Workspace.objects.filter(project_id=instance.project_id).update(revision=F('revision') + 1)
