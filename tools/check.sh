#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m py_compile zavod/*.py
bash tools/selftest.sh
python -m unittest discover -s tests -p test_instagram.py
python -m unittest discover -s tests -p test_redo_code_replies.py
