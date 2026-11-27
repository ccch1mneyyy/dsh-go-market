import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { canonicalRelease, releaseApproval, readCompanionReview, companionApproved } from '../scripts/companion-approval.mjs';
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
function fixture(kind='adapters') {
  const id=kind==='pets'?'author-cat':'a'.repeat(64), key=kind==='pets'?'id':'moc', version='1.0.0';
  const bytes=Object.fromEntries((kind==='pets'?['pack.zip','preview.png','preview.gif']:['adapter.json']).map(name=>[name,Buffer.from('Synthetic '+name)]));
  const asset=name=>({url:`/market/${kind}/${id}/${kind==='pets'?version+'/':''}${digest(bytes[name])}.${name.split('.').at(-1)}`,sha256:digest(bytes[name]),size:bytes[name].length});
  const entry={ [key]:id, version, author:'Reviewed author 🐳',license:'CC0-1.0',source:'https://example.org/art',minApp:'1.0.13',...asset(kind==='pets'?'pack.zip':'adapter.json') };
  if(kind==='pets')Object.assign(entry,{title:{zh:'猫',en:'Cat'},pixelArt:true,preview:{png:asset('preview.png'),gif:asset('preview.gif')},risk:{level:'low',flags:['data-only','maintainer-reviewed']}});
  const release={schema:2,kind,owner:'author',rights:{redistribute:true,generalAudience:true},entry};
  const approval=releaseApproval(release), item={kind,id,version};
  const audit={schema:2,passed:true,results:[{kind,[key]:id,version,status:'approved',sha256:entry.sha256,release,approval}]};
  const policy={schema:2,pets:{},adapters:{},withdrawnPets:[],withdrawnAdapters:[]};
  policy[kind][id]={owner:'author',approved:{[version]:approval}};
  const review={release:structuredClone(release),approval:structuredClone(approval),files:Object.fromEntries(Object.entries(bytes).map(([name,data])=>[name,{size:data.length,sha256:digest(data)}]))};
  return {item,audit,policy,review,bytes};
}
const eligible=f=>companionApproved(f.item,f.audit,f.policy,f.review);

test('CI eligibility binds metadata and rights to the exact reviewed v2 release',()=>{
  for(const kind of ['pets','adapters']) {
    assert(eligible(fixture(kind)));
    for(const field of ['author','license','source','minApp','version',kind==='pets'?'id':'moc']) {
      const f=fixture(kind), row=f.audit.results[0];
      row.release.entry[field]+='changed';
      // A stale or forged status and unchanged artifact digest are insufficient.
      assert.equal(row.status,'approved');assert(!eligible(f),`${kind}:${field}`);
    }
    for(const mutate of [r=>r.owner='other',r=>r.rights.generalAudience=false,r=>r.entry.size++,
      r=>r.entry.sha256='b'.repeat(64),r=>r.entry.url+='/other']) {
      const f=fixture(kind);mutate(f.audit.results[0].release);assert(!eligible(f));
    }
  }
  for(const mutate of [r=>r.entry.title.zh='换标题',r=>r.entry.title.en='New title',r=>r.entry.pixelArt=false,
    r=>r.entry.preview.png.sha256='b'.repeat(64),r=>r.entry.preview.gif.size++]) {
    const f=fixture('pets');mutate(f.audit.results[0].release);assert(!eligible(f));
  }
});

test('a report cannot grant approval without matching trusted policy and exact review bytes',()=>{
  for(const mutate of [f=>f.policy.schema=1,
    f=>f.policy.adapters[f.item.id].approved[f.item.version]=f.audit.results[0].sha256,
    f=>f.audit.schema=1,f=>f.audit.passed=false,
    f=>f.audit.results.push(structuredClone(f.audit.results[0])),
    f=>f.review.release.entry.author='different review',
    f=>f.review.approval={schema:2,releaseSha256:'b'.repeat(64)},
    f=>f.review.files['adapter.json'].sha256='b'.repeat(64),
    f=>f.review.files['adapter.json'].size++,
    f=>f.audit.results[0].status='technical-ready',
    f=>f.policy.withdrawnAdapters.push({moc:f.item.id,version:f.item.version,reason:'withdrawn'}),
  ]) {const f=fixture();mutate(f);assert(!eligible(f));}
  const changed=fixture();changed.audit.results[0].release.entry.author='New author';
  const next=releaseApproval(changed.audit.results[0].release);
  changed.audit.results[0].approval=next;changed.review.release=structuredClone(changed.audit.results[0].release);changed.review.approval=next;
  assert(!eligible(changed)); // Recomputed artifacts/report do not modify policy.
  changed.policy.adapters[changed.item.id].approved[changed.item.version]=next;
  assert(eligible(changed)); // Only this trusted maintenance change authorizes it.
  assert(companionApproved(null,null,null,null));
  assert(!companionApproved(undefined,null,null,null));
});

