"""Parameterized circuit construction with static filler."""

import copy
import random
import numpy as np
from qiskit.circuit import QuantumCircuit
from dataclasses import dataclass, field
from . import backbone
from . import reference
from . import checks


def solve_rtm_composition(n_ryd_layers: int, n_routing_phases: int, n_mov_layers: int) -> dict:
    """Compute primitive counts after subtracting the initial Rydberg stage."""
    n223 = n_mov_layers - n_routing_phases
    n111 = 3 * n_routing_phases - 2 * n_mov_layers
    n100 = n_ryd_layers - n_routing_phases
    if n223 < 0 or n111 < 0 or n100 < 0:
        return None
    return {"223": n223, "111": n111, "100": n100}


class LayeredCircuit:
    def __init__(self, n_qubits):
        self.n_qubits = n_qubits

        self.layers = []
        self.backbone_qubits = []

    def add_layer(self, gates: list, **info):
        self.layers.append({
            'ops': gates,
            'filled': [],
            'extra': [],
            'info': info
        })

    def insert_gate_to_layer(self, layer_idx: int, gate: tuple):
        if 0 <= layer_idx < len(self.layers):
            self.layers[layer_idx]['filled'].append(gate)

    def to_qiskit(self):
        qc = QuantumCircuit(self.n_qubits)

        for layer in self.layers:
            all_ops = layer['ops'] + layer['filled'] + layer['extra']

            for gate_name, *qubits in all_ops:
                if hasattr(qc, gate_name):
                    getattr(qc, gate_name)(*qubits)
        return qc

    def count_gates(self):
        all_ops = []
        for layer in self.layers:
            all_ops.extend(layer['ops'])
            all_ops.extend(layer['filled'])
            all_ops.extend(layer['extra'])
        gate_count = {
            '1q': sum(1 for op in all_ops if len(op) == 2),
            '2q': sum(1 for op in all_ops if len(op) == 3)
        }
        return gate_count


@dataclass
class GenerationTask:
    config: dict

    target_1q_gatenum: int = 0
    target_2q_gatenum: int = 0
    rtm_composition: dict = field(default_factory=dict)
    generation_record: dict = field(default_factory=dict)

    circuit: LayeredCircuit = None

    def initialize_targets(self):
        N = self.config['qubit']

        T = self.config.get('depth', 0)
        d1 = self.config.get('d1', 0.0)
        d2 = self.config.get('d2', 0.0)

        if N < backbone.MIN_BACKBONE_QUBITS:
            raise ValueError(
                f"Task Error: qubit number must be at least {backbone.MIN_BACKBONE_QUBITS}"
            )

        if self.config['hardware']['type'] != 'common':
            raise ValueError("Task Error: only common hardware is supported by the 223 backbone")

        if self.config['n_ryd_layers'] < 1 or self.config['n_routing_phases'] < 0 or self.config['n_mov_layers'] < 0:
            raise ValueError(
                "Task Error: n_ryd_layers must be positive and routing/movement counts cannot be negative"
            )

        self.rtm_composition = solve_rtm_composition(
            self.config['n_ryd_layers'] - 1,
            self.config['n_routing_phases'],
            self.config['n_mov_layers'],
        )

        if self.rtm_composition is None:
            raise ValueError(f"Task Error: Invalid R-T-M combination: {self.config}")

        self.target_1q_gatenum = int(np.ceil(d1 * N * T))
        self.target_2q_gatenum = int(np.ceil(d2 * N * T / 2))


