.PHONY: install playground test lint generate-traces grade

install:
	uv sync --link-mode=copy

playground:
	uv run python -m expense_agent.fast_api_app

test:
	uv run pytest

lint:
	uv run ruff check .

generate-traces:
	uv run python tests/eval/generate_traces.py

grade:
	uv run python tests/eval/grade_traces.py
