"""Private JSON-lines worker; stdout is protocol only, not a public endpoint."""

import contextlib
import json
import math
import os
import resource
import signal
import sys

MEMORY_BYTES = 2 * 1024**3
CPU_SECONDS = 8
MAX_INPUT = 64 * 1024**2
MAX_OUTPUT = 32 * 1024**2


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    signal.signal(signal.SIGXCPU, lambda *_: os._exit(128 + signal.SIGXCPU))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    with contextlib.redirect_stdout(sys.stderr):
        from html_extract import extract
    print('{"ready":true}', flush=True)
    for line in sys.stdin.buffer:
        if len(line) > MAX_INPUT:
            break
        try:
            body = json.loads(line)
            used = resource.getrusage(resource.RUSAGE_SELF)
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (min(60, math.ceil(used.ru_utime + used.ru_stime) + CPU_SECONDS), 60),
            )
            with contextlib.redirect_stdout(sys.stderr):
                result = extract(body["url"], body["html"])
            used = resource.getrusage(resource.RUSAGE_SELF)
            output = json.dumps(
                {"ok": True, "result": result, "recycle": used.ru_utime + used.ru_stime >= 45},
                ensure_ascii=True,
            )
            if len(output) > MAX_OUTPUT:
                output = '{"ok":false,"error":"extraction_output_limit"}'
        except MemoryError:
            output = '{"ok":false,"error":"extraction_memory_limit"}'
        except Exception as exc:
            output = json.dumps({"ok": False, "error": "extraction_failed:" + type(exc).__name__})
        print(output, flush=True)


if __name__ == "__main__":
    main()
