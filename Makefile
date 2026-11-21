.PHONY: test seed install build run dev
test:
	cd backend && python3 -m pytest -q
seed:
	cd backend && python3 -m app.seed --db ../demo.db
install:
	pip install -r backend/requirements.txt && cd frontend && npm install
build:
	cd frontend && npm run build
# One command: build the UI and serve everything at http://localhost:8000
run: build
	cd backend && python3 -m uvicorn app.api:app --port 8000
# Two terminals for development: `make dev-api` and `make dev-ui` (UI on :5173, proxied to the API)
dev-api:
	cd backend && python3 -m uvicorn app.api:app --reload --port 8000
dev-ui:
	cd frontend && npm run dev
