# Credential-free SDK footprint lab

**Confirmed credential-free Linux/ARM64 measurements, not authenticated or release acceptance.**

**Result:** original-artifact prewarmed cache reduced median cgroup peak **153.44 → 61.27 MiB (−60.1%)**. Cache + Oz reached **53.30 MiB**, but Oz **increased uncached peak to 252.16 MiB**. Descriptor pruning/DCE alone was not a substantial memory fix. See the [campaign report](evidence/campaign-report.md).
Shipping `core.wasm`, SDK defaults, `go.mod`/`go.sum`, P0 synchronization/retry and public API are unchanged. No authenticated or ESO tests can pass acceptance in this lane. No lifecycle redesign, stable cache API, private Wazero cache parsing, unsafe reflection, custom allocator, or library-wide GC tuning is included.

## Evidence and corrected specifications

- [Confirmed campaign and recommendations](evidence/campaign-report.md), [357-process integrity audit](evidence/campaign-audit.json)
- [Canonical footprint specification](../../docs/memory/onepassword-sdk-go-footprint-reduction-spec.md)
- [Canonical lifecycle proposal (future work)](../../docs/memory/onepassword-go-sdk-memory-spec.md)
- [Artifact report](evidence/artifacts/report.md), [exact tools/flags/digests and full ABI/section report](evidence/artifacts/artifacts.json)
- [Local smoke report](evidence/smoke-report.md), [raw trials](evidence/smoke/trials.json), [summary](evidence/smoke/summary.json), [manifest/order](evidence/smoke/manifest.json), [archive checksums](evidence/smoke/archive.json)
- [Historical raw archive and missing-source caveat](evidence/legacy/README.md)
- [Validation commands/results](evidence/validation.md)

The original+Oz control has **4,555 bodies**, versus prune+Oz's **4,554**. Almost all Oz body-count reduction also happens without pruning. Prune-only retains all 9,537 bodies; DCE after pruning leaves 8,485. Body counts/file size are not memory evidence. Do not attribute Binaryen's general optimization/merging benefit to descriptor removal or speculate about unavailable Rust source/build profiles.

## Source accounting

Pinned Go 1.27.1, Extism 1.7.1, Wazero 1.11.0; no dependency/toolchain upgrades.

- Wazero `internal/wasm/memory.go`: default linear-memory buffers are Go `[]byte`, **subsets of Go heap/GOMEMLIMIT**, not native allocations to add to heap. Page counts measure logical sizes, not independently resident RSS.
- Extism `extism.go`: `Plugin.Memory()` returns **kernel** memory. `Plugin.Module()` returns a wrapper whose shipping API exposes only functions. The accessor overlay in `build.py` uses `m.inner.Memory().Grow(0)` to measure **SDK main** pages without the 4-GiB `Size()` overflow. Original module.go SHA-256 is pinned in source; the complete dependency-copy file digests and license are retained in generated builds. No module-cache edit occurs.
- Wazero `internal/engine/wazevo/engine_cache.go`: maps anonymous executable storage, `io.ReadFull`s the entire native segment, then CRC-checks it before use. Avoiding compiler allocations—not lazily faulting only guest-reached code—is the supported warm-cache explanation. Authentication still gates data/session/growth and functional compatibility.
- Process mapping RSS is partitioned into file, anonymous executable, and anonymous non-executable/other. Go stats, stacks and both linear memories explain subsets, **not additive buckets**. Cgroup `memory.stat` file/page-cache charges are distinct from anonymous executable memory and process file RSS; whole cache files are hashed/touched before a warm trial. Host cache is uncontrolled and never purged.

## Reproduce locally

Replay the checked-in evidence without launching benchmarks:

```sh
python3 benchmarks/footprint/report.py
```

Each new campaign keeps reviewable JSON summaries and a checksummed `raw.tar.gz` containing byte-exact text evidence, not native code or cache blobs. `bundle.py` generates these deterministic bundles; `report.py` verifies/replays them without extracting paths into the checkout.

Run from repository root. Tools must already exist at the pinned paths. Outputs must not exist; choose a fresh directory for every rerun. All commands are offline except the explicitly separate SSH transport below.

```sh
PYTHONPATH=benchmarks/footprint python3 -m unittest discover -s benchmarks/footprint/tests -v
python3 benchmarks/footprint/artifacts.py --out benchmarks/footprint/generated/variants-next
for v in original stripped prune-only prune-dce prune-oz original-oz; do
  python3 benchmarks/footprint/build.py \
    --artifact benchmarks/footprint/generated/variants-next/$v.wasm \
    --out benchmarks/footprint/generated/next/$v
 done
python3 benchmarks/footprint/controller.py \
  --build original=benchmarks/footprint/generated/next/original \
  --build prune-oz=benchmarks/footprint/generated/next/prune-oz \
  --build original-oz=benchmarks/footprint/generated/next/original-oz \
  --cache disabled --cache empty --cache warm-rw --calls 2 --settle 0 \
  --out benchmarks/footprint/generated/next-smoke
```

