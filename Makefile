format:
	uv run ruff format .

lint:
	uv run ruff check . --fix

typecheck:
	uv run mypy src/qgis_plugin_microcredito src/database src/cli src/installer

test:
	uv run pytest

build:
	uv run build

install:
	uv run install