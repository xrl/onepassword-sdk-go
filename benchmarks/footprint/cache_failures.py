#!/usr/bin/env python3
"""Credential-free, read-only-cache negative cases; not a require-hit implementation."""
import argparse
import json
from pathlib import Path
import platform
from controller import cache_inventory, digest, host, run_process, validate, write


def run(original, stale, out):
    if platform.system() != 'Linux':
        raise RuntimeError('run on Linux target with the bounded systemd runner')
    builds = {}
    for key, path in [('original', original.resolve()), ('stale', stale.resolve())]:
        info = json.loads((path / 'build.json').read_text())
        if digest(path / 'probe') != info['binary_sha256']:
            raise ValueError('binary digest mismatch')
        builds[key] = (path, info)
    if builds['original'][1]['artifact_sha256'] == builds['stale'][1]['artifact_sha256']:
        raise ValueError('stale case requires a different embedded module')
    out = out.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    write(out / 'manifest.json', {'host': host(), 'builds': {key: info for key, (_, info) in builds.items()},
                                 'source_sha256': {name: digest(Path(__file__).parent / name) for name in ['cache_failures.py', 'controller.py', 'linux_trial.py']},
                                 'cases': ['missing-core-entry', 'different-core', 'truncated-core-entry']})
    results = []
    for case in ['missing-core-entry', 'different-core', 'truncated-core-entry']:
        cache = out / ('cache-' + case)
        cache.mkdir(mode=0o700)
        base_path, base_info = builds['original']
        samples, code, cg, decode_error = run_process(out / ('populate-' + case), base_path / 'probe',
                                                      ['--cache=' + str(cache), '--calls=0', '--settle=0'], True, memory_limit='off')
        population_errors = validate(samples, code, base_info['artifact_sha256'], 0, 'none', cg)
        if decode_error or population_errors or cg is None:
            raise RuntimeError('population failed: ' + str((decode_error, population_errors)))
        before = cache_inventory(cache)
        entry_name = max(before, key=lambda name: before[name]['bytes'])
        entry = cache / entry_name
        # No private-format parsing: manipulate only this task's newly populated largest file.
        if case == 'missing-core-entry':
            entry.unlink()
        elif case == 'truncated-core-entry':
            with entry.open('r+b') as file:
                file.truncate(entry.stat().st_size // 2)
        test_path, test_info = builds['stale' if case == 'different-core' else 'original']
        mutated = cache_inventory(cache)
        directory = out / case
        samples, code, cg, decode_error = run_process(directory, test_path / 'probe',
                                                      ['--cache=' + str(cache), '--calls=0', '--settle=0', '--acquisitions=1'],
                                                      True, readonly_cache=cache, memory_limit='off')
        stderr = (directory / 'stderr.txt').read_text() if (directory / 'stderr.txt').exists() else ''
        after = cache_inventory(cache)
        errors = []
        if decode_error or [sample.get('stage') for sample in samples] != ['baseline-ready', 'load-error']:
            errors.append('unexpected failure protocol')
        if code == 0 or 'failed to initialize plugin:' not in stderr:
            errors.append('expected startup failure missing')
        expected = 'unexpected EOF' if case == 'truncated-core-entry' else 'read-only file system'
        if expected.lower() not in stderr.lower():
            errors.append('wrong startup error')
        if not cg or not cg.get('readonly_cache', {}).get('verified'):
            errors.append('read-only mount unverified')
        if before == {} or after != mutated:
            errors.append('cache inventory mismatch')
        if samples and (samples[-1].get('load_attempts') != 1 or samples[-1].get('identities') != []):
            errors.append('unexpected loader/identity count')
        limits = (cg or {}).get('cgroup_after', {})
        if limits.get('memory.max', '').strip() != '536870912' or limits.get('memory.swap.max', '').strip() != '0':
            errors.append('cgroup limits mismatch')
        events = dict(line.split() for line in limits.get('memory.events', '').splitlines())
        if not events or any(int(events.get(key, 0)) != 0 for key in ['max', 'oom', 'oom_kill']):
            errors.append('missing events or memory pressure')
        result = {'case': case, 'exit_code': code, 'invalid_reasons': errors, 'tested_artifact_sha256': test_info['artifact_sha256'],
                  'cache_before_mutation': before, 'cache_after_mutation': mutated, 'cache_after_trial': after,
                  'cgroup_peak_bytes': int(limits.get('memory.peak', '0')), 'expected_error_fragment': expected,
                  'raw_sha256': {p.name: digest(p) for p in directory.iterdir() if p.is_file()}}
        results.append(result)
        write(out / 'results.json', results)
    write(out / 'host-after.json', host())
    print(json.dumps(results, indent=2))
    return int(any(result['invalid_reasons'] for result in results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--stale', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.original, args.stale, args.out))
