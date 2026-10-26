import yaml

ALLOWED_ROUTERS = (
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105"
)

METHOD_ACTIONS = {
    "restconf": ("status", "plan", "apply"),
    "netconf": ("status", "plan", "apply"),
    "ansible": ("apply",),
    "netmiko-textfsm": ("status", "delete")
}

FULL_STATE_ACTIONS = ("plan", "apply")
ADMIN_STATES = ("up", "down")

def _error(code):
    return {"status": "error", "result": code}

def _is_missing(value):
    return value is None

def validate_request(data):
    """
    Validate one IPA2026 desired-state request.
    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    # Root must be a mapping (a list, string, number or empty file is not).
    if not isinstance(data, dict):
        return _error("invalid_yaml")
    # 1. version: must be the integer 1.
    version = data.get("version")
    if type(version) is not int or version != 1:
        return _error("invalid_version")
    # 2. router
    router = data.get("router")
    if _is_missing(router):
        return _error("missing_router")
    if router not in ALLOWED_ROUTERS:
        return _error("invalid_router")
    # 3. method
    method = data.get("method")
    if _is_missing(method):
        return _error("missing_method")
    # isinstance first: an unhashable value (list/dict) would crash `in dict`.
    if not isinstance(method, str) or method not in METHOD_ACTIONS:
        return _error("invalid_method")
    # 4. action (must be supported by the selected method)
    action = data.get("action")
    if _is_missing(action):
        return _error("missing_action")
    if not isinstance(action, str) or action not in METHOD_ACTIONS[method]:
        return _error("invalid_action")
    # 5. desired -> interface -> name (required for every action)
    desired = data.get("desired")
    if _is_missing(desired) or not isinstance(desired, dict):
        return _error("missing_desired")
    interface = desired.get("interface")
    if _is_missing(interface) or not isinstance(interface, dict):
        return _error("missing_interface")
    name = interface.get("name")
    if not isinstance(name, str) or not name.strip():
        return _error("missing_interface_name")
    # 6. Complete desired state: plan and apply ONLY.
    if action in FULL_STATE_ACTIONS:
        if _is_missing(interface.get("ipv4")):
            return _error("missing_ipv4")
        if _is_missing(interface.get("description")):
            return _error("missing_description")
        admin_state = interface.get("admin_state")
        if _is_missing(admin_state):
            return _error("missing_admin_state")
        if not isinstance(admin_state, str) or admin_state not in ADMIN_STATES:
            return _error("invalid_admin_state")
    return {"status": "ok", "result": "accepted"}

def load_request_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f), None
    except (yaml.YAMLError, UnicodeDecodeError):
        return None, _error("invalid_yaml")

def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    data, error = load_request_file(path)
    if error is not None:
        return error
    return validate_request(data)
