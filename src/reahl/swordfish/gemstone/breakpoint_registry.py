import uuid


breakpoints_by_session_key = {}
breakpoints_by_id = {}
session_key_by_breakpoint_id = {}


def session_key_for(gemstone_session):
    return id(gemstone_session)


def breakpoint_for_session(gemstone_session, breakpoint_id):
    selected_session_key = session_key_for(gemstone_session)
    session_breakpoints = breakpoints_by_session_key.get(
        selected_session_key,
        {},
    )
    breakpoint_entry = session_breakpoints.get(breakpoint_id)
    if breakpoint_entry is None:
        return None
    return dict(breakpoint_entry)


def list_breakpoints_for_session(gemstone_session):
    selected_session_key = session_key_for(gemstone_session)
    session_breakpoints = breakpoints_by_session_key.get(
        selected_session_key,
        {},
    )
    return [
        dict(entry)
        for entry in sorted(
            session_breakpoints.values(),
            key=lambda entry: (
                entry['class_name'],
                entry['method_selector'],
                entry['show_instance_side'],
                entry['source_offset'],
                entry['breakpoint_id'],
            ),
        )
    ]


def find_breakpoint_for_method_step_point(
    gemstone_session,
    class_name,
    show_instance_side,
    method_selector,
    step_point,
):
    session_breakpoints = list_breakpoints_for_session(gemstone_session)
    matching_breakpoint = None
    index = 0
    session_breakpoint_count = len(session_breakpoints)
    while index < session_breakpoint_count:
        breakpoint_entry = session_breakpoints[index]
        same_class = breakpoint_entry['class_name'] == class_name
        same_side = (
            breakpoint_entry['show_instance_side'] == show_instance_side
        )
        same_selector = breakpoint_entry['method_selector'] == method_selector
        same_step_point = breakpoint_entry['step_point'] == step_point
        if same_class and same_side and same_selector and same_step_point:
            matching_breakpoint = breakpoint_entry
        index += 1
    return matching_breakpoint


def record_breakpoint_for_session(
    gemstone_session,
    class_name,
    show_instance_side,
    method_selector,
    source_offset,
    step_point,
):
    existing_breakpoint = find_breakpoint_for_method_step_point(
        gemstone_session,
        class_name,
        show_instance_side,
        method_selector,
        step_point,
    )
    if existing_breakpoint is not None:
        return existing_breakpoint
    breakpoint_id = str(uuid.uuid4())
    breakpoint_entry = {
        'breakpoint_id': breakpoint_id,
        'class_name': class_name,
        'show_instance_side': show_instance_side,
        'method_selector': method_selector,
        'source_offset': source_offset,
        'step_point': step_point,
    }
    selected_session_key = session_key_for(gemstone_session)
    breakpoints_by_session_key.setdefault(selected_session_key, {})
    breakpoints_by_session_key[selected_session_key][breakpoint_id] = (
        breakpoint_entry
    )
    breakpoints_by_id[breakpoint_id] = breakpoint_entry
    session_key_by_breakpoint_id[breakpoint_id] = selected_session_key
    return dict(breakpoint_entry)


def remove_breakpoint_for_session(gemstone_session, breakpoint_id):
    selected_session_key = session_key_for(gemstone_session)
    if session_key_by_breakpoint_id.get(breakpoint_id) != selected_session_key:
        return None
    session_breakpoints = breakpoints_by_session_key.get(
        selected_session_key,
        {},
    )
    breakpoint_entry = session_breakpoints.pop(breakpoint_id, None)
    breakpoints_by_id.pop(breakpoint_id, None)
    session_key_by_breakpoint_id.pop(breakpoint_id, None)
    if not session_breakpoints and selected_session_key in breakpoints_by_session_key:
        breakpoints_by_session_key.pop(selected_session_key)
    if breakpoint_entry is None:
        return None
    return dict(breakpoint_entry)


def clear_breakpoints_for_session(gemstone_session):
    selected_session_key = session_key_for(gemstone_session)
    session_breakpoints = breakpoints_by_session_key.pop(
        selected_session_key,
        {},
    )
    removed_breakpoints = []
    for breakpoint_id, breakpoint_entry in session_breakpoints.items():
        breakpoints_by_id.pop(breakpoint_id, None)
        session_key_by_breakpoint_id.pop(breakpoint_id, None)
        removed_breakpoints.append(dict(breakpoint_entry))
    return removed_breakpoints


def clear_all_breakpoints():
    breakpoints_by_session_key.clear()
    breakpoints_by_id.clear()
    session_key_by_breakpoint_id.clear()
