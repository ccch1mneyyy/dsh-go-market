"""C710 PNG regression cases: tiny images and small mocked resource caps."""
import base64
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pet_pack import Denied, L, png


def chunk(kind, data=b''):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


def tiny(*, depth=8, color=6, interlace=0, pixels=b'\x00\x01\x02\x03\xff',
         compressed=None, before=(), after=(), idats=None):
    header = struct.pack('>IIBBBBB', 1, 1, depth, color, 0, 0, interlace)
    stream = zlib.compress(pixels) if compressed is None else compressed
    body = [chunk(b'IDAT', stream)] if idats is None else list(idats)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + b''.join(before) + b''.join(body) + b''.join(after) + chunk(b'IEND')


def corpus():
    cases = []
    def add(name, accepted, **kwargs):
        cases.append({'name': name, 'accepted': accepted,
                      'base64': base64.b64encode(tiny(**kwargs)).decode()})
    stream = zlib.compress(b'\x00\x01\x02\x03\xff')
    add('rgba8', True)
    add('unknown-valid-chunk-type', True, before=(chunk(b'vpAg'),))
    add('invalid-chunk-type-native-rejects', False, before=(chunk(b'a000'),))
    add('rgba8-adam7-one-pixel', True, interlace=1)
    add('rgba16', True, depth=16, pixels=b'\0' + b'\x01\x02'*4)
    for depth in (1, 2, 4, 8, 16):
        add(f'gray{depth}', True, depth=depth, color=0,
            pixels=b'\0' + bytes((depth + 7)//8))
    add('rgb8', True, color=2, pixels=b'\0\x01\x02\x03')
    add('gray-alpha8', True, color=4, pixels=b'\0\x01\xff')
    add('palette1', True, color=3, depth=1, pixels=b'\0\0',
        before=(chunk(b'PLTE', b'\x01\x02\x03'),))
    add('palette-transparency', True, color=3, depth=1, pixels=b'\0\0',
        before=(chunk(b'PLTE', b'\x01\x02\x03'), chunk(b'tRNS', b'\x80')))
    add('contiguous-idat', True,
        idats=(chunk(b'IDAT', stream[:4]), chunk(b'IDAT', stream[4:])))
    add('split-idat-by-text', False,
        idats=(chunk(b'IDAT', stream[:4]), chunk(b'tEXt', b'x\0y'), chunk(b'IDAT', stream[4:])))
    add('missing-deflate-final', False, compressed=stream[:2] + bytes([stream[2] & 254]) + stream[3:])
    add('zlib-trailing', False, compressed=stream + b'x')
    add('zlib-concatenated', False, compressed=stream + zlib.compress(b''))
    add('zlib-adler', False, compressed=stream[:-1] + bytes([stream[-1] ^ 1]))
    add('short-scanline', False, pixels=b'\0\x01')
    add('long-scanline', False, pixels=b'\0\x01\x02\x03\xff\0')
    add('filter-five', False, pixels=b'\x05\x01\x02\x03\xff')
    add('rgba-depth-four', False, depth=4)
    add('palette-missing', False, color=3, depth=1, pixels=b'\0\0')
    add('palette-too-many-entries', False, color=3, depth=1, pixels=b'\0\0',
        before=(chunk(b'PLTE', b'\0'*9),))
    add('palette-duplicate', False,
        before=(chunk(b'PLTE', b'\0'*3), chunk(b'PLTE', b'\0'*3)))
    add('palette-after-transparency', False, color=2, pixels=b'\0\1\2\3',
        before=(chunk(b'tRNS', b'\0'*6), chunk(b'PLTE', b'\0'*3)))
    add('rgba-transparency-invalid', False, before=(chunk(b'tRNS', b'\0'*6),))
    add('palette-after-idat', False, after=(chunk(b'PLTE', b'\0'*3),))
    add('text', True, before=(chunk(b'tEXt', b'name\0hello'),))
    for kind in (b'iCCP', b'zTXt'):
        prefix = b'name\0\0'
        add(kind.decode()+'-bounded', True, before=(chunk(kind, prefix + zlib.compress(b'hello')),))
        add(kind.decode()+'-trailing', False, before=(chunk(kind, prefix + zlib.compress(b'hello')+b'x'),))
        add(kind.decode()+'-method', False, before=(chunk(kind, b'name\0\1'+zlib.compress(b'hello')),))
    add('itxt-uncompressed', True, before=(chunk(b'iTXt', b'name\0\0\0en\0title\0hello'),))
    add('itxt-compressed', True, before=(chunk(b'iTXt', b'name\0\1\0en\0title\0'+zlib.compress(b'hello')),))
    add('itxt-compressed-trailing', False,
        before=(chunk(b'iTXt', b'name\0\1\0\0\0'+zlib.compress(b'hello')+b'x'),))
    add('itxt-flag', False, before=(chunk(b'iTXt', b'name\0\2\0\0\0hello'),))
    add('itxt-missing-terminator', False, before=(chunk(b'iTXt', b'name\0\1\0en'),))
    add('text-empty-keyword', False, before=(chunk(b'tEXt', b'\0hello'),))
    add('text-long-keyword', False, before=(chunk(b'tEXt', b'x'*80+b'\0hello'),))
    return {'ruleRevision': 2, 'description': 'Original synthetic 1x1 PNGs; no third-party pixels.', 'cases': cases}


class PngV2Tests(unittest.TestCase):
    def test_shared_tiny_corpus(self):
        saved = json.loads((Path(__file__).parent/'fixtures/pet-png-v2.json').read_text())
        self.assertEqual(saved, corpus())
        for case in saved['cases']:
            with self.subTest(case=case['name']):
                raw = base64.b64decode(case['base64'])
                if case['accepted']:
                    encoded, image = png(raw)
                    self.assertEqual(image.size, (1, 1))
                    image.close()
                    self.assertTrue(encoded.startswith(b'\x89PNG'))
                else:
                    with self.assertRaises(Denied):
                        png(raw)

    def test_compressed_metadata_cap_with_small_limits(self):
        with patch.dict(L, {'pngMetadataChunkBytes': 8, 'pngMetadataTotalBytes': 24}):
            for kind, prefix in [(b'iCCP', b'x\0\0'), (b'zTXt', b'x\0\0'), (b'iTXt', b'x\0\1\0\0\0')]:
                with self.subTest(kind=kind):
                    _, image = png(tiny(before=(chunk(kind, prefix+zlib.compress(b'x'*8)),)))
                    image.close()
                    with self.assertRaises(Denied):
                        png(tiny(before=(chunk(kind, prefix+zlib.compress(b'x'*9)),)))

    def test_metadata_total_and_uncompressed_compatibility(self):
        with patch.dict(L, {'pngMetadataChunkBytes': 8, 'pngMetadataTotalBytes': 24}):
            _, image = png(tiny(before=(chunk(b'tEXt', b'x\0'+b'x'*24),)))
            image.close()
            with self.assertRaises(Denied):
                png(tiny(before=(chunk(b'tEXt', b'x\0'+b'x'*25),)))
            with self.assertRaises(Denied):
                png(tiny(before=tuple(chunk(b'zTXt', b'x\0\0'+zlib.compress(b'x'*8)) for _ in range(4))))


if __name__ == '__main__':
    unittest.main()
