# Executable causal core-memory protocol

**Protocol ID:** `op-go-extism-core-memory/v1`  
**Target:** Darwin/arm64, fresh-process, warm-OS-cache behavior of `internal.GetExtismCore`  
**A (base):** `5866f43111ffeee5952e43a13da1aafef98200c8` at `/Users/xavier/code/dekopon/.worktrees/onepassword-sdk-go-memory-base`  
**B (fix):** `da768afd327a9393e7bb8033d0d3fa01f9e999fd` at `/Users/xavier/code/dekopon/.worktrees/onepassword-sdk-go-memory-fix`

## 1. Question and scope

The treatment is the mutex added around the package-global Extism core's nil check, complete WASM/plugin initialization, publication, wrapper construction, and release. The primary question is whether simultaneous cold callers create multiple live plugins in A, while B creates exactly one, and whether that difference explains higher process RSS.

The primary outcome is Darwin `/usr/bin/time -l` **maximum resident set size**. Secondary outcomes are sampled current RSS with returned wrappers live, Go `runtime.MemStats`, batch/per-call latency, failures, and ordinal identities of returned `*internal.ExtismCore` objects.

This is offline core acquisition only. Do not call `InitClient`, `Invoke`, `ReleaseClient`, a business API, or the shared-library backend. The sole public-API scenario deliberately returns from option processing before backend selection. No credential is read or supplied. An empty or malformed-token `NewClient` call is **not** run because the public API does not guarantee that it cannot attempt network access.

This protocol makes no claim about authenticated clients, network operations, payloads, production OOMs, race freedom, an exact per-core byte cost, or platforms/caller counts outside Darwin/arm64 and `N<=4`.

## 2. One harness, two builds

Create the benchmark project outside Git at `/Users/xavier/code/dekopon/onepassword-sdk-go-memory-benchmark`. Give its module an import path below the SDK's internal boundary, for example `github.com/1password/onepassword-sdk-go/benchdriver`, so it may legally import `github.com/1password/onepassword-sdk-go/internal`. Its canonical `go.mod` must replace the SDK with `./sdk`; repoint that single symlink to A and then B for the two builds. Thus driver source, `go.mod`, `go.sum`, and the textual build command are identical; only the recorded symlink target/commit changes. Use separate clean build caches for A and B to prevent stale reuse.

Before building, require:

- `git rev-parse HEAD` in each tree equals the pinned full commit above;
- both worktrees are clean;
- the SHA-256 values of `go.mod`, `go.sum`, and `internal/wasm/core.wasm` match across trees; and
- the local toolchain reports exactly Go `1.27.1`.

Abort rather than update dependencies or download a toolchain. Build both once with a pre-populated module cache and network-disabled module resolution:

```text
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 GOTOOLCHAIN=local GOPROXY=off \
  GOCACHE=<variant-specific-empty-cache> \
  <go1.27.1>/bin/go build -mod=readonly -trimpath -pgo=off \
  -buildvcs=false -o <neutral-bin-dir>/<variant> ./cmd/coremem
```

Do not use race, coverage, `go run`, or `go test` instrumentation for these numbers. Save the exact commands, toolchain binary hash, driver/lockfile hashes, resolved source paths and commits, binary SHA-256 values, WASM SHA-256, and `go version -m` output. Run both binaries directly from the same neutral working directory. Compilation is outside every timed run. Wait 60 seconds after the second build; do not purge filesystem caches. The reported condition is therefore a fresh process with a warm OS file cache.

## 3. Child contract and liveness

Both executables accept at least `-scenario`, `-n`, `-variant`, `-source-commit`, `-binary-sha256`, `-wasm-sha256`, and `-run-id`. At startup they verify the supplied binary hash by hashing `os.Executable`, verify `runtime.GOMAXPROCS(0)`, and reject any environment key beginning `OP_`.

The child emits versioned JSONL only on stdout. Every event contains protocol/schema version, run ID, variant, source commit, binary and WASM hashes, PID, scenario, `n`, GOMAXPROCS, UTC `RFC3339Nano` time, and nanoseconds from a process-local monotonic origin. Required events are `hello`, `ready`, `post_raw`, `post_gc`, and `done`; setup failure or premature termination is explicit. The controller treats duplicate, missing, out-of-order, or malformed events as run failures.

