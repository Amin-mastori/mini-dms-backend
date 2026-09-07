# Contributing

Contributions should preserve the project's security boundaries, API contract
and reproducible test workflow.

## Development workflow

1. Create a focused branch from the latest `main` revision.
2. Keep migrations, the OpenAPI contract and English documentation synchronized
   with behavioral changes.
3. Add tests for success, authorization and failure paths.
4. Run the quality suite before opening a pull request:

   ```bash
   docker compose --profile test run --build --rm test pytest --cov --cov-fail-under=90
   docker compose --profile test run --rm test ruff check .
   docker compose --profile test run --rm test ruff format --check .
   docker compose exec api python manage.py spectacular --validate --fail-on-warn
   ```

5. Explain design tradeoffs and production impact in the pull request. Do not
   commit `.env`, credentials, real documents, database dumps or generated
   runtime artifacts.

Report security issues according to [SECURITY.md](SECURITY.md), not through a
public issue.
