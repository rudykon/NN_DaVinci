#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 0.2.3 deliberately keeps nightly as an alias. Full already executes canonical
# matrix/post-seal parity mutations plus the composite mutation suite,
# 100-seed SCC differential, 20-distribution spatial adversaries, clean Python
# package installs and a clean npm ci. Nightly adds zero workloads and is never
# counted as independent coverage.
exec "$PROJECT_DIR/scripts/verify-full.sh"
