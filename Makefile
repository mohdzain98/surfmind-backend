.PHONY: venv install run migrate admin format lint check clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3.11 -m venv $(VENV)

install:
	$(PIP) install -r requirements.txt

migrate:
	$(VENV)/bin/alembic upgrade head

run:
	$(VENV)/bin/uvicorn src.controller.main_controller:app --reload --host 0.0.0.0 --port 8000

# --pool=solo: macOS's multiprocessing defaults to "spawn", which breaks
# Celery's prefork pool ("not enough values to unpack" in fast_trace_task).
# Linux (where the deploy/ systemd units actually run) doesn't hit this —
# solo is a local-dev-only workaround, not needed in deploy/.
celery:
	$(VENV)/bin/celery -A src.celery_app worker --loglevel=info --pool=solo

admin:
	$(PYTHON) -m scripts.create_admin --username $(username)

format:
	$(VENV)/bin/black .

lint:
	$(VENV)/bin/ruff check .

check: format lint

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
