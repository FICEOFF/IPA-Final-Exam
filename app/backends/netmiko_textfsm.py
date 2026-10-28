import os, re
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

def _error(code):
    return {"status": "error", "result": code}

def _error_from_exception(exc):
    if isinstance(exc, (PermissionError, NetmikoAuthenticationException)):
        return _error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError, NetmikoTimeoutException)):
        return _error("connection_failed")
    return _error("backend_failed")

def _connect(router):
    return ConnectHandler(
        device_type="cisco_ios",
        host=router,
        username=os.environ.get("ROUTER_USER", ""),
        password=os.environ.get("ROUTER_PASS", "")
    )

def _read(connection, interface_name):
    ip_info = connection.send_command(
        f"show ip interface {interface_name}",
        use_textfsm=True
    )
    if isinstance(ip_info, str) and "Invalid input" in ip_info:
        return [], []
    descriptions = connection.send_command(
        "show interfaces description",
        use_textfsm=True
    )
    return ip_info, descriptions

def _default_netmiko_get(router, interface_name):
    with _connect(router) as connection:
        return _read(connection, interface_name)

def _default_netmiko_delete(router, interface_name):
    with _connect(router) as connection:
        ip_info, descriptions = _read(connection, interface_name)
        if _normalize(ip_info, descriptions, interface_name) is None:
            return "not_found"
        connection.send_config_set([f"no interface {interface_name}"])
        ip_info, descriptions = _read(connection, interface_name)
        if _normalize(ip_info, descriptions, interface_name) is not None:
            raise RuntimeError(f"{interface_name} still exists after delete")
        return "deleted"

def _expand_loopback(port):
    match = re.fullmatch(r"Lo(?:opback)?(\d+)", port.strip())
    return f"Loopback{match.group(1)}" if match else port.strip()

def _normalize(ip_info, descriptions, interface_name):
    if not isinstance(ip_info, list) or not isinstance(descriptions, list):
        raise ValueError("CLI output was not parsed by TextFSM")
    record = next((item for item in ip_info if item["interface"] == interface_name), None)
    if record is None:
        return None
    ipv4 = None
    if record["ip_address"]:
        ipv4 = f"{record['ip_address'][0]}/{record['prefix_length'][0]}"
    if "administratively down" in record["link_status"].lower():
        admin_state = "down"
    else:
        admin_state = "up"
    description = None
    for item in descriptions:
        if _expand_loopback(item["port"]) == interface_name:
            description = item["description"].strip() or None
            break
    return {
        "name": interface_name,
        "ipv4": ipv4,
        "description": description,
        "admin_state": admin_state
    }

def get_interface_state(router, interface_name, netmiko_get=None):
    netmiko_get = netmiko_get or _default_netmiko_get
    try:
        ip_info, descriptions = netmiko_get(router, interface_name)
        interface = _normalize(ip_info, descriptions, interface_name)
        if interface is None:
            return {"status": "ok", "result": "not_found", "interface": None}
        return {"status": "ok", "result": "found", "interface": interface}
    except Exception as exc:
        return _error_from_exception(exc)

def delete_interface(router, interface_name, netmiko_delete=None):
    netmiko_delete = netmiko_delete or _default_netmiko_delete
    try:
        outcome = netmiko_delete(router, interface_name)
    except Exception as exc:
        return _error_from_exception(exc)
    if outcome == "deleted":
        return {"status": "ok", "result": "deleted"}
    if outcome == "not_found":
        return {"status": "ok", "result": "not_found", "interface": None}
    return _error("backend_failed")
