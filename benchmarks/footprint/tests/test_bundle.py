import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from bundle import bundle


class BundleTests(unittest.TestCase):
    def test_byte_exact_deterministic_evidence_and_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            content = b'{"value":1}\r\n'
            (source / 'summary.json').write_bytes(content)
            (source / 'archive.json').write_text(json.dumps({'summary.json': {'sha256': hashlib.sha256(content).hexdigest()}}))
            bundle(source, root / 'a')
            bundle(source, root / 'b')
            self.assertEqual((root / 'a/raw.tar.gz').read_bytes(), (root / 'b/raw.tar.gz').read_bytes())
            self.assertEqual((root / 'a/summary.json').read_bytes(), content)
            with tarfile.open(root / 'a/raw.tar.gz') as tar:
                self.assertEqual(tar.extractfile('summary.json').read(), content)
            (source / 'summary.json').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                bundle(source, root / 'c')
            self.assertFalse((root / 'c').exists())

    def test_reject_nested_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                bundle(Path(tmp), Path(tmp) / 'nested')
