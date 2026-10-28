import json, os, subprocess
from ipaddress import IPv4Interface
from pathlib import Path

ANSIBLE_DIR = Path(__file__).resolve().parents[2] / "ansible"
INVENTORY = ANSIBLE_DIR / "inventory.ini"
PLAYBOOK = ANSIBLE_DIR / "apply_interface.yml"

TIMEOUT = 60

_CONNECTION_MARKERS = (
    "unable to connect",
    "timed out",
    "connection refused",
    "no route to host",
    "network is unreachable",
    "name or service not known"
)

def _error(code):
    return {"status": "error", "result": code}

def _error_from_exception(exc):
    if isinstance(exc, PermissionError):
        return _error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return _error("connection_failed")
    return _error("backend_failed")

def _failure(stdout):
    try:
        for play in json.loads(stdout)["plays"]:
            for task in play["tasks"]:
                for result in task["hosts"].values():
                    if result.get("failed") or result.get("unreachable"):
                        return str(result.get("msg", "")), bool(result.get("unreachable"))
    except (ValueError, KeyError, TypeError):
        pass
    return "", False

def _default_run_playbook(variables):
    env = {
        **os.environ,
        "ANSIBLE_STDOUT_CALLBACK": "ansible.posix.json",
        "ANSIBLE_HOST_KEY_CHECKING": "False"
    }
    try:
        completed = subprocess.run(
            [
                "ansible-playbook",
                "-i", str(INVENTORY),
                str(PLAYBOOK),
                "--extra-vars", json.dumps(variables)
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("ansible-playbook timed out") from exc
    if completed.returncode == 0:
        return
    message, unreachable = _failure(completed.stdout)
    lowered = message.lower()
    if "authentication" in lowered or "permission denied" in lowered:
        raise PermissionError(message)
    if unreachable or any(marker in lowered for marker in _CONNECTION_MARKERS):
        raise ConnectionError(message)
    raise RuntimeError(message or completed.stderr)

def apply_interface(
    router, desired_interface, run_playbook=None):
    run_playbook = run_playbook or _default_run_playbook
    try:
        ip = IPv4Interface(desired_interface["ipv4"])
        run_playbook(
            {
                "router": router,
                "interface_name": desired_interface["name"],
                "description": desired_interface["description"],
                "ipv4_address": str(ip.ip),
                "netmask": str(ip.netmask),
                "shutdown": desired_interface["admin_state"] == "down"
            }
        )
        return {"status": "ok", "result": "applied"}
    except Exception as exc:
        return _error_from_exception(exc)
