## Behaviour

Describe the concrete trigger and resulting behaviour. State whether the change
is compatible, removes a capability, changes a default or is documentation only.

## Documentation and contracts

- Affected HTTP/MCP/CLI/configuration/workflow surfaces:
- Guides, generated references and examples reviewed/updated:
- Inventory regeneration/check result:
- Historical evidence preserved or explicitly annotated:
- If no documentation change is needed, explain why:

Use the change-impact matrix in `docs/DOCUMENTATION-MAINTENANCE.md`. Check module
comments and advertised capabilities as well as Markdown. New docs need a lifecycle
and navigation entry. Generated tables should come from source.

## Validation

Record the relevant commands and outcomes, including skips and original failures.
For measured claims, link the workload, baseline, raw results and limitations.
Distinguish helper timings from end-to-end gains and source reads from answer accuracy.

## Delivery

State what was actually completed: source only, built package, published artifact,
or deployment. Link exact-version CI when applicable. An authorized rollout needs
artifact/hash checks, retained data/rollback, and live API/MCP identity verification.
Do not include credentials or private host identifiers in this description.
