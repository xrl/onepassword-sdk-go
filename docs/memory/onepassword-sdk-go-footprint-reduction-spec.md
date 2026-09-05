# P2 proposal: reduce the active `onepassword-sdk-go` core footprint

- **Status:** Draft / experiment-first; Linux/ARM64 credential-free confirmation complete
- **Target:** `github.com/1Password/onepassword-sdk-go`, service-account path
- **Motivating stack:** `onepassword-sdk-go` v0.4.1, Extism Go SDK v1.7.1, Wazero v1.11.0
- **Primary deployment:** External Secrets Operator on Linux/ARM64
- **Related correctness change:** <https://github.com/1Password/onepassword-sdk-go/pull/285>
- **Related lifecycle proposal:** [`onepassword-go-sdk-memory-spec.md`](./onepassword-go-sdk-memory-spec.md)

> Canonical in-Git specification. The current delivery is a credential-free, benchmark-only lab, not a cache API, lifecycle redesign, shipping artifact change, or release-acceptance result. See [lab source, protocol and evidence](../../benchmarks/footprint/README.md). Historic exploratory source was not preserved; [archived raw evidence and caveat](../../benchmarks/footprint/evidence/legacy/README.md) are not regenerated results. Authentication, private integration and ESO acceptance are blocked without credentials.
>
> Accounting correction (pinned Wazero 1.11.0 / Extism 1.7.1): default WASM linear memories are Go `[]byte`, subsets of Go heap and `GOMEMLIMIT` accounting, not additive native buckets. SDK main memory and Extism kernel memory are separate; `Plugin.Memory()` returns the kernel. `Plugin.Module()` exists, but its public wrapper exposes only exported functions. The lab uses a digest-pinned benchmark-only accessor overlay. `WithMemoryLimitPages` caps each memory separately, not their sum. Wazero eagerly copies the entire native code segment into anonymous executable mappings and CRC-checks it on a cache load; there is no supported lazy-native-page explanation for the warm-cache saving. Authentication still matters for data, sessions, operation growth and compatibility.

## Executive decision

The confirmed credential-free Linux/ARM64 measurements change the priority: **move compilation out of the constrained application; do not equate a smaller WASM file with a smaller compiler working set.** The [reproducible campaign report](../../benchmarks/footprint/evidence/campaign-report.md) records source, raw evidence, controls and limitations.

1. **Trusted prewarmed cache first.** Ten measured fresh processes plus two warmups per condition reduced the original artifact's median cgroup peak from **153.44 to 61.27 MiB (−60.1%)**, through malformed initialization/invocation and 30-second settling. Supported require-hit semantics, runtime ownership and authenticated acceptance remain prerequisites for production low-memory use.
2. **General size optimization is a conditional cache companion, not an uncached fix.** Prune+`-Oz` with a warm cache reached **53.30 MiB**, but uncached peak rose to **252.16 MiB (+64%)**. Original+`-Oz` produced nearly the same body count and warm-cache result without pruning. Any extra ~8 MiB benefit must justify its miss peak and compatibility risk.
3. **Descriptor pruning is not the large memory lever originally hypothesized.** Prune-only retained all 9,537 bodies. Prune+DCE left 8,485 but reduced confirmed uncached peak by only **2.5%**, below the 20% slim-core memory gate. It may still be ABI/build hygiene; source-level capability reduction remains untested.
4. **Small Go memory limits are not the main fix.** Uncached screening saved about 10–11% of peak while increasing startup cost 2–3× and GC cycles from 8 to hundreds. Never apply these SDK-only process budgets directly to a full controller.

Empty-cache screening peaked around **195 MiB** for the original artifact and **291–292 MiB** for Oz variants. Missing/stale entries on a verified read-only mount still compiled before a write error. Keep cold-start headroom until a supported strict-cache implementation exists.

These are core/parser experiments, not authenticated SDK or ESO acceptance. The next experiment is a dedicated private fixture with the **original artifact and trusted prewarmed cache**, then the exact controller image. Shipping WASM, SDK defaults and the live 512 MiB controller limit are unchanged.

## Relationship to P0 and P1

This document is deliberately limited to **P2: making one active core smaller**.

It does not replace:

- **P0 synchronization:** PR #285 prevents concurrent cold callers from compiling and retaining multiple cores.
- **P1 ownership:** deterministic `Client.Close`, `Plugin.Close`, core leases, and runtime shutdown prevent resources from accumulating across clients or generations.

P0 is a prerequisite for meaningful footprint measurements: each successful P2 load must prove exactly one loader attempt and one published core identity. Failure scenarios must report attempts and show that no partial core was published. P1 remains a separate API/lifecycle change. No P2 patch should quietly absorb P1 or weaken P0's retry-after-load-failure behavior.

## Problem statement

With duplicate initialization removed, one credential-free call to `internal.GetExtismCore` still raises a small Go process from roughly 41 MiB to roughly 159 MiB on the current Darwin/ARM64 harness. A full controller adds its own binary, caches, informers, TLS, and reconciliation state on top of that floor.

That leaves three distinct memory questions:

