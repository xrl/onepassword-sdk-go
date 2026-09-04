#!/usr/bin/env python3
"""Sequential fresh-process comparisons, never a release gate on developer smoke data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import random
import shutil
import statistics
import subprocess
import time

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def cache_inventory(directory):
    return {str(p.relative_to(directory)): {'sha256': digest(p), 'bytes': p.stat().st_size}
            for p in sorted(directory.rglob('*')) if p.is_file()}


def order(cells, repeats, warmups, seed):
    rng = random.Random(seed)
    result = []
    for phase, count in [('warmup', warmups), ('measured', repeats)]:
        for round_number in range(count):
            block = list(cells)
            rng.shuffle(block)
            result.extend(dict(cell=cell, phase=phase, round=round_number) for cell in block)
    return result


def validate(samples, exit_code, expected_sha, calls, diagnostic, linux=None):
    reasons = []
    if not isinstance(samples, list) or any(not isinstance(s, dict) for s in samples):
        return ['invalid sample structure']
    for sample in samples:
        if (not isinstance(sample.get('stage'), str)
                or any(type(sample.get(k)) is not int for k in ['elapsed_ns', 'expected_errors', 'unexpected_errors', 'load_attempts', 'main_pages', 'kernel_pages'])
                or not isinstance(sample.get('identities'), list)
                or not isinstance(sample.get('process'), dict)
                or not isinstance(sample.get('go'), dict)
                or type(sample.get('go', {}).get('HeapAlloc')) is not int):
            return ['invalid checkpoint schema']
    expected_stages = ['baseline-ready', 'core-ready', 'invalid-init'] + ['invalid-invoke'] * calls + ['settled']
    if diagnostic != 'none':
        expected_stages.append('diagnostic')
    expected_stages.append('closed')
    if exit_code != 0:
        reasons.append('nonzero exit: ' + str(exit_code))
    if [s.get('stage') for s in samples] != expected_stages:
        reasons.append('checkpoint protocol mismatch')
    if not samples:
        return reasons + ['no samples']
    previous_time = -1
    previous_errors = 0
    identity = None
    for sample in samples:
        stage = sample.get('stage')
        if sample.get('elapsed_ns', -1) < previous_time:
            reasons.append('nonmonotonic time')
        previous_time = sample.get('elapsed_ns', -1)
        if sample.get('unexpected_errors') != 0:
            reasons.append('unexpected guest/load outcome')
        if stage == 'baseline-ready':
            if sample.get('dependencies') != {'github.com/extism/go-sdk': 'v1.7.1', 'github.com/tetratelabs/wazero': 'v1.11.0'}:
                reasons.append('runtime dependency identity mismatch')
            if sample.get('load_attempts') != 0 or sample.get('identities') != []:
                reasons.append('baseline already loaded')
        else:
            if sample.get('embedded_sha256') != expected_sha:
                reasons.append('embedded digest mismatch')
            ids = sample.get('identities', [])
            if sample.get('load_attempts') != 1 or len(ids) != 1:
                reasons.append('P0 loader/identity invariant')
            elif identity is not None and identity != ids[0]:
                reasons.append('identity changed')
            elif ids:
                identity = ids[0]
        if stage in ['invalid-init', 'invalid-invoke']:
            previous_errors += 1
            if not sample.get('error_sha256'):
                reasons.append('missing expected error fingerprint')
        if sample.get('expected_errors') != previous_errors:
            reasons.append('expected error count mismatch')
        process = sample.get('process', {})
        if process.get('gomaxprocs') != 2:
            reasons.append('GOMAXPROCS mismatch')
        if not process.get('peak_rss_bytes') or not ('rss_bytes' in process or 'status_VmRSS_bytes' in process):
            reasons.append('missing process metrics')
        if any(k.endswith('_error') for k in process):
            reasons.append('process metric read error')
        if stage not in ['baseline-ready', 'closed'] and (sample.get('main_pages', 0) <= 0 or sample.get('kernel_pages', 0) <= 0):
            reasons.append('missing module pages')
        if process.get('os') == 'linux':
            cg = sample.get('cgroup', {})
            if any(not cg.get(k) or cg[k].startswith('ERROR') for k in ['memory.current', 'memory.peak', 'memory.events', 'memory.stat']):
                reasons.append('missing cgroup metrics')
    if linux is not None:
        cg = linux.get('cgroup_after', {})
        if cg.get('memory.max', '').strip() != '536870912' or cg.get('memory.swap.max', '').strip() != '0':
            reasons.append('cgroup limits mismatch')
        cpu = cg.get('cpu.max', '').split()
        if len(cpu) != 2 or not all(v.isdigit() for v in cpu) or int(cpu[0]) != 2 * int(cpu[1]):
            reasons.append('cgroup CPU quota mismatch')
        for key, value in (line.split() for line in cg.get('memory.events', '').splitlines()):
            if key in ['oom', 'oom_kill', 'max'] and int(value) != 0:
                reasons.append('cgroup pressure event: ' + key)
    return sorted(set(reasons))


def summary(trials):
    result = {}
    for trial in trials:
        if trial['phase'] != 'measured':
            continue
        cell = trial['cell']
        group = result.setdefault(cell, {'valid': 0, 'failures': [], 'metrics': {}})
        if trial['invalid_reasons']:
            group['failures'].append({'trial': trial['id'], 'reasons': trial['invalid_reasons']})
            continue
        group['valid'] += 1
        for metric, value in trial['metrics'].items():
            group['metrics'].setdefault(metric, []).append(value)
    for group in result.values():
        for metric, values in group['metrics'].items():
            group['metrics'][metric] = dict(median=statistics.median(values), min=min(values), max=max(values), range=max(values)-min(values), n=len(values))
    return result


def host():
    uname = list(platform.uname())
    uname[1] = 'benchmark-host'
    result = dict(platform=platform.platform(), uname=uname, cpu_count=os.cpu_count(), page_bytes=os.sysconf('SC_PAGE_SIZE'), load=os.getloadavg())
    for path in ['/proc/meminfo', '/proc/cpuinfo', '/proc/swaps', '/proc/pressure/memory']:
        if Path(path).exists():
            result[path] = '\n'.join(line for line in Path(path).read_text().splitlines()
                                     if not line.lower().startswith('serial')) + '\n'
    result['page_cache_protocol'] = 'Uncontrolled host cache; no purge. Per-cell fresh directory, warm population reads whole cache files to hash them before trial. Anonymous executable mappings remain separate from file cache.'
    return result


def run_process(directory, binary, args, systemd, readonly_cache=None, memory_limit=None):
    directory.mkdir(mode=0o700)
    command = [str(binary), *args]
    env = dict(PATH=os.defpath, GOMEMLIMIT=memory_limit or os.environ.get('GOMEMLIMIT', 'off'),
               GOMAXPROCS='2', GOGC='100', GOTRACEBACK='none')
    # Never record the inherited environment; it could contain unrelated credentials.
    if systemd:
        command = ['sudo', '-n', 'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                   '--unit=op-sdk-footprint-' + directory.name + '-' + str(os.getpid()),
                   '--property=User=' + pwd.getpwuid(os.getuid()).pw_name, '--property=MemoryMax=512M', '--property=MemorySwapMax=0',
                   '--property=CPUQuota=200%', '--property=LimitCORE=0', '--property=RuntimeMaxSec=180',
                   '--property=TimeoutStopSec=5', '--property=KillMode=control-group',
                   '--property=PrivateNetwork=yes', '--property=NoNewPrivileges=yes', '--property=UMask=0077',
                   '--setenv=GOMEMLIMIT=' + env['GOMEMLIMIT'], '--setenv=GOMAXPROCS=2', '--setenv=GOTRACEBACK=none', '--setenv=GOGC=100',
                   *(['--property=BindReadOnlyPaths=' + str(readonly_cache),
                      '--setenv=FOOTPRINT_READONLY_CACHE=' + str(readonly_cache)] if readonly_cache else []),
                   '/usr/bin/python3', str(HERE / 'linux_trial.py'), str(directory), *command]
    write(directory / 'command.json', {'command': command, 'GOMEMLIMIT': env['GOMEMLIMIT'], 'GOMAXPROCS': 2, 'GOGC': env['GOGC'], 'start_ns': time.time_ns()})
    try:
        p = subprocess.run(command, env=env, capture_output=True, timeout=195)
        code, stdout, stderr = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr = 124, error.stdout or b'', error.stderr or b''
    if systemd:
        (directory / 'systemd.stdout').write_bytes(stdout)
        (directory / 'systemd.stderr').write_bytes(stderr)
    else:
        (directory / 'stdout.jsonl').write_bytes(stdout)
        (directory / 'stderr.txt').write_bytes(stderr)
    samples, decode_error = [], None
    try:
        samples = [json.loads(line) for line in (directory / 'stdout.jsonl').read_text().splitlines()]
    except (ValueError, OSError) as error:
        decode_error = str(error)
    linux = json.loads((directory / 'linux.json').read_text()) if (directory / 'linux.json').exists() else None
    return samples, code, linux, decode_error


def campaign(a):
    out = a.out.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    (out / 'go.mod').write_text('module footprint.evidence\n\ngo 1.24.0\n')
    builds = {}
    for entry in a.build:
        name, path = entry.split('=', 1)
        if not name.replace('-', '').isalnum() or name in builds:
            raise ValueError('unique alphanumeric build names required')
        path = Path(path).resolve()
        manifest = json.loads((path / 'build.json').read_text())
        if digest(path / 'probe') != manifest['binary_sha256']:
            raise ValueError('binary digest mismatch')
        builds[name] = (path, manifest)
        metadata = out / 'builds' / name
        metadata.mkdir(parents=True)
        for filename in ['build.json', 'overlay.json', 'module.go', 'extism_core.go', 'bench.mod', 'bench.sum', 'dependency-digests.json']:
            shutil.copyfile(path / filename, metadata / filename)
    memory_limits = {}
    for entry in a.memory_limit or []:
        name, limit = entry.split('=', 1)
        if name not in builds or name in memory_limits or limit not in ['off', '32MiB', '48MiB', '64MiB', '96MiB', '128MiB']:
            raise ValueError('memory-limit requires unique BUILD=off|32MiB|48MiB|64MiB|96MiB|128MiB')
        memory_limits[name] = limit
    available = [name + ':' + mode for name in builds for mode in a.cache]
    cells = a.cell or available
    if len(cells) != len(set(cells)) or any(cell not in available for cell in cells):
        raise ValueError('cells must be unique configured BUILD:CACHE pairs')
    schedule = order(cells, a.repeats, a.warmups, a.seed)
    write(out / 'manifest.json', dict(host=host(), options=vars(a) | {'out': str(out)}, order=schedule,
                                     source_sha256={str(p.relative_to(HERE)): digest(p) for p in sorted(HERE.rglob('*.py')) if 'generated' not in p.parts}))
    trials = []
    args = ['--calls=' + str(a.calls), '--settle=' + a.settle, '--input-bytes=' + str(a.input_bytes), '--diagnostic=' + a.diagnostic]
    for i, item in enumerate(schedule):
        name, mode = item['cell'].split(':')
        path, build = builds[name]
        memory_limit = memory_limits.get(name)
        trial_id = f'{i:04d}-{name}-{mode}'
        cache = out / ('cache-' + trial_id)
        cache.mkdir(mode=0o700)
        cache_args = [] if mode == 'disabled' else ['--cache=' + str(cache)]
        reasons = []
        if mode in ['warm-rw', 'warm-ro']:
            population = out / ('populate-' + trial_id)
            ps, pc, pl, pe = run_process(population, path / 'probe', ['--calls=0', '--settle=0', *cache_args], a.systemd, memory_limit=memory_limit)
            reasons.extend('population: ' + r for r in validate(ps, pc, build['artifact_sha256'], 0, 'none', pl))
            if pe:
                reasons.append('population decode: ' + pe)
        before = cache_inventory(cache)
        directory = out / trial_id
        samples, code, linux, decode_error = run_process(directory, path / 'probe', args + cache_args, a.systemd, cache if mode == 'warm-ro' else None, memory_limit=memory_limit)
        reasons.extend(validate(samples, code, build['artifact_sha256'], a.calls, a.diagnostic, linux))
        if a.systemd and linux is None:
            reasons.append('missing final cgroup report')
        if (directory / 'stderr.txt').exists() and (directory / 'stderr.txt').stat().st_size:
            reasons.append('unexpected process stderr')
        if decode_error:
            reasons.append('sample decode: ' + decode_error)
        after = cache_inventory(cache)
        certainty = {'disabled': 'disabled', 'empty': 'fresh-writable-population', 'warm-rw': 'unknown-public-api-no-hit-signal', 'warm-ro': 'unknown'}[mode]
        if mode == 'warm-ro':
            if not a.systemd:
                reasons.append('warm-ro requires Linux systemd read-only bind mount')
            elif before and before == after and not reasons and linux and linux.get('readonly_cache', {}).get('verified'):
                certainty = 'known-hit-pinned-version-success-readonly-unchanged'
            else:
                reasons.append('known-hit evidence failed')
        metrics = {}
        if samples and not reasons:
            metrics['process_peak_bytes'] = max(s.get('process', {}).get('peak_rss_bytes', 0) for s in samples)
            for s in samples:
                if s.get('stage') in ['core-ready', 'invalid-init', 'settled', 'closed']:
                    metrics[s['stage'] + '_process_peak_bytes'] = s['process']['peak_rss_bytes']
                    if s.get('cgroup', {}).get('memory.peak', '').strip().isdigit():
                        metrics[s['stage'] + '_cgroup_peak_bytes'] = int(s['cgroup']['memory.peak'])
                    for key in ['user_cpu_us', 'system_cpu_us']:
                        metrics[s['stage'] + '_' + key] = s['process'].get(key, 0)
                    for key in ['NumGC', 'PauseTotalNs', 'TotalAlloc']:
                        metrics[s['stage'] + '_' + key] = s['go'].get(key, 0)
                    metrics[s['stage'] + '_heap_alloc_bytes'] = s['go']['HeapAlloc']
                    metrics[s['stage'] + '_rss_bytes'] = s['process'].get('rss_bytes', s['process'].get('status_VmRSS_bytes', 0))
                    metrics[s['stage'] + '_main_pages'] = s['main_pages']
                    metrics[s['stage'] + '_kernel_pages'] = s['kernel_pages']
                    metrics[s['stage'] + '_operation_ns'] = s.get('operation_ns', 0)
            invoke_times = [s['operation_ns'] for s in samples if s['stage'] == 'invalid-invoke']
            if invoke_times:
                metrics['invalid_invoke_median_ns'] = statistics.median(invoke_times)
                metrics['invalid_invoke_max_ns'] = max(invoke_times)
        if linux and linux.get('cgroup_after', {}).get('memory.peak', '').strip().isdigit():
            metrics['cgroup_peak_bytes'] = int(linux['cgroup_after']['memory.peak'])
        metrics['cache_bytes'] = sum(v['bytes'] for v in after.values())
        trial = dict(item, id=trial_id, invalid_reasons=sorted(set(reasons)), exit_code=code, cache_certainty=certainty,
                     cache_before=before, cache_after=after, metrics=metrics,
                     raw_sha256={p.name: digest(p) for p in directory.iterdir() if p.is_file()})
        write(directory / 'trial.json', trial)
        trials.append(trial)
        write(out / 'trials.json', trials)
        write(out / 'summary.json', summary(trials))
    write(out / 'host-after.json', host())
    # Cache blobs/native binaries are disposable, metadata/raw samples are evidence.
    print(json.dumps(summary(trials), indent=2))
    return int(any(t['invalid_reasons'] for t in trials))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', action='append', required=True, help='NAME=build-directory')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--memory-limit', action='append', help='BUILD=off|32MiB|48MiB|64MiB|96MiB|128MiB (application diagnostic)')
    p.add_argument('--cell', action='append', help='select configured BUILD:CACHE pair; defaults to all pairs')
    p.add_argument('--cache', action='append', choices=['disabled', 'empty', 'warm-rw', 'warm-ro'])
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--warmups', type=int, default=0)
    p.add_argument('--seed', type=int, default=285)
    p.add_argument('--calls', type=int, default=2)
    p.add_argument('--input-bytes', type=int, default=64)
    p.add_argument('--settle', default='1s')
    p.add_argument('--diagnostic', choices=['none', 'gc', 'free-os-memory'], default='none')
    p.add_argument('--systemd', action='store_true', help='execute on Linux target, one fresh bounded unit per process')
    a = p.parse_args()
    a.cache = a.cache or ['disabled']
    if a.repeats < 1 or a.warmups < 0 or a.repeats > 100 or a.warmups > 10:
        p.error('bounded repeats=1..100 and warmups=0..10 required')
    if a.systemd and platform.system() != 'Linux':
        p.error('--systemd must run on the target Linux host')
    raise SystemExit(campaign(a))
