.PHONY: test seed
test:
	cd backend && python3 -m pytest -q
seed:
	cd backend && python3 -m app.seed --db ../demo.db
