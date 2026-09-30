"""Operator-only diagnostics: docker compose exec faf-analyzer python -m app.diagnostics."""
import json
import os
from .store import Store


def main():
    store = Store(os.getenv('DATABASE_PATH', 'data/faf.sqlite3'))
    print(json.dumps({'configuration_error': store.policy()['error'],
                      'files': [{key: value for key, value in row.items() if key != 'roster'}
                                for row in store.files()]}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
