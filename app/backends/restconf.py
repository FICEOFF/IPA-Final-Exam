import os, requests
from ipaddress import IPv4Interface
from app.backends import planning

YANG_JSON = "application/yang-data+json"

TIMEOUT = 10

def _error(code):
    return {"status": "error", "result": code}

def _error_from_exception(exc):
    if isinstance(exc, PermissionError):
        return _error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError, requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return _error("connection_failed")
    return _error("backend_failed")

def _auth():
    return (
        os.environ.get("ROUTER_USER", ""),
        os.environ.get("ROUTER_PASS", "")
    )

def _default_http_get(url):
    return requests.get(
        url,
        headers={"Accept": YANG_JSON},
        auth=_auth(),
        verify=False,
        timeout=TIMEOUT
    )

def _default_http_put(url, json):
    return requests.put(
        url,
        json=json,
        headers={"Accept": YANG_JSON, "Content-Type": YANG_JSON},
        auth=_auth(),
        verify=False,
        timeout=TIMEOUT
    )

def _normalize(data):
    raw = data["ietf-interfaces:interface"]
    ipv4 = None
    addresses = raw.get("ietf-ip:ipv4", {}).get("address", [])
    if addresses:
        address = addresses[0]
        ipv4 = str(IPv4Interface(f"{address['ip']}/{address['netmask']}"))
    return {
        "name": raw["name"],
        "ipv4": ipv4,
        "description": raw.get("description"),
        "admin_state": "up" if raw["enabled"] else "down"
    }

def get_interface_state(router, interface_name, http_get=None):
    http_get = http_get or _default_http_get
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )
    try:
        response = http_get(url)
        if response.status_code == 404:
            return {"status": "ok", "result": "not_found", "interface": None}
        if response.status_code in (401, 403):
            return _error("authentication_failed")
        if response.status_code != 200:
            return _error("backend_failed")
        return {
            "status": "ok",
            "result": "found",
            "interface": _normalize(response.json())
        }
    except Exception as exc:
        return _error_from_exception(exc)

def plan_interface(router, desired_interface, http_get=None):
    def status(router_, interface_name):
        return get_interface_state(router_, interface_name, http_get)
    return planning.plan_interface(router, desired_interface, status)

def _native_payload(number, desired_interface):
    ip = IPv4Interface(desired_interface["ipv4"])
    loopback = {
        "name": number,
        "description": desired_interface["description"],
        "ip": {
            "address": {
                "primary": {
                    "address": str(ip.ip),
                    "mask": str(ip.netmask)
                }
            }
        }
    }
    if desired_interface["admin_state"] == "down":
        loopback["shutdown"] = [None]
    return {"Cisco-IOS-XE-native:Loopback": loopback}

def apply_interface(router, desired_interface, http_put=None):
    http_put = http_put or _default_http_put
    try:
        number = int(desired_interface["name"].removeprefix("Loopback"))
        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )
        response = http_put(url, json=_native_payload(number, desired_interface))
        if response.status_code in (200, 201, 204):
            return {"status": "ok", "result": "applied"}
        if response.status_code in (401, 403):
            return _error("authentication_failed")
        return _error("backend_failed")
    except Exception as exc:
        return _error_from_exception(exc)
