#!/usr/bin/env bash
# Disposable, offline controls. No production services, volumes or host DNS edits.
set -euo pipefail
cd "$(dirname "$0")/../.."
list_file=$(realpath "${1:?Supply a previously downloaded HaGeZi adblock/pro.txt}")
architecture=$(uname -m)
[[ $architecture != aarch64 ]] || architecture=arm64
out=${2:-"/tmp/dethrottled-adblock-$(date -u +%Y%m%dT%H%M%SZ)"}
mkdir -p "$out"
out=$(realpath "$out")
printf "Writing new observations to %s\n" "$out"
api_image=${ADBLOCK_API_IMAGE:-dethrottled:adblock-candidate}
browser_image=${ADBLOCK_BROWSER_IMAGE:-dethrottled-browser-search:adblock-candidate}
crawl_image=${CRAWL4AI_IMAGE:-unclecode/crawl4ai:0.9.5}
for mode in 0 1; do
  docker run --rm --user 0 --network none -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/source/src -v "$PWD:/source:ro" -v "$out:/results" \
    -v "$list_file:/list:ro" --entrypoint python "$api_image" \
    /source/evaluations/adblock/native.py --list /list --enabled "$mode" \
    --output "/results/$architecture-native-final-$mode.json"
  for workload in ads clean; do
    label=browser; repeats=3
    [[ $workload != clean ]] || { label=clean; repeats=7; }
    docker run --rm --user 0 --network none --shm-size=1g -e DISPLAY=:98 \
      -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD/evaluations/adblock:/lab:ro" -v "$out:/results" \
      -v "$list_file:/list:ro" --entrypoint sh "$browser_image" -c \
      "Xvfb :98 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & sleep 1; \
       exec python /lab/browser.py --backend patchright --enabled $mode \
       --workload $workload --repetitions $repeats --list /list \
       --output /results/$architecture-$label-$mode.json"
  done
  docker run --rm --user 0 --network none --shm-size=1g \
    -e PYTHONDONTWRITEBYTECODE=1 -e CRAWL4AI_NO_CLOUD_NOTICE=1 -e PYTHONPATH=/policy \
    -e DETHROTTLED_ADBLOCK="$mode" \
    -v "$PWD/src/dethrottled/adblock.py:/policy/dethrottled_adblock.py:ro" \
    -v "$PWD/src/dethrottled/adblock_browser.py:/policy/dethrottled_adblock_browser.py:ro" \
    -v "$PWD/src/dethrottled/adblock_proxy.py:/policy/dethrottled_adblock_proxy.py:ro" \
    -v "$PWD/evaluations/adblock:/lab:ro" -v "$out:/results" -v "$list_file:/list:ro" \
    --entrypoint python "$crawl_image" /lab/browser.py --backend crawl4ai \
    --enabled "$mode" --list /list --output "/results/$architecture-crawl4ai-$mode.json"
done
