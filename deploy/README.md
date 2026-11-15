# Deploy — systemd units

Not auto-installed by the GitHub Actions deploy workflows
(`.github/workflows/main.yml`/`staging.yml`) — those only restart the
existing `surfmind.service`/`surfmind-staging.service` (the FastAPI app).
The Celery worker (background page classification, `src/celery_app.py`)
needs its own systemd unit, installed once by hand on each server.

## Install (prod or staging)

```bash
# on the server, as whatever user can sudo:
sudo cp deploy/surfmind-celery.service /etc/systemd/system/
# (staging: sudo cp deploy/surfmind-celery-staging.service /etc/systemd/system/)

sudo systemctl daemon-reload
sudo systemctl enable --now surfmind-celery.service
# (staging: surfmind-celery-staging.service)
```

Paths are already filled in, matching the real checkout layout the
deploy workflows use — `/home/zain/surfmind/surfmind-backend` (prod) and
`/home/zain/surfmind/surfmind-backend-staging` (staging), both via
`senv/`. Nothing to edit before copying unless that layout changes.

## After that, deploys don't need to touch it

New code (including new/changed Celery tasks) arrives via the existing
`git reset --hard` + restart flow in the deploy workflows — once this
unit is enabled, a `sudo systemctl restart surfmind-celery.service`
(add this to the deploy workflow's restart step if you want it to pick
up changes automatically; not done here since that's a workflow change,
not a systemd one) picks up new code the same way the app service does.

## Checking it's running

```bash
sudo systemctl status surfmind-celery.service
journalctl -u surfmind-celery.service -f
```

A successful start logs `[tasks] . classify_pages_task` and `Connected to
redis://...` — same Redis instance the app already uses as broker/result
backend (`src/celery_app.py`), no new infra.