For parallel scenarios, preallocate result and wrapper slots, start exactly `n` goroutines, wait until all are parked on one closed-channel start barrier, and emit `ready`. After the controller's `GO`, take the pre-operation `MemStats`, start the batch monotonic timer, close the barrier, and wait for all callers. Each caller times only its SDK call and writes one preassigned result slot. Batch time runs from immediately before barrier release through final completion. Sequential scenarios use one worker behind the same barrier and execute `n` operations in order.

After timing stops, take the raw `MemStats`, then emit `post_raw` with all results. After controller acknowledgement, call `debug.FreeOSMemory()` exactly once, take a distinct `post_gc` snapshot, and emit `post_gc`. Wait for the final acknowledgement, call `runtime.KeepAlive` on the retention slice, emit `done`, and exit. This keeps all returned wrappers live through both RSS checkpoints and the forced-GC probe, except in the explicitly named drop-generation scenario.

For every acquisition, type-assert `wrapper.InnerCore` to `*internal.ExtismCore`. Convert that pointer to a run-local key, assign first-seen ordinal IDs in caller-index order after all workers join, and emit only the ordinal vector and `unique_core_count`—never a pointer or address. Pointer keys must not be emitted. `GEN_DROP_4` must use non-rooting `uintptr` keys so its discarded wrappers are genuinely collectible; all other acquisition scenarios also retain wrappers independently of the identity map.

Record attempt count, contract-success count, bounded error category, per-call monotonic duration, and panic category. Recover ordinary per-worker panics. Hash the complete original error/panic text with SHA-256, but emit at most 160 sanitized UTF-8 bytes after replacing home/worktree paths, control characters, and token-like strings. Fatal runtime failures and signals remain controller failures.

Every `MemStats` snapshot contains `HeapAlloc`, `HeapInuse`, `HeapSys`, `StackInuse`, `Sys`, `TotalAlloc`, `Mallocs`, `Frees`, `NumGC`, and `PauseTotalNs`.

## 4. Exact scenario registry

Every row is a separate fresh process. All cells use `GOMAXPROCS=10` and run on both A and B. `ReleaseCore` is called only sequentially in A; deliberately racing it in A would add another unsafe treatment and is excluded.

| ID | `-n` | Setup before `ready` | Timed operation | Retention and expected identity |
|---|---:|---|---|---|
| `IDLE` | 0 | None | Barrier/checkpoint machinery only | No wrapper or identity. Harness/process baseline. |
| `PUBLIC_OPTION_ERROR` | 1 | None | `NewClient(ctx, func(*Client) error { return sentinel })` | Require nil client and `errors.Is(err, sentinel)`; count this expected error as contract success. It exits before core selection, credentials, or network and has no core identity. |
| `COLD_1` | 1 | `ReleaseCore()` | One `GetExtismCore` | Retain wrapper; exactly one identity. One-core reference. |
| `SEQ_WARM_4` | 4 | `ReleaseCore()` | Four serial `GetExtismCore` calls | Retain all; first call cold, next three warm; exactly one identity. |
| `WARM_PAR_2` | 2 | `ReleaseCore()`, acquire and retain one seed wrapper | Two simultaneous `GetExtismCore` calls | Retain seed and results; all identities, including seed, must be one. Scheduling/goroutine negative control. |
| `WARM_PAR_3` | 3 | As above | Three simultaneous warm calls | Same expectation. |
| `WARM_PAR_4` | 4 | As above | Four simultaneous warm calls | Same expectation. |
| `COLD_PAR_2` | 2 | `ReleaseCore()` | Two simultaneous `GetExtismCore` calls | Retain all. B must have one identity; A may have one or two. |
| `COLD_PAR_3` | 3 | `ReleaseCore()` | Three simultaneous cold calls | B must have one; A may have one through three. |
| `COLD_PAR_4` | 4 | `ReleaseCore()` | Four simultaneous cold calls | B must have one; A may have one through four. |
| `RELEASE_ONLY_4` | 4 | `ReleaseCore()`, acquire and retain one seed wrapper | Four serial `ReleaseCore()` calls | Seed remains retained; operation allocates no new core. First release detaches the global, later releases see nil. |
| `GEN_KEEP_4` | 4 | `ReleaseCore()` | Four serial generations, each `ReleaseCore(); GetExtismCore()` | Retain all four wrappers; exactly four identities in both variants. This intentionally demonstrates accumulation when generations remain reachable. |
| `GEN_DROP_4` | 4 | `ReleaseCore()` | Same four serial generations | Drop generations 1–3 before the next iteration; retain only generation 4. Raw peak is churn; post-GC is a labeled, nondeterministic reclamation probe. Historical identity count is descriptive only. |

