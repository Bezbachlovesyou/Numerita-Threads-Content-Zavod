#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m unittest discover -s tests -p test_safety_followups.py
# Hard-code a dedicated local fixture: never point destructive tests at production.
DELIVERY_TEST_DSN='postgresql://postgres@/numerita_factory_safety?host=/tmp&port=5433' \
  python -m unittest discover -s tests -p test_safety_followups.py
