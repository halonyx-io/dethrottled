#!/bin/sh
set -eu
python - <<'PY'
from pathlib import Path
for name in ('/tmp/.X99-lock', '/tmp/.X11-unix/X99'):
    Path(name).unlink(missing_ok=True)
PY
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
sleep 1
exec uvicorn dnb_service:app --host 0.0.0.0 --port 19888
