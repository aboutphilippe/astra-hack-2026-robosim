.PHONY: setup dev api web test build server
setup:
	uv sync
	cd web && npm ci
api:
	uv run nono-api
web:
	cd web && npm run dev -- --host 127.0.0.1
dev:
	uv run python scripts/dev.py
test:
	uv run pytest
build:
	cd web && npm run build
server:
	uv run nono-server
