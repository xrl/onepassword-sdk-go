# Historical evidence (unmodified archive)

The four exploratory probes were run on Darwin/ARM64 before this lab. **Their source was not preserved.** `.out`, `.time`, and `results.tsv` are original raw evidence, not regenerated numbers and not reproducible experiments. Native binaries and compilation-cache blobs are deliberately excluded. `archive.json` records original paths, sizes, and SHA-256. Historical commands embedded in `.time` are provenance only, not runnable instructions.

The P0 report, raw CSV, manifest and protocol are copied unchanged from the prior controlled synchronization campaign. Its complete source/runs remain in the original campaign directory named in the manifest; this is a small relevant excerpt, not a full P0 reproduction archive. Original report/protocol references to omitted files are historical, not claims those files are included here.

Interpret old measurements using the [corrected accounting](../../../../docs/memory/onepassword-sdk-go-footprint-reduction-spec.md): both WASM memories are Go-heap allocations with the default allocator; `Plugin.Memory()` is the Extism kernel, not SDK main memory; cache loading eagerly copies and CRC-checks all native code. No lazy executable-page explanation is supported. Authentication and ESO acceptance remain blocked.