1. **Cold compilation peak:** can the process survive the first core load?
2. **Active-core floor:** how much remains while the plugin is usable?
3. **Operation growth:** how much additional memory do authentication, client state, secret payloads, and repeated calls consume?

All three matter, but they require different remedies. A page limit may bound operation growth without changing compilation peak. A compilation cache may remove compiler allocations without shrinking a fully exercised module. A smaller core can improve both.

## Current evidence

### Confirmed footprint campaign

The [Linux/ARM64 and Darwin/ARM64 report](../../benchmarks/footprint/evidence/campaign-report.md) and [integrity audit](../../benchmarks/footprint/evidence/campaign-audit.json) cover 357 fresh processes including screening, confirmation, warmups, cache population and expected negative cases. Linux confirmation uses six selected cells, each with ten measured processes and two warmups; Darwin confirms four cells. No unexpected protocol failure occurred. Authenticated operations, Linux AMD64, cold-node page-cache charging and full ESO acceptance remain unmeasured.

Every Linux process used its own 512 MiB/no-swap cgroup, two-core CPU quota and `GOMAXPROCS=2`. Cgroup peak includes the small supervisor; process RSS and cgroup page-cache accounting are not interchangeable. Warm artifacts were populated and hashed before the measured process. Do not extrapolate these prewarmed-file-cache results to a cold node.

The historical data below remain separate and retain their original limitations; they are not pooled with the confirmed campaign.

### Controlled P0 benchmark

The reviewed 96-process comparison used 70 measured samples and 26 warmups. For one cold caller, the P0 synchronization change was intentionally neutral:

| Variant | Ready RSS | Peak RSS | Core identities |
|---|---:|---:|---:|
| SDK base | 40.9 MiB | 158.8 MiB | 1 |
| P0 fix (`da768af`) | 40.9 MiB | 159.4 MiB | 1 |

For the fixed one-core variant, median memory snapshots were:

| Metric | Before load | Immediately after load | After forced Go GC |
|---|---:|---:|---:|
| Process RSS | 40.9 MiB | 159.3 MiB | 159.4 MiB |
| Go `HeapAlloc` | 27.5 MiB | 106.4 MiB | 16.0 MiB |
| Go `HeapSys` | 31.7 MiB | 115.6 MiB | 115.5 MiB |
| Go `Sys` | 36.9 MiB | 124.1 MiB | 124.1 MiB |

Median `TotalAlloc` immediately after load was 148.6 MiB, and median load duration was 1.68 seconds.

The important shape is that approximately 90 MiB of heap objects become unreachable after GC while the Go heap reservation and observed RSS remain high. This points to eager compilation and compiler working sets as the first target. It does **not** prove that all post-GC RSS is unreclaimable under Linux pressure; RSS, Go heap reservations, executable mappings, and cgroup accounting must be separated there.

The canonical report and raw results are:

- [`onepassword-sdk-go-memory-benchmark/artifacts/report.md`](../../benchmarks/footprint/evidence/legacy/p0/report.md)
- [`onepassword-sdk-go-memory-benchmark/artifacts/raw.csv`](../../benchmarks/footprint/evidence/legacy/p0/raw.csv)

### Embedded core anatomy

The current `internal/wasm/core.wasm` has SHA-256:

```text
23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23
```

Its relevant structure is:

| Property | Current value |
|---|---:|
| File size | 9,509,477 bytes |
| Functions | 9,537 |
| Exports | 1,759 |
| Code section | 5,233,016 bytes |
| Data section | 2,983,333 bytes |
| `name` custom section | 971,489 bytes |
| `__wasm_bindgen_unstable` custom section | 207,230 bytes |
| Initial linear memory | 62 pages / 3.875 MiB |
| Declared maximum memory | none |

Of the 1,759 exports:

| Export class | Count |
|---|---:|
| `__wbindgen_describe_*` | 1,741 |
| SDK ABI (`memory`, `init_client`, `invoke`, `release_client`) | 4 |
| Other `__wbindgen_*` allocator/exception exports | 4 |
| Random hooks | 3 |
| Ring symbol | 1 |
| Externref/data/heap symbols | 6 |

The descriptor exports include broad browser APIs such as animation frames, IndexedDB, window operations, image creation, and many timer variants. They are not part of the Go SDK's Extism call surface. Because exported functions are linker roots and Wazero eagerly compiles the module, this is a high-value build-pipeline lead. The final required export allowlist must still be established by core integration tests rather than inferred solely from names.

### Exploratory cache probe

A standalone Darwin/ARM64 probe passed a Wazero `RuntimeConfig` through Extism's existing `PluginConfig.RuntimeConfig` field. Five fresh processes were measured per condition.

| Condition | Median peak RSS | Difference from no cache |
|---|---:|---:|
| No compilation cache | 156.4 MiB | baseline |
| Empty writable persistent cache | 181.2 MiB | **+15.8%** |
| Prewarmed persistent cache | 64.4 MiB | **-58.8%** |

The cache contained one approximately 25 MiB native-code entry for the SDK core and a roughly 22 KiB entry for the Extism runtime.

