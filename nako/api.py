"""Circuit generation and initial-mapping interfaces."""

from collections import defaultdict
from dataclasses import dataclass
import json
import math
from numbers import Integral, Real
from pathlib import Path
import random

from qiskit import QuantumCircuit, qasm2

from .generator import BenchmarkGenerator


@dataclass
class Benchmark:
    """A logical circuit, its reference schedule, and achieved parameters."""

    circuit: QuantumCircuit
    schedule: list[dict]
    record: dict
    config: dict

    @property
    def resources(self):
        return {key: self.record["generated"][key] for key in ("R", "T", "M")}

    def save(self, directory):
        """Write QASM, configuration, reference operations, and achieved counts."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        qasm2.dump(self.circuit, str(directory / "circuit.qasm"))
        for name, value in (
            ("config.json", self.config),
            ("reference.json", self.schedule),
            ("generation_record.json", self.record),
        ):
            (directory / name).write_text(
                json.dumps(value, indent=2) + "\n", encoding="utf-8"
            )
        return directory

    def initial_mapping(self, compiler, architecture):
        """Export a mapping for architecture [n_x, n_y, n_c, n_r]."""
        if len(architecture) != 4:
            raise ValueError("Architecture requires [n_x, n_y, n_c, n_r].")
        architecture = tuple(
            _integer(v, "architecture dimension", 1) for v in architecture
        )
        locations = self.schedule[0]["location"]
        if compiler == "enola":
            return _enola_mapping(locations, architecture)
        if compiler == "olsq-dpqa":
            return _dpqa_mapping(locations, architecture)
        raise ValueError("Compiler must be 'enola' or 'olsq-dpqa'.")


def generate(
    *, qubits, depth, rtm, densities=(0.4, 0.4), grid=(16, 16), seed=0,
    count=1, variant=0,
):
    """Generate seeded benchmarks with targets (R, T, M) on a two-slot site grid."""
    qubits = _integer(qubits, "qubits", 8)
    depth = _integer(depth, "depth", 1)
    count = _integer(count, "count", 1)
    seed = _integer(seed, "seed", 0)
    variant = _integer(variant, "variant", 0)
    if len(rtm) != 3 or len(grid) != 2 or len(densities) != 2:
        raise ValueError(
            "Expected three resource counts, two grid dimensions, and two densities."
        )
    R, T, M = (
        _integer(v, name, lower)
        for v, name, lower in zip(rtm, ("R", "T", "M"), (1, 0, 0))
    )
    rows, cols = (
        _integer(v, name, lower)
        for v, name, lower in zip(grid, ("rows", "columns"), (1, 8))
    )
    if not (T <= M and 2 * M <= 3 * T and R >= T + 1):
        raise ValueError("Targets must satisfy T <= M <= 3T/2 and R >= T + 1.")
    if depth < R:
        raise ValueError("Depth must be at least R.")
    if qubits > 2 * rows * cols - 8:
        raise ValueError("Qubit count exceeds the grid capacity 2*rows*columns - 8.")
    if any(
        isinstance(v, bool) or not isinstance(v, Real)
        or not math.isfinite(v) or not 0 <= v <= 1
        for v in densities
    ):
        raise ValueError("Densities must be finite values in [0, 1].")
    d1, d2 = map(float, densities)
    configuration = {
        "qubits": qubits, "depth": depth, "rtm": [R, T, M],
        "densities": [d1, d2], "grid": [rows, cols], "seed": seed,
    }
    task_config = {
        "qubit": qubits, "depth": depth,
        "n_ryd_layers": R, "n_routing_phases": T, "n_mov_layers": M,
        "d1": d1, "d2": d2,
        "hardware": {"type": "common", "grid_size": [rows, cols]},
    }
    generator = BenchmarkGenerator()
    generator.set_paras(config=task_config)
    random_state = random.getstate()
    try:
        random.seed(seed)
        results, _ = generator.generate(variant + count)
    finally:
        random.setstate(random_state)
    if len(results) != variant + count:
        raise RuntimeError("Generation did not produce the requested number of circuits.")
    return [
        Benchmark(
            circuit=result["task"].circuit.to_qiskit(),
            schedule=result["state_list"],
            record=result["generation_record"],
            config={**configuration, "variant": result["id"]},
        )
        for result in results[variant:]
    ]


def _integer(value, name, minimum):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}.")
    return int(value)


def _enola_mapping(locations, architecture):
    n_x, n_y, _, _ = architecture
    if n_x % 2:
        raise ValueError("Enola mapping requires an even n_x.")
    sites = defaultdict(dict)
    for qubit, (row, col, slot) in locations.items():
        sites[row, col][slot] = int(qubit)
    if 2 * len(sites) > n_x * n_y:
        raise ValueError("Enola architecture has insufficient coordinate pairs.")
    mapping = [None] * len(locations)
    for index, site in enumerate(sorted(sites)):
        y, x = divmod(2 * index, n_x)
        for slot, qubit in sites[site].items():
            mapping[qubit] = [x + slot, y]
    return mapping


def _dpqa_mapping(locations, architecture):
    n_x, n_y, n_c, n_r = architecture
    mapping = [None] * len(locations)
    for qubit, (row, col, slot) in locations.items():
        if col >= min(n_x, n_c) or row >= min(n_y, n_r):
            raise ValueError("OLSQ-DPQA architecture does not cover the reference locations.")
        mapping[int(qubit)] = {
            "id": int(qubit), "x": col, "y": row, "a": slot, "c": col, "r": row,
        }
    return mapping
