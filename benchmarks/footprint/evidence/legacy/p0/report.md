# Extism core memory benchmark report

Protocol: `op-go-extism-core-memory/v1`. All 96 planned fresh processes completed; 26 warmups are retained but excluded from summaries.

## Primary peak RSS

| Scenario | A median MiB (MAD, range) | B median MiB (MAD, range) | median paired B-A MiB | median paired B/A | A identities | B identities |
|---|---:|---:|---:|---:|---|---|
| COLD_1 | 158.844 (0.250, 158.234-159.094) | 159.391 (0.125, 159.266-159.719) | +0.672 | 1.0042 | [1] | [1] |
| COLD_PAR_2 | 289.453 (2.438, 287.016-300.984) | 158.984 (0.172, 158.812-159.469) | -129.984 | 0.5509 | [2] | [1] |
| COLD_PAR_3 | 418.438 (2.875, 415.562-430.141) | 158.969 (0.219, 158.375-159.188) | -259.250 | 0.3798 | [3] | [1] |
| COLD_PAR_4 | 547.344 (1.984, 545.359-550.922) | 159.000 (0.281, 158.594-159.312) | -388.578 | 0.2898 | [4] | [1] |

## Checkpoints and controls

| Scenario | Variant | median ready/raw/GC MiB | median peak MiB | median unique |
|---|---|---:|---:|---:|
| IDLE | A | 41.0/41.2/41.6 | 41.6 | 0 |
| IDLE | B | 41.0/41.2/41.7 | 41.7 | 0 |
| PUBLIC_OPTION_ERROR | A | 40.9/41.2/41.7 | 41.7 | 0 |
| PUBLIC_OPTION_ERROR | B | 40.9/41.1/41.5 | 41.5 | 0 |
| SEQ_WARM_4 | A | 40.9/158.6/158.7 | 158.7 | 1 |
| SEQ_WARM_4 | B | 40.9/159.0/159.0 | 159.0 | 1 |
| WARM_PAR_2 | A | 158.7/158.9/159.0 | 159.0 | 1 |
| WARM_PAR_2 | B | 158.7/158.9/159.0 | 159.0 | 1 |
| WARM_PAR_3 | A | 158.6/158.8/159.0 | 159.0 | 1 |
| WARM_PAR_3 | B | 159.1/159.3/159.3 | 159.4 | 1 |
| WARM_PAR_4 | A | 158.9/159.0/159.1 | 159.1 | 1 |
| WARM_PAR_4 | B | 159.0/159.2/159.2 | 159.2 | 1 |
| RELEASE_ONLY_4 | A | 158.9/159.0/159.1 | 159.1 | 1 |
| RELEASE_ONLY_4 | B | 159.4/159.6/159.7 | 159.7 | 1 |
| GEN_KEEP_4 | A | 41.0/322.0/322.0 | 322.0 | 4 |
| GEN_KEEP_4 | B | 41.0/320.7/320.7 | 320.7 | 4 |
| GEN_DROP_4 | A | 41.1/215.6/215.6 | 215.6 | 4 |
| GEN_DROP_4 | B | 41.1/202.1/202.1 | 202.1 | 4 |

## Predeclared checks

- N=2: B identities=[1]; B median peak=159.0 MiB; allowed bound=183.3 MiB; PASS. A duplicate median peak/control=289.5/159.0 MiB; raw/control=289.4/158.9 MiB; material effect=yes.
- N=3: B identities=[1]; B median peak=159.0 MiB; allowed bound=183.3 MiB; PASS. A duplicate median peak/control=418.4/159.0 MiB; raw/control=418.3/158.8 MiB; material effect=yes.
- N=4: B identities=[1]; B median peak=159.0 MiB; allowed bound=183.3 MiB; PASS. A duplicate median peak/control=547.3/159.1 MiB; raw/control=547.2/159.0 MiB; material effect=yes.

Single-cold B/A median peak ratio: **1.003** (inside [0.85, 1.15]).
Validity: **PASS**. Fixed synchronization/memory check: **PASS**. Final causal verdict: **CAUSAL PASS**.

A shows concurrent cold duplicate identities while B always returns one, and the duplicate-core A processes materially exceed the matching one-core-plus-warm-scheduling controls. Warm parallel controls do not show comparable excess. This supports a concurrent-cold-start causal memory effect in the scoped host/process condition. It does not establish an exact per-core cost or a production leak.

