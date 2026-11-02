#!/usr/bin/env bash
# Model weights (~1.2 GB), resumable and checksum-verified. Pass --samples for the public-domain
# clips used by tests. The same downloader (mouthpiece/weights.py, stdlib only) runs in the app.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=$(command -v python3)
"$PY" mouthpiece/weights.py models
if [[ "${1:-}" == "--samples" ]]; then
  "$PY" mouthpiece/weights.py --samples samples
fi
