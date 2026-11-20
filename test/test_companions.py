import copy
import io
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pet_pack import Denied, L, canonical, normalize, png, sha, validate, market_manifest, app_import_compatible, parse_json, rounded, read_member
from build_companions import adapter, build, valid_id, version_key, text, https_source

FIXTURES=json.loads((Path(__file__).parent/'fixtures/pet-pack-v1.json').read_text())
BASE=copy.deepcopy(FIXTURES['cases'][1]['pack'])

def image_bytes(size=(2,2)):
    im=Image.new('RGBA',size,(255,0,0,128)); b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()

def package(pack=None, extras=None, prefix='', image=None):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(prefix+'pack.json',canonical(pack or BASE))
        z.writestr(prefix+'cat.png',image or image_bytes())
        for name,data in (extras or {}).items():z.writestr(name,data)
    return b.getvalue()

def mutated_member(name, raw, *, declared=None, crc=None, method=zipfile.ZIP_DEFLATED, transform=None):
    # Put the attacked member last, then rewrite its compressed span and both
    # headers. The ordinary stdlib writer supplies every other ZIP structure.
    members={'pack.json':canonical(BASE),'cat.png':image_bytes()}
    members[name]=raw
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',method) as z:
        for key in [k for k in members if k!=name]+[name]:z.writestr(key,members[key])
    data=b.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        entry=z.getinfo(name);central=z.start_dir
    local=entry.header_offset
    a,b=struct.unpack_from('<HH',data,local+26);start=local+30+a+b
    payload=data[start:start+entry.compress_size]
    payload=transform(payload) if transform else payload
    delta=len(payload)-entry.compress_size
    data=bytearray(data[:start]+payload+data[start+entry.compress_size:])
    at=central+delta
    while data[at:at+4]==b'PK\x01\x02':
        n,e,c=struct.unpack_from('<HHH',data,at+28)
        if data[at+46:at+46+n]==name.encode():break
        at+=46+n+e+c
    else:raise AssertionError('fixture central member missing')
    size=len(raw) if declared is None else declared
    checksum=zlib.crc32(raw) if crc is None else crc
    struct.pack_into('<III',data,local+14,checksum,len(payload),size)
    struct.pack_into('<III',data,at+16,checksum,len(payload),size)
    struct.pack_into('<I',data,data.rfind(b'PK\x05\x06')+16,central+delta)
    return bytes(data)


