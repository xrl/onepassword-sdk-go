import copy
import errno
import json
from unittest.mock import patch
from linux_trial import readonly_check
from pathlib import Path
import tempfile
import unittest
from controller import cache_inventory, order, run_process, summary, validate


def samples():
    stages = ['baseline-ready', 'core-ready', 'invalid-init', 'invalid-invoke', 'settled', 'closed']
    result = []
    errors = 0
    for i, stage in enumerate(stages):
        if stage.startswith('invalid-'):
            errors += 1
        result.append(dict(dependencies={'github.com/extism/go-sdk': 'v1.7.1', 'github.com/tetratelabs/wazero': 'v1.11.0'}, stage=stage, elapsed_ns=i, unexpected_errors=0, expected_errors=errors,
                           load_attempts=int(i > 0), identities=['one'] if i else [], embedded_sha256='abc',
                           go={'HeapAlloc': 20}, error_sha256='error', main_pages=62, kernel_pages=16,
                           process={'peak_rss_bytes': 100, 'rss_bytes': 90, 'os': 'darwin', 'gomaxprocs': 2}))
    return result


class ControllerTests(unittest.TestCase):
    def test_protocol_and_invalid_outcomes(self):
        self.assertEqual(validate(samples(), 0, 'abc', 1, 'none'), [])
        cases = []
        for key, value in [('load_attempts', 2), ('identities', ['one', 'two']), ('embedded_sha256', 'wrong'),
                           ('unexpected_errors', 1), ('expected_errors', 10), ('elapsed_ns', 'bad'), ('go', {}), ('main_pages', 0), ('process', {})]:
            candidate = samples()
            candidate[2][key] = value
            cases.append(candidate)
        candidate = samples()
        candidate[3]['identities'] = ['other']
        cases.extend([candidate, samples()[:-1], [], [None]])
        for candidate in cases:
            self.assertTrue(validate(candidate, 0, 'abc', 1, 'none'))
        self.assertTrue(validate(samples(), 1, 'abc', 1, 'none'))

    def test_explicit_cpu_setting_is_required(self):
        candidate = samples()
        candidate[0]['process']['gomaxprocs'] = 4
        self.assertIn('GOMAXPROCS mismatch', validate(candidate, 0, 'abc', 1, 'none'))

    def test_readonly_check_requires_erofs_not_permissions(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(readonly_check(temp)['verified'])
            self.assertEqual(list(Path(temp).iterdir()), [])
            with patch('linux_trial.os.open', side_effect=OSError(errno.EROFS, 'read-only filesystem')):
                self.assertTrue(readonly_check(temp)['verified'])
            with patch('linux_trial.os.open', side_effect=OSError(errno.EACCES, 'permission denied')):
                self.assertFalse(readonly_check(temp)['verified'])

    def test_cgroup_events_and_limits(self):
        linux = {'cgroup_after': {'cpu.max': '200000 100000\n', 'memory.max': '536870912\n', 'memory.swap.max': '0\n', 'memory.events': 'oom_kill 0\nmax 0\n'}}
        self.assertEqual(validate(samples(), 0, 'abc', 1, 'none', linux), [])
        linux['cgroup_after']['memory.events'] = 'oom_kill 1\n'
        self.assertTrue(validate(samples(), 0, 'abc', 1, 'none', linux))

    def test_interleaving_is_reproducible_and_complete(self):
        cells = ['base:empty', 'base:disabled', 'candidate:disabled']
        planned = order(cells, 3, 2, 285)
        self.assertEqual(planned, order(cells, 3, 2, 285))
        self.assertEqual(len(planned), 15)
        for i in range(0, len(planned), 3):
            self.assertEqual(sorted(x['cell'] for x in planned[i:i+3]), sorted(cells))
        self.assertEqual(sum(x['phase'] == 'warmup' for x in planned), 6)

    def test_summary_keeps_failures_excludes_warmups(self):
        trial = dict(phase='measured', cell='base', id='0', invalid_reasons=[], metrics={'peak': 20})
        second = copy.deepcopy(trial)
        second['metrics']['peak'] = 40
        result = summary([trial, second, trial | {'phase': 'warmup'}, trial | {'invalid_reasons': ['OOM']}])['base']
        self.assertEqual(result['valid'], 2)
        self.assertEqual(result['metrics']['peak'], {'median': 30, 'min': 20, 'max': 40, 'range': 20, 'n': 2})
        self.assertEqual(len(result['failures']), 1)

    def test_fresh_cache_inventories_detect_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / 'cell-a', root / 'cell-b'
            a.mkdir(mode=0o700)
            b.mkdir(mode=0o700)
            self.assertEqual(cache_inventory(a), {})
            (a / 'entry').write_bytes(b'code')
            before = cache_inventory(a)
            self.assertEqual(cache_inventory(b), {})
            self.assertEqual(before['entry']['bytes'], 4)
            (a / 'entry').write_bytes(b'CODE')
            self.assertNotEqual(before, cache_inventory(a))

    def test_runner_starts_fresh_processes_and_records_raw_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'probe'
            binary.write_text("#!/bin/sh\nprintf '{\"pid\": %s}\\n' \"$$\"\n")
            binary.chmod(0o700)
            a, code_a, _, error_a = run_process(root / 'a', binary, [], False)
            b, code_b, _, error_b = run_process(root / 'b', binary, [], False)
            self.assertEqual((code_a, code_b, error_a, error_b), (0, 0, None, None))
            self.assertNotEqual(a[0]['pid'], b[0]['pid'])
            self.assertEqual(json.loads((root / 'a/command.json').read_text())['GOMAXPROCS'], 2)
            self.assertTrue((root / 'b/stdout.jsonl').is_file())