`GetExtismCore` only instantiates the embedded Extism plugin; allowed-host declarations grant capability but do not themselves make a request. Any non-nil acquisition error invalidates that run. Do not inspect exact embedded-core error prose.

## 5. Repetitions and pre-generated order

A **cell** is `(scenario, variant, GOMAXPROCS)`. Save all warmups but exclude them from numerical summaries.

- Five measured processes per cell: `COLD_1`, `COLD_PAR_2`, `COLD_PAR_3`, `COLD_PAR_4` (40 measured).
- Three measured processes per cell: `WARM_PAR_2`, `WARM_PAR_3`, `WARM_PAR_4` (18 measured).
- One measured diagnostic process per cell: `IDLE`, `PUBLIC_OPTION_ERROR`, `SEQ_WARM_4`, `RELEASE_ONLY_4`, `GEN_KEEP_4`, `GEN_DROP_4` (12 measured). These rows are qualitative controls, not standalone distribution estimates.
- Exactly one discarded warmup precedes measured use of every one of the 26 cells (26 warmups).

The complete plan is **70 measured + 26 warmup = 96 fresh processes**. No A run above four cold callers is allowed. N=8/64 scale runs and a GOMAXPROCS=1 arm are intentionally omitted: the required controls/churn consume the roughly 20-minute budget, N>4 widens the causal claim and safety exposure, and GOMAXPROCS=1 tends to suppress the overlap needed to expose A. Results are scoped accordingly.

Before the first child, generate immutable `order.json` with seed string `op-go-core-v1:5866f431:da768afd`. Within each stage/block, order scenario IDs by ascending raw SHA-256 of `seed + NUL + stage + NUL + block + NUL + scenario`. Expand every scenario to an adjacent A/B pair. The first variant for a scenario is selected by the low bit of `SHA256(seed + NUL + "first" + NUL + scenario)` in repetition 1 and flips on every later repetition; its warmup uses the opposite order. This supplies deterministic rotation, adjacent pairing, and alternating variant-first order.

Execute these stages exactly:

1. warmups for the four cold primary scenarios;
2. measured cold-primary repetition blocks 1–3;
3. warmups for all three warm controls, then their measured blocks 1–3;
4. for each diagnostic scenario in its seeded order, its A/B warmup pair followed by its A/B measured pair;
5. measured cold-primary repetition blocks 4–5.

Pause two seconds after every child. Run one target at a time. Never reorder, add retries, lower `n`, or replace a missing repetition based on observed results. This staging ensures every required scenario and three primary repetitions occur before the final two precision blocks if the campaign reaches the time ceiling.

## 6. Host preparation, launch, sampling, and limits

Require Darwin/arm64 and record, before and after the campaign: `sw_vers`, `uname`, 32-GiB physical memory, 10 logical CPUs, 16-KiB host page size, AC-power state, raw `vm_stat`, `sysctl vm.swapusage`, and memory-pressure status. Record deviations and do not pool a run from another host shape. Use AC power, close avoidable workloads, and do not purge caches.

Launch each target as the direct utility of:

```text
/usr/bin/time -l <absolute-binary> <arguments>
```

Use a new process group, a per-run stdout JSONL file, and a separate raw stderr/time file. Start the 75-second timeout at spawn. Give the child a clean allowlist environment containing only locale/timezone and explicit `GOGC=100`, `GOMEMLIMIT=off`, and `GOMAXPROCS=10`; no `OP_*`, credential, proxy, or SDK configuration variable may survive.

On `hello`, poll `/bin/ps -o rss= -p <PID>` every 50 ms using controller monotonic timestamps. Preserve raw values; Darwin reports KiB, so multiply by 1024 for bytes. At `ready`, `post_raw`, and `post_gc`, the child waits until the controller has collected five valid samples whose timestamps follow that event; the checkpoint RSS is their median. Preserve `sampled_max` as a lower bound only. Parse the integer on the raw `maximum resident set size` line from `/usr/bin/time -l` as bytes; it is the authoritative whole-run high-water mark.

