#!/usr/bin/env bash
# Host-side optional GPU discovery; the base stack still works without a GPU.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_files=(-f "$task_repo/docker-compose.yml")
task_gpu=()
if [[ ${DETHROTTLED_GPU:-auto} != off && -e /dev/dri/card0 ]]; then
    task_nodes=(/dev/dri/renderD*)
    if [[ -e ${task_nodes[0]} ]]; then
        export DETHROTTLED_GPU_RENDER_GID
        export DETHROTTLED_GPU_VIDEO_GID
        DETHROTTLED_GPU_RENDER_GID=$(stat -c '%g' -- "${task_nodes[0]}")
        DETHROTTLED_GPU_VIDEO_GID=$(stat -c '%g' -- /dev/dri/card0)
        task_gpu=(-f "$task_repo/docker-compose.gpu.yml")
    fi
fi
# Let Compose interpret .env/interpolation itself; never source/eval a dotenv
# file. Preserve configured overlays when adding the optional graphics file.
task_environment=$(docker compose --project-directory "$task_repo" config --environment)
task_paths=""
task_separator=:
while IFS= read -r task_setting; do
    case "$task_setting" in
        COMPOSE_FILE=*) task_paths=${task_setting#COMPOSE_FILE=} ;;
        COMPOSE_PATH_SEPARATOR=*) task_separator=${task_setting#COMPOSE_PATH_SEPARATOR=} ;;
    esac
done <<< "$task_environment"
unset task_environment task_setting
if [[ -n "$task_paths" ]]; then
    IFS="$task_separator" read -r -a task_custom <<< "$task_paths"
    task_files=()
    for task_path in "${task_custom[@]}"; do
        [[ $task_path = /* ]] || task_path="$task_repo/$task_path"
        task_files+=(-f "$task_path")
    done
fi
task_files+=("${task_gpu[@]}")
exec docker compose --project-directory "$task_repo" "${task_files[@]}" "$@"
