import hashlib
import json
import time

import service
from fastapi import HTTPException

body = service.DriveRequest(
    session="compat-test",
    operation_id="click-once",
    steps=[{"action": "click", "selector": "#submit"}],
)
legacy = body.model_dump(exclude={"operation_id"})
for step in legacy["steps"]:
    step.pop("frame")
old = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
for digest in [old, service._operation_fingerprint(body, normalize=False)]:
    service.DRIVE_OPERATIONS[(body.session, body.operation_id)] = {
        "fingerprint": digest,
        "state": "completed",
        "created": time.time(),
        "result": {"ok": True, "sentinel": "already-done"},
    }
    assert service._operation_lookup(body)["operation_replayed"]
    changed = body.model_copy(
        update={"steps": [service.DriveStep(action="click", selector="#submit", frame="#embedded")]}
    )
    try:
        service._operation_lookup(changed)
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("frame change must conflict")
    service.DRIVE_OPERATIONS[(body.session, body.operation_id)]["state"] = "outcome_unknown"
    try:
        service._operation_lookup(body)
    except HTTPException as error:
        assert "outcome_unknown" in str(error.detail)
    else:
        raise AssertionError("unknown outcome repeated")
print(
    "PASS: 0.6 and early 0.7 journals replay; "
    "changed-frame conflict and unknown-outcome fence preserved"
)
