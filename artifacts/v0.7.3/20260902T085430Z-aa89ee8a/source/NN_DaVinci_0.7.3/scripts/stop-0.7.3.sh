#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${NN_DAVINCI_PYTHON:-$PROJECT_DIR/../envs/python-tools/bin/python}"
exec "$PYTHON_BIN" "$PROJECT_DIR/scripts/service_lifecycle_0_7_3.py" stop "$@"
