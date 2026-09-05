#!/usr/bin/env python3
"""Verify bundled raw evidence and regenerate the credential-free campaign report."""
import hashlib
import json
from pathlib import Path
import tarfile
from controller import summary, validate

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'
CASES = ['linux-smoke', 'linux-screen-artifacts', 'linux-screen-caches', 'linux-screen-tuning',
         'linux-confirmation', 'linux-cache-negative', 'darwin-screen', 'darwin-confirmation']


def load_case(name):
    directory = EVIDENCE / name
    metadata = json.loads((directory / 'bundle.json').read_text())
    packed = directory / 'raw.tar.gz'
    assert hashlib.sha256(packed.read_bytes()).hexdigest() == metadata['sha256'], name
    with tarfile.open(packed) as tar:
        members = tar.getmembers()
        assert len(members) == metadata['members'] and all(m.isfile() for m in members), name
        files = {m.name: tar.extractfile(m).read() for m in members}
    archive = json.loads(files['archive.json'])
    for path, record in archive.items():
        assert hashlib.sha256(files[path]).hexdigest() == record['sha256'], (name, path)
    for path in ['manifest.json', 'summary.json', 'trials.json', 'results.json']:
        if (directory / path).exists():
            assert (directory / path).read_bytes() == files[path], (name, path)
    return files


def audit(name, files):
    if 'trials.json' not in files:
        results = json.loads(files['results.json'])
        assert len(results) == 3 and all(not r['invalid_reasons'] and r['exit_code'] != 0 for r in results)
        for result in results:
            prefix = result['case'] + '/'
            for path, expected in result['raw_sha256'].items():
                assert hashlib.sha256(files[prefix + path]).hexdigest() == expected
            cg = json.loads(files[prefix + 'linux.json'])
            assert cg['readonly_cache']['verified'] and int(cg['cgroup_after']['memory.peak']) == result['cgroup_peak_bytes']
            assert result['expected_error_fragment'].lower() in files[prefix + 'stderr.txt'].decode().lower()
            assert result['cache_after_trial'] == result['cache_after_mutation']
        return {'negative_cases': len(results), 'processes': sum(p.endswith('/stdout.jsonl') for p in files)}
    manifest = json.loads(files['manifest.json'])
    options = manifest['options']
    trials = json.loads(files['trials.json'])
    assert len(trials) == len(manifest['order']), name
    assert summary(trials) == json.loads(files['summary.json']), name
    for trial, planned in zip(trials, manifest['order']):
        for key in ['cell', 'phase', 'round']:
            assert trial[key] == planned[key], (name, trial['id'])
        prefix = trial['id'] + '/'
        samples = [json.loads(line) for line in files[prefix + 'stdout.jsonl'].splitlines()]
        linux = json.loads(files[prefix + 'linux.json']) if prefix + 'linux.json' in files else None
        build = trial['cell'].split(':')[0]
        info = json.loads(files['builds/' + build + '/build.json'])
        assert validate(samples, trial['exit_code'], info['artifact_sha256'], options['calls'], options['diagnostic'], linux) == [], (name, trial['id'])
        assert not trial['invalid_reasons'], (name, trial['id'])
        for path, expected in trial['raw_sha256'].items():
            assert hashlib.sha256(files[prefix + path]).hexdigest() == expected, (name, prefix + path)
        if linux:
            assert trial['metrics']['cgroup_peak_bytes'] == int(linux['cgroup_after']['memory.peak'])
        assert trial['metrics']['process_peak_bytes'] == max(s['process']['peak_rss_bytes'] for s in samples)
        settled = next(s for s in samples if s['stage'] == 'settled')
        last_call = next(s for s in reversed(samples) if s['stage'].startswith('invalid-'))
        assert settled['elapsed_ns'] - last_call['elapsed_ns'] >= float(options['settle'].removesuffix('s')) * 1e9
        assert not files[prefix + 'stderr.txt']
        assert trial['metrics']['settled_rss_bytes'] == settled['process'].get('rss_bytes', settled['process'].get('status_VmRSS_bytes'))
        if trial['cell'].endswith(':warm-ro'):
            assert linux['readonly_cache']['verified'] and trial['cache_before'] == trial['cache_after'] and trial['cache_before']
            assert trial['cache_certainty'] == 'known-hit-pinned-version-success-readonly-unchanged'
    processes = []
    groups = []
    for path, data in files.items():
        if path.endswith('/stdout.jsonl'):
            first = json.loads(data.splitlines()[0])
            assert first['stage'] == 'baseline-ready' and first['process']['gomaxprocs'] == 2
            processes.append(first['process']['pid'])
            if path.startswith('populate-'):
                prefix = path.removesuffix('stdout.jsonl')
                trial_id = prefix.removeprefix('populate-').rstrip('/')
                trial = next(t for t in trials if t['id'] == trial_id)
                build = trial['cell'].split(':')[0]
                info = json.loads(files['builds/' + build + '/build.json'])
                population = [json.loads(line) for line in data.splitlines()]
                cg = json.loads(files[prefix + 'linux.json']) if prefix + 'linux.json' in files else None
                assert validate(population, cg['exit_code'] if cg else 0, info['artifact_sha256'], 0, 'none', cg) == []
                assert not files[prefix + 'stderr.txt']
        if path.endswith('/linux.json'):
            groups.append(json.loads(data)['cgroup_after']['path'])
    assert len(processes) == len(set(processes)), (name, 'PID reuse')
    assert len(groups) == len(set(groups)), (name, 'cgroup reuse')
    return {'measured': sum(t['phase'] == 'measured' for t in trials),
            'warmups': sum(t['phase'] == 'warmup' for t in trials),
            'population': sum(p.startswith('populate-') and p.endswith('/stdout.jsonl') for p in files),
            'processes': len(processes), 'unexpected_failures': 0}


