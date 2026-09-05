# Generated artifact report

Generator: `python3 benchmarks/footprint/artifacts.py --out benchmarks/footprint/generated/variants`.
Shipping artifact untouched. Only descriptor exports removed; full private integration remains required.

| Artifact | Bytes | Bodies | Exports | Code bytes | Data bytes | SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| original | 9509477 | 9537 | 1759 | 5233016 | 2983333 | 23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23 |
| stripped | 8330390 | 9537 | 1759 | 5233016 | 2983333 | 6225844ca49530fa7276bf4e3a3c206d1d20947337c0c75e3d0e7b4eaa013f2f |
| prune-only | 9411364 | 9537 | 18 | 5233016 | 2983333 | d3f2ef3068e8fb8230e3c61da80a5b4cac0a0e8ade10dd4a77cf5632fa03e408 |
| prune-dce | 8375886 | 8485 | 18 | 5170135 | 2983333 | 186fe383fc9bfa7a594c8f11ed56a590ef20d84363b01c757eeccfc22639ec49 |
| prune-oz | 7540521 | 4554 | 18 | 4373537 | 2948059 | b8d2b56077402f9ae63182d7ba5e00042d641b20fa38b604f4cfaac34cdfb113 |
| original-oz | 7638637 | 4555 | 1759 | 4373541 | 2948059 | d6c8db3365c14b16cdbdb5d9106d607e5bfaf6efcaef89abda40e31f680d0d93 |
