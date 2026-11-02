"""Reference schedules from construction-time movements."""

import copy

from . import backbone


class ReferenceCompiler:
    def __init__(self):
        self.state_list = []
        self.grid_size = None

    def compile(self, task):
        current_locations = {
            q: tuple(location)
            for q, location in task.init['locations'].items()
        }
        self.state_list = [{
            "class": "location",
            "location": copy.deepcopy(current_locations),
        }]

        for layer_index, layer in enumerate(task.circuit.layers):
            transition = layer.get('info', {}).get('transition')
            if transition is not None:
                current_locations = self._append_transition(
                    task,
                    layer_index,
                    current_locations,
                    transition,
                )
            self._append_gate_operations(layer)

        return task, self.state_list

    def _append_transition(self, task, layer_index, current_locations, transition):
        start_locations = {
            int(q): tuple(location)
            for q, location in transition['start_locations'].items()
        }
        end_locations = {
            int(q): tuple(location)
            for q, location in transition['end_locations'].items()
        }
        movement_layers = copy.deepcopy(transition['movement_layers'])

        for q in task.circuit.backbone_qubits:
            if current_locations[q] != start_locations[q]:
                raise ValueError(
                    f"Layer {layer_index} movement plan starts from the wrong location for q{q}: "
                    f"compiled={current_locations[q]}, planned={start_locations[q]}"
                )

        backbone.validate_transition(start_locations, movement_layers, end_locations)
        self.state_list.append({
            "class": "trans",
            "movement_layers": movement_layers,
        })

        new_locations = copy.deepcopy(current_locations)
        new_locations.update(end_locations)
        self.state_list.append({
            "class": "location",
            "location": copy.deepcopy(new_locations),
        })
        return new_locations

    def _append_gate_operations(self, layer):
        all_ops = layer.get('ops', []) + layer.get('filled', []) + layer.get('extra', [])
        cz_pairs = [tuple(op[1:]) for op in all_ops if op[0] == 'cz']
        h_gates = [op[1] for op in all_ops if op[0] == 'h']

        if cz_pairs:
            self.state_list.append({
                "class": "rydberg",
                "gates": cz_pairs,
            })
        if h_gates:
            self.state_list.append({
                "class": "single-qubit gate",
                "gates": h_gates,
            })
