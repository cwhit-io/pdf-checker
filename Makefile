# Makefile for pdf-checker FastAPI app

.PHONY: run dev lint format test clean

run:
	uvicorn app.main:app --reload

dev:
	uvicorn app.main:app --reload --port 8000

lint:
	ruff app

format:
	ruff format app

test:
	pytest

clean:
	rm -rf __pycache__ .pytest_cache
