#!/bin/sh
# Git pre-push hook: run the public-safety guard on the working tree AND on the whole history.
# Install (once, in your own clone):  cp tools/pre-push.sh .git/hooks/pre-push && chmod +x .git/hooks/pre-push
# For your own name and employers, keep a deny-list OUTSIDE the repo and export
#   DAJS_PRIVATE_DENYLIST=/path/to/denylist.txt      (one regex per line)
# before you push. Without it the guard still runs its built-in rules.
set -e
ROOT="$(git rev-parse --show-toplevel)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
if [ -z "$DAJS_PRIVATE_DENYLIST" ]; then
  echo "pre-push: note: DAJS_PRIVATE_DENYLIST is not set, so your own name and employers are not checked." >&2
fi
exec "$PY" "$ROOT/tools/public_safety_check.py" --root "$ROOT" --history