A second probe called `init_client` with credential-free invalid input so that compiled guest code executed before measurement:

| Condition | Median peak RSS |
|---|---:|
| No cache, invalid `init_client` call | 164.5 MiB |
| Prewarmed cache, invalid `init_client` call | 74.8 MiB |

The warm result is consistent with avoiding compiler working allocations. Wazero copies and CRC-checks the entire native code segment into anonymous executable memory before use; do not attribute this saving to touching only guest-reached native pages. It must not be extrapolated to authenticated data/session/linear-memory growth or a long-running workload without measurement. The historic probe source was not preserved.

The empty-cache regression is material. Cache population serializes native code and touches cache-backed filesystem pages in addition to compiling. A low-memory mode must never assume that “cache configured” means “cache hit.”

### Exploratory low-leverage probes

Five-process local probes also found:

- `wasm-tools strip --all` reduced the artifact from 9,509,477 to 8,330,390 bytes (**-12.4%**) but median core-load peak only from 155.8 to 154.2 MiB (about **-1.0%**).
- `WithDebugInfoEnabled(false)` did not produce a repeatable peak-RSS reduction. The current artifact has a name section but no listed DWARF sections.
- `debug.FreeOSMemory()` raised median `HeapReleased` from about 3.9 MiB to 93.9 MiB, but did not lower immediate Darwin RSS or cold peak. It remains a useful Linux diagnostic, not an SDK default.
- Wazero's interpreter had already measured worse for this module and is not a presumed low-memory mode.

These probes were intentionally narrow and are not release evidence. They exist to rank the next experiments.

## Goals

1. Reduce the peak memory needed to create one usable service-account core.
2. Reduce the active-core RSS after a representative authenticated operation.
3. Reduce Wazero's compiler input and eliminate runtime-unneeded core features.
4. Preserve SDK behavior, error semantics, supported operations, and the P0 one-core invariant.
5. Preserve retry after initialization failure.
6. Keep the default SDK free of implicit filesystem writes unless maintainers explicitly choose otherwise.
7. Make every cache miss, incompatibility, corruption, and fallback observable and testable.
8. Prevent compilation-cache configuration from becoming a native-code injection path.
9. Produce authoritative Linux/ARM64 cgroup data before changing downstream memory limits.
10. Keep optimizations independently reviewable and independently reversible.

## Non-goals

- Treating P0 duplicate prevention as a single-core footprint improvement.
- Solving P1 client/runtime cleanup in the same patch.
- Claiming that a 20 MiB process is realistic with the current architecture.
- Moving a cold peak into an init container and reporting that as a reduction in total work.
- Enabling a writable disk cache by default in a library release.
- Exposing Wazero or Extism implementation types in the stable public SDK API.
- Pooling buffers containing credentials or secret values.
- Lowering the production controller limit to 256 MiB before end-to-end headroom is demonstrated.

## Definitions

- **Process baseline:** memory after process readiness but before loading the core.
- **Cold miss:** no usable compiled artifact exists; Wazero must compile the module.
- **Warm hit:** the exact module, Wazero version, OS, architecture, and CPU feature set match a trusted compiled artifact.
- **Core-ready:** Extism has compiled and instantiated the plugin, but no SDK client is authenticated.
- **Client-ready:** a valid service-account client has completed `init_client`.
- **Worked state:** the client has completed representative secret/item operations.
- **Settled:** memory sampled at 1, 10, 30, and 120 seconds after work, without a forced application-wide GC in the primary measurement.
- **Peak:** kernel/cgroup high-water memory, not the largest sampled RSS value alone.
- **Strict cache mode (future proposal, not available in this lab or Wazero public API):** a missing, stale, corrupt, or incompatible cache returns a typed startup error and never falls back to compilation in the constrained process.

## Acceptance budgets

All release gates use an interleaved baseline and candidate built with the same Go toolchain and flags. Relative gates are primary; absolute numbers are deployment-specific.

### SDK gates

| Gate | Requirement |
|---|---|
| Default regression | Default no-cache peak and p95 operation latency are no more than 5% worse than baseline. |
| Warm-cache core load | At least 30% lower Linux/ARM64 core-ready peak than no-cache baseline. |
| Warm-cache worked state | At least 25% lower Linux/ARM64 peak and 30-second RSS after valid authentication plus representative reads. |
| Cache miss | Strict mode performs no hidden compilation; read-write mode documents and measures its miss peak. |
| Slim core | At least 20% lower Linux/ARM64 no-cache core-load peak, or it is shipped only as a binary-size optimization rather than called a memory fix. |
| Functional parity | All unit, race, integration, and cross-platform SDK suites pass. |
| Security | No token, account identifier, request, response, or secret payload enters cache files, metrics, profiles, or checked-in artifacts. |

A candidate that reduces median RSS but creates a wider or higher tail does not pass. Use at least 10 measured fresh processes per condition for SDK gates and report median, p95 where meaningful, maximum, range, and every failure.

### External Secrets Operator gate

A 256 MiB controller limit is considered only after the exact production image demonstrates all of the following on Linux/ARM64:

