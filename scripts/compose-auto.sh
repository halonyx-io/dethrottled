#!/usr/bin/env bash
# Host-side optional GPU discovery; the base stack still works without a GPU.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_files=(-f "$task_repo/docker-compose.yml")
task_gpu=()
# Host device paths only make sense for a native Linux daemon on this machine.
# A remote context or Docker Desktop VM cannot inherit the CLI host's /dev/dri.
if [[ -n ${DOCKER_CONTEXT:-} ]]; then
    task_docker_host=$(docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')
else
    task_docker_host=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
fi
if [[ ${DETHROTTLED_GPU:-auto} != off && $(uname -s) == Linux &&
      $task_docker_host == unix://* && $(docker context show) != desktop-linux ]]; then
    task_cards=(/dev/dri/card*)
    task_nodes=(/dev/dri/renderD*)
    task_native_daemon=$(docker info --format '{{.OperatingSystem}}' 2>/dev/null || true)
    if [[ -e ${task_cards[0]} && -e ${task_nodes[0]} && -n $task_native_daemon &&
          $task_native_daemon != *"Docker Desktop"* ]]; then
        export DETHROTTLED_GPU_RENDER_GID
        export DETHROTTLED_GPU_VIDEO_GID
        DETHROTTLED_GPU_RENDER_GID=$(stat -c '%g' -- "${task_nodes[0]}")
        DETHROTTLED_GPU_VIDEO_GID=$(stat -c '%g' -- "${task_cards[0]}")
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
