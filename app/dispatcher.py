from app.backends import ansible, netconf, netmiko_textfsm, restconf

ROUTES = {
    ("restconf", "status"): (restconf, "get_interface_state"),
    ("restconf", "plan"): (restconf, "plan_interface"),
    ("restconf", "apply"): (restconf, "apply_interface"),
    ("netconf", "status"): (netconf, "get_interface_state"),
    ("netconf", "plan"): (netconf, "plan_interface"),
    ("netconf", "apply"): (netconf, "apply_interface"),
    ("ansible", "apply"): (ansible, "apply_interface"),
    ("netmiko-textfsm", "status"): (netmiko_textfsm, "get_interface_state"),
    ("netmiko-textfsm", "delete"): (netmiko_textfsm, "delete_interface")
}

def dispatch_request(data):
    route = ROUTES.get((data["method"], data["action"]))
    if route is None:
        return {"status": "error", "result": "invalid_action"}
    module, function_name = route
    backend = getattr(module, function_name)
    router = data["router"]
    interface = data["desired"]["interface"]
    if data["action"] in ("status", "delete"):
        return backend(router, interface["name"])
    return backend(router, interface)
