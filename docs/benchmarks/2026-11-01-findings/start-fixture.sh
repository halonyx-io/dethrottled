#!/bin/sh
set -e
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99
exec uvicorn fixture_browser:app --host 0.0.0.0 --port 19888
