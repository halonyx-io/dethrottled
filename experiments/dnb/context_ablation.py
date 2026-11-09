"""Inside-image diagnostic: compare fresh contexts with SAME-OWNER reuse.

Reuse is an ablation only, not an exposed API or production default. One fixture,
no cookies from outside the experiment. Run when other lab traffic is stopped.
"""

import asyncio
import json
import time
from pathlib import Path

import service


def cpu():
    return (
        int(
            dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())[
                "usage_usec"
            ]
        )
        / 1e6
    )


async def main():
    result = []
    async with service.lifespan(service.app):
        for reuse in (False, True, True, False):
            state = None
            before = cpu()
            start = time.monotonic()
            try:
                for _ in range(10):
                    if state is None:
                        state = await service._make_drive_state(service.app.state.browser, [])
                    await service._navigate(
                        state,
                        service.DriveRequest(),
                        "http://fixture:8090/article",
                        5000,
                        time.monotonic() + 5,
                    )
                    await asyncio.sleep(0.5)
                    await state["page"].content()
                    if not reuse:
                        await state["context"].close()
                        state = None
            finally:
                if state:
                    await state["context"].close()
            result.append(
                {
                    "same_owner_context_reused": reuse,
                    "requests": 10,
                    "cpu_seconds": cpu() - before,
                    "elapsed_s": time.monotonic() - start,
                }
            )
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
