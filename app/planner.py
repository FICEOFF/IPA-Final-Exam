MANAGED_FIELDS = ("ipv4", "description", "admin_state")

def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    changes = {}
    if current_interface is None:
        # The interface does not exist: every managed field is a change, and there is no "from" value to report.
        operation = "create"
        for field in MANAGED_FIELDS:
            changes[field] = {"to": desired_interface[field]}
    else:
        # The interface exists: report only the fields that differ.
        # .get() because normalized state uses None for "not configured"
        # (e.g. an interface with no description).
        for field in MANAGED_FIELDS:
            current_value = current_interface.get(field)
            desired_value = desired_interface[field]
            if current_value != desired_value:
                changes[field] = {"from": current_value, "to": desired_value}
        operation = "update" if changes else "no_change"
    return {"status": "ok", "result": "planned", "operation": operation, "changes": changes}