class ArchiveReadTests(unittest.TestCase):
    def test_forged_sizes_never_inflate_large_png_or_json_prefix(self):
        factory=zlib.decompressobj
        for name,prefix in [('cat.png',image_bytes()),('pack.json',canonical(BASE))]:
            for method in (zipfile.ZIP_DEFLATED,zipfile.ZIP_STORED):
                data=mutated_member(name,prefix+b'\0'*(16*1024*1024),declared=len(prefix),crc=zlib.crc32(prefix),method=method)
                calls=[]
                class Recorded:
                    def __init__(self,*args,**kwargs):self.value=factory(*args,**kwargs)
                    def __getattr__(self,key):return getattr(self.value,key)
                    def decompress(self,raw,max_length=0):
                        if not 0<max_length<=65536:raise AssertionError('unbounded inflate request')
                        out=self.value.decompress(raw,max_length)
                        calls.append((len(raw),max_length,len(out)))
                        return out
                    def flush(self,*args):raise AssertionError('unbounded flush')
                with self.subTest(name=name,method=method),patch('pet_pack.zlib.decompressobj',Recorded):
                    with self.assertRaises(Denied) as error:normalize(data)
                    self.assertEqual(error.exception.code,'archive-member-size')
                    self.assertTrue(all(i<=65536 and o<=n for i,n,o in calls))
                    self.assertLessEqual(sum(o for i,n,o in calls),len(canonical(BASE))+len(image_bytes())+1)
    def test_deflate_must_end_exactly_without_trailing_streams(self):
        prefix=image_bytes()
        for transform,code in [(lambda raw:raw[:-1],'archive-deflate-truncated'),
                               (lambda raw:raw+b'padding','archive-deflate-trailing')]:
            with self.subTest(code=code),self.assertRaises(Denied) as error:
                normalize(mutated_member('cat.png',prefix,transform=transform))
            self.assertEqual(error.exception.code,code)
    def test_actual_size_and_crc_must_match(self):
        prefix=image_bytes()
        for kwargs,code in [({'declared':len(prefix)+1},'archive-member-size'),
                            ({'crc':zlib.crc32(prefix)^1},'archive-member-crc')]:
            with self.subTest(code=code),self.assertRaises(Denied) as error:
                normalize(mutated_member('cat.png',prefix,**kwargs))
            self.assertEqual(error.exception.code,code)
    def test_valid_stored_deflate_descriptor_zip64_and_unicode(self):
        class Stream(io.BytesIO):
            def seek(self,*args):raise io.UnsupportedOperation('stream')
        expected=normalize(package())['zip']
        for method in (zipfile.ZIP_DEFLATED,zipfile.ZIP_STORED):
            for streaming in (False,True):
                for zip64 in (False,True):
                    b=Stream() if streaming else io.BytesIO()
                    with zipfile.ZipFile(b,'w',method) as z:
                        for name,raw in [('猫/pack.json',canonical(BASE)),('猫/cat.png',image_bytes())]:
                            with z.open(name,'w',force_zip64=zip64) as member:member.write(raw)
                    with self.subTest(method=method,streaming=streaming,zip64=zip64):
                        self.assertEqual(normalize(b.getvalue())['zip'],expected)
    def test_valid_multi_chunk_deflate_output_and_input(self):
        import random
        for raw in (b'abcd'*100000,random.Random(7).randbytes(262144)):
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('data',raw)
            data=b.getvalue()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                self.assertEqual(read_member(z,data,z.getinfo('data'),len(raw)),raw)


