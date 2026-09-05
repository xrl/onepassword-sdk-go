# SDK footprint experiment: confirmed Linux/ARM64 results

**Credential-free core/parser measurements, not authenticated SDK or ESO acceptance. No shipping WASM, ordinary SDK behavior, production dependency, or cluster limit changed.**

## Decision

- **Prioritize a trusted precompiled cache:** original core median cgroup peak 153.44 → 61.27 MiB (**60.1% lower**).
- **Cache + Oz is a secondary experiment:** 53.30 MiB (**65.3% lower** than original cold). This is not a safe cold-start configuration.
- **Do not ship `-Oz` as an uncached memory fix.** Despite halving function bodies, its uncached peak is about 64% higher. Removing descriptor exports alone is negligible; prune+DCE saves only about 2.5% of peak, below the 20% slim-core memory gate.
- **Do not force a small `GOMEMLIMIT` into the SDK/controller as the main fix.** This screening saved only about 10–11% of cold peak with substantially more GC and 2–3× startup cost.

## Linux confirmation

Ten measured fresh processes plus two warmups per cell, interleaved (seed 285). Each performs one malformed `init_client`, three malformed `invoke` calls, then settles for 30 seconds without forced GC. Every acquisition wave has one loader attempt and one core identity.

| Configuration | Cgroup peak median / max MiB | Core-ready cgroup peak MiB | 30s process RSS MiB | Core-ready seconds |
|---|---:|---:|---:|---:|
| Original / no cache | 153.44 / 155.28 | 145.62 | 162.55 | 4.408 |
| Prune + DCE / no cache | 149.66 / 151.39 | 143.34 | 158.40 | 4.350 |
| Prune + Oz / no cache | 252.16 / 255.33 | 248.45 | 259.76 | 6.137 |
| Original / warm RO | 61.27 / 61.91 | 52.17 | 70.06 | 0.126 |
| Original + Oz / warm RO | 53.68 / 55.08 | 46.62 | 61.12 | 0.105 |
| Prune + Oz / warm RO | 53.30 / 55.05 | 46.86 | 60.95 | 0.105 |

Ranges, maxima, CPU time, allocation/GC statistics, malformed-call latency, page counts and individual failures are retained in [summary](linux-confirmation/summary.json), [trials](linux-confirmation/trials.json), [manifest/order](linux-confirmation/manifest.json) and the [byte-exact raw bundle](linux-confirmation/raw.tar.gz). With n=10, a nearest-rank p95 is the maximum; these data do not establish rare-tail behavior.

SDK main memory is 62 pages at core-ready and 63 after these parser calls; Extism kernel memory is 16 pages. These are separate 64-KiB logical WASM pages, both backed by Go heap, **not additive RSS categories**. The native cache is about 25.0 MiB for the original core plus kernel, and 22.4 MiB for either Oz variant.

### Artifact attribution

Original+Oz has 4,555 bodies and prune+Oz 4,554; their native caches differ by only 104 bytes. Their warm-cache results are close. Almost all body-count reduction comes from general Binaryen optimization/merging, not descriptor removal. The immutable shipping artifact is still 9,509,477 bytes with its original SHA-256. See [artifact ABI/size report](artifacts/report.md). Smaller input/function count did not predict a smaller compiler working set; allocation profiles are needed before attributing the regression to a specific Wazero compiler hotspot.

## Cache population and failure cases

Three measured processes plus one warmup per screening cell: original empty-cache median peak was about 195 MiB, versus about 154 MiB with caching disabled. Oz empty-cache peaks were about 291–292 MiB. A cache miss is not a low-memory mode. See [cache screening](linux-screen-caches/summary.json).

Read-only mounts were independently checked using `EROFS`, not merely file permissions. A successful pinned-version load with unchanged populated entries establishes a known hit; this does **not** implement a supported strict/require-hit API. Three negative cases, each in its own fresh no-swap cgroup, passed their expected-error contract:

| Negative case (n=1 each) | Cgroup peak MiB | Result |
|---|---:|---|
| missing-core-entry | 164.52 | Startup error, one loader attempt, no published core |
| different-core | 168.50 | Startup error, one loader attempt, no published core |
| truncated-core-entry | 35.00 | Startup error, one loader attempt, no published core |

The missing/different-core cases compiled and reached the cache write error; a read-only mount alone cannot protect a small container from the compilation peak. Truncation failed during cache reading. Files were selected by size and removed/truncated only in task-owned caches; no private Wazero format was parsed. [Results](linux-cache-negative/results.json), [raw errors and cgroups](linux-cache-negative/raw.tar.gz).

## Go memory-limit screening

Three measured processes plus one warmup per cell; 1-second settling. Same original-artifact probe binary, GOMAXPROCS=2, GOGC=100, cgroup limit 512 MiB and swap disabled. These cells are not pooled with the 30-second confirmation.

