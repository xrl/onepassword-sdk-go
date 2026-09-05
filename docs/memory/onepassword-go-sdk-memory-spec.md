# Proposal: Bounded-memory runtime lifecycle for `onepassword-sdk-go`

- **Status:** Draft
- **Target:** `github.com/1Password/onepassword-sdk-go`
- **Motivating version:** v0.4.1
- **Primary path:** service-account authentication through the embedded Extism/Wazero core

> Canonical in-Git specification. The current delivery is a credential-free, benchmark-only lab, not a cache API, lifecycle redesign, shipping artifact change, or release-acceptance result. See [lab source, protocol and evidence](../../benchmarks/footprint/README.md). Historic exploratory source was not preserved; [archived raw evidence and caveat](../../benchmarks/footprint/evidence/legacy/README.md) are not regenerated results. Authentication, private integration and ESO acceptance are blocked without credentials.
>
> Accounting correction (pinned Wazero 1.11.0 / Extism 1.7.1): default WASM linear memories are Go `[]byte`, subsets of Go heap and `GOMEMLIMIT` accounting, not additive native buckets. SDK main memory and Extism kernel memory are separate; `Plugin.Memory()` returns the kernel. `Plugin.Module()` exists, but its public wrapper exposes only exported functions. The lab uses a digest-pinned benchmark-only accessor overlay. `WithMemoryLimitPages` caps each memory separately, not their sum. Wazero eagerly copies the entire native code segment into anonymous executable mappings and CRC-checks it on a cache load; there is no supported lazy-native-page explanation for the warm-cache saving. Authentication still matters for data, sessions, operation growth and compatibility.

## Summary

The Go SDK should guarantee that a process loads at most one embedded WASM core per SDK runtime, expose deterministic client/runtime cleanup, and establish measured low-memory operating modes.

The work should be delivered in three stages:

1. **Correctness hotfix:** serialize lazy WASM-core initialization so concurrent `NewClient` calls cannot compile and retain duplicate runtimes.
2. **Lifecycle API:** add `Client.Close` and an explicitly owned `Runtime` with reference-counted core leases and deterministic shutdown.
3. **Footprint reduction:** profile the WASM build and Wazero configuration, then ship only optimizations proven to reduce peak and steady-state RSS without unacceptable latency or security regressions.

The first stage addresses the observed cold-start OOM behavior. It will not make the SDK a 20 MiB component: one initialized SDK core currently adds roughly 100 MiB or more in real applications. Reaching a substantially lower floor requires changes to the embedded core or execution architecture.

## Motivation

### Observed memory behavior

A public report against SDK v0.3.1 shows a Go service increasing from approximately 20 MiB to 116.5 MiB after one `onepassword.NewClient` call:

- <https://github.com/1Password/onepassword-sdk-go/issues/209>

An offline ARM64 test against the v0.4.1 embedded core produced the following process peak-RSS results. These numbers include the Go test harness and are not production sizing guidance; the relative growth is the relevant signal.

| Scenario | Peak RSS |
|---|---:|
| One core initialization | 157 MiB |
| Two concurrent core initializations | 290 MiB |
| Three concurrent core initializations | 418 MiB |

Running the concurrent test with `go test -race` reports a data race in `GetExtismCore`.

### Current initialization race

The v0.4.1 service-account backend uses an unsynchronized package global:

```go
var core *ExtismCore

func GetExtismCore() (*CoreWrapper, error) {
    if core == nil {
        p, err := loadWASM(context.Background())
        if err != nil {
            return nil, err
        }
        core = &ExtismCore{plugin: p}
    }
    return &CoreWrapper{InnerCore: core}, nil
}
```

If two goroutines enter while `core == nil`, both may compile and instantiate the approximately 9.1 MiB WASM module. Each caller can retain a wrapper around a different core, so the duplicate is not necessarily temporary or collectible.

The mutex inside `ExtismCore` serializes calls **after** initialization; it does not protect initialization itself.

