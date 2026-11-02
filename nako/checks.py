"""Runtime checks for circuit dimensions and resource counts."""

import numpy as np


class Verifier:
    def __init__(self, task, state_list):
        self.task = task
        self.state_list = state_list
        self.config = task.config
        self.circuit = task.circuit
        self.qc_qiskit = task.circuit.to_qiskit()

    def verify(self):
        self._check_qubit_and_depth()
        self._check_densities()
        self._check_n_ryd_layers()
        self._check_n_routing_phases_and_mov()
        return True

    def _check_qubit_and_depth(self):
        if self.qc_qiskit.num_qubits != self.config['qubit']:
            raise AssertionError(
                f"Qubit count mismatch: expected {self.config['qubit']}, got {self.qc_qiskit.num_qubits}")

        if self.qc_qiskit.depth() != self.config['depth']:
            raise AssertionError(f"Depth mismatch: expected {self.config['depth']}, got {self.qc_qiskit.depth()}")

    def _check_densities(self):
        N = self.config['qubit']
        T = self.config['depth']

        expected_1q = int(np.ceil(self.config['d1'] * N * T))
        expected_2q = int(np.ceil(self.config['d2'] * N * T / 2))

        counts = self.circuit.count_gates()
        actual_1q = counts['1q']
        actual_2q = counts['2q']

        if self.config.get('strict_gate_targets', False) and actual_1q != expected_1q:
            raise AssertionError(f"D1 (1Q Gate) mismatch: expected {expected_1q}, got {actual_1q}")

        if self.config.get('strict_gate_targets', False) and actual_2q != expected_2q:
            raise AssertionError(f"D2 (2Q Gate) mismatch: expected {expected_2q}, got {actual_2q}")

        record = getattr(self.task, 'generation_record', None)
        if record:
            generated = record.get('generated', {})
            if generated.get('one_qubit_gates') != actual_1q:
                raise AssertionError("generation_record 1Q count does not match the circuit")
            if generated.get('two_qubit_gates') != actual_2q:
                raise AssertionError("generation_record 2Q count does not match the circuit")

    def _check_n_ryd_layers(self):
        rydberg_blocks = [s for s in self.state_list if s.get('class') == 'rydberg']

        if len(rydberg_blocks) != self.config['n_ryd_layers']:
            raise AssertionError(f"n_ryd_layers mismatch: expected {self.config['n_ryd_layers']}, got {len(rydberg_blocks)}")

        for idx, block in enumerate(rydberg_blocks):
            used_qubits = set()
            gates = block.get('gates', [])
            for pair in gates:
                q0, q1 = pair[0], pair[1]
                if q0 in used_qubits or q1 in used_qubits:
                    raise AssertionError(f"Rydberg layer {idx} has overlapping qubits: {pair}")
                used_qubits.add(q0)
                used_qubits.add(q1)

    def _check_n_routing_phases_and_mov(self):
        trans_blocks = [s for s in self.state_list if s.get('class') == 'trans']

        if len(trans_blocks) != self.config['n_routing_phases']:
            raise AssertionError(f"n_routing_phases mismatch: expected {self.config['n_routing_phases']}, got {len(trans_blocks)}")

        total_mov_layers = 0
        for block in trans_blocks:
            layers = block.get('movement_layers')
            if layers is None:
                layers = block.get('movements')

            if layers:
                total_mov_layers += len(layers)

        if total_mov_layers != self.config['n_mov_layers']:
            raise AssertionError(
                f"n_mov_layers mismatch: expected {self.config['n_mov_layers']}, got {total_mov_layers}"
            )
