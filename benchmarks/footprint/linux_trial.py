#!/usr/bin/env python3
"""Run INSIDE one fresh systemd unit. Small Python supervisor overhead is included."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def cgroup():
    path = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    directory = Path('/sys/fs/cgroup') / path.lstrip('/')
    result = {'path': str(directory)}
    for name in ['memory.current', 'memory.peak', 'memory.events', 'memory.stat', 'memory.max', 'memory.swap.max', 'memory.swap.current', 'cpu.max']:
        try:
            result[name] = (directory / name).read_text()
        except OSError as error:
            result[name] = 'ERROR: ' + str(error)
    return result


def readonly_check(directory):
    """EROFS proves a read-only mount, unlike owner permissions (EACCES)."""
    path = Path(directory) / ('.footprint-write-check-' + str(os.getpid()))
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        return {'verified': error.errno == errno.EROFS, 'errno': error.errno}
    else:
        os.close(fd)
        path.unlink()  # Remove only the unique empty file created by this check.
        return {'verified': False, 'errno': 0}


if __name__ == '__main__':
    directory = Path(sys.argv[1])
    started = time.time_ns()
    before = cgroup()
    ro = readonly_check(os.environ['FOOTPRINT_READONLY_CACHE']) if os.environ.get('FOOTPRINT_READONLY_CACHE') else None
    failure = None
    code = 1
    with (directory / 'stdout.jsonl').open('w') as stdout, (directory / 'stderr.txt').open('w') as stderr:
        if ro is not None and not ro['verified']:
            failure = 'cache read-only mount not verified; probe not launched'
        else:
            try:
                code = subprocess.run(sys.argv[2:], stdout=stdout, stderr=stderr, timeout=160).returncode
            except subprocess.TimeoutExpired:
                code, failure = 124, 'probe timeout'
    result = dict(exit_code=code, started_ns=started, ended_ns=time.time_ns(), cgroup_before=before, cgroup_after=cgroup(),
                  readonly_cache=ro, failure=failure, supervisor_pid=os.getpid(), page_bytes=os.sysconf('SC_PAGE_SIZE'))
    (directory / 'linux.json').write_text(json.dumps(result, indent=2) + '\n')
    sys.exit(code)
