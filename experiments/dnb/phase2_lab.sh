#!/bin/sh
# Offline scope gate. Requires a built DNB image and no production mounts/ports.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
output=${1:?Usage: phase2_lab.sh OUTPUT_DIRECTORY}
mkdir -p "$output"
output=$(CDPATH= cd -- "$output" && pwd)
image=${DNB_IMAGE:-dethrottled-dnb:prototype}
network="dnb-phase2-$$"
container="dnb-phase2-gate-$$"
cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM
python3 - "$output" <<'PY'
import hashlib
import json
import sys
import time
from pathlib import Path
path = Path(sys.argv[1]) / 'filter'
path.mkdir(exist_ok=True)
body = "[Adblock Plus]\n! HaGeZi's Multi PRO - SYNTHETIC TEST FIXTURE\n! Number of entries: 10000\n||blocked.test^\n"
body += ''.join('||fixture-%d.phase2.invalid^\n' % i for i in range(9999))
(path / 'multi-pro.json').write_text(json.dumps({
    'body':body, 'sha256':hashlib.sha256(body.encode()).hexdigest(),
    'source':'https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/adblock/pro.txt',
    'checked_at':time.time(), 'updated_at':time.time()}))
PY
# A globally classified address tests the real public-IP gate; --internal
# provides no upstream route. Never whitelist RFC1918 just to pass a test.
docker network create --internal --subnet 11.253.72.0/24 "$network" >/dev/null
docker run --name "$container" --network "$network" --ip 11.253.72.10 \
    --add-host origin.test:11.253.72.10 --add-host cdn.test:11.253.72.10 \
    --add-host forbidden.test:11.253.72.10 --add-host blocked.test:11.253.72.10 \
    --memory 4g --cpus 4 --pids-limit 1024 --shm-size 1g \
    -e DETHROTTLED_ADBLOCK=1 -e DETHROTTLED_ADBLOCK_READER=1 \
    -e DETHROTTLED_ADBLOCK_DIR=/filter -e PYTHONPATH=/app:/tests \
    -v "$repo/experiments/dnb:/tests:ro" -v "$output/filter:/filter:ro" \
    "$image" sh -c 'Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/x.log 2>&1 &
        export DISPLAY=:99
        sleep 1
        python /tests/phase2_check.py /tmp/phase2-results.json' >"$output/wire.log" 2>&1 || {
    docker cp "$container:/tmp/phase2-results.json.failed-hits.json" \
        "$output/failed-hits.json" 2>/dev/null || true
    cat "$output/wire.log"
    exit 1
}
docker cp "$container:/tmp/phase2-results.json" "$output/wire.json"
cat "$output/wire.log"