This pattern occurs naturally in controller processes. For example, one controller may validate a secret store while another simultaneously reconciles a secret. A process with a 256 MiB cgroup limit can therefore OOM during a cold start even if a serialized startup later settles below that limit.

### Incomplete lifecycle management

The current lifecycle has two additional limitations:

- Clients release core-side client state only through a Go finalizer; callers cannot deterministically close a client.
- `ReleaseCore` sets the package pointer to `nil` but does not call `extism.Plugin.Close`, so it does not deterministically release Wazero resources and can allow another core to be loaded while old wrappers remain alive.

## Goals

1. Make core initialization race-free.
2. Ensure concurrent client creation performs one core load per SDK runtime.
3. Bound cold-start peak memory independently of the number of concurrent callers.
4. Allow callers to deterministically release per-client state.
5. Allow an owning application to deterministically close the WASM plugin/runtime.
6. Preserve the existing `onepassword.NewClient` API and behavior.
7. Measure heap, RSS, WASM memory, startup time, and operation latency on supported platforms.
8. Provide a supported low-memory profile only after benchmarks establish its trade-offs.
9. Avoid retaining authentication tokens or secret payloads longer than required.

## Non-goals

- Guaranteeing a 20 MiB process footprint with the current embedded core.
- Changing the 1Password authentication protocol.
- Caching service-account sessions or secret values without explicit caller control.
- Guaranteeing byte-for-byte zeroization of immutable Go strings.
- Making the Extism plugin concurrently callable; calls may remain serialized.
- Exposing Wazero or Extism types in the public SDK API.

## Proposal

### Phase 1: serialize core initialization

Introduce a private manager for the service-account core and route `GetExtismCore` through it.

The patch-release implementation can deliberately be simple: hold a mutex while checking and loading the core.

```go
type extismCoreManager struct {
    mu     sync.Mutex
    core   *ExtismCore
    loader func(context.Context) (*extism.Plugin, error)
}

func (m *extismCoreManager) get(ctx context.Context) (*CoreWrapper, error) {
    m.mu.Lock()
    defer m.mu.Unlock()

    if m.core == nil {
        plugin, err := m.loader(ctx)
        if err != nil {
            return nil, err
        }
        m.core = &ExtismCore{plugin: plugin}
    }

    return &CoreWrapper{InnerCore: m.core}, nil
}
```

Holding the lock during compilation is intentional. Core loading is rare, and blocking other constructors is substantially safer than allowing an O(N) memory spike. A failed load leaves the manager empty so a later call can retry.

`ReleaseCore` must use the same lock. Until reference counting exists, it should remain internal/test-only and must not close a core that active clients may still use.

#### Phase 1 acceptance criteria

- A barrier test with 64 concurrent calls invokes the injected loader exactly once.
- Every successful caller receives the same `InnerCore` identity.
- Loader failure is returned without publishing a partial core; a subsequent call can retry.
- `go test -race ./...` reports no core initialization race.
- In the core-only benchmark, peak RSS for 2, 8, and 64 concurrent acquisitions is no more than 15% above one acquisition on the same runner.
- No public API change is required.

### Phase 2: deterministic client and runtime lifecycle

#### Add `Client.Close`

Add an idempotent public method:

```go
func (c *Client) Close(ctx context.Context) error
```

`Close` must:

1. reject new operations;
2. wait for any in-flight operation on that client to finish;
3. invoke `release_client` exactly once;
4. remove SDK-owned references to the service-account token and client configuration where practical;
5. release the client's core lease; and
6. return cleanup errors to the caller.

Subsequent operations return a stable exported `ErrClientClosed`. Concurrent calls to `Close` return the same result and never release the client twice.

The existing finalizer should remain only as a best-effort fallback and delegate to the same once-only close path. If the minimum Go version permits, `runtime.AddCleanup` should be evaluated in preference to `runtime.SetFinalizer`. Documentation must make clear that deterministic cleanup requires explicitly calling `Close`.

