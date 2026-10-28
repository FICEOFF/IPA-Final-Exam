from app.planner import build_plan

def plan_interface(router, desired_interface, get_interface_state):
    response = get_interface_state(router, desired_interface["name"])
    if response["status"] == "error":
        return response
    if response["result"] == "found":
        current_interface = response["interface"]
    else:
        current_interface = None
    return build_plan(desired_interface, current_interface)
