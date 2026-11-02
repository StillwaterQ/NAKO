"""Reusable eight-qubit movement primitives."""

import copy
from collections import defaultdict

MIN_BACKBONE_QUBITS = 8
REQUIRED_COMMON_COLS = 8
BACKBONE_QUBITS = tuple(range(MIN_BACKBONE_QUBITS))

INITIAL_SITE_PAIRS = ((0, 1), (2, 3), (6, 7), (4, 5))


def initial_locations(row=0):
    locations = {}
    for col, pair in enumerate(INITIAL_SITE_PAIRS):
        locations[pair[0]] = (row, col, 0)
        locations[pair[1]] = (row, col, 1)
    return locations


def pairs_at_locations(locations):
    groups = _ordered_site_groups(locations)
    if len(groups) != 4 or any(len(qubits) != 2 for _, qubits in groups):
        raise ValueError("Backbone state must contain four fully occupied sites.")
    return [tuple(qubits) for _, qubits in groups]


def build_111_transition(locations, direction):
    groups = _ordered_site_groups(locations)
    if len(groups) != 4 or any(len(qubits) != 2 for _, qubits in groups):
        raise ValueError("111 requires four pair sites on one row.")

    rows = {site[0] for site, _ in groups}
    if len(rows) != 1:
        raise ValueError("111 requires all backbone pairs on one row.")

    (left_site, left_pair), (right_site, right_pair) = groups[-2:]
    row = left_site[0]
    left_col = left_site[1]
    right_col = right_site[1]
    if right_col != left_col + 1:
        raise ValueError("111 requires its two active pair sites to be adjacent.")

    a, b = left_pair
    c, d = right_pair
    new_locations = copy.deepcopy(locations)

    if direction == "right":
        new_locations[c] = (row, right_col, 0)
        new_locations[a] = (row, right_col, 1)
        new_locations[b] = (row, right_col + 1, 0)
        new_locations[d] = (row, right_col + 1, 1)
    elif direction == "left":
        new_locations[a] = (row, left_col - 1, 0)
        new_locations[c] = (row, left_col - 1, 1)
        new_locations[d] = (row, left_col, 0)
        new_locations[b] = (row, left_col, 1)
    else:
        raise ValueError(f"Unsupported 111 direction: {direction}")

    transition = _build_transition(locations, [new_locations])
    return pairs_at_locations(new_locations), transition, new_locations


def build_223_transitions(locations, grid_cols):
    groups = _ordered_site_groups(locations)
    if len(groups) != 4 or any(len(qubits) != 2 for _, qubits in groups):
        raise ValueError("223 requires four pair sites on one row.")

    rows = {site[0] for site, _ in groups}
    if len(rows) != 1:
        raise ValueError("223 requires all backbone pairs on one row.")

    row = groups[0][0][0]
    initial_cols = [site[1] for site, _ in groups]
    template_cols = initial_cols + [initial_cols[-1] + offset for offset in (1, 2, 3)]
    if template_cols[-1] >= grid_cols:
        raise ValueError(
            f"223 needs columns through {template_cols[-1]}, but hardware width is {grid_cols}."
        )

    roles = {}
    roles[0], roles[1] = groups[0][1]
    roles[2], roles[3] = groups[1][1]
    roles[6], roles[7] = groups[2][1]
    roles[4], roles[5] = groups[3][1]

    state1 = _locations_from_role_state(
        roles,
        row,
        template_cols,
        {
            0: (1, 1), 1: (2, 0), 2: (1, 0), 3: (2, 1),
            4: (3, 0), 5: (5, 1), 6: (3, 1), 7: (5, 0),
        },
    )
    state2 = _locations_from_role_state(
        roles,
        row,
        template_cols,
        {
            0: (3, 0), 1: (2, 0), 2: (1, 0), 3: (4, 0),
            4: (6, 1), 5: (5, 1), 6: (3, 1), 7: (5, 0),
        },
    )
    state3 = _locations_from_role_state(
        roles,
        row,
        template_cols,
        {
            0: (3, 0), 1: (2, 0), 2: (0, 0), 3: (1, 0),
            4: (3, 1), 5: (2, 1), 6: (0, 1), 7: (1, 1),
        },
    )

    first_transition = _build_transition(locations, [state1])
    second_transition = _build_transition(state1, [state2, state3])

    if {pos[:2] for pos in state3.values()} != {pos[:2] for pos in locations.values()}:
        raise AssertionError("223 template did not preserve the occupied site set.")

    return (
        pairs_at_locations(state1),
        first_transition,
        pairs_at_locations(state3),
        second_transition,
        state3,
    )


def validate_transition(start_locations, movement_layers, end_locations):
    current = copy.deepcopy(start_locations)
    for layer in movement_layers:
        moved = []
        next_locations = copy.deepcopy(current)
        for movement in layer:
            q = movement["qubit"]
            start = tuple(movement["start_logical"])
            end = tuple(movement["end_logical"])
            if tuple(current[q]) != start:
                raise ValueError(f"Movement for q{q} starts from a stale location.")
            next_locations[q] = end
            moved.append(q)

        if len(set(next_locations.values())) != len(next_locations):
            raise ValueError("Movement layer places two qubits in the same slot.")

        for i, qa in enumerate(moved):
            for qb in moved[i + 1:]:
                if _relation(_x(current[qa]), _x(current[qb])) != _relation(
                    _x(next_locations[qa]), _x(next_locations[qb])
                ):
                    raise ValueError("Movement layer violates AOD x-order preservation.")
                if _relation(current[qa][0], current[qb][0]) != _relation(
                    next_locations[qa][0], next_locations[qb][0]
                ):
                    raise ValueError("Movement layer violates AOD y-order preservation.")

        current = next_locations

    if current != end_locations:
        raise ValueError("Movement layers do not reach the declared final state.")
    return True


def _build_transition(start_locations, states):
    movement_layers = []
    current = copy.deepcopy(start_locations)
    for next_locations in states:
        layer = []
        for q in sorted(current):
            if current[q] != next_locations[q]:
                layer.append({
                    "qubit": q,
                    "start_logical": list(current[q]),
                    "end_logical": list(next_locations[q]),
                })
        movement_layers.append(layer)
        current = copy.deepcopy(next_locations)

    transition = {
        "start_locations": copy.deepcopy(start_locations),
        "movement_layers": movement_layers,
        "end_locations": copy.deepcopy(current),
    }
    validate_transition(
        transition["start_locations"],
        transition["movement_layers"],
        transition["end_locations"],
    )
    return transition


def _ordered_site_groups(locations):
    groups = defaultdict(list)
    for q, (row, col, slot) in locations.items():
        groups[(row, col)].append((slot, q))

    ordered = []
    for site in sorted(groups):
        ordered.append((site, [q for _, q in sorted(groups[site])]))
    return ordered


def _locations_from_role_state(roles, row, cols, role_state):
    return {
        roles[role]: (row, cols[col_idx], slot)
        for role, (col_idx, slot) in role_state.items()
    }


def _x(location):
    return 2 * location[1] + location[2]


def _relation(a, b):
    return (a > b) - (a < b)
