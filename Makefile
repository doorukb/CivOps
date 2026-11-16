# Despatch: one-command tasks. Run `make help` for the list.
# Works on macOS and Linux. On Windows use the commands in the README.

PY := backend/.venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help setup dev backend frontend demo test lint eval-check clean

help: ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

setup: ## Create the virtualenv and install backend and frontend dependencies
	python3 -m venv backend/.venv
	$(PY) -m pip install -q -r backend/requirements-dev.txt
	cd frontend && npm ci
	@test -f backend/.env || cp backend/.env.example backend/.env
	@echo "Done. Optional: put your API keys in backend/.env (the scripted calls work without them)."

dev: ## Run backend and frontend together (Ctrl-C stops both)
	@$(MAKE) -j2 backend frontend

backend: ## Backend with auto-reload on http://127.0.0.1:8000
	cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend: ## Frontend on http://localhost:5173
	cd frontend && npm run dev

demo: ## Backend without auto-reload, bound to localhost (use this on demo day)
	cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

test: ## All tests: backend (pytest) and frontend (vitest). No paid API calls.
	cd backend && .venv/bin/python -m pytest -q --cov=app --cov-report=term
	cd frontend && npm test

lint: ## Ruff, ESLint and the TypeScript build
	cd backend && .venv/bin/ruff check app scripts eval tests
	cd frontend && npm run lint && npm run build

eval-check: ## Validate the evaluation case files (free; makes no paid calls)
	cd backend && .venv/bin/python -m eval.missed_escalations --check
	cd backend && .venv/bin/python -m eval.bias_pairs --check
	cd backend && .venv/bin/python -m eval.escalation_v2 --check
	cd backend && .venv/bin/python -m eval.bias_pairs_v2 --check
	cd backend && .venv/bin/python -m eval.extraction_accuracy --check

clean: ## Remove caches, build output and the local call log
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.coverage backend/data frontend/dist
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
