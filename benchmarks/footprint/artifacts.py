#!/usr/bin/env python3
"""Pinned, bounded artifact experiment; only export section 7 is edited in Python."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOOLS = '/Users/xavier/.cargo/bin/wasm-tools'
OPT = '/opt/homebrew/bin/wasm-opt'
CORE_SHA = '23d115f4ac7519b48172df3e8615945572dbda7033d51b44c9490fd533ae0f23'
PREFIX = '__wbindgen_describe_'
MAGIC = b'\0asm\x01\0\0\0'


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError('truncated WASM')
        data = self.data[self.pos:self.pos + size]
        self.pos += size
        return data

    def uint(self):
        value = 0
        for i in range(5):
            byte = self.take(1)[0]
            value |= (byte & 127) << (i * 7)
            if not byte & 128:
                if value > 0xffffffff:
                    raise ValueError('u32 overflow')
                return value
        raise ValueError('overlong u32')

    def name(self):
        return self.take(self.uint()).decode('utf8')

    def done(self):
        if self.pos != len(self.data):
            raise ValueError('trailing bytes')


def uint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def sections(data):
    r = Reader(data)
    if r.take(8) != MAGIC:
        raise ValueError('invalid WASM header/version')
    while r.pos < len(data):
        begin = r.pos
        kind = r.take(1)[0]
        payload = r.take(r.uint())
        yield kind, payload, data[begin:r.pos]


def exports(payload):
    r = Reader(payload)
    entries = []
    for _ in range(r.uint()):
        begin = r.pos
        name, kind, index = r.name(), r.take(1)[0], r.uint()
        entries.append((name, kind, index, payload[begin:r.pos]))
    r.done()
    return entries


def prune(data):
    result, removed, seen = bytearray(MAGIC), [], False
    for kind, payload, raw in sections(data):
        if kind != 7:
            result.extend(raw)
            continue
        if seen:
            raise ValueError('duplicate export section')
        seen = True
        retained = []
        for name, export_kind, _, record in exports(payload):
            if name.startswith(PREFIX):
                if export_kind != 0:
                    raise ValueError('descriptor export is not a function')
                removed.append(name)
            else:
                retained.append(record)
        payload = uint(len(retained)) + b''.join(retained)
        result.extend(b'\x07' + uint(len(payload)) + payload)
    return bytes(result), removed


def sha(data):
    return hashlib.sha256(data).hexdigest()


def report(path):
    data = path.read_bytes()
    report = dict(bytes=len(data), sha256=sha(data), sections=[], defined_bodies=0, exports=0)
    function_types = []
    for kind, payload, _ in sections(data):
        entry = dict(id=kind, payload_bytes=len(payload))
        if kind == 0:
            entry['name'] = Reader(payload).name()
        if kind == 3:
            reader = Reader(payload)
            function_types = [reader.uint() for _ in range(reader.uint())]
            reader.done()
        if kind == 10:
            report['defined_bodies'] = Reader(payload).uint()
            report['code_bytes'] = len(payload)
        if kind == 11:
            report['data_bytes'] = len(payload)
        if kind == 7:
            report['exports'] = len(exports(payload))
            report['descriptor_exports'] = sum(n.startswith(PREFIX) for n, _, _, _ in exports(payload))
        report['sections'].append(entry)
    # wasm-tools supplies human-readable ABI types rather than a second private decoder.
    wat = subprocess.check_output([TOOLS, 'print', str(path)], text=True)
    abi = {name: [] for name in ['type', 'import', 'export', 'memory', 'table', 'global']}
    imported_types = []
    for line in wat.splitlines():
        match = re.match(r'^  \((type|import|export|memory|table|global)\b', line)
        if match:
            abi[match[1]].append(line.strip())
            if match[1] == 'import' and '(func ' in line:
                imported_types.append(int(re.search(r'\(type (\d+)\)', line)[1]))
    types = {int(re.search(r'\(;([0-9]+);\)', line)[1]): line[line.index('(func'):-1] for line in abi['type']}
    indices = imported_types + function_types
    export_signatures = {}
    # Printed function references may be symbolic; numeric indices come from section 7.
    for kind, payload, _ in sections(data):
        if kind == 7:
            for name, export_kind, index, _ in exports(payload):
                export_signatures[name] = dict(kind=export_kind, signature=types[indices[index]] if export_kind == 0 else None)
    report['export_signatures'] = export_signatures
    report['abi'] = abi
    return report


def abi_contract(report):
    # Ignore symbolic names and numeric comments, not actual limits or signatures.
    def normalize(line):
        line = re.sub(r'\(;\d+;\)', '', line)
        line = re.sub(r'\$[^\s()]+', '', line)
        return ' '.join(line.split())
    return {k: sorted(normalize(s) for s in report['abi'][k]) for k in ['memory', 'table', 'global']}


def generate(directory):
    directory.mkdir(parents=True, exist_ok=False)
    versions = {TOOLS: 'wasm-tools 1.236.1', OPT: 'wasm-opt version 132'}
    for tool, expected in versions.items():
        if subprocess.check_output([tool, '--version'], text=True).strip() != expected:
            raise RuntimeError('tool version mismatch')
    original = ROOT / 'internal/wasm/core.wasm'
    if sha(original.read_bytes()) != CORE_SHA:
        raise RuntimeError('shipping core digest mismatch')
    shutil.copyfile(original, directory / 'original.wasm')
    pruned, removed = prune(original.read_bytes())
    if len(removed) != 1741:
        raise RuntimeError('unexpected descriptor count')
    (directory / 'prune-only.wasm').write_bytes(pruned)
    commands = [[TOOLS, 'strip', '--all', str(original), '-o', str(directory / 'stripped.wasm')]]
    for name, flags in [('prune-dce', ['--remove-unused-module-elements']), ('prune-oz', ['-Oz'])]:
        commands.append([OPT, str(directory / 'prune-only.wasm'), *flags, '-o', str(directory / (name + '.wasm'))])
    commands.append([OPT, str(directory / 'original.wasm'), '-Oz', '-o', str(directory / 'original-oz.wasm')])
    for command in commands:
        subprocess.run(command, check=True)
    reports = {}
    for name in ['original', 'stripped', 'prune-only', 'prune-dce', 'prune-oz', 'original-oz']:
        path = directory / (name + '.wasm')
        command = [TOOLS, 'validate', str(path)]
        subprocess.run(command, check=True)
        commands.append(command)
        reports[name] = report(path)
    baseline = reports['original']
    for name, candidate in reports.items():
        expected = {k: v for k, v in baseline['export_signatures'].items() if name in ['original', 'stripped', 'original-oz'] or not k.startswith(PREFIX)}
        if candidate['export_signatures'] != expected or abi_contract(candidate) != abi_contract(baseline):
            raise RuntimeError('ABI contract changed: ' + name)
        # Import type indices may be renumbered; compare resolved signatures.
        def imports(rep):
            types = rep['abi']['type']
            result = []
            for line in rep['abi']['import']:
                index = int(re.search(r'\(type (\d+)\)', line)[1])
                result.append((re.findall(r'"([^"]*)"', line), types[index][types[index].index('(func'):-1]))
            return result
        if imports(candidate) != imports(baseline):
            raise RuntimeError('imports changed: ' + name)
    manifest = dict(generator_sha256=sha(Path(__file__).read_bytes()), rejected_attempt={'flags': ['--all-features', '--remove-unused-module-elements'], 'validation_error': 'invalid leading byte (0x7f) for external kind (at offset 0x2d3)', 'disposition': 'Rejected before smoke tests. Binaryen all-features enables proposals not accepted by pinned wasm-tools; default input features validate. No rejected artifact used.'}, tools=versions, tool_sha256={p: sha(Path(p).read_bytes()) for p in versions}, commands=commands,
                    removed_exports=removed, artifacts=reports,
                    cache_sizes='Measured per target and fresh cache cell by controller, not inferred from WASM size.')
    (directory / 'artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')
    lines = ['# Generated artifact report', '', 'Generator: `python3 benchmarks/footprint/artifacts.py --out benchmarks/footprint/generated/variants`.',
             'Shipping artifact untouched. Only descriptor exports removed; full private integration remains required.', '',
             '| Artifact | Bytes | Bodies | Exports | Code bytes | Data bytes | SHA-256 |', '|---|---:|---:|---:|---:|---:|---|']
    for name, r in reports.items():
        lines.append(f"| {name} | {r['bytes']} | {r['defined_bodies']} | {r['exports']} | {r['code_bytes']} | {r['data_bytes']} | {r['sha256']} |")
    (directory / 'report.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True, type=Path)
    generate(p.parse_args().out.resolve())
