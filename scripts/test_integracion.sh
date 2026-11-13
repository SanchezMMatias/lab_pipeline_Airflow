#!/usr/bin/env bash
# Corre tests/test_idempotencia.py dentro del worker contra el SQL Server del compose.
set -euo pipefail
cd "$(dirname "$0")/.."
D=/tmp/labtests_$(date +%s)   # directorio nuevo cada vez (ver docstring del test)
docker compose cp tests "airflow-worker:$D" > /dev/null
docker compose exec -T airflow-worker bash -c \
  "python -c 'import pytest' 2>/dev/null || pip install -q pytest; cd /tmp && python -B -m pytest -q -p no:cacheprovider $D/test_idempotencia.py"