The client state should use a lock with a consistent ordering relative to the existing core call lock:

- operations take a client read lock, check `closed`, then call the core;
- `Close` takes the client write lock, marks it closed, releases core-side state, and drops its lease.

This ensures that `Close` cannot race with an invocation or free a client ID that is still in use.

#### Add an explicitly owned `Runtime`

Add a public runtime object that owns one core manager:

```go
type Runtime struct { /* private */ }

type RuntimeProfile string

const (
    RuntimeProfileBalanced RuntimeProfile = "balanced"
    RuntimeProfileLowMemory RuntimeProfile = "low-memory"
)

func NewRuntime(options ...RuntimeOption) (*Runtime, error)
func (r *Runtime) NewClient(ctx context.Context, options ...ClientOption) (*Client, error)
func (r *Runtime) Close(ctx context.Context) error
func (r *Runtime) Stats() RuntimeStats
```

Existing code remains source-compatible:

```go
func NewClient(ctx context.Context, options ...ClientOption) (*Client, error) {
    return defaultRuntime.NewClient(ctx, options...)
}
```

The process-global default runtime retains its core for the process lifetime, preserving current latency behavior. Applications that require deterministic memory release use an explicitly owned runtime:

```go
runtime, err := onepassword.NewRuntime()
if err != nil {
    return err
}
defer runtime.Close(context.Background())

client, err := runtime.NewClient(ctx,
    onepassword.WithServiceAccountToken(token),
    onepassword.WithIntegrationInfo("example", "1.0.0"),
)
if err != nil {
    return err
}
defer client.Close(context.Background())
```

#### Core leases and shutdown

The runtime manager tracks:

- unloaded, loading, ready, closing, and closed states;
- the current core generation;
- active client leases;
- a completion channel for the current load/close operation; and
- the last load result for callers waiting on the same attempt.

Required behavior:

- one goroutine performs a load while all other callers wait;
- all callers waiting on one failed attempt receive that attempt's error;
- a later independent call may retry;
- canceled waiters return their context error without canceling a load needed by other callers;
- `Runtime.Close` rejects new clients and waits, subject to its context, for active leases to reach zero;
- once there are no leases, shutdown calls `extism.Plugin.Close(ctx)` and clears the core reference;
- close and acquire cannot cross generations or close a newly loaded core accidentally.

An optional idle-retention policy may close an explicit runtime after its final client closes:

```go
onepassword.WithCoreIdleTimeout(30 * time.Second)
```

This option must use a generation token so a stale timer cannot close a core that has since been reacquired. It should not be enabled by default until authentication, latency, and rate-limit effects are measured.

#### Phase 2 acceptance criteria

- `Client.Close` is idempotent and race-free.
- An invocation concurrent with `Close` either completes normally or begins after closure and receives `ErrClientClosed`.
- Core-side client state is released exactly once.
- `Runtime.Close` calls `Plugin.Close` exactly once after all clients close.
- New clients are rejected after runtime shutdown begins.
- Finalizer/cleanup fallback cannot double-release state.
- Tests cover close during load, close during invocation, canceled close, failed load, and load after failure.
- No token or secret value is emitted in logs, errors, stats, traces, or benchmark artifacts.

### Phase 3: reduce the single-core footprint

The focused follow-up specification is [`onepassword-sdk-go-footprint-reduction-spec.md`](./onepassword-sdk-go-footprint-reduction-spec.md). Its [confirmed credential-free campaign](../../benchmarks/footprint/evidence/campaign-report.md) reduced Linux/ARM64 median cgroup peak from 153.44 to 61.27 MiB with a trusted prewarmed original-artifact cache. Prune+DCE alone saved only 2.5%; `-Oz` increased uncached peak despite making the file smaller. Supported strict-cache semantics, P1 ownership and authenticated/ESO acceptance remain outstanding; no shipping artifact or default behavior changed.

