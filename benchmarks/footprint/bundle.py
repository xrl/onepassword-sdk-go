#!/usr/bin/env python3
"""Pack byte-exact text evidence; keep reviewable summaries without thousands of files."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

TOP = ('manifest.json', 'summary.json', 'trials.json', 'results.json')


def bundle(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError('destination must not be inside source')
    inventory = json.loads((source / 'archive.json').read_text())
    for name, record in inventory.items():
        path = source / name
        if path.is_symlink() or source not in path.resolve().parents:
            raise ValueError('unsafe archive path: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('evidence checksum mismatch: ' + name)
    destination.mkdir(parents=True, exist_ok=False)
    names = sorted([*inventory, 'archive.json'])
    with (destination / 'raw.tar.gz').open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(mode='w', fileobj=compressed) as tar:
                for name in names:
                    path = source / name
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = path.stat().st_size, 0o644
                    with path.open('rb') as data:
                        tar.addfile(info, data)
    for name in TOP:
        if (source / name).exists():
            shutil.copyfile(source / name, destination / name)
    compressed = destination / 'raw.tar.gz'
    metadata = {'sha256': hashlib.sha256(compressed.read_bytes()).hexdigest(), 'bytes': compressed.stat().st_size,
                'members': len(names), 'content': 'Byte-exact text evidence and its original archive.json; no executable/cache blobs.',
                'recipe': 'python3 benchmarks/footprint/bundle.py EXTRACTED_EVIDENCE OUTPUT_DIRECTORY'}
    (destination / 'bundle.json').write_text(json.dumps(metadata, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    bundle(args.source, args.destination)