A sampled RSS of **1.40 GiB (1,503,238,554 bytes)** triggers SIGTERM to the target process group and SIGKILL 250 ms later. Mark the run censored at the largest observed RSS and stop future entries for that exact cell. Apply the same action at 75 seconds. Do not use `ulimit -v`. Abort the campaign if a completed time record reaches 2 GiB, swap usage rises above its pre-campaign value (at the reporting precision), or system memory pressure becomes warning/critical. Check swap/pressure after every repetition block.

Start the campaign clock with the first warmup. At 18 minutes launch no new child; at 20 minutes terminate the current process group and stop. Mark every unlaunched order entry `missing_time_budget`; never silently reduce repetitions. Only these predeclared safety/time actions may change the saved order.

For every run, save `stdout.jsonl`, raw `stderr.time`, raw timestamped `ps.jsonl`, and `controller.json` containing spawn/exit times, expected/observed PID, acknowledgements, timeout/watchdog actions, exit code or signal, malformed/missing events, time-parse status, and skip/censor reason. Publish warmups, failures, censored runs, and missing entries as well as successful runs.

## 7. Derived values and statistics

For each valid process derive:

- authoritative peak `P` from `/usr/bin/time -l`;
- checkpoint medians `R_ready`, `R_raw`, and `R_gc`, sampled maximum, and deltas `P-R_ready`, `R_raw-R_ready`, and `R_gc-R_ready`;
- pre-to-raw and pre-to-GC deltas for every recorded `MemStats` field;
- batch latency and within-run caller nearest-rank p50, p95, and maximum (rank `ceil(q*n)` after sorting); and
- attempts, successes, error/panic categories, ordinal identity vector, and unique count.

The process—not a caller—is the replicate. For every measured cell summarize each run-level metric with median, unscaled MAD (`median(abs(x-median(x)))`), and min–max. Never pool callers across processes. Exclude warmups, failed, malformed, and censored runs from numerical summaries, but include them as numerators/denominators in a complete failure table. Censored RSS is reported separately as a lower bound.

Pair A and B by scenario repetition block and report B/A ratios for positive absolute peak/current-RSS and MemStats values, plus B-minus-A differences for signed deltas. Report B `COLD_PAR_N`/B `COLD_1` peak ratios. Analyze identity count as categorical exposure; for A, tabulate peak and raw RSS by both caller count and observed unique count. A returned-pointer count is a lower bound on actual loads because an unreturned plugin can be overwritten before wrapper construction.

RSS is not Go heap. Discuss RSS as including Go heap/stacks, embedded module, Wazero code/mappings, WASM linear memory, allocator retention, and shared pages. Do not subtract `Sys` or `HeapAlloc` from RSS to estimate plugin memory. Treat post-GC RSS only as a reclamation probe, never as the primary outcome.

## 8. Predeclared hypotheses and verdicts

Let `P1_V` be median peak RSS for variant `V` in `COLD_1`. For `N=2,3,4`, let warm scheduling overhead be:

```text
H(V,N) = max(0, median_peak(V,WARM_PAR_N) - P1_V)
```

and let the corresponding peak control band be `C(V,N) = P1_V + H(V,N)`. Define an analogous raw-current control from median `R_raw`.

### Validity requirements

A full verdict requires all planned primary repetitions, correct build/host metadata, parseable time output, and no primary failure/censoring. All successful `COLD_1`, `SEQ_WARM_4`, and warm-control runs must report one identity. `GEN_KEEP_4` must report four. Public-option runs must return the sentinel contract error without a client. A one-cold paired median B/A peak ratio outside `[0.85, 1.15]` is an unexplained single-core difference and blocks attribution to the synchronization change pending investigation.

### Expected fixed behavior

B passes the synchronization/memory check only if:

1. every call in every measured B cold-primary run succeeds;
2. every B `COLD_PAR_2/3/4` run reports exactly one identity; and
3. for each `N`, `median_peak(B,COLD_PAR_N) <= 1.15 * P1_B + H(B,N)`.

