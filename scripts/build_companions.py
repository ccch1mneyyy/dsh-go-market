"""Build reviewed data-only companion catalogues; never fetch submission URLs."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from pet_pack import Denied, L, canonical, normalize, object_, parse_json, require, sha

HEX = re.compile(r'[0-9a-f]{64}\Z')
RELEASE_RECORD_CAP = 65536
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?\Z')
OWNER = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?\Z')
# Deliberately a small, redistributable artwork/data licence profile. A different
# licence requires a maintainer policy/code change, not an author-supplied bypass.
LICENSES = {'CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause'}

def version_key(value):
    require(isinstance(value, str) and len(value) <= 80 and bool(VERSION.fullmatch(value)), 'metadata-version')
    m = VERSION.fullmatch(value)
    pre = m[4]
    return (*map(int, m.group(1, 2, 3)), pre is None,
            tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split('.')) if pre else ())

def valid_id(value):
    return isinstance(value, str) and len(value) <= 40 and not value.startswith('user-') and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value))

def text(value, cap=256):
    return isinstance(value, str) and value.strip() and len(value) <= cap and not any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff for c in value)

def https_source(value):
    # Deliberately a conservative subset of the Worker's WHATWG URL grammar.
    # This is syntax validation only: no DNS lookup or HTTP request is made.
    from urllib.parse import urlsplit
    from ipaddress import IPv4Address, IPv6Address
    if not text(value, 2048) or not value.startswith('https://') or '\\' in value or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        port = url.port  # Access validates numeric form and the 0..65535 range.
        if not host or '@' in url.netloc or '%' in host: return False
        if ':' in host:
            if not re.fullmatch(r'\[[0-9A-Fa-f:.]+\](?::[0-9]+)?', url.netloc): return False
            IPv6Address(host)
        else:
            if not re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]+)?', url.netloc): return False
            host = host.removesuffix('.')
            if re.fullmatch(r'[0-9.]+', host):
                IPv4Address(host)
            else:
                labels = host.split('.')
                if len(host) > 253 or not re.match(r'[A-Za-z]', labels[-1]): return False
                if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', s) for s in labels): return False
                # Validate ASCII Punycode labels; raw Unicode hosts must be
                # supplied as A-labels so parser normalization cannot diverge.
                if host.encode('ascii').decode('idna').encode('idna').decode('ascii').lower() != host.lower(): return False
        return port is None or 0 <= port <= 65535
    except (ValueError, UnicodeError):
        return False

def metadata(value, kind, identity, version):
    require(isinstance(value, dict) and type(value.get('schema')) is int and value['schema'] == 1, 'metadata-schema')
    key = 'id' if kind == 'pets' else 'moc'
    require(value.get(key) == identity and (valid_id(identity) if kind == 'pets' else bool(HEX.fullmatch(identity))), 'metadata-identity')
    require(value.get('version') == version, 'metadata-directory-version')
    version_key(version); version_key(value.get('minApp'))
    require(isinstance(value.get('owner'), str) and bool(OWNER.fullmatch(value['owner'])), 'metadata-owner')
    require(text(value.get('author')), 'metadata-author')
    require(value.get('license') in LICENSES, 'metadata-license')
    require(https_source(value.get('source')), 'metadata-source')
    rights = object_(value.get('rights'))
    require(rights.get('redistribute') is True and rights.get('generalAudience') is True, 'metadata-rights-declaration')
    if kind == 'pets':
        require(all(text(object_(value.get('title')).get(k), 120) for k in ('zh', 'en')), 'metadata-title')
    return value


# These semantic names are already consumed by the c76 mainline stage. Keeping
# the prior C700 arbitrary-name/toggles grammar would publish ignored behavior.
PARAMS = set('ParamAngleX ParamAngleY ParamAngleZ ParamBodyAngleX ParamBodyAngleY ParamBodyAngleZ ParamBreath ParamEyeLOpen ParamEyeROpen ParamEyeBallX ParamEyeBallY ParamEyeSmile ParamMouthOpenY ParamMouthForm ParamBrowLY ParamBrowRY ParamBrowLAngle ParamBrowRAngle'.split())
EMOTIONS = set('calm happy shy sad angry surprised confused smug sleepy worried'.split())
ACTIONS = set('nod nodSmall shake tilt tiltLeft lookUp recoil duck sway stretch yawn wave'.split())
ZONES = set('head face body tail legs'.split())

def adapter(value, moc):
    require(isinstance(moc,str) and bool(HEX.fullmatch(moc)) and isinstance(value, dict)
            and type(value.get('adapter')) is int and value['adapter'] == 1 and value.get('moc') == moc, 'adapter-identity')
    # Publication profile for c76 companion_adapt.dart / stage.js. The market
    # has no model/probe: the App must recheck target IDs and ranges at install.
    for k in ('params','emotions','actions','framing','pose'):
        require(k not in value or isinstance(value[k],dict), 'adapter-container', k)
    for k in ('zones','tail'):
        require(k not in value or isinstance(value[k],list), 'adapter-container', k)
    allowed = {'adapter','moc','params','emotions','actions','zones','framing','tail','pose','notes'}
    require(set(value) <= allowed, 'adapter-field')
    def ident(v):
        require(text(v, 160), 'adapter-id')
    def numeric(v, lo, hi):
        from pet_pack import number
        require(number(v) and lo <= v <= hi, 'adapter-range')
    for name, raw in object_(value.get('params')).items():
        require(name in PARAMS, 'adapter-param-name')
        require(isinstance(raw, dict) and set(raw) <= {'id','scale','offset'}, 'adapter-param')
        targets = raw.get('id')
        if isinstance(targets, list):
            require(bool(targets), 'adapter-id')
            for target in targets: ident(target)
        else: ident(targets)
        if 'scale' in raw:
            numeric(raw['scale'], -1000, 1000)
            require(raw['scale'] != 0, 'adapter-scale')
        if 'offset' in raw: numeric(raw['offset'], -1000, 1000)
    for name, raw in object_(value.get('emotions')).items():
        require(name in EMOTIONS, 'adapter-emotion-name')
        require(isinstance(raw, dict) and set(raw) <= {'expression','face'}, 'adapter-emotion')
        if 'expression' in raw: ident(raw['expression'])
        require('face' not in raw or isinstance(raw['face'],dict), 'adapter-container','face')
        for key, val in object_(raw.get('face')).items(): ident(key); numeric(val,-1000,1000)
    for name, raw in object_(value.get('actions')).items():
        require(name in ACTIONS, 'adapter-action-name')
        require(isinstance(raw, dict) and set(raw) == {'motion'}, 'adapter-action'); ident(raw['motion'])
    for raw in value.get('zones', []):
        require(isinstance(raw, dict) and {'id','from','to'} <= set(raw) <= {'id','from','to','xFrom','xTo'}, 'adapter-zone')
        require(isinstance(raw['id'],str) and raw['id'] in ZONES, 'adapter-zone')
        numeric(raw['from'],0,1); numeric(raw['to'],0,1)
        for key in ('xFrom','xTo'):
            if key in raw: numeric(raw[key],-1.5,1.5)
        if 'xFrom' in raw and 'xTo' in raw: require(raw['xFrom'] < raw['xTo'], 'adapter-zone')
        require(raw['from'] < raw['to'], 'adapter-zone')
    framing = object_(value.get('framing'))
    require(set(framing) <= {'zoom','y'}, 'adapter-framing')
    if 'zoom' in framing: numeric(framing['zoom'], .3, 3)
    if 'y' in framing: numeric(framing['y'], -1, 1)
    for v in value.get('tail', []): ident(v)
    for name, amount in object_(value.get('pose')).items(): ident(name); numeric(amount,-1000,1000)
    if 'notes' in value: require(text(value['notes'], 4000), 'adapter-notes')
    # Reject wrong container types instead of silently discarding a whole table.
    for k in ('params','emotions','actions','framing','pose'):
        require(k not in value or isinstance(value[k],dict), 'adapter-container', k)
    for k in ('zones','tail'):
        require(k not in value or isinstance(value[k],list), 'adapter-container', k)
    require(len(canonical(value)) <= 262144, 'adapter-size')
    return canonical(value)

def regular(path):
    require(path.is_file() and not path.is_symlink(), 'source-regular', str(path))
    return path

def file_json(path, cap=16384):
    regular(path); require(path.stat().st_size <= cap, 'source-size', str(path))
    return parse_json(path.read_bytes(), cap)

def validate_policy(policy):
    # v1 approved only artifact bytes. It cannot authorize entry metadata and
    # must never be silently upgraded into a v2 release approval.
    require(isinstance(policy, dict) and type(policy.get('schema')) is int and policy['schema'] == 2,
            'policy-schema-v2-required')
    require(set(policy) == {'schema','pets','adapters','withdrawnPets','withdrawnAdapters'}, 'policy-shape')
    for kind in ('pets','adapters'):
        owners = policy[kind]
        require(isinstance(owners,dict), 'policy-shape')
        for identity, permit in owners.items():
            require(valid_id(identity) if kind == 'pets' else isinstance(identity,str) and bool(HEX.fullmatch(identity)), 'policy-identity')
            require(isinstance(permit,dict) and set(permit) <= {'owner','approved'}
                    and isinstance(permit.get('owner'),str) and bool(OWNER.fullmatch(permit['owner'])), 'policy-owner')
            approved = permit.get('approved', {})
            require(isinstance(approved,dict), 'policy-approved')
            for version, approval in approved.items():
                version_key(version)
                require(isinstance(approval,dict) and set(approval) == {'schema','releaseSha256'}
                        and type(approval.get('schema')) is int and approval['schema'] == 2
                        and isinstance(approval.get('releaseSha256'),str) and bool(HEX.fullmatch(approval['releaseSha256'])),
                        'policy-approval-v2-required')


def build(root, output, policy, now=None, review=None):
    validate_policy(policy)
    now = now or datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    require(isinstance(now,str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z',now)), 'catalogue-time')
    try: datetime.fromisoformat(now.replace('Z','+00:00'))
    except ValueError as e: raise Denied('catalogue-time') from e
    require(output.resolve() != root.resolve(), 'output-is-source')
    import shutil
    for kind in ('pets','adapters'):
        dest=output/kind
        if dest.exists():
            require(dest.is_dir() and not dest.is_symlink(), 'output-directory')
            shutil.rmtree(dest)
    result, audit = {}, []
    for kind, key in (('pets','id'), ('adapters','moc')):
        tombs = policy['withdrawnPets' if kind == 'pets' else 'withdrawnAdapters']
        owners = policy[kind]
        require(isinstance(tombs,list) and len(tombs) <= 4000, 'policy-shape')
        blocked = set()
        for t in tombs:
            require(isinstance(t,dict) and set(t) == {key,'version','reason'} and text(t.get('reason'),1000), 'policy-tombstone')
            identity = t.get(key)
            require(valid_id(identity) if kind == 'pets' else isinstance(identity,str) and bool(HEX.fullmatch(identity)), 'policy-identity')
            version_key(t.get('version'))
            require((identity,t['version']) not in blocked, 'policy-duplicate-tombstone')
            blocked.add((identity,t['version']))
        selected = {}
        directory = root/kind
        if not directory.exists():
            entries = []
        else:
            require(directory.is_dir() and not directory.is_symlink(), 'source-directory')
            entries = sorted(directory.glob('*/*/entry.json'))
        for entry_path in entries:
            version_dir, identity_dir = entry_path.parent, entry_path.parent.parent
            require(not version_dir.is_symlink() and not identity_dir.is_symlink(), 'source-directory')
            identity, version = identity_dir.name, version_dir.name
            meta = metadata(file_json(entry_path), kind, identity, version)
            permit = owners.get(identity, {}); approved = permit.get('approved', {})
            require(not permit or permit.get('owner') == meta['owner'], 'owner-conflict', identity)
            base = f'{kind}/{identity}/{version}' if kind == 'pets' else f'{kind}/{identity}'
            if kind == 'pets':
                source = regular(version_dir/'pack.zip')
                require(source.stat().st_size <= L['archiveBytes'], 'archive-size')
                pack = normalize(source.read_bytes())
                require(pack['pack'].get('id') == identity, 'pack-market-id')
                require(all(pack['pack'].get(k) == meta[k] for k in ('author','license','source')), 'pack-market-metadata')
                artifact = pack['zip']; ext = 'zip'
            else:
                pack = None
                artifact = adapter(file_json(version_dir/'adapter.json',262144), identity); ext = 'json'
            blobs = [(artifact, ext)] + [(pack[k], k) for k in ('png','gif')] if pack else [(artifact, ext)]
            def descriptor(content, extension):
                require(len(content) <= (4*1024*1024 if extension in ('png','gif') else 50*1024*1024), 'artifact-size')
                digest = sha(content)
                return {'url':f'/market/{base}/{digest}.{extension}', 'sha256':digest, 'size':len(content)}
            row = {k:meta[k] for k in (key,'author','license','source','version','minApp')}
            row.update(descriptor(artifact, ext))
            if pack:
                row.update(title={k:meta['title'][k] for k in ('zh','en')}, pixelArt=pack['pack'].get('pixelArt') is not False,
                           preview={k:descriptor(pack[k],k) for k in ('png','gif')},
                           risk={'level':'low','flags':['data-only','maintainer-reviewed']})
            # Exactly the authored/derived public release semantics, plus the
            # owner and rights declaration the maintainer reviewed. Generated
            # time and trusted-policy withdrawals are separate governance state.
            release = {'schema':2, 'kind':kind, 'owner':meta['owner'],
                       'rights':{k:meta['rights'][k] for k in ('redistribute','generalAudience')}, 'entry':row}
            release_bytes = canonical(release)
            require(len(release_bytes) <= RELEASE_RECORD_CAP, 'approval-record-size')
            approval = {'schema':2, 'releaseSha256':sha(release_bytes)}
            if review and review.get('kind') == kind and review.get('id') == identity and review.get('version') == version:
                target = Path(review['directory']); target.mkdir(parents=True,exist_ok=True)
                (target/('pack.zip' if pack else 'adapter.json')).write_bytes(artifact)
                for media in ('png','gif') if pack else []:
                    (target/('preview.'+media)).write_bytes(pack[media])
                (target/'release.json').write_bytes(release_bytes)
                (target/'approval.json').write_bytes(canonical(approval))
            require(version not in approved or approved[version] == approval, 'approved-release-mismatch', base)
            state = 'withdrawn' if (identity,version) in blocked else 'approved' if approved.get(version) == approval else 'technical-ready'
            audit.append({'kind':kind, key:identity,'version':version,'sha256':row['sha256'],
                          'approval':approval,'release':release,'status':state,'dropped':pack['dropped'] if pack else []})
            if state != 'approved':
                continue
            for content, extension in blobs:
                path = descriptor(content, extension)['url'].removeprefix('/market/')
                dest = output/path; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(content)
            # Never mutate the approved release record when attaching dynamic
            # policy state to the published catalogue row.
            row = dict(row)
            if pack:
                require(sum(i == identity for i,v in blocked) <= 1000, 'blocked-versions-count')
                row['blockedVersions'] = sorted(v for i,v in blocked if i == identity)
            if identity not in selected or version_key(version)>version_key(selected[identity]['version']):
                selected[identity] = row
        require(len(selected) <= 1000, 'catalogue-count')
        catalogue = {'schema':1,'generatedAt':now,kind:sorted(selected.values(),key=lambda r:r[key]),'withdrawn':tombs}
        require(len(canonical(catalogue)) <= 2*1024*1024, 'catalogue-size')
        output.mkdir(parents=True,exist_ok=True)
        (output/f'{kind}.json').write_bytes(canonical(catalogue))
        result[kind] = catalogue
    return result, audit

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',default='.'); p.add_argument('--output',default='dist'); p.add_argument('--policy',default='companion-policy.json'); p.add_argument('--report',default='reports/companions.json')
    args=p.parse_args()
    report=Path(args.report)
    try:
        # Clear only this generated review output, never reuse a stale record
        # from a previous local/CI build after a failure.
        import shutil
        review_dir=Path('reports/companion-review')
        if review_dir.exists():
            require(review_dir.is_dir() and not review_dir.is_symlink(), 'review-directory')
            shutil.rmtree(review_dir)
        descriptor=Path('reports/submission.json')
        review=file_json(descriptor) if descriptor.exists() else None
        if isinstance(review,dict): review={**review,'directory':'reports/companion-review'}
        _, audit=build(Path(args.root),Path(args.output),file_json(Path(args.policy),1048576),review=review)
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_bytes(canonical({'schema':2,'passed':True,'rulesSha256':sha((Path(__file__).resolve().parents[1]/'schema/pet-pack.rules.json').read_bytes()),'results':audit}))
        print(json.dumps({'passed':True,'approved':sum(r['status']=='approved' for r in audit),'technicalReady':sum(r['status']=='technical-ready' for r in audit)}))
    except (Denied, TypeError, KeyError, OSError) as e:
        failed={'schema':2,'passed':False,'error':{'code':getattr(e,'code','build-error'),'path':getattr(e,'path','')}}
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_bytes(canonical(failed))
        print(json.dumps(failed),file=sys.stderr);sys.exit(1)