test('the uploaded review record and physical artifacts are read and verified by the CI gate',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'release-review-'));
  try {
    const f=fixture('pets');
    await writeFile(join(directory,'release.json'),canonicalRelease(f.review.release));
    await writeFile(join(directory,'approval.json'),JSON.stringify(f.review.approval));
    for(const [name,bytes] of Object.entries(f.bytes))await writeFile(join(directory,name),bytes);
    f.review=await readCompanionReview(directory);assert(eligible(f));
    const changed=Buffer.from(f.bytes['preview.png']);changed[0]^=1;
    await writeFile(join(directory,'preview.png'),changed);
    f.review=await readCompanionReview(directory);assert(!eligible(f));
    await writeFile(join(directory,'pack.zip'),Buffer.from('wrong size'));
    await assert.rejects(readCompanionReview(directory),/Invalid review artifact/);
  } finally {await rm(directory,{recursive:true,force:true});}
});

test('real Python technical-review, v2 policy, rebuild and JavaScript CI gate agree for pet and adapter',async()=>{
  const directory=await mkdtemp(join(tmpdir(),'release-python-ci-'));
  try {
    const python=`from pathlib import Path
import json,sys
sys.path[:0]=[str(Path('scripts').resolve()),str(Path('test').resolve())]
from test_release_approval import ReleaseApprovalTests
from build_companions import build
from pet_pack import canonical
root=Path(sys.argv[1]);out=[]
for kind in ('pets','adapters'):
 source=root/kind;identity,entry,path,policy=ReleaseApprovalTests().setup_release(source,kind)
 review=source/'review';item={'kind':kind,'id':identity,'version':'1.0.0'}
 descriptor={**item,'directory':str(review)}
 _,audit=build(source,source/'dist',policy,'2026-11-08T00:00:00Z',review=descriptor)
 assert audit[0]['status']=='technical-ready'
 policy[kind][identity]={'owner':entry['owner'],'approved':{'1.0.0':audit[0]['approval']}}
 _,audit=build(source,source/'dist',policy,'2026-11-08T00:00:01Z',review=descriptor)
 out.append({'item':item,'policy':policy,'audit':{'schema':2,'passed':True,'results':audit},'reviewPath':str(review)})
(root/'result.json').write_bytes(canonical(out))
`;
    const result=spawnSync('python',['-c',python,directory],{cwd:new URL('..',import.meta.url),encoding:'utf8'});
    assert.equal(result.status,0,result.stdout+result.stderr);
    for(const f of JSON.parse(await readFile(join(directory,'result.json'),'utf8'))) {
      f.review=await readCompanionReview(f.reviewPath);
      assert(eligible(f),f.item.kind);
      f.review.release.entry.minApp='0.0.1';
      assert(!eligible(f),f.item.kind+' mutated review');
    }
  } finally {await rm(directory,{recursive:true,force:true});}
});

test('the trusted workflow uses the bound gate and uploads the exact review on build failure',async()=>{
  const source=await readFile(new URL('../.github/workflows/check.yml',import.meta.url),'utf8');
  assert.match(source,/companionApproved\(item,audit,policy,review\)/);
  assert.match(source,/await readCompanionReview\('reports\/companion-review'\)/);
  assert.match(source,/if: always\(\) && steps\.entry\.outcome == 'success'/);
  assert(!source.includes('audit.results.some'));
});



test('release canonical bytes are bounded and preserve scalar text without Unicode normalization',()=>{
  const f=fixture();
  f.review.release.entry.author='\ufeff\u0085🐳';
  const text=canonicalRelease(f.review.release);
  assert(text.endsWith('\n'));assert(text.includes('\ufeff\u0085🐳'));
  const a=structuredClone(f.review.release),b=structuredClone(f.review.release);
  a.entry.author='é';b.entry.author='e\u0301';
  assert.notDeepEqual(releaseApproval(a),releaseApproval(b));
  for(const author of ['\ud800','\udfff','x'.repeat(65536)]) {
    const value=structuredClone(f.review.release);value.entry.author=author;
    assert.throws(()=>canonicalRelease(value));
  }
});
