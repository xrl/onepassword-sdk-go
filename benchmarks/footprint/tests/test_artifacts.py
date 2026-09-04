import unittest
from artifacts import MAGIC, PREFIX, Reader, exports, prune, sections, uint


def section(kind, payload):
    return bytes([kind]) + uint(len(payload)) + payload


def export(name, kind, index):
    name = name.encode()
    return uint(len(name)) + name + bytes([kind]) + uint(index)


class ArtifactTests(unittest.TestCase):
    def test_only_descriptor_function_exports_removed(self):
        keep = export('invoke', 0, 129) + export('memory', 2, 0) + export('__wbindgen_malloc', 0, 3)
        original = MAGIC + section(0, b'\x03fooXXX') + section(7, uint(4) + keep + export(PREFIX + 'x', 0, 1)) + section(10, b'\x00')
        result, removed = prune(original)
        self.assertEqual(removed, [PREFIX + 'x'])
        self.assertEqual(result, MAGIC + section(0, b'\x03fooXXX') + section(7, uint(3) + keep) + section(10, b'\x00'))
        self.assertEqual(prune(result), (result, []))
        self.assertEqual([x[0] for x in exports(list(sections(result))[1][1])], ['invoke', 'memory', '__wbindgen_malloc'])

    def test_reject_descriptor_nonfunction(self):
        with self.assertRaises(ValueError):
            prune(MAGIC + section(7, uint(1) + export(PREFIX + 'x', 2, 0)))

    def test_truncation_overflow_and_duplicate(self):
        for data in [b'', MAGIC + b'\x07\x7f', MAGIC + section(7, b'\x00') * 2]:
            with self.assertRaises(ValueError):
                prune(data)
        for data in [b'\x80' * 6, b'\xff\xff\xff\xff\x7f']:
            with self.assertRaises(ValueError):
                Reader(data).uint()

    def test_u32_roundtrip(self):
        for n in [0, 127, 128, 16384, 0xffffffff]:
            self.assertEqual(Reader(uint(n)).uint(), n)
