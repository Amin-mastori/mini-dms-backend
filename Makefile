.PHONY: init up down test lint schema smoke logs
init:
	python3 scripts/init_env.py
up:
	docker compose up --build -d --wait --wait-timeout 180
down:
	docker compose down
test:
	docker compose --profile test run --build --rm test pytest --cov --cov-fail-under=90
lint:
	docker compose --profile test run --build --rm test ruff check .
schema:
	docker compose exec api python manage.py spectacular --validate --fail-on-warn
smoke:
	docker compose --profile test run --build --rm test python scripts/smoke_test.py
logs:
	docker compose logs -f api worker dispatcher