Any valid B cold-concurrent run with more than one identity directly falsifies the synchronization hypothesis. A median bound violation (therefore at least three of five runs influencing the median) falsifies the claimed one-core memory band for that `N`, even if identity remains one.

### Evidence for the causal memory effect

A **causal pass** requires the B check above and, in A:

1. at least one valid measured `COLD_PAR_2/3/4` run with `unique_core_count > 1`;
2. duplicate-core runs whose median peak or median raw-current RSS exceeds the matching `C(A,N)` control by more than 15%; and
3. no comparable >15% excess in the warm controls.

Report normalized excess versus control by observed identity count; a nondecreasing excess with identity/caller count is dose-response corroboration. If A exposes a duplicate but not material RSS excess, report **mechanism observed, memory effect not established**. If A never exposes a duplicate or core-sized excess, report **no causal verdict**, not “no bug”: the start barrier cannot guarantee that A overlapped inside its unsynchronized nil-check/load window. A base peak can also reflect an overwritten, unreturned plugin even when observed unique count is one.

`RELEASE_ONLY_4`, `GEN_KEEP_4`, and `GEN_DROP_4` are interpretation controls, not PR pass criteria. In particular, similar retained-generation growth in A and B is expected because neither variant closes an Extism plugin when `ReleaseCore` merely clears the global pointer. Reclamation after dropping wrappers is GC/allocator dependent and cannot establish or refute a leak.

## 9. Required publication

Publish the immutable protocol/order, harness and controller source hashes, build/host manifests, every raw run directory, skip/censor/failure tables, per-cell summaries, paired ratios/differences, identity-by-memory tables, and the final validity/causal verdict. Explicitly list ASLR, GC timing, macOS compression/reclamation, thermal and P/E-core scheduling, file-cache state, shared mappings, and 50-ms sampler miss risk as residual confounders.

Base detached worktree must remain at 5866f43111ffeee5952e43a13da1aafef98200c8: /Users/xavier/code/dekopon/.worktrees/onepassword-sdk-go-memory-base

Fixed detached worktree must remain at da768afd327a9393e7bb8033d0d3fa01f9e999fd: /Users/xavier/code/dekopon/.worktrees/onepassword-sdk-go-memory-fix

You may create only /Users/xavier/code/dekopon/onepassword-sdk-go-memory-benchmark plus temporary untracked harness directories in those two benchmark worktrees.

Do not touch the clean PR worktree, primary clone, tracked SDK files, commits, branches, remotes, GitHub PR, or files elsewhere. Do not commit or push.

First verify both SHAs and clean status. Create a canonical Go harness and driver under the output directory. Copy it temporarily into each checkout where Go internal-package rules require it, build two binaries with identical flags, then remove temporary checkout files. Never run go mod tidy.

Each sample must be a fresh process. Synchronize concurrent callers with a start barrier, retain returned wrappers/clients or errors through measurement, and report unique core identities for direct-core scenarios. Include a no-initialization idle baseline.

Capture raw per-sample /usr/bin/time -l maximum RSS in bytes, a second RSS observation if feasible, runtime.MemStats, elapsed time, caller/error/unique-core counts, commit, scenario, repetition, environment, and exact command. Never substitute Go heap for RSS.

Use a fixed-seed interleaved base/fix order, discarded warmups, bounded repetitions, and a watchdog that kills any sample above 2 GiB or a run materially beyond 20 minutes. Never run benchmark processes concurrently.

No credentials are present. Never inspect credential values, contact live 1Password endpoints, or resolve secrets. A public NewClient scenario is allowed only if it fails locally and safely with no network dependence; otherwise mark it unsupported.

Preserve raw JSONL or CSV, summarized CSV, environment and commands, harness source, driver source, and report.md under the output directory.

Calculate median, min/max or MAD, absolute delta, and base/fix ratio per scenario. Clearly separate peak RSS, steady/sample RSS, and Go heap. State whether the fix affects concurrent cold start, single/warm paths, and ReleaseCore churn without overclaiming.

Run a harness smoke test and result-count/data integrity checks. End with both Git worktrees clean and pinned.

If the protocol is impossible, make only the smallest scientifically justified adjustment and document it. Return concise status, key numbers, deviations, commands, clean-worktree evidence, and exact report/raw-data paths.