def metric(rows, cell, key, stat='median'):
    return rows[cell]['metrics'][key][stat]


def main():
    files = {name: load_case(name) for name in CASES}
    checks = {name: audit(name, data) for name, data in files.items()}
    linux = json.loads(files['linux-confirmation']['summary.json'])
    darwin = json.loads(files['darwin-confirmation']['summary.json'])
    tuning = json.loads(files['linux-screen-tuning']['summary.json'])
    cold = metric(linux, 'original:disabled', 'cgroup_peak_bytes')
    warm = metric(linux, 'original:warm-ro', 'cgroup_peak_bytes')
    optimized = metric(linux, 'prune-oz:warm-ro', 'cgroup_peak_bytes')
    labels = {'original:disabled': 'Original / no cache', 'prune-dce:disabled': 'Prune + DCE / no cache',
              'prune-oz:disabled': 'Prune + Oz / no cache', 'original:warm-ro': 'Original / warm RO',
              'original-oz:warm-ro': 'Original + Oz / warm RO', 'prune-oz:warm-ro': 'Prune + Oz / warm RO'}
    lines = ['# SDK footprint experiment: confirmed Linux/ARM64 results', '',
             '**Credential-free core/parser measurements, not authenticated SDK or ESO acceptance. No shipping WASM, ordinary SDK behavior, production dependency, or cluster limit changed.**', '',
             '## Decision', '',
             f'- **Prioritize a trusted precompiled cache:** original core median cgroup peak {cold/1048576:.2f} → {warm/1048576:.2f} MiB (**{(1-warm/cold)*100:.1f}% lower**).',
             f'- **Cache + Oz is a secondary experiment:** {optimized/1048576:.2f} MiB (**{(1-optimized/cold)*100:.1f}% lower** than original cold). This is not a safe cold-start configuration.',
             '- **Do not ship `-Oz` as an uncached memory fix.** Despite halving function bodies, its uncached peak is about 64% higher. Removing descriptor exports alone is negligible; prune+DCE saves only about 2.5% of peak, below the 20% slim-core memory gate.',
             '- **Do not force a small `GOMEMLIMIT` into the SDK/controller as the main fix.** This screening saved only about 10–11% of cold peak with substantially more GC and 2–3× startup cost.', '',
             '## Linux confirmation', '',
             'Ten measured fresh processes plus two warmups per cell, interleaved (seed 285). Each performs one malformed `init_client`, three malformed `invoke` calls, then settles for 30 seconds without forced GC. Every acquisition wave has one loader attempt and one core identity.', '',
             '| Configuration | Cgroup peak median / max MiB | Core-ready cgroup peak MiB | 30s process RSS MiB | Core-ready seconds |',
             '|---|---:|---:|---:|---:|']
    for cell, label in labels.items():
        lines.append(f"| {label} | {metric(linux,cell,'cgroup_peak_bytes')/1048576:.2f} / {metric(linux,cell,'cgroup_peak_bytes','max')/1048576:.2f} | {metric(linux,cell,'core-ready_cgroup_peak_bytes')/1048576:.2f} | {metric(linux,cell,'settled_rss_bytes')/1048576:.2f} | {metric(linux,cell,'core-ready_operation_ns')/1e9:.3f} |")
    lines += ['', 'Ranges, maxima, CPU time, allocation/GC statistics, malformed-call latency, page counts and individual failures are retained in [summary](linux-confirmation/summary.json), [trials](linux-confirmation/trials.json), [manifest/order](linux-confirmation/manifest.json) and the [byte-exact raw bundle](linux-confirmation/raw.tar.gz). With n=10, a nearest-rank p95 is the maximum; these data do not establish rare-tail behavior.', '',
              'SDK main memory is 62 pages at core-ready and 63 after these parser calls; Extism kernel memory is 16 pages. These are separate 64-KiB logical WASM pages, both backed by Go heap, **not additive RSS categories**. The native cache is about 25.0 MiB for the original core plus kernel, and 22.4 MiB for either Oz variant.', '',
              '### Artifact attribution', '',
              'Original+Oz has 4,555 bodies and prune+Oz 4,554; their native caches differ by only 104 bytes. Their warm-cache results are close. Almost all body-count reduction comes from general Binaryen optimization/merging, not descriptor removal. The immutable shipping artifact is still 9,509,477 bytes with its original SHA-256. See [artifact ABI/size report](artifacts/report.md). Smaller input/function count did not predict a smaller compiler working set; allocation profiles are needed before attributing the regression to a specific Wazero compiler hotspot.', '',
              '## Cache population and failure cases', '',
              'Three measured processes plus one warmup per screening cell: original empty-cache median peak was about 195 MiB, versus about 154 MiB with caching disabled. Oz empty-cache peaks were about 291–292 MiB. A cache miss is not a low-memory mode. See [cache screening](linux-screen-caches/summary.json).', '',
              'Read-only mounts were independently checked using `EROFS`, not merely file permissions. A successful pinned-version load with unchanged populated entries establishes a known hit; this does **not** implement a supported strict/require-hit API. Three negative cases, each in its own fresh no-swap cgroup, passed their expected-error contract:', '',
              '| Negative case (n=1 each) | Cgroup peak MiB | Result |', '|---|---:|---|']
    for row in json.loads(files['linux-cache-negative']['results.json']):
        lines.append(f"| {row['case']} | {row['cgroup_peak_bytes']/1048576:.2f} | Startup error, one loader attempt, no published core |")
    lines += ['', 'The missing/different-core cases compiled and reached the cache write error; a read-only mount alone cannot protect a small container from the compilation peak. Truncation failed during cache reading. Files were selected by size and removed/truncated only in task-owned caches; no private Wazero format was parsed. [Results](linux-cache-negative/results.json), [raw errors and cgroups](linux-cache-negative/raw.tar.gz).', '',
              '## Go memory-limit screening', '',
              'Three measured processes plus one warmup per cell; 1-second settling. Same original-artifact probe binary, GOMAXPROCS=2, GOGC=100, cgroup limit 512 MiB and swap disabled. These cells are not pooled with the 30-second confirmation.', '',
              '| Original, uncached GOMEMLIMIT | Cgroup peak MiB | Core-ready seconds | GC cycles by settled |', '|---|---:|---:|---:|']
    for alias, limit in [('original','off'),('original32','32 MiB'),('original48','48 MiB'),('original64','64 MiB'),('original96','96 MiB')]:
        cell=alias+':disabled'
        lines.append(f"| {limit} | {metric(tuning,cell,'cgroup_peak_bytes')/1048576:.2f} | {metric(tuning,cell,'core-ready_operation_ns')/1e9:.3f} | {metric(tuning,cell,'settled_NumGC'):.0f} |")
    lines += ['', 'Go cannot collect the live compiler working set, and GOMEMLIMIT is soft. A small limit greatly increased GC without eliminating the cold peak. Warm-cache results changed little with these settings. A full controller has a different process-wide live heap: these SDK-only values are not recommended ESO settings. [All tuning cells](linux-screen-tuning/summary.json).', '',
              '## Darwin confirmation (developer signal)', '',
              'Ten measured processes plus two warmups per cell, same malformed operations and 30-second settling. Warm read-write cache outcomes remain unknown through the public Wazero API, unlike the independently verified Linux read-only hits.', '',
              '| Configuration | Process peak median / max MiB | Core-ready seconds |', '|---|---:|---:|']
    for cell in ['original:disabled','prune-oz:disabled','original:warm-rw','prune-oz:warm-rw']:
        lines.append(f"| {cell} | {metric(darwin,cell,'process_peak_bytes')/1048576:.2f} / {metric(darwin,cell,'process_peak_bytes','max')/1048576:.2f} | {metric(darwin,cell,'core-ready_operation_ns')/1e9:.3f} |")
    lines += ['', '[Darwin summary](darwin-confirmation/summary.json), [raw bundle](darwin-confirmation/raw.tar.gz). Do not use Darwin RSS for Kubernetes sizing.', '',
              '## Scope, controls, and remaining gates', '',
              '- Go 1.27.1, Extism 1.7.1, Wazero 1.11.0, wasm-tools 1.236.1 and Binaryen 132. Each binary genuinely re-embeds its reported artifact via the documented build overlay; manifests record source commit, dirty state, all input/dependency/overlay digests and binary hashes. Shipping files and module cache are not modified.',
              '- Linux: target Raspberry Pi-class ARM64, kernel 6.12.47+rpt-rpi-2712, 16-KiB OS pages, fresh systemd cgroup for **every** measured, warmup and population process; 512-MiB memory max, no swap, two-core CPU quota, GOMAXPROCS=2, denied network and core dumps. A small Python supervisor is included in cgroup peak, identically across cells.',
              '- Cgroup memory and process RSS are different accounting views. File-backed pages may already be charged elsewhere; the anonymous executable segment is copied eagerly in full. Population and hashing first-touch cache files outside the measured application cgroup. These are **prewarmed-file-cache** measurements, not cold-node image/page-cache acceptance. No global cache purge or swap change was made.',
              '- Only checkpoints are sampled; kernel cgroup high-water is authoritative. No primary heap profiles or forced GC. Thirty-second idle/parser RSS is not proof of authenticated active-core floor or indefinite steady state; normal application GC and Linux pressure can reclaim compiler working allocations.',
              '- Valid authentication, representative secret reads/payloads, cancellation/rotation, full private compatibility suites, Linux AMD64 measurements, cold-node cache accounting, and the exact ESO image’s 20-start/soak gate remain **not run / blocked**. The controller keeps its existing 512-MiB limit.',
              '- Next implementation: pursue supported Wazero require-hit/outcome hooks and runtime-scoped cache ownership (P1 dependency), then explicitly wire the ESO provider to that runtime. Validate the original artifact first with a dedicated private fixture; test Oz separately only if the additional ~8 MiB justifies its worse miss peak and compatibility risk. Do not silently configure the default global client or ship an unverified artifact.', '',
              '## Reproduction and integrity', '',
              'Use [the lab README](../README.md) and the exact option/order manifests. Run `python3 benchmarks/footprint/report.py` to revalidate archive digests, raw-to-summary peak/RSS arithmetic, protocol, source artifact identity, read-only hits and fresh PID/cgroup identities, then regenerate this report. `bundle.py` stores byte-exact text evidence with deterministic gzip metadata; no native cache or executable blobs are checked in.', '',
              '| Dataset | Measured | Warmups | Population | Total processes |', '|---|---:|---:|---:|---:|']
    for name, count in checks.items():
        lines.append(f"| {name} | {count.get('measured',count.get('negative_cases',0))} | {count.get('warmups',0)} | {count.get('population',3 if 'negative_cases' in count else 0)} | {count['processes']} |")
    lines += ['', 'All completed primary/screening/warmup trials were protocol-valid; the three negative cache processes exited nonzero as expected. Historical exploratory and initial tooling-smoke data are archived separately with their limitations and are not pooled into these campaigns.', '']
    (EVIDENCE / 'campaign-report.md').write_text('\n'.join(lines))
    (EVIDENCE / 'campaign-audit.json').write_text(json.dumps(checks, indent=2) + '\n')
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