Six artifacts only: original, `wasm-tools strip --all`, export-prune-only, prune + `wasm-opt --remove-unused-module-elements`, prune + `wasm-opt -Oz`, original + identical `wasm-opt -Oz`. The Python pruning function rewrites only section 7 and removes only function exports prefixed `__wbindgen_describe_`. All other raw sections remain identical at prune-only. After Binaryen, validation compares retained export signatures, resolved imports, memories, tables and globals. Function indices may change. Full private integration is still required; malformed-input smoke cannot establish all ABI behavior.

Rejected generator exploration: adding Binaryen `--all-features` produced `wasm-tools validate` error `invalid leading byte (0x7f) for external kind (at offset 0x2d3)` on prune+DCE. It enabled unnecessary features outside pinned wasm-tools support. That artifact was not used; final flags preserve input feature defaults. Exact rejected flags/disposition are in the artifact manifest.

`build.py` makes a task-owned copy of pinned Extism (Go 1.27 disallows overlays below GOMODCACHE), an alternate modfile with only a local Extism replace, and an overlay containing:

1. the minimal Extism main-page accessor;
2. the SDK loader counter and runtime-config/deny-all-hosts hooks;
3. the **embedded** WASM file replacement itself.

The shipping `GetExtismCore`/P0 lock and `loadWASM` path run, not a standalone Extism look-alike. Eight concurrent acquisitions verify all identities and one load attempt. The runtime reports the embedded digest and pinned dependency versions; controller checks against the build manifest. Generated directories have nested module boundaries so overlay source files do not contaminate default `go test ./...`. Archive copies suffix `.go.txt` for the same reason.

### Checkpoints and diagnostics

Probe options are typed and bounded: `--calls=0..1000`, `--input-bytes=1..1048576`, `--acquisitions=1..64`, `--settle=0..120s`, `--memory-pages=0..65536`, `--diagnostic=none|gc|free-os-memory`, plus `--idle` baseline-only. Inputs are fixed spaces followed by `{`; arbitrary payloads/tokens are not accepted. One invalid `init_client`, then N invalid `invoke` calls must return a parse error containing `EOF while parsing an object`, no response, and no trap/network error. Error fingerprints—not raw request/response bodies—are recorded.

Stages: baseline-ready, core-ready, invalid-init, repeated invalid-invoke, settled, optional diagnostic, closed. Every stage has monotonic timing, selected Go allocation/GC statistics, process RSS/high-water/CPU times, main/kernel pages, and loader/identity counters. Linux additionally has cgroup v2 current/peak/events/stat, smaps rollup and disjoint mapping RSS. Primary runs do **not** force GC. Close is a benchmark-only, sequential plugin/cache shutdown after work; it does not implement client leases or prove P1 reclamation. Zero pages at close means no live accessor handle, not proof RSS has been reclaimed.

Darwin uses `ps` for current RSS and `getrusage` for process peak; it is only developer signal. Linux uses `/proc` and cgroup high-water, not sampled maxima. This compact delivery samples **checkpoints**, not a 20-Hz timeline, and does not instrument Wazero's compiler-internal phases. Both limitations are explicit; kernel high-water remains authoritative. Profiles are intentionally omitted from primary trials; a separate credential-free profile lane is future optional work.

The controller interleaves cells with a recorded seed, launches sequential fresh processes, uses a distinct fresh cache per trial, keeps warmups and all failures, and summarizes medians/min/max/range/count (no spurious p95 for one sample). Raw stdout/stderr, commands, source/build/dependency/cache checksums, host state and exit codes are preserved. Default bounded smoke has zero warmups/one measured process; a campaign needs at least two warmups and ten measured processes per cell. `GOMAXPROCS=2` (validated), `GOGC=100`, no inherited credentials, no forced GC, `GOMEMLIMIT=off` by default. An explicitly supplied application `GOMEMLIMIT` is a separate recorded diagnostic; use `--memory-limit BUILD=64MiB` with a named build alias to interleave it with untuned controls, and `--cell BUILD:CACHE` to select exact comparisons. Do not pool tuning settings. Initial archived smoke predates the explicit CPU pin and is not pooled with new campaigns.

### Cache certainty

