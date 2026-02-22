#!/bin/bash
# Dev convenience: run radsim from source without pip install
# For production use, install with: pip install . && radsim
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="$SCRIPT_DIR" python3 -m radsim.cli "$@"
