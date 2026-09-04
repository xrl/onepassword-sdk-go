#!/usr/bin/env python3
"""Archive small campaign evidence, not generated executable/cache/dependency blobs."""
import argparse
import json
from pathlib import Path
import shutil
from controller import digest, write


def archive(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    records = {}
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if not path.is_file() or any(part.startswith('cache-') for part in relative.parts):
            continue
        if path.suffix not in ['.json', '.jsonl', '.txt', '.stdout', '.stderr', '.go', '.mod', '.sum']:
            continue
        # Archived overlay sources are text evidence, not packages in `go test ./...`.
        target = destination / relative
        if path.suffix == '.go':
            target = target.with_suffix('.go.txt')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        records[str(target.relative_to(destination))] = {'source': str(relative), 'sha256': digest(path), 'bytes': path.stat().st_size}
    write(destination / 'archive.json', records)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('destination', type=Path)
    a = p.parse_args()
    archive(a.source.resolve(), a.destination.resolve())