RSS includes Go heap/stacks, the embedded module, Wazero code/mappings, WASM linear memory, allocator retention, shared pages, and other process memory. No subtraction of Go `Sys` or heap from RSS is used. Post-GC RSS is only a reclamation probe.

## Additional comparisons

- B cold-parallel/COLD_1 peak ratios: N=2: 0.997, N=3: 0.997, N=4: 0.998.
- A normalized median peak excess versus matching control: 1 identity/caller: 0.0%, 2 identity/caller: 82.1%, 3 identity/caller: 163.2%, 4 identity/caller: 243.9%. This sequence is nondecreasing, corroborating dose response.
- `paired-summary.csv` reports medians, MADs, and ranges across repetition-matched B-minus-A and B/A values. `comparison-summary.csv` separately labels comparisons of cell medians. `identity-memory-summary.csv` aggregates A peak and raw RSS by caller and observed identity count.
- All 188 measured operation attempts and all 260 attempts including warmups were contract-successes; there were no unexpected errors or panics.
- Sampled RSS never exceeded authoritative peak RSS, and the largest peak-minus-sampled gap was 98304 bytes (0.094 MiB).

### Current RSS and Go heap dose response

| Cell | Unique identities/run | ready/raw/post-GC RSS MiB | raw/post-GC HeapAlloc MiB |
|---|---:|---:|---:|
| A `COLD_1` | [1] | 40.938/158.734/158.844 | 106.136/15.993 |
| A `COLD_PAR_2` | [2] | 40.875/289.359/289.453 | 201.722/31.621 |
| A `COLD_PAR_3` | [3] | 40.797/418.281/418.438 | 308.765/47.266 |
| A `COLD_PAR_4` | [4] | 40.984/547.203/547.344 | 411.384/62.942 |
| B `COLD_1` | [1] | 40.891/159.328/159.391 | 106.410/16.019 |
| B `COLD_PAR_2` | [1] | 41.031/158.906/158.984 | 105.973/15.994 |
| B `COLD_PAR_3` | [1] | 40.984/158.906/158.969 | 106.115/15.994 |
| B `COLD_PAR_4` | [1] | 41.031/158.891/158.969 | 106.207/15.996 |

- Host shape requirements held: Darwin/arm64, 32 GiB, 10 logical CPUs, 16 KiB pages, and AC power. `memory_pressure -Q` reported 77% free throughout and swap decreased from 2463.06 MiB to 2359.06 MiB, but the original controller did not capture a machine-readable pressure level; that safety-guard limitation is recorded in `review-disposition.md`. The hostname text changed between `uname` snapshots, while kernel/build and host shape were unchanged; no result was pooled from another host.
- The outer shell/tool timed out after the completed campaign had written all raw files. This was an orchestration failure, not a sample failure; recovery performed post-processing only and did not rebuild or rerun.
- Harness module bootstrap added already-locked indirect requirements using offline `go list -mod=mod`; no dependency version or `go.sum` changed and `go mod tidy` was not run. No checkout-local harness copy was necessary because the canonical module path is within the SDK internal boundary.

## Integrity and residual confounders

- `/usr/bin/time -l` peak is authoritative; 50-ms `ps` sampling may miss brief maxima.
- Residual confounders: ASLR, GC timing, macOS compression/reclamation, thermal and P/E-core scheduling, warm-but-changing file-cache state, shared mappings, and sampler miss risk.
- Scope is Darwin/arm64, GOMAXPROCS=10, fresh processes, warm OS cache, and N<=4. No credential, client initialization, network operation, business API, shared-library operation, race instrumentation, or dependency update was used.
- `GEN_KEEP_4`/`GEN_DROP_4`/`RELEASE_ONLY_4` are interpretation controls, not PR pass criteria. `ReleaseCore` clears a global; retained generation growth must not be labeled a leak.

## Published evidence

`order.json`, `build-manifest.json`, host snapshots/checks, `runs/*/{stdout.jsonl,stderr.time,ps.jsonl,controller.json}`, `raw.csv`, `summary.csv`, `comparison-summary.csv`, `paired.csv`, `paired-summary.csv`, `identity-memory.csv`, `identity-memory-summary.csv`, and `failure-table.csv`.
