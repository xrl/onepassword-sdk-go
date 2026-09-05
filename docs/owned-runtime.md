# Fork owned runtime and executable cache

This opt-in fork API leaves package-level `onepassword.NewClient` and its global
core unchanged. It does not implement upstream release support or claim private
integration acceptance.

```go
owner, err := onepassword.NewRuntime(onepassword.WithCompilationCache(
    "/var/cache/op-core", onepassword.CompilationCacheRequireHit))
if err != nil { return err }
defer owner.Close(context.Background())
if err := owner.Prepare(ctx); err != nil { return err }
client, err := owner.NewClient(ctx,
    onepassword.WithServiceAccountToken(token),
    onepassword.WithIntegrationInfo("external-secrets", version))
```

`NewRuntime` is lazy and performs no I/O. Without a cache option it uses an owned
in-memory compilation cache. `Prepare` compiles/loads and instantiates the original
embedded core, but does not create a client, authenticate, or make network requests.
Production AllowedHosts remain unchanged. Only `Runtime.NewClient` authenticates;
it rejects desktop options. No credentials, sessions, or secret values are cached
on disk. The API exposes no Extism or Wazero types.

## Ownership and failure

One mutex per runtime serializes loading, init, invoke, release and close. Only a
successful load is published. Failures close the attempt's compilation cache and
can be retried with a fresh cache. There is no automatic read-write fallback.
`Close` waits for active operations; it does **not** cancel them, and the context
cannot interrupt lock acquisition. Callers should finish/cancel their own request
contexts before shutdown. The first Close permanently closes the owner, attempts
plugin then compiled-plugin then cache cleanup, and retains joined cleanup errors
for repeated Close calls. Subsequent calls return `ErrRuntimeClosed`; clients'
late finalizers only reach a guarded no-op release, never a closed plugin.
Clients and extracted API handles must not outlive their runtime's useful life.
Create Runtime through NewRuntime and do not copy it; the zero value is unsupported.

Extism v1.7.1 does not expose a runtime when its compiled-plugin constructor fails.
Closing our per-attempt shared cache releases native compiler mappings and makes
that inaccessible runtime GC-eligible, **not deterministically closed**. Keep the
owned loader on its current no-WASI/no-observer/no-filesystem configuration. On
instance failure, close the compiled plugin before its cache. The global legacy
loader and finalizer policy are otherwise not redesigned.

## Populate separately, require hits at startup

```sh
go build -o op-cache ./cmd/op-cache
./op-cache -directory /trusted/cache -mode populate
./op-cache -directory /trusted/cache -mode verify
```

The credential-free tool defaults to `verify`; `populate` is the only explicit
read-write mode. It prints no guest payloads or credentials. Require-hit needs
existing compatible directories and entries: missing, stale, corrupt, I/O or
unsupported-engine errors fail startup without guest compilation or disk mutation.
Host trampolines and bounded hit preambles are still permitted by the runtime.
These files are **trusted native executable input**, not untrusted portable data:
restrict write access to the population process and mount read-only for consumers.
Do not reuse between unverified versions, targets, CPU feature sets, core artifacts,
compiler options, or toolchains. Concurrent population belongs outside startup.

## ESO integration contract

The reviewed runtime `github.com/xrl/wazero v1.12.0-xrl.0` is published and pinned
with checksums. Its v1.12.0 dependency floor requires `golang.org/x/sys v0.44.0`.
The parent publishes SDK `github.com/xrl/onepassword-sdk-go v0.4.1-xrl.0` only after
SDK review and native CI. ESO must repeat both
replacements in its main module; dependency replacements are not transitive:

```go
replace github.com/1password/onepassword-sdk-go => github.com/xrl/onepassword-sdk-go v0.4.1-xrl.0
replace github.com/tetratelabs/wazero => github.com/xrl/wazero v1.12.0-xrl.0
```

Use Wazero v1.12.0 requirements and Go 1.26.5 for both prewarm and ESO native builds.
The prewarm binary and ESO must resolve the same immutable replacement, compiler
configuration and shipping Wasm digest:
`23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23`.
The runtime replacement version partitions the cache; local replacement `dev`
results are preliminary evidence only, not published cross-binary compatibility.
Create one owner at provider/controller lifetime scope, Prepare with require-hit
before accepting work, route **all opted-in** clients through `owner.NewClient`,
and close only after users stop. Never implicitly retry via global NewClient or
read-write mode. No GOMEMLIMIT, altered Wasm, provider stripping or unrelated
package upgrades are part of this integration.

Fork CI pins Go 1.26.5, runs credential-free tests/race and original-digest checks
on native Linux AMD64/ARM64, builds all packages and compiles integration tests
without executing them, and verifies the tool in fresh processes. Upstream-only
credential workflows are disabled on forks. Real ESO/prewarm cross-binary hits,
native image verification and private integration acceptance remain parent gates.