Serialization removes multiplicative memory growth, but the single-core floor remains high. The following work should be benchmark-driven rather than exposed as unverified tuning knobs.

#### 3.1 Establish an authoritative benchmark suite

Add a standalone benchmark executable so measurements do not include the Go test harness. Record:

- current and peak RSS;
- Go `HeapAlloc`, `HeapInuse`, and `Sys`;
- SDK-main and Extism-kernel linear-memory pages separately (Go-heap subsets, not additional RSS buckets);
- core compilation and instantiation time;
- `NewClient` wall time and allocations;
- operation latency and allocations; and
- memory after client close and runtime close.

Required scenarios:

1. process baseline without SDK initialization;
2. core load only;
3. one authenticated client;
4. 2, 8, and 64 concurrent clients;
5. 1,000 sequential create/close cycles;
6. a long-running client with repeated operations;
7. payloads of 1 KiB, 1 MiB, 10 MiB, and the supported maximum; and
8. runtime close followed by a second runtime load.

Run at least on Linux AMD64, Linux ARM64, and Darwin ARM64, with the non-CGO Linux path explicitly represented. Memory regression jobs should use dedicated runners or cgroups and compare relative deltas to a checked-in baseline; noisy shared CI runners should not enforce tight absolute RSS values.

#### 3.2 Evaluate Wazero configuration

Evaluate, rather than assume, the following:

- compiler versus interpreter engine;
- debug information disabled;
- a measured `WithMemoryLimitPages` bound;
- confirmation that `WithMemoryCapacityFromMax(false)` remains in effect; and
- compilation cache behavior during runtime reloads.

Initial testing indicates that Wazero's interpreter can consume **more** RSS for this large module, so `low-memory` must not simply mean `NewRuntimeConfigInterpreter`. The profile should be selected from measured results per supported architecture.

The current module declares an initial memory of 62 pages, approximately 3.9 MiB. This indicates that the observed 100+ MiB process increase is not explained solely by initial WASM linear memory. A maximum-page limit is still valuable as a safety bound, but it is unlikely to provide the main baseline reduction.

The default memory limit must be derived from integration tests using realistic large secrets. Exceeding it must return a typed error rather than panic or terminate the process.

#### 3.3 Reduce the embedded core

Profile and optimize the SDK-core WASM artifact:

- remove unneeded exports;
- ensure release LTO and size optimization are enabled;
- strip name, debug, producer, and other unneeded custom sections;
- run `wasm-opt`/equivalent size passes and validate functionality;
- identify features that can be linked conditionally; and
- investigate whether service-account use can ship a smaller purpose-built module.

The current artifact contains roughly 9,500 functions and 1,700 exports. Reducing the compiler's input graph may lower both compilation peak and retained executable-code mappings more than tuning linear-memory pages.

#### 3.4 Reduce FFI copies

Audit request and response ownership across:

1. Go typed values;
2. `map[string]interface{}`;
3. JSON byte slices;
4. Extism input/output buffers; and
5. Rust deserialization.

Prefer `json.RawMessage` or byte-oriented internal APIs where they eliminate a full copy. In particular, avoid converting a response from `[]byte` to `string` only to parse or copy it again.

Do not pool buffers containing tokens or secrets by default: pooling can extend sensitive-data lifetime. Any reusable buffer strategy must clear memory before reuse and include a security review. Limits should be checked before allocating or copying large payloads whenever possible.

#### 3.5 Consider a native or isolated backend

If the in-process WASM floor cannot meet target environments, evaluate two longer-term options:

- a supported native core backend for service-account authentication; or
- an optional short-lived helper process that owns the WASM runtime and exits when idle.

A helper process would keep the parent Go process small and provide a hard OS/cgroup boundary, but total peak memory would still include the helper. It also adds IPC, packaging, credential-transfer, and crash-recovery complexity, so it is not part of the initial fix.

#### Phase 3 acceptance criteria

Before making `RuntimeProfileLowMemory` stable:

- it reduces single-client peak and steady-state RSS by at least 25% on Linux AMD64 and ARM64 relative to `balanced`;
- its operation latency and startup cost are documented;
- all SDK integration tests pass at the selected WASM memory bound;
- large-input failures are typed and recoverable;
- runtime close demonstrates that the plugin and Wazero runtime are no longer reachable; and
- security review finds no new long-lived copies of tokens or secret payloads.

If no tested configuration reaches the 25% threshold, do not expose a nominal low-memory profile; publish the measurements and prioritize core-artifact or backend work instead.

## Observability

`Runtime.Stats` should expose only non-sensitive lifecycle data:

```go
type RuntimeStats struct {
    State         RuntimeState
    LoadCount     uint64
    ActiveClients uint64
    Engine        string
    MemoryPages   uint32
}
```

It must not expose tokens, account identifiers, request bodies, secret references, or secret values. RSS and Go heap statistics should remain the application's responsibility because they are process-wide, not runtime-specific.

Optional event hooks may report core load/close duration and failures without adding a metrics-library dependency.

## Compatibility and migration

- Existing `onepassword.NewClient` callers continue to compile and use a process-retained default runtime.
- Adding `Client.Close` is backward-compatible; documentation and examples should immediately recommend it.
- The finalizer/cleanup fallback remains for callers that have not migrated.
- Runtime profiles are opt-in until benchmarked across supported targets.
- No existing caller is forced to accept idle unload, interpreter latency, or a new WASM memory limit in the initial patch.

## Security considerations

- Serialize core initialization without serializing or logging credentials outside the existing core call boundary.
- Ensure partial initialization failures close any plugin/runtime that was created but not published.
- Clear SDK-owned token references during `Client.Close`, while documenting that Go strings cannot be reliably zeroized.
- Do not allow `Runtime.Close` to free core memory during an active operation.
- Do not include real service-account tokens or secret payloads in memory profiles checked into CI.
- Treat an out-of-process backend as a separate threat-model review because it introduces local IPC and credential transfer.

## Rollout plan

1. **Patch release:** synchronized core initialization plus concurrency/race regression tests.
2. **Next minor release:** `Client.Close`, explicit `Runtime`, core leases, and deterministic `Plugin.Close`.
3. **Experimental release:** publish benchmark tooling and any validated low-memory profile behind an opt-in option.
4. **Later release:** consider changing defaults only after production telemetry and compatibility feedback.

Downstream applications with tight memory limits should retain temporary startup headroom until they consume the synchronization fix and verify one-core behavior in their own environment.

## Alternatives considered

### Only raise container memory limits

This prevents immediate OOMs but permits duplicate cores to remain resident and leaves the data race intact. It is mitigation, not a library fix.

### Use `sync.Once`

A plain `sync.Once` prevents duplicate successful loads but makes error retry and deterministic unload/reload awkward. A mutex is sufficient for the patch; a stateful manager is preferable once lifecycle control is added.

### Set a smaller WASM page limit only

The module's initial linear memory is approximately 3.9 MiB, much smaller than the observed RSS increase. A page cap protects against growth but does not address duplicate compilation or the dominant single-core footprint.

### Force the Wazero interpreter

A local core-load experiment showed higher, not lower, peak RSS in interpreter mode. Engine selection must therefore be evidence-based.

### Depend on garbage collection/finalizers

Finalizers are non-deterministic and cannot provide a reliable memory budget or shutdown boundary. They remain useful only as a fallback.

## Open questions

1. Which mappings account for the gap between Go heap profiles and process RSS: compiled code, module source, Wazero runtime structures, or allocator retention?
2. What is the maximum observed WASM page count for supported operations and payload sizes?
3. Can the core expose a cheaper reset operation while retaining compiled code?
4. Can SDK-core exports and linked features be reduced without splitting compatibility artifacts?
5. Should explicit runtimes release immediately at zero clients or default to a short idle timeout?
6. Is a native service-account core feasible on all supported Linux architectures?
