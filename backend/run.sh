#!/usr/bin/env bash
# One-command start. Creates the venv, installs, seeds, serves.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "==> creating venv"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> installing dependencies"
pip install -q -r requirements.txt

if [ ! -f ner_ews.db ] || [ "${RESEED:-0}" = "1" ]; then
  echo "==> seeding database"
  python -m app.seed
fi

echo "==> serving on http://localhost:8000  (docs: /docs)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
