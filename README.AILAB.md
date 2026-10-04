# AILAB Private Label Studio

This is a separate Apache-2.0 fork of Label Studio 1.23.0, not the native
AILAB Annotation version. Keep the upstream LICENSE and notices.

## Accounts and ownership

Verified AILAB users activate a separate password through `/annotate`.
Activation links are single-use and expire after ten minutes. Each account
has its own organization. Public signup, organization management,
API tokens and storage connectors are closed. Users create private projects,
configure the four image task types and import images or ZIPs in Label Studio.
The fork builds its own frontend, rather than redirecting project menus to AILAB.
Send to AILAB prepares an Import Preview; only confirmation registers a dataset.
Ownership checks run before the upstream views, including media, drafts,
Data Manager actions and annotation references. Do not remove this middleware.

## Deployment

Build `Dockerfile.ailab`; do not deploy the unmodified upstream image.
Use the deploy repository's `docker-compose.prod.yml`. Before first startup,
run `backend/scripts/setup_label_studio.py` in the backend image with the
deploy environment file mounted at `/deploy/.env.production`. It adds secrets
without displaying them and creates a separate PostgreSQL database/role.
The backend migration is additive: `scripts/apply_label_studio_schema.py`.
Label Studio applies its own Django migrations on startup.

Required environment names are `LABEL_STUDIO_DB`, `LABEL_STUDIO_DB_USER`,
`LABEL_STUDIO_DB_PASSWORD`, `LABEL_STUDIO_BRIDGE_SECRET`,
`LABEL_STUDIO_PUBLIC_URL` and `AILAB_PUBLIC_URL`. SMTP settings are shared
with AILAB for password reset, not account credentials. Never deploy
`ailab.test_settings` or test credentials.

The public proxy MUST deny `/ailab/internal` and `/ailab/internal/*`.
Only the backend and CPU worker receive the bridge secret. No public port
is published directly from the Label Studio container. LAN HTTP is for a
trusted LAN only: use separate HTTPS hostnames and update public URLs and
CSRF origins before exposing accounts outside the LAN.

The CPU worker consumes only `label_studio`, with concurrency one and a 1 GB
memory limit. Label Studio is capped at 2 GB. GPU training uses its existing
queue. PostgreSQL owns operation state; Redis loss is recoverable. A database
advisory lock prevents duplicate execution even when an RQ job is lost.
After three interrupted executions, automatic recovery stops until an explicit
retry. Caddy authenticates ZIP requests via `/api/internal/upload-auth` and
streams their bodies directly to the backend. The Next.js proxy must not handle
these large bodies: its request cloning can otherwise buffer the whole upload.

## Data and recovery

Back up BOTH PostgreSQL databases, the `label_studio_data` volume and AILAB's
dataset/run directories. Back up deployment configuration and image IDs before
cutover. Retain the previous frontend/backend/training worker images and the
native annotation data for rollback. Do not run `compose down -v`.

Publication freezes submitted annotations, validates the exported format,
then stages a preview. Confirmation atomically publishes an immutable `-vN`
dataset; cancelling removes only the preview, not the Label Studio project.
Unaccepted previews expire after seven days. A retry reuses its frozen
snapshot. Completed snapshots are released hourly. Failed/cancelled ZIPs are
kept seven days for retry, then deleted. Imported images remain after cancel.
Project deletion is a soft delete: media is intentionally retained for operator
recovery; it is inaccessible through public APIs. Published datasets survive.

Classification exports ImageFolder, detection exports COCO boxes (converted
for YOLO), semantic exports indexed PNG masks, and instance exports COCO
polygons/RLE. YOLO requires a nonempty validation split. Empty submitted
annotations are negative samples except in classification. Drafts block publish.
Images are limited to 25 million pixels, and combined brush masks to 100 million
pixels per image; use polygons or smaller source images for larger brush workloads.

## Verification

Run Django tests against an ISOLATED PostgreSQL database, never production:
`DJANGO_SETTINGS_MODULE=ailab.test_settings python manage.py test ailab.tests`.
The test settings use a fast password hasher and must not serve real users.
Run backend tests with an empty `DATABASE_URL` for the unit-test suite:
`DATABASE_URL= python -m unittest discover -s tests`.
Browser and train smoke checks must use separate test media and databases.