- `disabled`: no cache access.
- `empty`: per-trial fresh writable directory; measures population penalty. May peak higher than disabled.
- `warm-rw`: independently populated by a successful fresh probe, then reused. Public Wazero API exposes no hit signal, so **outcome remains unknown**, not require-hit support.
- `warm-ro`: Linux systemd read-only bind mount only; an `EROFS` write-check followed by successful load/guest smoke with one attempt, no retry/fallback wrapper, existing and unchanged entry hashes establishes a **known hit for this pinned version**. Missing/corrupt/stale entries can still compile first and fail on write: this is not strict miss handling and still needs 512-MiB headroom. No cache format is parsed. `cache_failures.py` tests a missing core entry, a different embedded core, and truncation of the task-owned core entry under verified read-only mounts. It preserves the version directory and Extism entry so the missing-entry test actually reaches SDK compilation rather than merely failing directory creation. These negative tests confirm startup failure, not strict miss handling.

All caches are owner-only task-owned code artifacts. Hashes are not signatures. Do not use untrusted caches or export native blobs to the evidence archive.

## Linux/ARM64 next operator

The Linux runner has now passed live isolated smoke, artifact/cache/tuning screening, and read-only-cache negative cases on the target ARM64 host. Confirmation results are recorded separately from screening. Reproductions should first run one smoke cell, verify health/fresh cgroup/limits/network isolation/metrics, then expand sequentially. Stop for host pressure or privilege problems; never alter the cluster, swap, node page cache or production limits.

Build locally:

```sh
for v in original stripped prune-only prune-dce prune-oz original-oz; do
  python3 benchmarks/footprint/build.py --goos linux --goarch arm64 \
    --artifact benchmarks/footprint/generated/variants-next/$v.wasm \
    --out benchmarks/footprint/generated/linux-next/$v
 done
```

Transfer **only** task binaries, small build metadata and lab scripts; no remote Go needed:

```sh
REMOTE=/var/tmp/op-sdk-footprint-$(date +%Y%m%d-%H%M%S)
SSH='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes'
SCP='scp -o BatchMode=yes -o StrictHostKeyChecking=yes'
$SSH xlange@rpi.lan "mkdir -m 700 '$REMOTE' '$REMOTE/builds'"
$SCP benchmarks/footprint/*.py xlange@rpi.lan:$REMOTE/
for v in original stripped prune-only prune-dce prune-oz original-oz; do
  b=benchmarks/footprint/generated/linux-next/$v
  $SSH xlange@rpi.lan "mkdir -m 700 '$REMOTE/builds/$v'"
  $SCP "$b/probe" "$b/build.json" "$b/overlay.json" "$b/module.go" \
    "$b/extism_core.go" "$b/bench.mod" "$b/bench.sum" "$b/dependency-digests.json" \
    xlange@rpi.lan:$REMOTE/builds/$v/
 done
$SSH xlange@rpi.lan "cd '$REMOTE' && python3 controller.py --systemd \
 --build original='$REMOTE/builds/original' --cache disabled --calls 2 --settle 1s \
 --out '$REMOTE/linux-smoke'"
```

Every measured **and population** process gets a fresh transient cgroup, `User=xlange`, `MemoryMax=512M`, `MemorySwapMax=0`, `CPUQuota=200%`, `LimitCORE=0`, `RuntimeMaxSec=180`, bounded stop, `PrivateNetwork=yes`, `NoNewPrivileges=yes`, owner-only umask. A small Python supervisor lives inside the same cgroup to preserve final `memory.peak/events/stat` after probe exit. Its memory is **included**, so keep identical instrumentation across all cells. Unit names are task-prefixed/unique and collected after exit. Controller rejects missing metrics, pressure events, wrong memory/CPU limits, protocol errors, wrong embedded digest/dependencies, multiple attempts/identities and unexpected guest/stderr outcomes. Population processes have separate raw results and their own cgroups; their work is not hidden inside warm-load peaks.

After accepting the remote smoke, screen all six artifacts with `--cache disabled --warmups 1 --repeats 3 --calls 3 --settle 1s`, then screen cache/tuning combinations separately. Confirm only selected attributable cells with `--warmups 2 --repeats 10 --calls 3 --settle 30s`, including the unmodified baseline. Do not multiply every artifact, mode and settle duration into an unnecessary large campaign. Diagnostic GC/FreeOSMemory, larger malformed input and application memory-limit settings remain separately labeled. Authentication/representative reads and full ESO startup remain blocked; none of these malformed-input jobs substitutes for them.

Archive small evidence on the target, then copy it back for review (do not commit native/cache blobs):

```sh
$SSH xlange@rpi.lan "cd '$REMOTE' && python3 archive.py '$REMOTE/linux-smoke' '$REMOTE/linux-smoke-evidence'"
$SCP -r xlange@rpi.lan:$REMOTE/linux-smoke-evidence benchmarks/footprint/evidence/
```

Keep only reviewed raw evidence/reports and intentional source in Git. Cleanup is limited to units/directories created by this task. Publication remains parent-owned.
