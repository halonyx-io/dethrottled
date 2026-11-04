# Installation issues and original failures

## Q6A package-manager prerequisite

The first standard Docker installation stopped at `apt update`: the host's existing
signed Radxa repository changed Origin (`noble` to `Radxa`) and Label (`noble` to
`Freight`). The original failure was retained. Retrying accepted only Origin/Label
changes; signature checking was not disabled. Docker Engine and Compose then installed
through Docker's official Ubuntu ARM64 repository. This was a host prerequisite issue,
not a Dethrottled runtime failure. The stack CLI does not install system packages.

## Candidate deployment context

The first candidate managed-stack build failed because the API Dockerfile referenced
a nonexistent top-level `pdf-worker` directory. The PDF utility actually lives under
`docker/pdf-worker`. The failed wheel/log were retained privately, the incorrect COPY
was removed, and wheel validation now checks all Docker COPY source paths before
starting deployment. The corrected wheel passed 47 source checks. Only the affected
candidate builds were stopped; production containers were untouched.

## Nested package build inside the API image

The corrected context exposed a second issue: the API image copied source and packaging
metadata but not its own Dockerfile into `/app`. The nested wheel build correctly
refused an incomplete context. The Dockerfile is now included, and the package validator
checks that this self-build prerequisite is copied. The original failing log is retained.
