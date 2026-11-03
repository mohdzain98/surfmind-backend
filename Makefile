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

admin:
	$(PYTHON) -m scripts.create_admin --username $(username)

format:
	$(VENV)/bin/black .

lint:
	$(VENV)/bin/ruff check .

check: format lint

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