class PackTests(unittest.TestCase):
    def rejects(self, data, code):
        with self.assertRaises(Denied) as e:normalize(data)
        self.assertEqual(e.exception.code,code)
    def test_dart_binary64_rounding_boundaries_and_int64_clamp(self):
        cases=[(math.nextafter(.5,0),0),(-math.nextafter(.5,0),0),(.5,1),(-.5,-1),
               (math.nextafter(.5,1),1),(-math.nextafter(.5,1),-1),
               (math.nextafter(1.5,0),1),(-math.nextafter(1.5,0),-1),(1.5,2),(-1.5,-2),
               (math.nextafter(1.5,2),2),(-math.nextafter(1.5,2),-2),
               (2**53-1,2**53-1),(2**53+1,2**53),(-(2**53+1),-2**53),
               (math.nextafter(float(2**63),0),2**63-1024),(2**63,2**63-1),
               (-2**63,-2**63),(1e100,2**63-1),(-1e100,-2**63)]
        for value,expected in cases:
            with self.subTest(value=value):self.assertEqual(rounded(value),expected)
        for field in ('frameW','frameH','cols'):
            p=copy.deepcopy(BASE);p['animations']['idle'][field]=math.nextafter(.5,0)
            with self.subTest(field=field),self.assertRaises(Denied):validate(p)
        p=copy.deepcopy(BASE);p['animations']['idle']['frames'][0]['i']=-math.nextafter(.5,0)
        self.assertEqual(validate(p)[0]['idle']['_frames'][0][0],0)
    def test_overflowed_numeric_values_cannot_become_defaults(self):
        p=copy.deepcopy(BASE);p['scale']=10**400
        with self.assertRaises(Denied) as error:parse_json(canonical(p))
        self.assertEqual(error.exception.code,'json-nonfinite')
        with self.assertRaises(Denied):validate(p)
        p['scale']='not numeric';validate(p)
    def test_android_float_multiplication_converts_both_operands(self):
        p=copy.deepcopy(BASE);p['scale']=16777219
        p['animations']['idle']['box'].update(w=1.7881389169360773e-7,h=1.7881389169360773e-7)
        self.rejects(package(p),'market-cell-box-scale')
    def test_shared_local_fixtures(self):
        self.assertEqual(FIXTURES['rulesRevision'],3)
        for c in FIXTURES['cases']:
            with self.subTest(c['name']):
                try: validate(c['pack']); actual=True
                except Denied: actual=False
                self.assertEqual(actual,c['parserValid'])
                try:
                    validate(c['pack'])
                    app_import_compatible(c['pack'])
                    app_actual = True
                except Denied: app_actual = False
                self.assertEqual(app_actual,c['appImportValid'])
                try:
                    a, _ = validate(c['pack'], market=True)
                    market_manifest(c['pack'], a)
                    market_actual = True
                except Denied: market_actual = False
                self.assertEqual(market_actual, c['marketValid'])
    def test_sheet_names_use_dart_utf16_length(self):
        p=copy.deepcopy(BASE)
        p['animations'][next(iter(p['animations']))]['sheet']='😀'*58+'.png'
        validate(p)
        p['animations'][next(iter(p['animations']))]['sheet']='😀'*59+'.png'
        with self.assertRaises(Denied) as error:validate(p)
        self.assertEqual(error.exception.code,'sheet-name')
    def test_json_lone_surrogate_is_strict_input_hardening(self):
        with self.assertRaises(Denied) as error:parse_json(b'{"name":"\\ud800"}')
        self.assertEqual(error.exception.code,'json-unicode')
    def test_market_metadata_counts_code_points_and_whole_value(self):
        self.assertTrue(text('😀'*256))
        self.assertFalse(text('x'+' '*256))
        self.assertFalse(text('\ud800'))
    def test_required_notices_survive_normalization(self):
        p=copy.deepcopy(BASE);p['licenseText']='Permission is hereby granted: synthetic fixture.';p['notice']='Copyright Synthetic Fixture Author'
        n=normalize(package(p,{'LICENSE':b'Permission is hereby granted: synthetic fixture.'}))
        self.assertEqual(n['pack']['licenseText'],p['licenseText']);self.assertEqual(n['pack']['notice'],p['notice'])
        self.assertIn('LICENSE',n['dropped'])
    def test_preview_pixel_art_fills_canvas_without_modifying_sheet(self):
        n=normalize(package());im=Image.open(io.BytesIO(n['png']))
        self.assertEqual(im.getbbox(),(0,0,256,256))
        with zipfile.ZipFile(io.BytesIO(n['zip'])) as z:self.assertEqual(Image.open(io.BytesIO(z.read('cat.png'))).size,(2,2))
    def test_float32_geometry_overflow_is_rejected(self):
        p=copy.deepcopy(BASE);p['animations'][next(iter(p['animations']))]['box']['w']=1e39
        with self.assertRaises(Denied):normalize(package(p))
    def test_market_geometry_is_additional(self):
        p=copy.deepcopy(BASE);p['scale']=2
        validate(p)
        self.rejects(package(p),'market-cell-box-scale')
    def test_deterministic_and_only_referenced_files(self):
        a=normalize(package(extras={'run.exe':b'code','unused.png':b'bad'}))
        b=normalize(package(prefix='author/'))
        self.assertEqual(a['zip'],b['zip'])
        self.assertEqual(a['dropped'],['run.exe','unused.png'])
        z=zipfile.ZipFile(io.BytesIO(a['zip']))
        self.assertEqual(z.namelist(),['pack.json','cat.png'])
        p=json.loads(z.read('pack.json'))
        self.assertEqual(p['scale'],1);self.assertTrue(p['pixelArt'])
        for ext in ('png','gif'):
            with Image.open(io.BytesIO(a[ext])) as im:im.load();self.assertEqual(im.size,(256,256))
    def test_dart_rounding_and_filtered_frames_are_explicit(self):
        p=copy.deepcopy(BASE);p['animations'][next(iter(p['animations']))]['frames']=[None,{'i':-.4,'ms':100.5}]
        out=normalize(package(p))
        self.assertEqual(out['pack']['animations']['idle']['frames'],[{'i':0,'ms':101}])
    def test_hostile_paths(self):
        for name in ('../run','/abs','C:/run','a\\b','a/../b'):
            with self.subTest(name):self.rejects(package(extras={name:b'x'}),'archive-path')
    def test_ambiguous_pack(self):
        self.rejects(package(extras={'other/pack.json':canonical(BASE)}),'archive-pack-count')
    def test_duplicate_alias(self):
        self.rejects(package(extras={'CAT.PNG':image_bytes()}),'archive-duplicate')
    def test_symlink(self):
        b=io.BytesIO(package())
        with zipfile.ZipFile(b,'a') as z:
            i=zipfile.ZipInfo('link');i.create_system=3;i.external_attr=0o120777<<16;z.writestr(i,'cat.png')
        self.rejects(b.getvalue(),'archive-type')
    def test_caps_before_decode(self):
        for field,cap,code in [('archiveBytes',1,'archive-size'),('archiveEntries',1,'archive-entries'),('archiveExpandedBytes',1,'archive-expanded-size'),('packJsonBytes',1,'pack-size'),('sheetBytes',1,'sheet-size'),('totalSheetBytes',1,'sheet-total-size')]:
            with self.subTest(field),patch.dict(L,{field:cap}):self.rejects(package(),code)
    def test_sheet_decoded_cap_boundary(self):
        encoded=image_bytes((4096,1024)); out,im=png(encoded)
        self.assertEqual(im.width*im.height*4,16777216)
        with self.assertRaises(Denied) as e:png(image_bytes((4096,1025)))
        self.assertEqual(e.exception.code,'sheet-decoded-size')
        with self.assertRaises(Denied):png(image_bytes((4097,1)))
    def test_png_crc_and_truncation(self):
        data=bytearray(image_bytes());data[-1]^=1
        self.rejects(package(image=bytes(data)),'png-crc')
        self.rejects(package(image=image_bytes()[:-12]),'png-truncated')
        self.rejects(package(image=image_bytes()+b'code'),'png-trailing')
    def test_full_decode_not_just_header(self):
        data=image_bytes();at=8;out=data[:8]
        while at<len(data):
            n=int.from_bytes(data[at:at+4],'big');kind=data[at+4:at+8];body=data[at+8:at+8+n]
            if kind==b'IDAT':body=b'not a zlib stream'
            out+=len(body).to_bytes(4,'big')+kind+body+(zlib.crc32(kind+body)&0xffffffff).to_bytes(4,'big');at+=12+n
        self.rejects(package(image=out),'png-zlib-invalid')
    def test_apng_rejected(self):
        b=io.BytesIO();a=Image.new('RGBA',(2,2),'red');a.save(b,format='PNG',save_all=True,append_images=[Image.new('RGBA',(2,2),'blue')],duration=100)
        self.rejects(package(image=b.getvalue()),'png-animated')
    def test_frame_bounds(self):
        p=copy.deepcopy(BASE);p['animations'][next(iter(p['animations']))]['frames'][0]['i']=1
        self.rejects(package(p),'sheet-frame-bounds')
    def test_json_duplicate_and_nonfinite(self):
        for raw in (b'{"id":1,"id":2}',b'{"a":NaN}',b'{"a":1e9999}'):
            with self.assertRaises(Denied):parse_json(raw)
    def test_unique_sheet_count(self):
        p=copy.deepcopy(BASE)
        for i in range(64):p['animations'][str(i)]={**p['animations'][next(iter(p['animations']))],'sheet':f'{i}.png'}
        with self.assertRaises(Denied) as e:validate(p)
        self.assertEqual(e.exception.code,'sheet-count')
    def test_local_nonascii_sheet_and_dot_rejection(self):
        p=copy.deepcopy(BASE);p['animations'][next(iter(p['animations']))]['sheet']='猫.png';validate(p)
        p['animations'][next(iter(p['animations']))]['sheet']='.cat.png'
        with self.assertRaises(Denied):validate(p)