- maximum `memory.peak` no greater than **192 MiB** across at least 20 fresh pod starts and full reconciliations, leaving 25% headroom;
- no OOM, panic, cache fallback, or failed core initialization;
- all six current `ExternalSecret` resources refresh successfully;
- `ClusterSecretStore` validation and `ExternalSecret` reconciliation can overlap without creating a second core;
- secret rotation is observed end to end; and
- steady memory remains bounded over at least one complete refresh interval.

Until then, the temporary 512 MiB controller limit remains the safe operational setting.

## Track A: authoritative memory decomposition

Before shipping an optimization, add a standalone process harness with explicit stage markers:

1. executable ready;
2. core bytes first touched;
3. Wazero runtime created;
4. Extism runtime compiled;
5. SDK core decoded;
6. SDK core compiled;
7. plugin instantiated;
8. `init_client` complete;
9. representative operation complete;
10. client close, when P1 exists;
11. plugin/runtime close, when P1 exists.

The production library should not gain permanent process-wide memory instrumentation. Stage callbacks may be an internal test seam or live only in a benchmark command.

At every applicable stage record:

- cgroup v2 `memory.current`, `memory.peak`, `memory.events`, and `memory.stat`;
- `/proc/<pid>/smaps_rollup` and selected mapping categories;
- RSS, PSS, anonymous RSS, file-backed RSS, and private dirty memory;
- Go `HeapAlloc`, `HeapInuse`, `HeapIdle`, `HeapReleased`, `HeapSys`, `Sys`, `TotalAlloc`, allocation count, and GC pauses;
- separate SDK-main and Extism-kernel logical WASM pages before and after calls (both default buffers are Go-heap subsets), plus their configured per-memory maxima;
- wall time and CPU time; and
- cache outcome: disabled, hit, miss, stale, corrupt, or unknown.

Collect Go heap/allocation profiles only in a separate diagnostic lane, never primary trials. The compact lab currently records checkpoints without profiles; future authenticated profiling requires private security review. Use disjoint mapping categories to account for RSS change: anonymous executable, file-backed, and anonymous non-executable/other, with residuals explicit. Go heap (including both modules’ default linear-memory buffers), stacks and runtime metadata are explanatory subsets, not additional RSS buckets. File-backed process RSS and whole-file cgroup page-cache charges are not interchangeable. Do not add Go heap statistics or WASM pages to those mapping totals. Do not infer live pressure from `HeapSys` alone.

Run diagnostic variants with `runtime.GC`, `debug.FreeOSMemory`, and a realistic `GOMEMLIMIT`, but keep them separate from the production-path measurement. A library must not trigger a whole-process GC or change the host application's memory limit by default.

## Track B: precompiled Wazero artifacts

### B1. Runtime configuration seam

Extism v1.7.1 already accepts `PluginConfig.RuntimeConfig`. Refactor `loadWASM` so an SDK-owned runtime configuration can be injected without exposing Wazero publicly:

```go
func loadWASM(ctx context.Context, options coreRuntimeOptions) (*extism.Plugin, error)
```

The default options must reproduce current behavior. Tests should compare the default runtime path before and after the refactor.

Public cache configuration belongs on the explicitly owned SDK `Runtime` proposed by P1, not on `ClientOption`: cache ownership is process/runtime-scoped, and two clients must not be able to request conflicting global cache policies.

An illustrative API, subject to normal API review, is:

```go
type CompilationCachePolicy uint8

const (
    CompilationCacheDisabled CompilationCachePolicy = iota
    CompilationCacheReadWrite
    CompilationCacheRequireHit
)

type CompilationCacheOptions struct {
    Directory string
    Policy    CompilationCachePolicy
}

func WithCompilationCache(options CompilationCacheOptions) RuntimeOption
```

Do not expose `wazero.RuntimeConfig` or `wazero.CompilationCache` from the stable SDK API.

### B2. Cache policy semantics

**Disabled**

- Current behavior.
- No filesystem access.
- Remains the default initially.

**Read-write**

- Reuses a hit and compiles/populates on a miss.
- Intended for applications with enough cold-start headroom that want cheaper later runtime generations or restarts.
- Must document that a miss can use more peak memory than no cache.
- Must not be marketed as strict low-memory behavior.

**Require-hit**

- Loads only an exact, verified cache hit.
- Missing, stale, corrupt, or incompatible entries return typed errors.
- Never cold-compiles a missing guest module or writes cache entries in the constrained process. Bounded cache-hit entry-preamble/host-glue generation is still measured; require-hit does not mean zero native-code generation.
- Is the preferred policy for a memory-bounded controller.

Wazero v1.11.0 does not expose a public read-only cache or cache-hit result, and its `CompilationCache` interface is not intended for third-party implementations. `RequireHit` must therefore not parse or reproduce Wazero's private cache format in SDK code. A real implementation requires an upstream Wazero read-only/require-hit API or equivalent supported hook.

