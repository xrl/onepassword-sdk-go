# Local tooling smoke (not acceptance measurements)

Go 1.27.1 Darwin/ARM64; one process per cell, no warmups, 64-byte fixed malformed JSON, two repeated invalid invokes, zero settle duration. Primary trials do not force GC. Each warm-rw cell has a separately archived population process. No authenticated data or network calls.

All 18 comparison trials and six population processes completed with expected parser errors, one loader attempt and one core identity. All six distinct runtime embedded digests match their build manifests. Caches are target-specific and warm-rw hit certainty remains unknown. Darwin results must not size Linux cgroups or imply release acceptance.

| Artifact | Mode | Process peak bytes (n=1) | Cache bytes after trial | Outcome certainty |
|---|---|---:|---:|---|
| stripped | disabled | 169410560 | 0 | disabled |
| original-oz | warm-rw | 69156864 | 23461254 | unknown-public-api-no-hit-signal |
| prune-oz | empty | 301776896 | 23461150 | fresh-writable-population |
| original | warm-rw | 78577664 | 26261274 | unknown-public-api-no-hit-signal |
| prune-only | warm-rw | 77905920 | 26261274 | unknown-public-api-no-hit-signal |
| original-oz | disabled | 271335424 | 0 | disabled |
| prune-dce | warm-rw | 73793536 | 26132106 | unknown-public-api-no-hit-signal |
| prune-dce | empty | 190644224 | 26132106 | fresh-writable-population |
| original-oz | empty | 301563904 | 23461254 | fresh-writable-population |
| original | disabled | 173277184 | 0 | disabled |
| prune-only | empty | 193052672 | 26261274 | fresh-writable-population |
| prune-only | disabled | 174555136 | 0 | disabled |
| stripped | warm-rw | 74399744 | 26261274 | unknown-public-api-no-hit-signal |
| stripped | empty | 197263360 | 26261274 | fresh-writable-population |
| original | empty | 200671232 | 26261274 | fresh-writable-population |
| prune-oz | warm-rw | 68534272 | 23461150 | unknown-public-api-no-hit-signal |
| prune-oz | disabled | 285605888 | 0 | disabled |
| prune-dce | disabled | 170868736 | 0 | disabled |

Independent archive check: 24 distinct PIDs across 18 trials and six population processes; main memory 62 pages at core-ready and 63 after malformed init, kernel memory 16 pages throughout live checkpoints. Pages are Go-heap subsets, not additive RSS buckets.

Separate [GC + 1-MiB bounded malformed input diagnostic](diagnostic-gc/summary.json), [FreeOSMemory diagnostic](diagnostic-free/summary.json), and [idle-only raw checkpoints](idle/stdout.jsonl) passed. These are not pooled with primary comparisons. No immediate-close result proves lifecycle reclamation.

The [artifact accounting](artifacts/report.md) demonstrates that original+Oz retains 4,555 bodies versus prune+Oz 4,554. Descriptor removal is not credited for the general Oz reduction. Fresh Linux cgroup confirmation and private integration remain required.

Source, exact commands, build/overlay/dependency fingerprints, raw samples, stderr/exit status, cache-file digests and host state are in [the campaign archive](smoke/archive.json). Native binaries, dependency copies, and cache blobs are intentionally excluded; rebuild from the checked-in generators. The manifests identify initial source HEAD plus dirty file hashes because this source/evidence commit was made after experiments. Archived `.go.txt` files are the actual overlay generation outputs, not compilable SDK packages.