class CatalogTests(unittest.TestCase):
    def setup_catalog(self,root):
        v=root/'pets/author-cat/1.0.0';v.mkdir(parents=True)
        meta={'schema':1,'id':'author-cat','version':'1.0.0','owner':'author','title':{'zh':'猫','en':'Cat'},'author':'Author','license':'CC0-1.0','source':'https://example.org/art','minApp':'1.0.13','rights':{'redistribute':True,'generalAudience':True}}
        (v/'entry.json').write_bytes(canonical(meta));(v/'pack.zip').write_bytes(package())
        return {'schema':2,'pets':{},'adapters':{},'withdrawnPets':[],'withdrawnAdapters':[]}
    def test_approval_exact_digest_gate_and_withdraw(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);policy=self.setup_catalog(root);out=root/'dist'
            results,audit=build(root,out,policy,'2026-11-07T19:00:00Z')
            self.assertEqual(results['pets']['pets'],[]);self.assertEqual(audit[0]['status'],'technical-ready')
            policy['pets']['author-cat']={'owner':'author','approved':{'1.0.0':audit[0]['approval']}}
            results,audit=build(root,out,policy,'2026-11-07T19:01:00Z');row=results['pets']['pets'][0]
            self.assertEqual(row['size'],len((out/row['url'].removeprefix('/market/')).read_bytes()))
            self.assertTrue(row['url'].endswith(row['sha256']+'.zip'))
            self.assertEqual(row['preview']['png']['sha256'],sha((out/row['preview']['png']['url'].removeprefix('/market/')).read_bytes()))
            policy['withdrawnPets']=[{'id':'author-cat','version':'1.0.0','reason':'Rights complaint'}]
            results,audit=build(root,out,policy,'2026-11-07T19:02:00Z')
            self.assertEqual(results['pets']['pets'],[]);self.assertFalse((out/'pets').exists())
    def test_approved_digest_cannot_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.setup_catalog(root);p['pets']['author-cat']={'owner':'author','approved':{'1.0.0':{'schema':2,'releaseSha256':'0'*64}}}
            with self.assertRaises(Denied) as e:build(root,root/'dist',p)
            self.assertEqual(e.exception.code,'approved-release-mismatch')
    def test_source_url_is_worker_compatible_https_subset(self):
        for source in ('https://example.org/a','https://example.org:443/a','https://127.0.0.1/a','https://[2001:db8::1]/a','https://xn--bcher-kva.example/a'):
            with self.subTest(source=source):self.assertTrue(https_source(source))
        for source in ('HTTPS://example.org/a','https://example.org:bad/a','https://exa mple.org/a','https://example.org:99999/a',
                       'https://exa|mple.org/a','https://example.999/a','https://999.999.999.999/a','https://user:pass@example.org/a','https://example.org\\evil/a'):
            with self.subTest(source=source):self.assertFalse(https_source(source))
    def test_id_normalization_injective_subset(self):
        for value in ('user-cat','a--b','A-cat','-cat','cat-','a'*41):self.assertFalse(valid_id(value))
        for value in ('cat','author-cat','a'*40):self.assertTrue(valid_id(value))
    def test_semver_order_and_invalid(self):
        self.assertLess(version_key('1.0.0-alpha.2'),version_key('1.0.0-alpha.10'))
        self.assertLess(version_key('1.0.0-rc.1'),version_key('1.0.0'))
        for v in ('1.0','v1.0.0','01.0.0','1.0.0-01','1.0.0+build','latest'):
            with self.assertRaises(Denied):version_key(v)
    def test_adapter_no_code_or_model(self):
        moc='a'*64
        valid={'adapter':1,'moc':moc,'params':{'ParamAngleX':{'id':'ANGLE_X','scale':-1,'offset':0}},'actions':{'wave':{'motion':'挥手'}},'framing':{'zoom':.86,'y':.06}}
        self.assertEqual(json.loads(adapter(valid,moc)),valid)
        for extra in ({'script':'code'},{'moc':'b'*64},{'params':[]},{'toggles':{'hide':'not-an-array'}},{'framing':{'zoom':0}},{'adapter':True}):
            with self.subTest(extra),self.assertRaises(Denied):adapter({**valid,**extra},moc)

if __name__=='__main__':unittest.main()
