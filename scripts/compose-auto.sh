#!/usr/bin/env bash
# Host-side optional GPU discovery; the base stack still works without a GPU.
set -euo pipefail
task_repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
task_files=(-f "$task_repo/docker-compose.yml")
task_gpu=()
# ── Worker thread sizing ─────────────────────────────────────────────────────
# The stack ships to more than one machine, so worker thread counts are derived
# from the host, never pinned to the box they were tuned on.
#
# Measured on a 16-thread host (2026-11-11), both workers:
#   docling, 6-page PDF : 1->21.9s 2->16.4s 4->13.8s 6->12.8s 8->12.9s 16->13.1s
#   whisper, 16s audio  : 1->16.2s 2-> 9.6s 4-> 6.7s 6-> 6.1s 8-> 7.3s 16->11.2s
# Both knee at 6 of 16 threads = 37.5%. Past that docling is flat and whisper is
# ~1.8x SLOWER (thread contention on an integrated-memory APU). 40% is the
# operating point: at the knee, leaving 60% of the host for everything else.
# Override with DETHROTTLED_WORKER_THREAD_RATIO, or set
# DETHROTTLED_WORKER_THREADS to bypass the calculation entirely.
if [[ -z ${DETHROTTLED_WORKER_THREADS:-} ]]; then
    task_nproc=$(nproc 2>/dev/null || echo 1)
    (( task_nproc < 1 )) && task_nproc=1
    task_ratio=${DETHROTTLED_WORKER_THREAD_RATIO:-0.40}
    # Bash has no float maths: parse the ratio into permille by hand.
    task_permille=400
    if [[ $task_ratio =~ ^([0-9]+)(\.([0-9]{1,3}))?$ ]]; then
        task_whole=${BASH_REMATCH[1]}
        task_frac=${BASH_REMATCH[3]}000
        task_permille=$(( 10#${task_whole}${task_frac:0:3} ))
        (( task_permille < 1 || task_permille > 1000 )) && task_permille=400
    fi
    DETHROTTLED_WORKER_THREADS=$(( task_nproc * task_permille / 1000 ))
    # Floor of 1 is correct on a single-thread host but wasteful on a small
    # multi-core one: bash integer maths rounds a 4-thread host down to 1, and
    # the measured curve shows 1 thread is roughly half the throughput of 2.
    # Give any host with room for it at least 2.
    (( DETHROTTLED_WORKER_THREADS < 1 )) && DETHROTTLED_WORKER_THREADS=1
    if (( task_nproc >= 2 && DETHROTTLED_WORKER_THREADS < 2 )); then
        DETHROTTLED_WORKER_THREADS=2
    fi
    # Ceiling: the measured curve is flat past the knee and slightly worse at
    # full width, so a very large host should not hand a single-file worker a
    # huge pool. 8 is where the 16-thread measurement stopped improving.
    if [[ -n ${DETHROTTLED_WORKER_THREADS_MAX:-} ]] &&
       (( DETHROTTLED_WORKER_THREADS > DETHROTTLED_WORKER_THREADS_MAX )); then
        DETHROTTLED_WORKER_THREADS=$DETHROTTLED_WORKER_THREADS_MAX
    fi
    (( DETHROTTLED_WORKER_THREADS > task_nproc )) && DETHROTTLED_WORKER_THREADS=$task_nproc
    export DETHROTTLED_WORKER_THREADS
fi
unset task_nproc task_ratio task_permille task_whole task_frac 2>/dev/null || true

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
