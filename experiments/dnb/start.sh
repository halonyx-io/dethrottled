#!/bin/sh
# DNB worker start (1.9.0).
#
# DETHROTTLED_BROWSER_NETWORK=native (default): runs as root only long enough to
#   1. start the DNS filter (drops to its own UID) and point /etc/resolv.conf at it,
#   2. load and verify the egress firewall (nftables; needs NET_ADMIN),
#   3. start one unprivileged Playwright server per browser identity, each as its
#      own UID with no capabilities: "public" (public addresses and the DNS
#      filter only) and "scoped" (the CONNECT gate only),
# then runs the worker as browsersearch with no capabilities, empty bounding set
# and no_new_privs. Any failure exits non-zero: the worker never starts with
# browsers the firewall does not confine.
#
# DETHROTTLED_BROWSER_NETWORK=gate: the 1.8 arrangement, chosen explicitly. Every
#   browser context goes through the CONNECT gate; no firewall, no identities.
set -eu

WORKER_UID="${DETHROTTLED_WORKER_UID:-10002}"
WORKER_GROUPS="${DETHROTTLED_WORKER_GROUPS:-10001}"
DNS_UID="${DETHROTTLED_DNS_FILTER_UID:-10003}"
PUBLIC_UID="${DETHROTTLED_PUBLIC_BROWSER_UID:-10005}"
SCOPED_UID="${DETHROTTLED_SCOPED_BROWSER_UID:-10006}"
SHARED_GID="${DETHROTTLED_BROWSER_SHARED_GID:-10010}"
GATE_PORTS="${DETHROTTLED_GATE_PORTS:-20000-20999}"
DOWNLOADS=/tmp/dethrottled-downloads
UPSTREAM=/run/dethrottled/resolv.upstream
DRIVER=/usr/local/lib/python3.12/site-packages/patchright/driver
DROP="--inh-caps=-all --bounding-set=-all --no-new-privs"

fail() { echo "dnb: $*; refusing to start (fail closed)" >&2; exit 1; }

worker() {
    if [ "${DETHROTTLED_XVFB_STARTED:-0}" != "1" ]; then
        python - <<'PY'
from pathlib import Path
for name in ('/tmp/.X99-lock', '/tmp/.X11-unix/X99'):
    Path(name).unlink(missing_ok=True)
PY
        Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
        sleep 1
    fi
    export DISPLAY=:99
    # Render gets its own headed browser with default graphics: half the CPU per
    # page of the Mesa drive browser (web-bench browser-settings-ab, round 6).
    export DETHROTTLED_CRAWL_SEPARATE="${DETHROTTLED_CRAWL_SEPARATE:-1}"
    export DETHROTTLED_GATE_PORTS="$GATE_PORTS"
    exec uvicorn dnb_service:app --host 0.0.0.0 --port 19888
}

if [ "${1:-}" = "--worker" ]; then
    worker
fi

lane="${DETHROTTLED_BROWSER_NETWORK:-native}"
case "$lane" in native|gate) ;; *) fail "DETHROTTLED_BROWSER_NETWORK must be native or gate" ;; esac

if [ "$(id -u)" != "0" ]; then
    [ "$lane" = "gate" ] || fail "the native lane needs to start as root with NET_ADMIN to load its firewall (or set DETHROTTLED_BROWSER_NETWORK=gate)"
    export DETHROTTLED_BROWSER_NETWORK=gate
    worker
fi

mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
install -d -m 2770 -o "$WORKER_UID" -g "$SHARED_GID" "$DOWNLOADS"

if [ "$lane" = "gate" ]; then
    export DETHROTTLED_BROWSER_NETWORK=gate
    exec setpriv --reuid="$WORKER_UID" --regid="$WORKER_UID" --groups="$WORKER_GROUPS,$SHARED_GID" \
        $DROP env HOME=/home/browsersearch USER=browsersearch sh "$0" --worker
fi

# X server for the headed browsers, as the worker UID (shared by every identity).
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99
setpriv --reuid="$WORKER_UID" --regid="$WORKER_UID" --clear-groups $DROP \
    Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DETHROTTLED_XVFB_STARTED=1

# 1. DNS filter: the only resolver; HaGeZi + public addresses only.
mkdir -p /run/dethrottled
cp /etc/resolv.conf "$UPSTREAM"
python /app/dethrottled_dns_filter.py --upstream-file "$UPSTREAM" \
    --user "$DNS_UID" --groups "$WORKER_GROUPS" >/tmp/dns-filter.log 2>&1 &
