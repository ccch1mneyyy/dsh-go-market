"""Schema-1 compatibility checker plus bounded, deterministic market packaging.
No submitted path is ever extracted or executed. Limits live in the shared rules.
"""
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import struct
import unicodedata
import warnings
import zipfile
import zlib
from PIL import Image
from pet_png import validate_png_structure

RULES = json.loads((Path(__file__).resolve().parents[1] / 'schema/pet-pack.rules.json').read_text())
L = RULES['limits']
if unicodedata.unidata_version != RULES['commonValidation']['unicodeVersion']:
    raise RuntimeError('Use Python 3.12 / Unicode 15.0.0 to match the Dart archive-name tables')

class Denied(ValueError):
    def __init__(self, code, path=''):
        self.code, self.path = code, path
        super().__init__(f'{code}:{path}')

def require(ok, code, path=''):
    if not ok:
        raise Denied(code, path)

def object_(v):
    return v if isinstance(v, dict) else {}

def array(v):
    return v if isinstance(v, list) else []

def utf16len(v):
    # Dart/JavaScript String.length counts UTF-16 code units.
    return len(v.encode('utf-16-le', errors='surrogatepass')) // 2

def number(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return False
    try:
        finite = math.isfinite(float(v))
    except OverflowError:
        finite = False
    # A numeric overflow is not a missing/non-numeric optional value. In Dart
    # _num returns a double, whose round() rejects infinity rather than defaulting.
    require(finite, 'number-nonfinite')
    return True

def rounded(v):
    require(number(v), 'number-type')
    v = float(v)  # PetPack._num always calls toDouble before round.
    if v >= 2**63: return 2**63-1
    if v <= -2**63: return -2**63
    whole = math.trunc(v)
    # Adding .5 first rounds nextafter(.5, 0) up to 1.0 in binary64.
    return whole + (1 if v > 0 else -1) if abs(v-whole) >= .5 else whole

def rect(v):
    v = object_(v)
    return all(number(v.get(k)) for k in ('x', 'y', 'w', 'h')) and v['w'] > 0 and v['h'] > 0

def canonical(v):
    return (json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def parse_json(data, cap=None):
    require(cap is None or len(data) <= cap, 'json-size')
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'json-duplicate', k)
            result[k] = v
        return result
    def walk(v, depth=0):
        require(depth <= L['jsonDepth'], 'json-depth')
        if isinstance(v, (int, float)):
            try: finite = math.isfinite(float(v))
            except OverflowError: finite = False
            require(finite, 'json-nonfinite')
        if isinstance(v, str):
            require(not any(0xd800 <= ord(c) <= 0xdfff for c in v), 'json-unicode')
        if isinstance(v, dict):
            for k in v: walk(k, depth+1)
        for child in v.values() if isinstance(v, dict) else v if isinstance(v, list) else []:
            walk(child, depth+1)
    try:
        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(Denied('json-nonfinite')))
        walk(result)
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as e:
        raise Denied('json-invalid') from e
    return result

def validate(pack, market=False):
    require(isinstance(pack, dict), 'pack-object')
    require(number(pack.get('schema')) and pack['schema'] == RULES['schema'], 'pack-schema')
    require(isinstance(pack.get('id'), str) and pack['id'], 'pack-id')
    canvas = object_(pack.get('canvas'))
    require(all(number(canvas.get(k)) and canvas[k] > 0 for k in ('w', 'h')), 'pack-canvas')
    require(rounded(pack['scale']) > 0 if number(pack.get('scale')) else True, 'pack-scale')
    require(rect(pack.get('contentBox')), 'pack-contentBox')
    animations = {}
    for name, raw in object_(pack.get('animations')).items():
        a = object_(raw)
        require(isinstance(a.get('sheet'), str) and rect(a.get('box')), 'pack-animation', name)
        require(all(number(a.get(k)) and rounded(a[k]) > 0 for k in ('frameW', 'frameH', 'cols')), 'pack-animation', name)
        frames = [(rounded(f['i']), rounded(f['ms'])) for f in map(object_, array(a.get('frames')))
                  if number(f.get('i')) and number(f.get('ms'))]
        require(bool(frames) and all(i >= 0 and ms > 0 for i, ms in frames), 'pack-frames', name)
        animations[name] = {**a, **{k: rounded(a[k]) for k in ('frameW', 'frameH', 'cols')}, '_frames': frames}
    require(bool(animations), 'pack-animations')
    def known(v, path):
        require(isinstance(v, str) and v in animations, 'pack-reference', path)
    states = {}
    for k, v in object_(pack.get('states')).items():
        for name in array(v):
            known(name, f'states.{k}')
        if array(v):
            states[k] = v
    require('idle' in states, 'pack-idle')
    for k, v in object_(pack.get('tiers')).items():
        for t in array(v):
            known(object_(t).get('anim'), f'tiers.{k}')
    for k, v in object_(pack.get('reactions')).items():
        known(v, f'reactions.{k}')
    roam = object_(pack.get('roam'))
    if roam.get('anim') is not None:
        known(roam['anim'], 'roam.anim')
    pool = pack.get('idlePool')
    for entry in pool if isinstance(pool, list) else array(object_(pool).get('anims')):
        known(object_(entry).get('anim'), 'idlePool')
    for k, entry in object_(pack.get('bonus')).items():
        for name in array(object_(entry).get('anims')):
            known(name, f'bonus.{k}')
    if market:
        for k in RULES['marketProfile']['metadataRequired']:
            require(isinstance(pack.get(k), str) and pack[k].strip(), 'pack-metadata', k)
    sheets = {a['sheet'] for a in animations.values()}
    require(len(sheets) <= L['sheetCount'], 'sheet-count')
    for sheet in sheets:
        require(0 < utf16len(sheet) <= L['sheetNameCharacters'] and not sheet.startswith('.')
                and not any(c in sheet for c in ('/', '\\', '\0')) and sheet.lower().endswith('.png'), 'sheet-name', sheet)
    return animations, states

