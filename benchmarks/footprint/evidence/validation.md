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

All passed: 13 Python tests, ordinary SDK internal tests, package compilation, and module checksum verification. The `-run '^$'` command compiles integration tests but does not execute them or claim authenticated acceptance.

The initial worker separately passed P0 race tests and the overlay-only real-loader/page/error/retry tests under `-race`; final exact-command validation will be recorded after the campaign. The shipping `TestLoadWASM` is run without the overlay, because its host-allowlist assertion intentionally differs from the benchmark's deny-all-hosts configuration.

## Measurement controls added after initial smoke

New campaigns explicitly set and validate `GOMAXPROCS=2`, retain `GOGC=100`, and record application `GOMEMLIMIT` per cell. Old smoke data used the earlier protocol and is not pooled with them. Read-only Linux cache trials must first observe `EROFS` from an attempted creation of a task-owned check file; permission errors do not qualify. Host names and CPU serials are excluded from new host metadata.

Shipping WASM, ordinary SDK code, `go.mod`, and `go.sum` remain unchanged from the P0 base. Generated dependency copies, overlaid sources, executables and native caches are excluded from Git; their recipes and small provenance records are retained.
