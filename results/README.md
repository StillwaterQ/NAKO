# Evaluation results

## Experiments

| ID | Variable or comparison |
| --- | --- |
| A | Logical depth |
| B | Qubit count |
| C | Two-qubit interaction load |
| D | Primitive composition with separate R, T, and M sweeps |
| E | Joint resource and gate-load sweeps |
| F | Four small primitive constructions |
| G | Default and reference initial mappings on identical circuits |
| H | Generator scalability |
| I | Hardware capacity on identical circuits |

Enola and OLSQ-DPQA compile the dependency-preserving CZ program with the full
qubit register. Runs use a 10,000-second limit and eight concurrent jobs per
compiler. Enola completes 324 runs; OLSQ-DPQA completes 312 and times out on 12.
Compilation was measured on Linux with Python 3.10.19. Generation was measured
on Windows with Python 3.12.14.

## Files

| File | Contents |
| --- | --- |
| `measurements.csv` | 648 compilation outcomes and resource measurements |
| `inputs.jsonl.gz` | 319 input configurations, QASM circuits, achieved counts, and reference schedules |
| `enola.jsonl.gz` | 324 compiled instruction sequences |
| `olsq_dpqa.jsonl.gz` | 312 compiled physical-state sequences |
| `generation.csv` | 12 generation-time and peak-allocation measurements |
| `enola_diagnosis.json` | Layout and batching controls, a placement-score comparison, and matching-slice results |
| `olsq_dpqa_diagnosis.json` | Four alternative continuations, preparation-state controls, and timeout measurements |

`case_id` joins inputs, measurements, and diagnosis records. Compilation outputs
also carry `initial_mapping` (`default` or `reference`); each compiler has its own
output file. Experiment G includes both mapping modes for each input. Experiment
I assigns a separate case ID to each circuit/grid combination, with `sample`
identifying the matched circuit across grids.

```python
import gzip
import json

with gzip.open("results/enola.jsonl.gz", "rt", encoding="utf-8") as stream:
    outputs = [json.loads(line) for line in stream]
```

## Measurements

R counts nonempty Rydberg stages. T counts intervals between successive Rydberg
stages that contain physical movement. M counts nonzero movement layers:
Enola exposes expanded move instructions, including loading and unloading
transport; OLSQ-DPQA exposes coordinate-changing transitions between states.
`reference_R`, `reference_T`, and `reference_M` are the corresponding NAKO targets.
Timeout rows retain their status and have empty resource fields.

Gate densities are `d1 = one_qubit_gates / (qubits * depth)` and
`d2 = 2 * cz_gates / (qubits * depth)`. Requested and achieved densities are stored
separately. Grids use `[rows, columns]`; compiler architectures use
`[n_x, n_y, n_c, n_r]`. Compilation and generation times are in seconds.
Generation timing includes construction, serialization, and QASM reload with
statistics; peak allocation is measured in Python-traced bytes.

## Diagnostic data

Enola's `layout_controls` records the initial mapping, cross-stage boundary
policy, batch selector, resource counts, placement score, and estimated fidelity
for the five G inputs. The `return` policy restores initial positions after each
stage; `dynamic` retains the compiler's evolving layouts. The placement example
includes both executable instruction sequences. Matching slices report 40
layouts each for QV and QFT, with the nine improved QV cases given individually.
Durations are in microseconds and fidelity follows Enola's execution model.

OLSQ-DPQA's `continuations` contains each fixed checkpoint, remaining gates, and
the complete alternative state sequence, together with original and alternative
resource counts. `preparation_controls` records feasibility outcomes and
satisfying states across hardware widths and search horizons. `retry_sequences`
contains the tested horizon sequences. `timeouts` links the 12 failed capacity
runs to their last progress and repeated local-query failures.
