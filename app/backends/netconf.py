import os, xml.etree.ElementTree as ET
from ipaddress import IPv4Interface
from xml.sax.saxutils import escape
from ncclient import manager
from ncclient.operations.errors import TimeoutExpiredError
from ncclient.transport.errors import AuthenticationError, TransportError
from app.backends import planning

IF_NS = "urn:ietf:params:xml:ns:yang:ietf-interfaces"
IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"
NC_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"

TIMEOUT = 10

def _error(code):
    return {"status": "error", "result": code}

def _error_from_exception(exc):
    if isinstance(exc, (PermissionError, AuthenticationError)):
        return _error("authentication_failed")
    if isinstance(exc, (ConnectionError, TimeoutError, OSError, TransportError, TimeoutExpiredError)):
        return _error("connection_failed")
    return _error("backend_failed")

def _connect(router):
    return manager.connect(
        host=router,
        port=830,
        username=os.environ.get("ROUTER_USER", ""),
        password=os.environ.get("ROUTER_PASS", ""),
        hostkey_verify=False,
        allow_agent=False,
        look_for_keys=False,
        timeout=TIMEOUT,
        device_params={"name": "iosxe"}
    )

def _default_netconf_get_config(router, filter_xml):
    with _connect(router) as session:
        reply = session.get_config(
            source="running",
            filter=("subtree", filter_xml)
        )
        return reply.data_xml

def _default_netconf_edit_config(router, config_xml):
    with _connect(router) as session:
        session.edit_config(target="running", config=config_xml)

def _text(element, path):
    found = element.find(path)
    if found is None or found.text is None:
        return None
    return found.text.strip()

def _normalize(xml_text, interface_name):
    root = ET.fromstring(xml_text)
    for interface in root.iter(f"{{{IF_NS}}}interface"):
        if _text(interface, f"{{{IF_NS}}}name") != interface_name:
            continue
        ipv4 = None
        address = interface.find(f"{{{IP_NS}}}ipv4/{{{IP_NS}}}address")
        if address is not None:
            ip = _text(address, f"{{{IP_NS}}}ip")
            netmask = _text(address, f"{{{IP_NS}}}netmask")
            ipv4 = str(IPv4Interface(f"{ip}/{netmask}"))
        enabled = _text(interface, f"{{{IF_NS}}}enabled")
        if enabled not in ("true", "false"):
            raise ValueError(f"unexpected <enabled> value: {enabled!r}")
        return {
            "name": interface_name,
            "ipv4": ipv4,
            "description": _text(interface, f"{{{IF_NS}}}description"),
            "admin_state": "up" if enabled == "true" else "down"
        }
    return None

def get_interface_state(router, interface_name, netconf_get_config=None):
    netconf_get_config = netconf_get_config or _default_netconf_get_config
    filter_xml = (
        f'<interfaces xmlns="{IF_NS}">'
        f"<interface><name>{escape(interface_name)}</name></interface>"
        f"</interfaces>"
    )
    try:
        xml_text = netconf_get_config(router, filter_xml)
        interface = _normalize(xml_text, interface_name)
        if interface is None:
            return {"status": "ok", "result": "not_found", "interface": None}
        return {"status": "ok", "result": "found", "interface": interface}
    except Exception as exc:
        return _error_from_exception(exc)

def plan_interface(router, desired_interface, netconf_get_config=None):
    def status(router_, interface_name):
        return get_interface_state(router_, interface_name, netconf_get_config)
    return planning.plan_interface(router, desired_interface, status)

def _config_xml(desired_interface):
    number = int(desired_interface["name"].removeprefix("Loopback"))
    ip = IPv4Interface(desired_interface["ipv4"])
    description = escape(desired_interface["description"])
    shutdown = "<shutdown/>" if desired_interface["admin_state"] == "down" else ""
    return (
        f'<config xmlns="{NC_NS}" xmlns:nc="{NC_NS}">'
        f'<native xmlns="{NATIVE_NS}"><interface>'
        f'<Loopback nc:operation="replace">'
        f"<name>{number}</name>"
        f"<description>{description}</description>"
        f"<ip><address><primary>"
        f"<address>{ip.ip}</address><mask>{ip.netmask}</mask>"
        f"</primary></address></ip>"
        f"{shutdown}"
        f"</Loopback></interface></native></config>"
    )

def apply_interface(router, desired_interface, netconf_edit_config=None):
    netconf_edit_config = netconf_edit_config or _default_netconf_edit_config
    try:
        netconf_edit_config(router, _config_xml(desired_interface))
        return {"status": "ok", "result": "applied"}
    except Exception as exc:
        return _error_from_exception(exc)
