.PHONY: venv install run migrate admin format lint check clean license license-check

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

admin:
	$(PYTHON) -m scripts.create_admin --username $(username)

format:
	$(VENV)/bin/black .

lint:
	$(VENV)/bin/ruff check .

check: format lint

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +

# Add the licence header to src/ and scripts/ .py files, or update an
# outdated one after HEADER in scripts/add_license_header.py changes.
license:
	$(PYTHON) scripts/add_license_header.py

# Report missing/outdated headers without changing anything; exits 1 if any.
license-check:
	$(PYTHON) scripts/add_license_header.py --check
