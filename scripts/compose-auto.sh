#!/usr/bin/env bash
# Host-side optional GPU discovery; the base stack still works without a GPU.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_files=(-f "$task_repo/docker-compose.yml")
if [[ ${DETHROTTLED_GPU:-auto} != off && -e /dev/dri/card0 ]]; then
    task_nodes=(/dev/dri/renderD*)
    if [[ -e ${task_nodes[0]} ]]; then
        export DETHROTTLED_GPU_RENDER_GID
        export DETHROTTLED_GPU_VIDEO_GID
        DETHROTTLED_GPU_RENDER_GID=$(stat -c '%g' -- "${task_nodes[0]}")
        DETHROTTLED_GPU_VIDEO_GID=$(stat -c '%g' -- /dev/dri/card0)
        task_files+=(-f "$task_repo/docker-compose.gpu.yml")
    fi
fi
exec docker compose --project-directory "$task_repo" "${task_files[@]}" "$@"