A warmed read-only Linux mount, successful load with no retry/fallback wrapper, and unchanged cache entry digests can establish a **known hit for this pinned Wazero version**; but it does not implement strict miss behavior: on a missing entry, Wazero compiles first and only then fails when it tries to write the result. Such a prototype must retain cold-compilation headroom and independently prove each hit. A marker file is also insufficient because an entry can become stale or corrupt after the marker is created.

### B3. Cache production

Evaluate two supported delivery mechanisms.

#### Image-baked cache

A build stage compiles the exact embedded core using the exact Extism/Wazero versions and copies the resulting cache into an immutable image layer.

Required metadata:

- SDK version and commit;
- core SHA-256;
- Extism and Wazero versions;
- Go version used by the precompiler;
- GOOS and GOARCH;
- CPU feature assumptions;
- runtime configuration fingerprint; and
- cache-file digests.

Wazero includes module identity, its own version, GOOS, GOARCH, and CPU features in cache selection. A cache generated on a CI ARM64 machine may therefore not hit on a Raspberry Pi. The image pipeline must build for a conservative CPU feature set or prove the hit on the target hardware. A build that silently falls back is a failed low-memory build.

#### Init-container cache

An init container compiles into a disk-backed `emptyDir`; the application container mounts it read-only. A supported require-hit API does not yet exist; the current lab can establish only a pinned-version known hit.

This does not reduce the init container's work. It only moves the cold compiler peak into a separately bounded phase whose memory can be set to 512 MiB while the application remains lower. The init container must use the same SDK core and dependency versions as the application image.

Do not use a memory-backed `emptyDir` without measurement: the approximately 25 MiB cache then directly consumes pod/cgroup memory. Disk-backed page-cache accounting must also be measured on the target kernel.

### B4. Cache lifecycle

A Wazero compilation cache owns an engine whose lifetime is not bound to one `wazero.Runtime`. The SDK runtime must therefore close resources in this order:

1. reject new clients;
2. wait for active operations and leases;
3. close the Extism plugin/Wazero runtime;
4. close the compilation cache; and
5. release SDK references.

Keeping a cache object open after plugin close can retain compiled code and would undermine P1. Closing it before the plugin can invalidate live executable state.

### B5. Cache observability

Expose only non-sensitive state through the future runtime stats/event hook:

- cache policy;
- hit/miss/error outcome;
- load source (`compiled` or `cache`);
- core-load duration; and
- core artifact digest prefix, if approved.

Never report the cache path by default; it may reveal usernames or deployment layout. Never include client configuration in cache identity or cache content.

## Track C: produce a smaller Extism core

The current artifact appears to carry a browser-oriented `wasm-bindgen` surface into an Extism runtime. The core build should create a dedicated Extism/service-account artifact rather than asking a post-processing strip command to infer what is safe.

### C1. Establish the actual ABI

Create a checked-in ABI report containing:

- imports by module/name/signature;
- exports by name/kind/signature;
- initial and maximum memory;
- table size;
- function, code, and data-section counts/sizes; and
- all custom sections.

The expected callable SDK surface is currently:

```text
memory
init_client
invoke
release_client
```

The core owners must confirm whether allocator, random, externref, table, start, or compatibility exports are externally required. Host functions imported *by* the module are separate from exports and must remain intact.

### C2. Remove descriptor roots and run DCE

Produce a variant that:

1. does not export the 1,741 `__wbindgen_describe_*` functions;
2. removes descriptor-only call graphs;
3. excludes browser APIs not reachable from the Extism SDK surface;
4. runs linker and WASM dead-code elimination after export pruning; and
5. validates the final module with `wasm-tools validate`.

Merely deleting export records is not sufficient if all 9,537 function bodies remain and Wazero still compiles them. Report both file size **and function count** after every transformation.

Prefer fixing target-specific features and exports in source/build configuration. A post-link Binaryen/`wasm-opt` step is acceptable only when its exact version and flags are pinned, reproducible, and covered by the full integration suite.

### C3. Future source/build-profile matrix (not current evidence)

No Rust source or original build recipe is available in this lane. The following are untested future owner questions, not explanations of observed reductions. This delivery bounds artifacts to original, stripped, prune-only, prune+DCE, prune+Oz, and original+the identical Oz passes. Benchmark future source changes only with reproducible source, one variable at a time:

- current profile;
- `opt-level = "s"`;
- `opt-level = "z"`;
- thin versus fat LTO;
- `codegen-units = 1`;
- `panic = "abort"`, if compatible with SDK error guarantees;
- `default-features = false` with an explicit Extism feature set; and
- pinned DCE/size passes.

Do not assume the smallest file has the smallest compiler peak. For every variant record file bytes, function count, code bytes, data bytes, compilation peak, cache size, startup time, operation latency, and steady memory.

### C4. Feature partitioning

If export pruning is insufficient, evaluate separate artifacts by supported capability, for example:

- secrets-reference resolution only;
- item read operations;
- full item CRUD; and
- environments or other higher-level APIs.

This is a larger compatibility decision. It must not cause callers to discover at runtime that a normal SDK operation is absent. Capability-specific artifacts would need explicit construction-time selection, typed unsupported-operation errors, independent integration suites, and clear versioning.