def png(data, path=''):
    w, h, rendering = validate_png_structure(data, L, require, path)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(rendering)) as image:
                require(image.format == 'PNG' and image.size == (w, h), 'png-format', path)
                image.load()  # Full decompression, not merely IHDR/verify.
                image = image.convert('RGBA')
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError) as e:
        if isinstance(e, Denied):
            raise
        raise Denied('png-decode', path) from e
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=False, compress_level=9)
    encoded = out.getvalue()
    require(len(encoded) <= L['sheetBytes'], 'sheet-normalized-size', path)
    return encoded, image

def previews(animations, states, sheets):
    # Keep at most one decoded sheet, independent of the 64-sheet count limit.
    current, image = None, None
    names = list(dict.fromkeys(states['idle'] + list(animations)))
    def frame(a, i):
        nonlocal current, image
        if current != a['sheet']:
            if image is not None: image.close()
            current = a['sheet']
            image = Image.open(io.BytesIO(sheets[current])); image.load()
        x, y = i % a['cols'] * a['frameW'], i // a['cols'] * a['frameH']
        im = image.crop((x, y, x+a['frameW'], y+a['frameH']))
        factor = min(256 / im.width, 256 / im.height)
        if a.get('_pixelArt', True) and factor >= 1: factor = max(1, int(factor))
        size = (max(1, round(im.width*factor)), max(1, round(im.height*factor)))
        resized = im.resize(size, Image.Resampling.NEAREST if a.get('_pixelArt', True) else Image.Resampling.LANCZOS)
        im.close(); im = resized
        canvas = Image.new('RGBA', (256, 256))
        canvas.alpha_composite(im, ((256-im.width)//2, (256-im.height)//2))
        im.close()
        return canvas
    static = frame(animations[names[0]], animations[names[0]]['_frames'][0][0])
    out = io.BytesIO(); static.save(out, format='PNG')
    png_bytes = out.getvalue()
    frames, durations, elapsed = [], [], 0
    for name in names:
        a = animations[name]
        for i, ms in a['_frames']:
            if elapsed >= 4000 or len(frames) >= 48:
                break
            duration = min(1000, max(40, ms), 4000-elapsed)
            rgb = Image.new('RGB', (256, 256), '#f5f5f5')
            art = frame(a, i)
            rgb.paste(art, mask=art.getchannel('A'))
            frames.append(rgb); durations.append(duration); elapsed += duration
        if elapsed >= 4000 or len(frames) >= 48:
            break
    out = io.BytesIO()
    frames[0].save(out, format='GIF', save_all=True, append_images=frames[1:], duration=durations, loop=0, disposal=2)
    if image is not None: image.close()
    return png_bytes, out.getvalue()

def market_manifest(pack, animations):
    # Match the Dart parsed integer values and Android's stricter cell geometry.
    # Do not silently resize source art or change its authored logical boxes.
    pack = json.loads(json.dumps(pack))
    scale = rounded(pack['scale']) if number(pack.get('scale')) else 1
    require(0 < scale <= 2147483647, 'market-scale')
    pack['scale'] = scale
    pack['pixelArt'] = pack.get('pixelArt') is not False
    for axis in ('w', 'h'):
        value = pack['canvas'][axis]
        require(value == int(value) and 0 < value <= L['sheetSide'], 'market-canvas-integer')
        pack['canvas'][axis] = int(value)
    def f32(v):
        try:
            result = struct.unpack('f', struct.pack('f', v))[0]
            require(math.isfinite(result), 'market-float32')
            return result
        except (OverflowError, struct.error) as e:
            raise Denied('market-float32') from e
    for name, a in animations.items():
        for k, axis in (('frameW','w'), ('frameH','h')):
            require(a[k] == int(f32(f32(a['box'][axis])*f32(scale))), 'market-cell-box-scale', name)
        target = pack['animations'][name]
        target.update({k:a[k] for k in ('frameW','frameH','cols')})
        target['frames'] = [{'i':i,'ms':ms} for i,ms in a['_frames']]
        require(all(i <= 2147483647 and ms <= 2147483647 for i,ms in a['_frames']), 'market-frame-int32', name)
    for raw in object_(pack.get('tiers')).values():
        for t in array(raw):
            t['min'] = rounded(t['min']) if number(t.get('min')) else 1
            require(-2147483648 <= t['min'] <= 2147483647, 'market-tier-int32')
    timings = object_(pack.get('timings'))
    for k in ('minDisplay','autoReturn','playMs'):
        if k in timings:
            timings[k] = {n:rounded(v) for n,v in object_(timings[k]).items() if number(v) and v > 0}
    if number(timings.get('wakeMs')): timings['wakeMs'] = rounded(timings['wakeMs'])
    pool = pack.get('idlePool')
    for item in pool if isinstance(pool,list) else array(object_(pool).get('anims')):
        item['ms'] = rounded(item['ms']) if number(item.get('ms')) else 0
    # PetPack.parse's permissive numeric/default rules are not the App's import
    # gate. Check the emitted manifest after normalization, without requiring
    # every authored number to have been integral before normalization.
    app_import_compatible(pack)
    return pack


def app_import_compatible(pack):
    """The c76 PetLibrary.overlayPackProblem gate; no parser behavior changes.

    Called on normalized market output. A local-import comparison may call it
    on the authored manifest, but must still run validate() first.
    """
    def whole(v, minimum=0, maximum=1 << 30):
        return number(v) and v == math.trunc(v) and minimum <= v <= maximum
    def depth(v):
        children = v.values() if isinstance(v, dict) else v if isinstance(v, list) else None
        return 0 if children is None else 1 + max((depth(x) for x in children), default=0)
    def f32(v):
        try:
            value = struct.unpack('f', struct.pack('f', v))[0]
            require(math.isfinite(value), 'app-import-geometry')
            return value
        except (OverflowError, struct.error) as e:
            raise Denied('app-import-geometry') from e
    require(isinstance(pack, dict) and depth(pack) <= 60, 'app-import-depth')
    scale = pack.get('scale')
    if scale is None: scale = 1
    require(whole(scale, 1, 4096), 'app-import-scale')
    canvas = object_(pack.get('canvas'))
    require(all(whole(canvas.get(k), 1) for k in ('w','h')), 'app-import-canvas')
    require(isinstance(pack.get('animations'), dict), 'app-import-animations')
    for name, a in pack['animations'].items():
        require(isinstance(a, dict), 'app-import-animation', name)
        require(all(whole(a.get(k), 1, 4096) for k in ('frameW','frameH','cols')), 'app-import-cell', name)
        box = object_(a.get('box'))
        require(all(number(box.get(k)) for k in ('w','h')), 'app-import-geometry', name)
        for k, axis in (('frameW','w'), ('frameH','h')):
            # scale is already an integer <=4096, hence exact in Float32.
            require(a[k] == math.trunc(f32(f32(box[axis])*scale)), 'app-import-geometry', name)
        require(isinstance(a.get('frames'), list), 'app-import-frames', name)
        for frame in a['frames']:
            require(isinstance(frame, dict) and whole(frame.get('i')) and whole(frame.get('ms'), 1),
                    'app-import-frames', name)


def read_member(archive, data, entry, cap):
    """Verify actual member bytes without ZipExtFile's size-truncating inflater."""
    require(0 <= entry.file_size <= cap, 'archive-member-size', entry.filename)
    # Keep zipfile's local-name, flags and overlap checks, but never read through
    # ZipExtFile: its read/flush can inflate beyond a forged declared file_size.
    with archive.open(entry):
        pass
    offset = entry.header_offset
    require(0 <= offset <= len(data)-30, 'archive-header', entry.filename)
    name_size, extra_size = struct.unpack_from('<HH', data, offset+26)
    start = offset+30+name_size+extra_size
    end = start+entry.compress_size
    require(start <= end <= archive.start_dir <= len(data), 'archive-member-range', entry.filename)
    if entry.compress_type == zipfile.ZIP_STORED:
        require(entry.compress_size == entry.file_size, 'archive-member-size', entry.filename)
        result = data[start:end]  # Already bounded by the real span and cap.
    else:
        require(entry.compress_type == zipfile.ZIP_DEFLATED, 'archive-encoding', entry.filename)
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        result = bytearray()
        at, pending = start, b''
        while not inflater.eof:
            if not pending and at < end:
                stop = min(at+65536, end)
                pending = data[at:stop]
                at = stop
            # Allow only one byte beyond the declared/resource budget, so a lie
            # is detected instead of silently truncating valid PNG/JSON prefixes.
            size = min(65536, entry.file_size-len(result)+1, cap-len(result)+1)
            chunk = inflater.decompress(pending, size)
            require(len(chunk) <= entry.file_size-len(result), 'archive-member-size', entry.filename)
            result.extend(chunk)
            require(chunk or inflater.eof or len(inflater.unconsumed_tail) < len(pending),
                    'archive-deflate-truncated', entry.filename)
            pending = inflater.unconsumed_tail
        # Do not flush: only a genuine DEFLATE EOF at the exact compressed span
        # is valid. Trailing/concatenated streams and early EOF are rejected.
        require(not inflater.unused_data and not pending and at == end,
                'archive-deflate-trailing', entry.filename)
        require(len(result) == entry.file_size, 'archive-member-size', entry.filename)
        result = bytes(result)
    require(zlib.crc32(result) & 0xffffffff == entry.CRC, 'archive-member-crc', entry.filename)
    return result


def normalize(data, market=True):
    require(len(data) <= L['archiveBytes'], 'archive-size')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            require(len(entries) <= L['archiveEntries'], 'archive-entries')
            require(sum(e.file_size for e in entries) <= L['archiveExpandedBytes'], 'archive-expanded-size')
            files, seen = {}, set()
            for e in entries:
                name = e.orig_filename
                parts = name.rstrip('/').split('/')
                alias = unicodedata.normalize('NFC', name).casefold()
                require(name and not name.startswith('/') and '\\' not in name and '\0' not in name
                        and all(p not in ('', '.', '..') and ':' not in p for p in parts), 'archive-path', name)
                require(alias not in seen, 'archive-duplicate', name)
                seen.add(alias)
                kind = stat.S_IFMT(e.external_attr >> 16)
                require(kind in (0, stat.S_IFDIR if e.is_dir() else stat.S_IFREG), 'archive-type', name)
                require(not e.flag_bits & 1 and e.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'archive-encoding', name)
                if not e.is_dir():
                    files[name] = e
            candidates = [n for n in files if n == 'pack.json' or re.fullmatch(r'[^/]+/pack\.json', n)]
            require(len(candidates) == 1, 'archive-pack-count')
            pack_name = candidates[0]; prefix = pack_name[:-9]
            require(files[pack_name].file_size <= L['packJsonBytes'], 'pack-size')
            pack = parse_json(read_member(archive, data, files[pack_name], L['packJsonBytes']), L['packJsonBytes'])
            animations, states = validate(pack, market)
            encoded, sizes, total = {}, {}, 0
            names = sorted({a['sheet'] for a in animations.values()})
            require(len({unicodedata.normalize('NFC', n).casefold() for n in names}) == len(names), 'sheet-alias')
            for name in names:
                e = files.get(prefix+name)
                require(e is not None, 'sheet-missing', name)
                require(e.file_size <= L['sheetBytes'], 'sheet-size', name)
                require(total+e.file_size <= L['totalSheetBytes'], 'sheet-total-size')
                raw = read_member(archive, data, e, min(L['sheetBytes'], L['totalSheetBytes']-total)); total += len(raw)
                encoded[name], image = png(raw, name)
                sizes[name] = image.size
                image.close()
            require(sum(map(len, encoded.values())) <= L['totalSheetBytes'], 'sheet-normalized-total-size')
            for name, a in animations.items():
                w, h = sizes[a['sheet']]
                require(a['cols']*a['frameW'] <= w and (max(i for i, _ in a['_frames'])//a['cols']+1)*a['frameH'] <= h, 'sheet-frame-bounds', name)
                a['_pixelArt'] = pack.get('pixelArt') is not False
            if market:
                pack = market_manifest(pack, animations)
            manifest = canonical(pack)
            require(len(manifest) <= L['packJsonBytes'], 'pack-normalized-size')
            out = io.BytesIO()
            with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
                for name, content in [('pack.json', manifest), *sorted(encoded.items())]:
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.create_system = 3; info.external_attr = (stat.S_IFREG | 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    target.writestr(info, content)
            static, animated = previews(animations, states, encoded)
            return {'pack': pack, 'zip': out.getvalue(), 'png': static, 'gif': animated,
                    'dropped': sorted(set(files)-{pack_name, *(prefix+n for n in names)}),
                    'rulesSha256': sha((Path(__file__).resolve().parents[1] / 'schema/pet-pack.rules.json').read_bytes())}
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as e:
        raise Denied('archive-invalid') from e