python - <<'PY' || fail "DNS filter did not answer"
import sys, time
import dns.resolver
probe = dns.resolver.Resolver(configure=False)
probe.nameservers, probe.lifetime = ["127.0.0.1"], 1.0
for _ in range(50):
    try:
        probe.resolve("dns-filter-ready.invalid", "A")
        sys.exit(0)
    except dns.resolver.NXDOMAIN:
        sys.exit(0)  # the filter answered
    except Exception:
        time.sleep(0.2)
sys.exit(1)
PY
{ grep -E '^(search|options)' "$UPSTREAM" || true; echo "nameserver 127.0.0.1"; } >/tmp/resolv.conf.dnb
cat /tmp/resolv.conf.dnb >/etc/resolv.conf   # Docker bind-mounts it: write in place

# 2. Egress firewall: loaded atomically, then probed from each identity.
python /app/dethrottled_egress_firewall.py --public-uid "$PUBLIC_UID" \
    --scoped-uid "$SCOPED_UID" --gate-ports "$GATE_PORTS" || fail "egress firewall not verified"

# 3. One Playwright server per identity. Chrome is its child over pipes and
#    inherits its UID; the worker connects on loopback, which neither browser
#    UID may reach.
# GPU (docker-compose.gpu.yml): the groups owning the DRM nodes, so Chrome's
# GPU process can open them under its own UID. Empty without the overlay.
GPU_GROUPS="$(stat -c '%g' /dev/dri/renderD* /dev/dri/card* 2>/dev/null | sort -u | tr '\n' ',' | sed 's/,$//')"
BROWSER_GROUPS="$SHARED_GID${GPU_GROUPS:+,$GPU_GROUPS}"
# The machine's own timezone and language (compose-auto.sh fills them from the
# host), so the browser does not report UTC from a Malaysian address.
BROWSER_ENV=""
[ -n "${DETHROTTLED_BROWSER_TIMEZONE:-}" ] && BROWSER_ENV="TZ=$DETHROTTLED_BROWSER_TIMEZONE"
[ -n "${DETHROTTLED_BROWSER_LANG:-}" ] && BROWSER_ENV="$BROWSER_ENV LANG=$DETHROTTLED_BROWSER_LANG LANGUAGE=$DETHROTTLED_BROWSER_LANG"

start_server() {
    name="$1" uid="$2" port="$3"
    token="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
    home="/home/dnb-$name"
    install -d -m 2770 -o "$uid" -g "$SHARED_GID" "$DOWNLOADS/$name"
    setpriv --reuid="$uid" --regid="$uid" --groups="$BROWSER_GROUPS" $DROP \
        env HOME="$home" USER="dnb-$name" DISPLAY=:99 $BROWSER_ENV \
        "$DRIVER/node" "$DRIVER/package/cli.js" run-server --host 127.0.0.1 --port "$port" \
        --path "/$token" --unsafe --artifacts-dir "$DOWNLOADS/$name" \
        >"/tmp/browser-server-$name.log" 2>&1 &
    for _ in $(seq 1 50); do
        grep -q "Listening on" "/tmp/browser-server-$name.log" 2>/dev/null && break
        sleep 0.2
    done
    grep -q "Listening on" "/tmp/browser-server-$name.log" || fail "$name browser server did not start"
    echo "ws://127.0.0.1:$port/$token"
}
DETHROTTLED_BROWSER_SERVER_PUBLIC="$(start_server public "$PUBLIC_UID" 19901)"
DETHROTTLED_BROWSER_SERVER_SCOPED="$(start_server scoped "$SCOPED_UID" 19902)"
export DETHROTTLED_BROWSER_SERVER_PUBLIC DETHROTTLED_BROWSER_SERVER_SCOPED
export DETHROTTLED_DNS_UPSTREAM_FILE="$UPSTREAM"
export DETHROTTLED_EGRESS_FIREWALL=verified
export DETHROTTLED_BROWSER_NETWORK=native

# 4. The worker: no capabilities, empty bounding set, no_new_privs.
exec setpriv --reuid="$WORKER_UID" --regid="$WORKER_UID" --groups="$WORKER_GROUPS,$SHARED_GID" \
    $DROP env HOME=/home/browsersearch USER=browsersearch sh "$0" --worker
