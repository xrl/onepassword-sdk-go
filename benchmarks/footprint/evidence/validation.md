# Tooling validation

Credential-free only. No authenticated integration or live ESO acceptance was run.

The initial tooling worker reached its orchestration timeout after saving source and successful tests, before committing/reporting. The parent inspected the complete worktree and resumed directly; no completed historical/smoke dataset was relabeled as a new campaign.

## Parent-verified checks

From repository root, Go 1.27.1 Darwin/ARM64:

```sh
PYTHONPATH=benchmarks/footprint python3 -m unittest discover -s benchmarks/footprint/tests -v
GOPROXY=off GOTOOLCHAIN=local go test ./internal
GOPROXY=off GOTOOLCHAIN=local go test ./... -run '^$'
GOPROXY=off GOTOOLCHAIN=local go mod verify
```

All passed: 15 Python tests, ordinary SDK internal tests, package compilation, and module checksum verification. The `-run '^$'` command compiles integration tests but does not execute them or claim authenticated acceptance.

The parent also passed the exact P0 and overlay race commands below. The planned independent child methodology/final-review stages did not run after tooling timed out; this is parent source review and evidence replay, not an independent compatibility approval. The shipping `TestLoadWASM` is run without the overlay, because its host-allowlist assertion intentionally differs from the benchmark's deny-all-hosts configuration.

## Measurement controls added after initial smoke

New campaigns explicitly set and validate `GOMAXPROCS=2`, retain `GOGC=100`, and record application `GOMEMLIMIT` per cell. Old smoke data used the earlier protocol and is not pooled with them. Read-only Linux cache trials must first observe `EROFS` from an attempted creation of a task-owned check file; permission errors do not qualify. Host names and CPU serials are excluded from new host metadata.

Shipping WASM, ordinary SDK code, `go.mod`, and `go.sum` remain unchanged from the P0 base. Generated build trees, full copied dependencies, executables and native caches are excluded from Git. Overlay diffs/source snapshots and provenance are retained as non-compilable text in raw evidence.

## Final campaign validation

Both Linux and Darwin campaign binaries were built from clean commit `ca21b38cd6c4359d1898a30b79c771e9b7ce52ff`. Build manifests retain exact source, dependency, overlay and binary hashes. Post-campaign changes package/replay evidence, update documentation and force offline/local-toolchain behavior for build metadata lookups; they do not alter the measured Go probe or shipping runtime.

Additional commands, all passed:

```sh
GOPROXY=off GOTOOLCHAIN=local go test -race ./internal -run 'Test(GetExtismCore|ReleaseCore)'
b=benchmarks/footprint/generated/darwin-campaign/original
GOPROXY=off GOTOOLCHAIN=local go test -race -modfile="$b/bench.mod" \
  -overlay="$b/overlay.json" -tags=footprint ./internal ./benchmarks/footprint/cmd/probe \
  -run 'Test(Footprint|GetExtismCore|ReleaseCore|ExpectedInvalid)'
python3 benchmarks/footprint/report.py
```

Replay verifies bundled member digests, manifest trial order, raw-to-summary peak/RSS arithmetic, actual settle duration, protocol/loader identity, read-only cache immutability/EROFS, and distinct process/cgroup identities. All **357** new campaign processes are retained, including warmups/population and three expected negative exits. They are not pooled with legacy evidence.

The shipping WASM SHA-256 remains `23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23`. No production credentials, Secrets or Kubernetes changes were made; the live controller limit remains 512 MiB. Authenticated SDK/ESO acceptance and a supported strict-cache API remain open gates.
