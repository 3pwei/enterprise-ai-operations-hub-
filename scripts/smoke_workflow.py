"""Exercise the Compose API through actual PostgreSQL and MCP subprocesses."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = "http://127.0.0.1:8000/api/workflows"


def call(path, token, method="GET", data=None):
    request = Request(ROOT + path, method=method,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"},
                      data=json.dumps(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=40) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


analyst = os.environ["DEMO_ANALYST_TOKEN"]
manager = os.environ["DEMO_MANAGER_TOKEN"]
status, draft = call("", analyst, "POST", {"message": "請評估採購 P-300"})
assert status == 200 and draft["status"] == "awaiting_confirmation" and draft["quantity"] == 16, draft
path = "/" + draft["id"]
assert call(path + "/submit", analyst, "POST")[0] == 403
status, submitted = call(path + "/submit", manager, "POST")
assert status == 200 and submitted["status"] == "submitted", submitted
assert call(path + "/submit", manager, "POST")[1]["purchase_id"] == submitted["purchase_id"]
status, approval = call(path + "/approval", manager)
assert status == 200 and approval["data"]["status"] == "pending", approval
print("Compose procurement smoke: draft, RBAC, submit, idempotency and EIP status passed")