A dedicated External Secrets artifact may be useful experimentally, but the upstream SDK should prefer capability-oriented profiles over a consumer-branded fork.

## Track D: reduce Wazero compiler cost

Use the `alloc_space` profile to identify exact Wazero and Wasm-decoder hotspots before patching. Evaluate:

1. the current Wazero release;
2. newer supported Wazero and Extism releases independently;
3. a prewarmed file cache;
4. empty-cache serialization;
5. compilation with the slim core; and
6. compiler-level changes only when profiles identify a dominant allocation.

Likely upstream topics include:

- streaming cache serialization instead of constructing a full native-code buffer;
- releasing compiler IR and function metadata sooner;
- avoiding whole-module duplicate buffers;
- read-only/require-hit cache support;
- explicit cache outcome instrumentation; and
- lazy function compilation, if Wazero maintainers consider it viable.

Do not add broad pools as a reflex. Pools can preserve high-water memory and keep sensitive buffers alive. Any Wazero patch should be contributed upstream rather than maintained as an indefinite SDK fork.

Dependency upgrades must be isolated from core-artifact changes so their memory effect and compatibility risk are attributable.

## Track E: bound operation-time growth

Compilation dominates the observed cold floor, but authenticated use can grow linear memory and create copies across Go, JSON, Extism, and Rust.

### E1. WASM memory bound

The SDK module starts at 62 pages with no declared maximum; the separately instantiated Extism kernel starts at 16 pages. `Plugin.Memory()` exposes only the kernel. Measure both separately, using the benchmark-only main-module accessor (or a supported upstream equivalent), and report their sum only as logical bytes, not additional RSS. Wazero's default permits up to 65,536 pages **per memory**; `WithMemoryLimitPages` is not a combined SDK+kernel budget. Determine each memory's maximum page count reached by:

- client authentication;
- one and many small secret reads;
- representative item operations;
- 1 KiB, 1 MiB, 10 MiB, and near-limit payloads;
- errors and canceled requests; and
- repeated calls over a complete refresh interval.

Choose a bound only after these tests. A breach must become a typed recoverable SDK error, not a panic or process termination. The bound is a safety rail for growth; it is not presented as the main cold-start fix.

Keep `WithMemoryCapacityFromMax(false)`: it is already Wazero's default. Eagerly allocating an unset maximum could reserve 4 GiB.

### E2. FFI copy audit

Account for ownership and peak overlap across:

1. Go typed values;
2. `map[string]interface{}` representations;
3. JSON byte slices;
4. Extism input/output copies;
5. WASM linear memory; and
6. Rust deserialization and response buffers.

Eliminate copies only when profiles show material overlap. Prefer byte-oriented internal APIs where they preserve public behavior. Check size limits before allocation.

Do not pool token, request, response, or secret buffers by default. If a reusable buffer is justified, define clearing semantics and obtain security review.

### E3. Logical client state

Measure one, three, and many authenticated clients sharing the same core. This distinguishes the fixed runtime cost from live per-client session state. Client deduplication is not automatic: two callers can have different tokens, integration metadata, permissions, and lifetimes. Any sharing would require explicit identity and reference-counting semantics and belongs with P1, not an incidental P2 optimization.

## Track F: alternate execution backends

If a precompiled cache plus a slim artifact cannot meet the target, write a separate architecture RFC for one of these options:

### Native service-account core

Compile the core to a supported native C ABI and load it through cgo or platform dynamic loading. This can remove Wazero compilation and its executable mappings, but it introduces:

- per-platform and libc build matrices;
- CGO/cross-compilation constraints;
- native crash and memory-safety blast radius;
- library distribution and signing;
- ABI versioning; and
- a larger supply-chain review.

The existing desktop-app shared-library path is IPC-oriented and is not proof that a native service-account core already exists.

### Isolated helper

Run the WASM core in a dedicated helper or sidecar with a hard memory boundary. This can keep the controller process smaller and allow one runtime to be shared deliberately, but it does not remove total memory. It adds local IPC, credential transport, health management, and deployment complexity.

These are fallback architectures, not the first P2 implementation.

## Benchmark protocol

### Platforms

Required release platforms:

1. Linux ARM64 on the target Raspberry Pi class, under cgroup v2;
2. Linux AMD64 on a dedicated runner; and
3. Darwin ARM64 as a regression/developer signal.

Do not use Darwin RSS to size a Linux Kubernetes limit.

### Build controls

Record and pin:

- repository commit and dirty state;
- core SHA-256;
- Go, Extism, Wazero, Rust, LLVM, and optimization-tool versions;
- GOOS, GOARCH, CGO mode, build tags, linker flags, and PGO state;
- kernel and cgroup versions;
- CPU model/features;
- cache medium and mount mode; and
- binary and cache sizes.

Build outside the timed region. Run offline core-only cases with `GOPROXY=off`. Keep each process fresh and never compare two variants in the same process.

### Scenario matrix

Every candidate runs:

| Scenario | Purpose |
|---|---|
| `IDLE` | Executable/process baseline |
| `CORE_NO_CACHE` | True cold compile |
| `CORE_CACHE_EMPTY` | Miss and population penalty |
| `CORE_CACHE_HIT` | Precompiled load |
| `CORE_CACHE_STALE` | Version/core mismatch behavior |
| `CORE_CACHE_CORRUPT` | Corruption and fallback behavior |
| `CLIENT_VALID` | Authenticated initialization |
| `READ_SMALL` | Normal External Secrets-style operation |
| `READ_LARGE` | Payload/copy growth |
| `CLIENTS_3` | Expected multi-namespace logical clients |
| `CLIENTS_64` | Bounded stress, still one core |
| `SOAK` | Full refresh interval and repeated operations |
| `CLOSE` | P1-only deterministic reclamation diagnostic |

Cache-hit scenarios must execute guest code and ultimately representative authenticated work. Cache loading already copies and CRC-checks the whole native segment; the operation gate measures data/session/linear-memory growth and compatibility, not lazy native-page faulting.

### Sampling and comparison

- Run at least two untimed warmups per binary and condition.
- Run at least 10 measured fresh processes per SDK condition and 20 fresh pods for the ESO gate.
- Interleave baseline and candidate to control thermal and background drift.
- Sample process metrics at 20 Hz or faster, while treating cgroup `memory.peak` as authoritative.
- Preserve stdout, stderr, exit status, stage timestamps, raw samples, and checksums.
- Reject, do not silently discard, runs with protocol errors, unexpected network access, multiple core identities, cache ambiguity, or sampling failure.
- Report every invalid run and its reason.

Credentials are allowed only in the private authenticated lane. Redact command lines and environment, disable core dumps, and do not publish authenticated heap profiles unless security review confirms they contain no token or secret material.

## Security requirements for compiled caches

A Wazero cache contains executable native code. Treat it as code, not as disposable performance data.

Required controls:

- cache directories are created with owner-only permissions;
- production cache entries come from a signed/attested image build or a trusted init container;
- the application mounts a prebuilt cache read-only in strict mode;
- world-writable and cross-tenant cache locations are rejected/documented as unsupported;
- cache artifacts have digests and provenance tied to the core and dependencies;
- symlink/path replacement risks are reviewed;
- stale or corrupt entries fail closed in strict mode;
- cache content never depends on service-account tokens or responses; and
- image scanners and SBOM/provenance include the native cache artifact.

Wazero's checksum detects accidental corruption; it is not a signature against an attacker who can rewrite the cache and checksum.

## Downstream External Secrets composition

SDK work should be measured in the real controller because application baseline matters. The downstream validation image should combine, as separate attributable layers:

1. External Secrets Operator v2.10.0;
2. P0 SDK synchronization (`da768af` or a released successor);
3. one selected P2 candidate;
4. the ordinary full-provider ESO build; and, in a separate comparison,
5. a provider-only ESO build.

A prior exploratory provider-only build reduced the ARM64 binary from roughly 270 MiB to 134 MiB and reduced pre-client RSS by roughly 45–55 MiB. That does not shrink Wazero, but it may be necessary to put the full controller below a safe cgroup budget. It should remain a downstream build experiment unless ESO adopts an official provider-selection mechanism.

`GOMEMLIMIT` is also an application-level experiment, not an SDK setting. Test it against Linux `memory.current`, operation latency, and GC CPU. It includes default WASM linear-memory buffers in Go-managed memory, but cannot cap anonymous executable mappings or other non-Go/native allocations and must not substitute for a cgroup safety margin.

The GitOps rollout remains:

1. build and attest the exact Linux/ARM64 image;
2. deploy through the Argo CD repository with a 512 MiB controller limit;
3. verify cache outcome, one-core identity, pod stability, store readiness, all secret refreshes, and rotation;
4. gather startup and soak evidence; and
5. lower the limit only if the 192 MiB maximum gate is met.

No ad hoc cluster mutation is part of this specification.

## Delivery plan and PR boundaries

### P2.0 — benchmark and artifact accounting

- Add the standalone Linux-capable harness.
- Check in the core ABI/section report and generation command.
- Add cache hit/miss/stale/corrupt scenarios.
- Publish raw credential-free results.
- No production behavior change.

### P2.1 — core export pruning and DCE

- Change the core build pipeline, not SDK lifecycle code.
- Produce a reproducible artifact and provenance.
- Show function/code/export reductions and no-cache memory results.
- Run full private integration tests.

### P2.2 — experimental compilation-cache support

- Add the private runtime-config seam.
- Validate prewarmed cache behavior on Linux ARM64/AMD64.
- Resolve strict read-only/cache-hit semantics with Wazero.
- Expose an opt-in runtime-scoped API only after security review.
- Keep default behavior unchanged.

P2.1 and P2.2 are independent: either may ship without the other, and their combined result must be measured rather than added arithmetically.

### P2.3 — profiled dependency/compiler improvements

- Upgrade or patch Extism/Wazero one dependency at a time.
- Link each change to allocation or mapping evidence.
- Avoid an SDK-local permanent fork.