class BenchmarkGenerator:
    def __init__(self):
        self.config = None

    def set_paras(self, **kwargs):
        self.__dict__.update(kwargs)
        assert self.config["depth"] >= self.config["n_ryd_layers"], f'Circuit depth {self.config["depth"]} must more than or equal to rydberg layers {self.config["n_ryd_layers"]}.'
        hardware = self.config.get('hardware', {})
        if hardware.get('type') != 'common':
            raise ValueError("The 223 backbone currently supports common hardware only.")
        rows, cols = hardware.get('grid_size', (0, 0))
        if rows < 1 or cols < backbone.REQUIRED_COMMON_COLS:
            raise ValueError(
                f"Common hardware must have at least 1 row and {backbone.REQUIRED_COMMON_COLS} columns; "
                f"got grid_size={hardware.get('grid_size')}."
            )

    def generate_backbone_circuit(self, task: GenerationTask):
        task.circuit = LayeredCircuit(task.config['qubit'])
        rtm_composition = task.rtm_composition

        task.circuit.backbone_qubits = list(backbone.BACKBONE_QUBITS)

        task.backbone_initial_locations = backbone.initial_locations()
        task.backbone_workspace_cols = backbone.REQUIRED_COMMON_COLS
        task.circuit, state = self._add_substrate(
            task.circuit,
            task.backbone_initial_locations,
        )

        for i in range(rtm_composition['111']):
            task.circuit, state = self._add_111(task.circuit, state, i)

        for i in range(rtm_composition['223']):
            task.circuit, state = self._add_223(
                task.circuit,
                state,
                task.config['hardware']['grid_size'][1],
            )

        task.circuit, state = self._add_100(task.circuit, state, rtm_composition['100'])
        task.backbone_final_locations = copy.deepcopy(state)

        return task

    def _add_substrate(self, l_circuit, locations):
        locations = copy.deepcopy(locations)
        gates = [('cz', *pair) for pair in backbone.pairs_at_locations(locations)]
        l_circuit.add_layer(gates, type="100")
        return l_circuit, locations

    def _add_111(self, l_circuit, locations, index):
        direction = "right" if index % 2 == 0 else "left"
        gates, transition, new_locations = backbone.build_111_transition(
            locations,
            direction,
        )
        l_circuit.add_layer(
            [('cz', *pair) for pair in gates],
            type="111",
            transition=transition,
        )
        return l_circuit, new_locations

    def _add_223(self, l_circuit, locations, grid_cols):
        l0_gates, trans0, l1_gates, trans1, new_locations = backbone.build_223_transitions(
            locations,
            grid_cols,
        )
        l_circuit.add_layer(
            [('cz', *pair) for pair in l0_gates],
            type="223",
            gadget_stage=0,
            transition=trans0,
        )
        l_circuit.add_layer(
            [('cz', *pair) for pair in l1_gates],
            type="223",
            gadget_stage=1,
            transition=trans1,
        )
        return l_circuit, new_locations

    def _add_100(self, l_circuit, locations, count):
        for _ in range(count):
            gates = [('cz', *pair) for pair in backbone.pairs_at_locations(locations)]
            l_circuit.add_layer(gates, type="100")
        return l_circuit, locations

    def _extend_depth_with_h_gates(self, task: GenerationTask, need_1q_gatenum):
        target_depth = task.config['depth']

        while True:
            current_qc = task.circuit.to_qiskit()
            current_depth = current_qc.depth()

            delta_l = target_depth - current_depth

            if delta_l <= 0:
                break

            current_counts = task.circuit.count_gates()
            budget_1q = need_1q_gatenum - current_counts['1q']

            inserted_count = 0
            layers = task.circuit.layers

            for i in range(len(layers) - 1):
                if inserted_count >= delta_l:
                    break

                curr_layer = layers[i]
                next_layer = layers[i + 1]

                def get_qubits(layer):
                    qs = set()
                    for op in layer['ops'] + layer['filled']:
                        qs.update(op[1:])
                    return qs

                curr_qs = get_qubits(curr_layer)
                next_qs = get_qubits(next_layer)

                common_qs = list(curr_qs.intersection(next_qs))

                if common_qs:
                    target_q = random.choice(common_qs)

                    task.circuit.insert_gate_to_layer(i, ('h', target_q))

                    inserted_count += 1
                    budget_1q -= 1

            if inserted_count < delta_l:
                remaining_needed = delta_l - inserted_count
                last_layer = layers[-1]

                qs_in_last = set()
                for op in last_layer['ops'] + last_layer['filled']:
                    qs_in_last.update(op[1:])

                target_q = list(qs_in_last)[0] if qs_in_last else 0

                for _ in range(remaining_needed):
                    task.circuit.add_layer([('h', target_q)], type="tail_extension")
                    budget_1q -= 1
                    inserted_count += 1

        final_counts = task.circuit.count_gates()
        remaining_1q = need_1q_gatenum - final_counts['1q']

        return remaining_1q

    def _fill_remaining_gates(self, task, need_1q_gatenum, need_2q_gatenum):
        rydberg_layers = [
            layer for layer in task.circuit.layers
            if any(op[0] == 'cz' for op in layer['ops'] + layer['filled'])
        ]
        n_rydberg = len(rydberg_layers)
        if n_rydberg <= 0:
            raise ValueError("Static filler requires at least one Rydberg layer.")

        rows, cols = task.config['hardware']['grid_size']
        other_qubits = task.circuit.n_qubits - len(task.circuit.backbone_qubits)
        available_sites = rows * cols - task.backbone_workspace_cols
        min_pairs = max(0, other_qubits - available_sites)
        max_pairs = other_qubits // 2

        requested_extra_2q = need_2q_gatenum
        if requested_extra_2q <= 0:
            closest_pairs = 0
        else:
            quotient, remainder = divmod(requested_extra_2q, n_rydberg)
            closest_pairs = quotient + int(2 * remainder >= n_rydberg)
        selected_pairs = min(max(closest_pairs, min_pairs), max_pairs)

        init = self._allocate_storage_for_qubits_common(
            task,
            pair_count=selected_pairs,
        )
        task.init = copy.deepcopy(init)
        pair_ids = [(p[0], p[1]) for p in init['pairs']]

        for layer in rydberg_layers:
            layer['extra'].extend(('cz', q0, q1) for q0, q1 in pair_ids)
        added_2q = len(pair_ids) * n_rydberg

        added_1q = 0
        remaining_1q = max(0, need_1q_gatenum)
        if remaining_1q:
            terminal_depths = self._terminal_qubit_depths(task.circuit)
            target_depth = task.config['depth']
            additions = []
            for q, qubit_depth in enumerate(terminal_depths):
                capacity = max(0, target_depth - qubit_depth)
                add_count = min(capacity, remaining_1q)
                additions.extend([('h', q)] * add_count)
                remaining_1q -= add_count
                added_1q += add_count
                if remaining_1q == 0:
                    break
            task.circuit.layers[-1]['extra'].extend(additions)

        final_depth = task.circuit.to_qiskit().depth()
        if final_depth != task.config['depth']:
            raise AssertionError(
                f"Best-effort filler changed depth: expected {task.config['depth']}, got {final_depth}."
            )

        rest_1qgates = need_1q_gatenum - added_1q
        rest_2qgates = need_2q_gatenum - added_2q
        return task, rest_1qgates, rest_2qgates

    @staticmethod
    def _terminal_qubit_depths(circuit):
        depths = [0] * circuit.n_qubits
        for layer in circuit.layers:
            for operation in layer['ops'] + layer['filled'] + layer['extra']:
                qubits = operation[1:]
                finish = max((depths[q] for q in qubits), default=-1) + 1
                for q in qubits:
                    depths[q] = finish
        return depths

    def generate(self, num_circuit):
        config = self.config.copy()

        base_task = GenerationTask(config=config)

        try:
            base_task.initialize_targets()
        except ValueError:
            return [], {}

        base_task = self.generate_backbone_circuit(base_task)

        gate_count = base_task.circuit.count_gates()
        base_need_1q = base_task.target_1q_gatenum - gate_count['1q']
        base_need_2q = base_task.target_2q_gatenum - gate_count['2q']

        base_need_1q = self._extend_depth_with_h_gates(base_task, base_need_1q)
        qc_qiskit_depth = base_task.circuit.to_qiskit().depth()
        assert qc_qiskit_depth == config['depth']

        results = []
        for variant_id in range(num_circuit):
            task_variant = copy.deepcopy(base_task)

            var_need_1q = base_need_1q
            var_need_2q = base_need_2q

            task_variant, var_need_1q, var_need_2q = self._fill_remaining_gates(
                task_variant, var_need_1q, var_need_2q
            )

            if task_variant.circuit.to_qiskit().depth() != config['depth']:
                raise AssertionError("Best-effort generation violated the requested depth.")

            nacom = reference.ReferenceCompiler()
            nacom.grid_size = self.config['hardware']['grid_size']
            task_variant, state_list = nacom.compile(task_variant)
            task_variant.generation_record = self._build_generation_record(
                task_variant,
                state_list,
            )
            v = checks.Verifier(task_variant, state_list)
            v.verify()

            results.append({
                "task": task_variant,
                "state_list": state_list,
                "success": True,
                "rest_1q": var_need_1q,
                "rest_2q": var_need_2q,
                "generation_record": task_variant.generation_record,
                "id": variant_id,
            })

        return results, base_task.rtm_composition

    @staticmethod
    def _build_generation_record(task, state_list):
        requested_1q = task.target_1q_gatenum
        requested_2q = task.target_2q_gatenum
        generated_counts = task.circuit.count_gates()
        generated_depth = task.circuit.to_qiskit().depth()
        denominator = task.config['qubit'] * task.config['depth']

        generated_r = sum(item.get('class') == 'rydberg' for item in state_list)
        generated_t = sum(item.get('class') == 'trans' for item in state_list)
        generated_m = sum(
            len([layer for layer in item.get('movement_layers', []) if layer])
            for item in state_list
            if item.get('class') == 'trans'
        )

        requested = {
            'depth': task.config['depth'],
            'one_qubit_gates': requested_1q,
            'two_qubit_gates': requested_2q,
            'd1': task.config.get('d1', 0.0),
            'd2': task.config.get('d2', 0.0),
            'R': task.config['n_ryd_layers'],
            'T': task.config['n_routing_phases'],
            'M': task.config['n_mov_layers'],
        }
        generated = {
            'depth': generated_depth,
            'one_qubit_gates': generated_counts['1q'],
            'two_qubit_gates': generated_counts['2q'],
            'd1': generated_counts['1q'] / denominator if denominator else 0.0,
            'd2': (2 * generated_counts['2q']) / denominator if denominator else 0.0,
            'R': generated_r,
            'T': generated_t,
            'M': generated_m,
        }

        storage = task.init.get('storage', {})
        deviations = []
        delta_1q = generated_counts['1q'] - requested_1q
        delta_2q = generated_counts['2q'] - requested_2q
        if delta_1q:
            deviations.append({
                'metric': 'one_qubit_gates',
                'delta': delta_1q,
                'reason': 'logical_depth_floor' if delta_1q > 0 else 'logical_depth_capacity',
            })
        if delta_2q:
            if delta_2q > 0 and storage.get('selected_pair_count') == storage.get('minimum_pair_count'):
                reason = 'static_storage_capacity'
            elif delta_2q < 0 and storage.get('selected_pair_count') == storage.get('maximum_pair_count'):
                reason = 'static_pair_capacity'
            else:
                reason = 'static_pair_granularity'
            deviations.append({
                'metric': 'two_qubit_gates',
                'delta': delta_2q,
                'reason': reason,
            })

        rtm_preserved = (
            generated_r == requested['R']
            and generated_t == requested['T']
            and generated_m == requested['M']
        )
        return {
            'schema_version': 1,
            'status': 'exact' if not deviations else 'best_effort',
            'policy': 'static_filler_no_extra_routing',
            'requested': requested,
            'generated': generated,
            'deviations': deviations,
            'static_filler': storage,
            'rtm_preserved': rtm_preserved,
            'generation_passes': 1,
        }

    def _allocate_storage_for_qubits_common(self, task, pair_count=None):
        rows, cols = task.config['hardware']['grid_size']
        num_qubits = task.config['qubit']
        workspace_cols = task.backbone_workspace_cols
        if cols < workspace_cols:
            raise ValueError(
                f"Backbone workspace needs {workspace_cols} columns, but hardware has {cols}."
            )

        grid = [[[None, None] for _ in range(cols)] for _ in range(rows)]
        blocked = [[False for _ in range(cols)] for _ in range(rows)]

        for q, (row, col, slot) in task.backbone_initial_locations.items():
            if row >= rows or col >= cols:
                raise ValueError("Initial backbone placement is outside the common grid.")
            grid[row][col][slot] = q

        for col in range(workspace_cols):
            blocked[0][col] = True

        other_ids = [
            q for q in range(num_qubits)
            if q not in task.circuit.backbone_qubits
        ]
        random.shuffle(other_ids)
        available_sites = rows * cols - workspace_cols
        minimum_pair_count = max(0, len(other_ids) - available_sites)
        maximum_pair_count = len(other_ids) // 2
        if pair_count is None:
            pair_count = maximum_pair_count
        if not minimum_pair_count <= pair_count <= maximum_pair_count:
            raise ValueError(
                f"Static filler pair count must be in [{minimum_pair_count}, "
                f"{maximum_pair_count}], got {pair_count}."
            )

        other_pairs = []
        for _ in range(pair_count):
            other_pairs.append((other_ids.pop(), other_ids.pop()))
        other_singles = list(other_ids)

        occupants = [list(pair) for pair in other_pairs]
        occupants.extend([[q, None] for q in other_singles])
        occupant_index = 0
        for row in range(rows):
            for col in range(cols):
                if occupant_index >= len(occupants):
                    break
                if blocked[row][col] or grid[row][col] != [None, None]:
                    continue
                grid[row][col] = occupants[occupant_index]
                occupant_index += 1

        if occupant_index != len(occupants):
            raise ValueError(
                "Common grid cannot fit all qubits after reserving the 223 workspace."
            )

        locations = {}
        for row in range(rows):
            for col in range(cols):
                q0, q1 = grid[row][col]
                if q0 is not None:
                    locations[q0] = (row, col, 0)
                if q1 is not None:
                    locations[q1] = (row, col, 1)

        pair_lookup = {}
        for q0, q1 in other_pairs:
            pair_lookup[q0] = q1
            pair_lookup[q1] = q0

        return {
            "locations": locations,
            "pairs": other_pairs,
            "pair_lookup": pair_lookup,
            "singles": other_singles,
            "storage": {
                "available_sites": available_sites,
                "minimum_pair_count": minimum_pair_count,
                "maximum_pair_count": maximum_pair_count,
                "selected_pair_count": pair_count,
                "two_qubit_gate_quantum": task.config['n_ryd_layers'],
            },
        }
