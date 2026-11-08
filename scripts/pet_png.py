"""Strict bounded PNG framing shared in behavior with C710's Dart validator.

The pixel decoder receives rendering chunks only. All original chunks are still
CRC checked, and compressed text/ICC is bounded before local clients retain it.
"""
import struct
import zlib


def inflate_zlib(data, cap, require, path):
    inflater = zlib.decompressobj()
    result = bytearray()
    at, pending = 0, b''
    try:
        while not inflater.eof:
            if not pending and at < len(data):
                stop = min(at + 65536, len(data))
                pending, at = data[at:stop], stop
            chunk = inflater.decompress(pending, min(65536, cap - len(result) + 1))
            require(len(chunk) <= cap - len(result), 'png-inflate-size', path)
            result.extend(chunk)
            require(chunk or inflater.eof or len(inflater.unconsumed_tail) < len(pending),
                    'png-zlib-truncated', path)
            pending = inflater.unconsumed_tail
        # No flush: EOF, Adler32 and the precise compressed span are required.
        require(not inflater.unused_data and not pending and at == len(data),
                'png-zlib-trailing', path)
    except zlib.error:
        require(False, 'png-zlib-invalid', path)
    return result


def metadata_size(kind, payload, limits, require, path):
    if kind not in (b'iCCP', b'zTXt', b'iTXt', b'tEXt'):
        return 0
    end = payload.find(b'\0')
    require(1 <= end <= 79, 'png-metadata', path)
    tail = payload[end + 1:]
    if kind == b'tEXt':
        return len(tail)
    if kind in (b'iCCP', b'zTXt'):
        require(len(tail) > 0 and tail[0] == 0, 'png-metadata', path)
        return len(inflate_zlib(tail[1:], limits['pngMetadataChunkBytes'], require, path))
    require(len(tail) >= 2 and tail[0] in (0, 1) and tail[1] == 0,
            'png-metadata', path)
    compressed, at = tail[0] == 1, 2
    for _ in range(2):  # language tag, translated keyword
        end = tail.find(b'\0', at)
        require(end >= 0, 'png-metadata', path)
        at = end + 1
    text = tail[at:]
    return len(inflate_zlib(text, limits['pngMetadataChunkBytes'], require, path)) if compressed else len(text)


def validate_png_structure(data, limits, require, path=''):
    require(len(data) <= limits['sheetBytes'], 'sheet-size', path)
    require(data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 33
            and data[12:16] == b'IHDR' and data[8:12] == b'\0\0\0\r',
            'png-header', path)
    w, h = struct.unpack('>II', data[16:24])
    require(0 < w <= limits['sheetSide'] and 0 < h <= limits['sheetSide']
            and w * h * 4 <= limits['sheetDecodedBytes'], 'sheet-decoded-size', path)
    depth, color, compression, filtering, interlace = data[24:29]
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    require(depth in depths.get(color, ()) and compression == 0 and filtering == 0
            and interlace in (0, 1), 'png-format', path)
    at, palette, metadata_total = 8, 0, 0
    ended = saw_idat = idat_ended = transparency = False
    idat, rendering = bytearray(), bytearray(data[:8])
    while at < len(data):
        require(at + 12 <= len(data), 'png-chunk', path)
        size = int.from_bytes(data[at:at + 4], 'big')
        require(size <= len(data) - at - 12, 'png-chunk', path)
        kind, payload = data[at + 4:at + 8], data[at + 8:at + 8 + size]
        require(all(65 <= c <= 90 or 97 <= c <= 122 for c in kind), 'png-chunk-type', path)
        require(zlib.crc32(data[at + 4:at + 8 + size]) & 0xffffffff
                == int.from_bytes(data[at + 8 + size:at + 12 + size], 'big'), 'png-crc', path)
        require(kind not in (b'acTL', b'fcTL', b'fdAT'), 'png-animated', path)
        require(kind != b'IHDR' or at == 8, 'png-duplicate-header', path)
        require(kind[0] & 32 or kind in (b'IHDR', b'PLTE', b'IDAT', b'IEND'),
                'png-critical-chunk', path)
        if kind == b'PLTE':
            require(not saw_idat and not palette and not transparency and color not in (0, 4)
                    and 0 < size <= 768 and size % 3 == 0, 'png-palette', path)
            palette = size // 3
            require(color != 3 or palette <= 1 << depth, 'png-palette', path)
        if kind == b'tRNS':
            require(not saw_idat and not transparency and
                    ((color == 0 and size == 2) or (color == 2 and size == 6)
                     or (color == 3 and palette > 0 and 0 < size <= palette)),
                    'png-transparency', path)
            transparency = True
        if kind == b'IDAT':
            require(not idat_ended and (color != 3 or palette > 0), 'png-idat-order', path)
            saw_idat = True
            idat.extend(payload)
        elif saw_idat:
            idat_ended = True
        metadata_total += metadata_size(kind, payload, limits, require, path)
        require(metadata_total <= limits['pngMetadataTotalBytes'], 'png-metadata-total', path)
        if kind in (b'IHDR', b'PLTE', b'tRNS', b'IDAT', b'IEND'):
            rendering.extend(data[at:at + size + 12])
        at += size + 12
        if kind == b'IEND':
            require(size == 0 and at == len(data), 'png-trailing', path)
            ended = True
            break
    require(ended and saw_idat, 'png-truncated', path)
    bpp = channels[color] * depth
    rows = []
    if not interlace:
        rows.append(((w * bpp + 7) // 8, h))
    else:
        for x, y, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8),
                             (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
            pw = 0 if w <= x else (w - x + dx - 1) // dx
            ph = 0 if h <= y else (h - y + dy - 1) // dy
            if pw and ph:
                rows.append(((pw * bpp + 7) // 8, ph))
    expected = sum((stride + 1) * count for stride, count in rows)
    inflated = inflate_zlib(idat, expected, require, path)
    require(len(inflated) == expected, 'png-scanline-size', path)
    at = 0
    for stride, count in rows:
        for _ in range(count):
            require(inflated[at] <= 4, 'png-filter', path)
            at += stride + 1
    return w, h, bytes(rendering)