### P2.4 — downstream ESO proof

- Build the exact patched image.
- Validate first under 512 MiB.
- Collect 20-start and soak evidence.
- Make any 256 MiB limit change in its own GitOps PR.

### P2.5 — alternate-backend RFC, only if needed

- Compare native core, helper/sidecar, and current WASM architecture.
- Include memory, latency, portability, security, and maintenance costs.

## Explicitly deprioritized approaches

### Force the interpreter

It measured worse locally for this large module and substantially changes runtime latency. It remains a data point, not the low-memory implementation.

### Strip custom sections only

It saves about 1.18 MiB of artifact size but only about 1% of local core-load peak. Keep stripping as build hygiene if compatible, but do not present it as the footprint solution.

### Disable debug information only

No repeatable peak reduction was observed, and the artifact does not carry normal DWARF sections. Retest after core build changes, but do not lead with it.

### Set a WASM page limit only

Initial linear memory is about 3.9 MiB, far below the observed roughly 118 MiB process increase. A page cap bounds future growth but does not remove eager compilation.

### Compress the embedded WASM only

Compression can reduce binary/file-backed size by at most the artifact's 9.1 MiB and requires a decompression buffer during startup. Evaluate it only after compiler-input reduction, with overlap measured.

### Call `debug.FreeOSMemory` in the SDK

It cannot reduce cold peak, affects the entire host process, and did not lower immediate Darwin RSS despite marking many heap pages released. Linux behavior is worth measuring diagnostically; a general-purpose library must not force global GC/scavenging by default.

### Add broad object or byte pools

Pools tend to retain high-water memory and can extend secret lifetime. Introduce one only for a profiled non-sensitive allocation with a strict size cap and clearing policy.

### Enable an automatic writable cache

The local empty-cache peak was 15.8% worse than no cache. Automatic filesystem writes and native-code trust also violate safe library defaults.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Warm cache saves compiler allocations but real operations grow data/session/linear-memory state | Require authenticated and worked-state measurements plus soak. |
| Empty/stale cache increases peak and recreates OOM | Strict require-hit mode; no hidden fallback in constrained process. |
| Cache generated on CI misses on Raspberry Pi CPU features | Target-hardware hit test and explicit build metadata. |
| Cache tampering becomes native code execution | Immutable/attested image layer or trusted init container; owner-only and read-only runtime mount. |
| Cache remains live after runtime close | Runtime owns and closes cache after plugin close; lifecycle tests. |
| Export pruning removes hidden ABI | Checked-in ABI report and full cross-language integration suite. |
| Smaller artifact regresses latency | Report startup and p50/p95 operation latency; keep variants isolated. |
| Linux page cache erases apparent RSS benefit | Use cgroup `memory.stat`, compare image layer/disk `emptyDir`/tmpfs, and use `memory.peak`. |
| Provider-only ESO fork creates maintenance burden | Treat as downstream composition and rebase/test against each ESO upgrade. |
| Memory target encourages unsafe 256 MiB rollout | Keep 512 MiB until the exact image meets the 192 MiB maximum gate. |

## Open questions

1. Which source repository and exact build recipe produce `internal/wasm/core.wasm`?
2. Why does the Extism artifact retain 1,741 `wasm-bindgen` descriptor exports?
3. Which exports beyond the four apparent SDK ABI entries are truly required?
4. How much code/function-count reduction follows descriptor removal plus DCE?
5. Does a prewarmed cache remain below budget after valid authentication and normal secret reads?
6. How does the target Linux kernel charge anonymous executable mappings and separate whole-file disk page cache to each trial cgroup?
7. Can Wazero expose read-only/require-hit semantics and cache outcome without private-format coupling?
8. Can a portable ARM64 cache be generated for the Raspberry Pi's CPU feature set, or must it be primed on target?
9. What is the maximum linear-memory page count under every supported SDK operation and payload size?
10. How much of full ESO startup memory is removed by an official provider-only build?
11. If WASM remains above budget, can the service-account core be distributed safely as a native library?

## Recommended next experiment

Do not repeat the completed credential-free matrix as a substitute for the missing acceptance lane. Under the existing 512 MiB headroom:

1. obtain an approved dedicated private service-account fixture, without recording its token or secret values;
2. compare original-artifact no-cache, empty-cache and verified prewarmed-cache paths through valid `NewClient` and representative reads;
3. measure both WASM memories, cgroup peak/file-cache accounting, operation/GC latency and a full refresh interval;
4. separately test cold-node cache charging and Linux AMD64;
5. resolve supported require-hit/outcome hooks and runtime-scoped ownership before wiring the ESO provider; the current default global `NewClient` does not opt into the proposed runtime option;
6. validate the exact ESO image at 512 MiB through the 20-start/rotation/soak gate before considering a lower limit.

The original-artifact cache path is the leading candidate. Reconsider Oz only as an independently validated secondary cache optimization. Descriptor pruning/DCE alone did not meet the memory gate; further core reduction needs owner/source evidence, and compiler patches need allocation profiles rather than inference from body count.