| Original, uncached GOMEMLIMIT | Cgroup peak MiB | Core-ready seconds | GC cycles by settled |
|---|---:|---:|---:|
| off | 153.25 | 4.343 | 8 |
| 32 MiB | 138.56 | 12.837 | 533 |
| 48 MiB | 138.55 | 12.837 | 519 |
| 64 MiB | 138.59 | 13.101 | 519 |
| 96 MiB | 136.58 | 8.841 | 263 |

Go cannot collect the live compiler working set, and GOMEMLIMIT is soft. A small limit greatly increased GC without eliminating the cold peak. Warm-cache results changed little with these settings. A full controller has a different process-wide live heap: these SDK-only values are not recommended ESO settings. [All tuning cells](linux-screen-tuning/summary.json).

## Darwin confirmation (developer signal)

Ten measured processes plus two warmups per cell, same malformed operations and 30-second settling. Warm read-write cache outcomes remain unknown through the public Wazero API, unlike the independently verified Linux read-only hits.

| Configuration | Process peak median / max MiB | Core-ready seconds |
|---|---:|---:|
| original:disabled | 167.05 / 167.59 | 1.638 |
| prune-oz:disabled | 268.71 / 268.94 | 1.777 |
| original:warm-rw | 74.45 / 74.67 | 0.072 |
| prune-oz:warm-rw | 65.13 / 65.22 | 0.058 |

[Darwin summary](darwin-confirmation/summary.json), [raw bundle](darwin-confirmation/raw.tar.gz). Do not use Darwin RSS for Kubernetes sizing.

## Scope, controls, and remaining gates

- Go 1.27.1, Extism 1.7.1, Wazero 1.11.0, wasm-tools 1.236.1 and Binaryen 132. Each binary genuinely re-embeds its reported artifact via the documented build overlay; manifests record source commit, dirty state, all input/dependency/overlay digests and binary hashes. Shipping files and module cache are not modified.
- Linux: target Raspberry Pi-class ARM64, kernel 6.12.47+rpt-rpi-2712, 16-KiB OS pages, fresh systemd cgroup for **every** measured, warmup and population process; 512-MiB memory max, no swap, two-core CPU quota, GOMAXPROCS=2, denied network and core dumps. A small Python supervisor is included in cgroup peak, identically across cells.
- Cgroup memory and process RSS are different accounting views. File-backed pages may already be charged elsewhere; the anonymous executable segment is copied eagerly in full. Population and hashing first-touch cache files outside the measured application cgroup. These are **prewarmed-file-cache** measurements, not cold-node image/page-cache acceptance. No global cache purge or swap change was made.
- Only checkpoints are sampled; kernel cgroup high-water is authoritative. No primary heap profiles or forced GC. Thirty-second idle/parser RSS is not proof of authenticated active-core floor or indefinite steady state; normal application GC and Linux pressure can reclaim compiler working allocations.
- Valid authentication, representative secret reads/payloads, cancellation/rotation, full private compatibility suites, Linux AMD64 measurements, cold-node cache accounting, and the exact ESO image’s 20-start/soak gate remain **not run / blocked**. The controller keeps its existing 512-MiB limit.
- Next implementation: pursue supported Wazero require-hit/outcome hooks and runtime-scoped cache ownership (P1 dependency), then explicitly wire the ESO provider to that runtime. Validate the original artifact first with a dedicated private fixture; test Oz separately only if the additional ~8 MiB justifies its worse miss peak and compatibility risk. Do not silently configure the default global client or ship an unverified artifact.

## Reproduction and integrity

Use [the lab README](../README.md) and the exact option/order manifests. Run `python3 benchmarks/footprint/report.py` to revalidate archive digests, raw-to-summary peak/RSS arithmetic, protocol, source artifact identity, read-only hits and fresh PID/cgroup identities, then regenerate this report. `bundle.py` stores byte-exact text evidence with deterministic gzip metadata; no native cache or executable blobs are checked in.

| Dataset | Measured | Warmups | Population | Total processes |
|---|---:|---:|---:|---:|
| linux-smoke | 2 | 0 | 1 | 3 |
| linux-screen-artifacts | 18 | 6 | 0 | 24 |
| linux-screen-caches | 18 | 6 | 12 | 36 |
| linux-screen-tuning | 42 | 14 | 28 | 84 |
| linux-confirmation | 60 | 12 | 36 | 108 |
| linux-cache-negative | 3 | 0 | 3 | 6 |
| darwin-screen | 18 | 6 | 0 | 24 |
| darwin-confirmation | 40 | 8 | 24 | 72 |

All completed primary/screening/warmup trials were protocol-valid; the three negative cache processes exited nonzero as expected. Historical exploratory and initial tooling-smoke data are archived separately with their limitations and are not pooled into these campaigns.
