import json
from pathlib import Path
import tempfile
import unittest
from archive import archive


class ArchiveTests(unittest.TestCase):
    def test_preserves_raw_not_blobs_or_compilable_go(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'cache-cell').mkdir()
            (source / 'cache-cell' / 'native.json').write_text('not evidence')
            (source / 'probe').write_bytes(b'binary')
            (source / 'stdout.jsonl').write_text('{}\n')
            (source / 'module.go').write_text('package extism\n')
            archive(source, root / 'archive')
            files = json.loads((root / 'archive/archive.json').read_text())
            self.assertEqual(set(files), {'module.go.txt', 'stdout.jsonl'})
            self.assertEqual((root / 'archive/stdout.jsonl').read_text(), '{}\n')
            with self.assertRaises(FileExistsError):
                archive(source, root / 'archive')
