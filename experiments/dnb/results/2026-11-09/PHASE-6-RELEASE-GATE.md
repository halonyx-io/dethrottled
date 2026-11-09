# Phase 6 release gate

2026-11-09. All technical Phase 6 checks pass. Nothing below the gate has been
released, published, version-bumped or deployed. Production remains on 1.7.1.

## What is verified

- Browser parity: 27 facts, 27 drive actions, download, network, concurrency and
  checkpoint restore.
- PDF, OCR, Office, layout and mixed-batch parity.
- Media/speech transcription parity, including the uncertainty warning.
- Paced live and controlled hostile-source parity, with failures preserved.
- 8 MiB HTML ceiling preserved and warned.
- Optional workers through the candidate API image.
- Native ARM64 build and runtime on `q6a`; 29/29 focused phase-1/2 tests.
- Wheel/sdist build, stack bundle verification, `twine check`, clean-wheel,
  sdist, source, PyPI and GitHub install routes.
- Mixed load, ten-minute memory soak, injected browser crash containment and
  rollback/volume preservation.
- Full offline suite: 875 passed, 135 skipped, 2 deselected.

## Release steps requiring approval

1. Approve 1.8.0.
2. Bump the version in `pyproject.toml` and `src/dethrottled/__init__.py`;
   update the checkout-version statement in `README.md` and any current-version
   operations text.
3. Rebuild both worker/API images from the approved commit with the 1.8.0 tag.
4. Rebuild the wheel and sdist, rerun `scripts/verify_stack_package.py`,
   `twine check`, clean-install smoke and the offline suite.
5. Tag the release, publish only through the existing trusted-publishing
   workflow, and keep the 1.7.1 images and volumes available for rollback.
6. Upgrade production separately, with `/health`, `/v2/capabilities`, a fetch
   smoke and rollback checked before removing 1.7.1.

## Known intentional differences

- Concise PDF responses omit the raw table array and carry
  `native_pdf_table_count`; content, tier and quality match. This is the Phase 4
  presentation change.
- The candidate may reach a readable headed result where 1.7.1 returned a
  partial or failed direct result on a single live request; repeated passes and
  controlled sources show no allow-list widening or failure masking.
- OCR on the generated PNG is identical on both sides and misreads one numeric
  token; the OCR warning is retained and no accuracy claim is made.

## Evidence index

- [PHASE-6.md](PHASE-6.md) - full progress record.
- [phase6-pdf-summary.json](phase6-pdf-summary.json)
- [phase6-optional-summary.json](phase6-optional-summary.json)
- [phase6-layout-mixed.json](phase6-layout-mixed.json)
- [phase6-html-ceiling.json](phase6-html-ceiling.json)
- [phase6-media-summary.json](phase6-media-summary.json)
- [phase6-live-hostile.json](phase6-live-hostile.json)
- [phase6-install.json](phase6-install.json)
- [phase6-load-crash-rollback.json](phase6-load-crash-rollback.json)
- [phase6-arm64-summary.json](phase6-arm64-summary.json)
- [phase6-pytest.log](phase6-pytest.log)
