# Published 1.4.0 installation verification

Recorded 4 November 2026 after publication. **Both actual installation routes passed on Q6A.**

The fresh GitHub clone used release tag `v1.4.0`, commit `e8bb9b4741f7e064cdbab254524a334a2ccdeb9e`. The Python route downloaded `dethrottled==1.4.0` from the ordinary public PyPI index into a new Python 3.12 virtual environment. A second fresh environment installed `[all]`. Commands ran outside a source checkout; the managed stack used its bundled deployment context.

| Gate | Result |
|---|---|
| Fresh PyPI core and optional-library installs | Passed; imports/help and dependency/artifact inventories retained |
| No services started by pip installation | Passed; running-container set unchanged before explicit stack startup |
| PyPI default stack | Five services ready; API/runtime version 1.4.0 |
| PyPI full profile | Seven services started; uncached inference workers honestly reported first-use initialization |
| PyPI functional / restart checks | 21/21 contracts; 1/1 four-storage-type restoration |
| Fresh GitHub tag clone | Default Compose build and all five services ready |
| GitHub functional / restart checks | 21/21 contracts; 1/1 four-storage-type restoration |
| Final Q6A state | Package-managed default stack ready at `127.0.0.1:8787` |

The optional workers’ successful inference and model costs were measured separately in the [two-device report](REPORT.md). This publication check verifies their distribution/startup and truthful initialization state; it does not claim freshly downloaded full-profile weights were exercised again.

## Recorded command times

These are single observed installations with existing Docker build/image caches. Fresh virtual environments and project volumes do not imply pristine image downloads.

| Operation | Wall time |
|---|---:|
| PyPI core package installation | 12.94 s |
| PyPI optional-library installation | 36.89 s |
| Managed default up, including cached build | 32.15 s |
| Fresh release-tag clone | 2.01 s |
| GitHub Compose up, including build/export | 183.18 s |
| Managed default restart | 13.56 s |

## Immutable release artifacts

The files attached to the [GitHub release](https://github.com/halonyx-io/dethrottled/releases/tag/v1.4.0) match PyPI SHA-256 values. Neither version nor artifact was overwritten.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `dethrottled-1.4.0-py3-none-any.whl` | 10118474 | `c64d53a8bd61fb4a90fff01df02ba6eeac0bd249ab122f3f2d3a6cbbdb0579aa` |
| `dethrottled-1.4.0.tar.gz` | 10134111 | `a7ef993a29cc0630f9d1128c88fdd87a2ef9904f10fc0dcf4d88acd14260da46` |

## Original index-propagation failure

The first install attempt failed because the normal PyPI Simple index still listed versions only through 1.3.0 while release JSON already exposed 1.4.0. That gate stopped. The original error and index response were preserved; after the index exposed 1.4.0, a new virtual environment installed normally. No package code, version or registry contents were changed to bypass this delay.

## Retained verification

[Machine-readable gates](publication/passed.json), [commands and timings](publication/commands.json), [artifact metadata](publication/pypi-artifacts.json), [final status](publication/pypi-final-status.json) and per-route contract/restart files are in `publication/`. Dependency names, versions and downloaded artifact hashes are retained; credentials and full third-party package metadata are omitted.

The installed API matches all 37 frozen non-management modules. The only changed API-package module is `stack.py`, which received prerequisite/port diagnostics after the HTTP workload was frozen. Browser runtime behavior is the same candidate implementation tested in the report.

Release publishing [workflow](https://github.com/halonyx-io/dethrottled/actions/runs/41817102684) and feature [CI](https://github.com/halonyx-io/dethrottled/actions/runs/41816369909) passed. szbox production remains 1.3.0; benchmark projects were stopped and their data preserved.

For Q6A operations:

```sh
~/dethrottled-release-1.4.0/pypi/bin/dethrottled stack status
```
