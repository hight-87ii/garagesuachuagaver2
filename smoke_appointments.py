import io
import json
import urllib.request

BASE = "http://127.0.0.1:8014"


def call(method, path, payload=None, token=None, params=""):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(BASE + path + params, data=data, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


_, login = call("POST", "/api/v1/auth/login", {"email": "admin@garage.vn", "password": "Admin@123"})
token = login["access_token"]

status, rules = call("GET", "/api/v1/appointments/rules", token=token)
print("rules", status, rules.get("working_days_text"), rules.get("working_hours"), "resources:", len(rules.get("resources", [])), "technicians:", rules.get("technicians"))

status, listed = call("GET", "/api/v1/appointments", token=token)
print("list", status, "total", listed["total"])
for item in listed["items"]:
    print("  ", item["id"], item["appointment_at"], item["status"], "|", item.get("technician") or "-", "/", item.get("resource_name") or "-", "|", item["plate"])

status, customers = call("GET", "/api/v1/customers", token=token)
customer = customers["items"][0]
status, detail = call("GET", f"/api/v1/customers/{customer['id']}", token=token)
vehicle = detail["vehicles"][0]
status, check = call(
    "GET", "/api/v1/appointments/conflicts", token=token,
    params=f"?at=2026-10-21T09:00&duration_min=60&technician=Nguy%E1%BB%85n%20V%C4%83n%20Nam",
)
print("precheck", status, check["ok"], check["message"])

status, created = call("POST", "/api/v1/appointments", {
    "customer_id": customer["id"], "vehicle_id": vehicle["id"], "service": "Bảo dưỡng định kỳ",
    "appointment_at": "2026-10-21T09:00", "reason": "Kiểm tra tổng quát", "technician": "Nguyễn Văn Nam",
    "duration_min": 90,
}, token=token)
print("create", status, created.get("id"), created.get("status"), created.get("plate"), "warnings:", len(created.get("warnings", [])))

if status == 201:
    appointment_id = created["id"]
    status, confirmed = call("POST", f"/api/v1/appointments/{appointment_id}/confirm", token=token)
    print("confirm", status, confirmed.get("status"), confirmed.get("confirmed_at"))
    status, forced = call("POST", f"/api/v1/appointments/{appointment_id}/receive", {"km_in": 43210}, token=token)
    print("receive", status, forced.get("code"), "already:", forced.get("already_received"), "reused:", forced.get("reused_existing"))
    status, again = call("POST", f"/api/v1/appointments/{appointment_id}/receive", {}, token=token)
    print("receive again", status, again.get("code"), "already:", again.get("already_received"))
    status, cancelled = call("POST", f"/api/v1/appointments/{appointment_id}/cancel", {"reason": "Kiểm thử"}, token=token)
    print("cancel after receive", status, cancelled.get("error", {}).get("message"))
