import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { classify, companionSubmission, newer } from '../scripts/ci-companions.mjs';
const BASE='a'.repeat(40), HEAD='b'.repeat(40), prefix='pets/alice-cat/1.0.0';
function fixture() {
  const bytes=[Buffer.from(JSON.stringify({owner:'alice'})),Buffer.from('untrusted ZIP bytes')];
  const files=['entry.json','pack.zip'].map((p,i)=>({filename:`${prefix}/${p}`,status:'added',sha:String(i+1).repeat(40)}));
  const directories=['pets','alice-cat','1.0.0'].map((p,i)=>({tree:[{path:p,type:'tree',mode:'040000',sha:String(i+5).repeat(40)}]}));
  const last={tree:files.map((f,i)=>({path:f.filename.split('/').at(-1),type:'blob',mode:'100644',sha:f.sha,size:bytes[i].length}))};
  const trees=[...directories,last];
  let n=0;
  const blobs=bytes.map((b,i)=>({sha:files[i].sha,size:b.length,encoding:'base64',content:b.toString('base64')}));
  const calls=[];
  const github={rest:{git:{
    getCommit:async args=>{calls.push(args);assert.equal(args.commit_sha,HEAD);return {data:{sha:HEAD,tree:{sha:'4'.repeat(40)}}};},
    getTree:async args=>{calls.push(args);assert.equal(args.tree_sha,String(n+4).repeat(40));return {data:trees[n++]};},
    getBlob:async args=>{calls.push(args);return {data:blobs[files.findIndex(f=>f.sha===args.file_sha)]};},
  }}};
  return {files,trees,blobs,calls,github,options:{repository:{owner:'maintainer',repo:'market'},headRepository:{owner:'alice',repo:'fork'},base:BASE,head:HEAD,author:'alice'}};
}
async function sandbox(body) {
  const cwd=process.cwd(), dir=await mkdtemp(join(tmpdir(),'market-ci-'));
  try {process.chdir(dir);await writeFile('companion-policy.json',JSON.stringify({pets:{},adapters:{}}));await body();}
  finally {process.chdir(cwd);await rm(dir,{recursive:true,force:true});}
}
test('companion PR accepts exactly two immutable data files',async()=>sandbox(async()=>{
  const f=fixture(), result=await companionSubmission(f.github,f.options,f.files);
  assert.deepEqual(result.companion,{kind:'pets',id:'alice-cat',version:'1.0.0',paths:f.files.map(f=>f.filename)});
  assert.equal(result.writes[1].bytes.toString(),'untrusted ZIP bytes');
  assert(f.calls.every(c=>c.owner==='alice'&&c.repo==='fork'));
}));
test('companion PR rejects code, mixed identities, mutable releases and unsafe paths',()=>{
  const original=fixture().files;
  for(const files of [[],original.slice(0,1),[...original,{filename:'scripts/build_companions.py',status:'modified'}],
    original.map(f=>({...f,status:'modified'})), original.map(f=>({...f,filename:f.filename.replace('alice-cat','user-cat')})),
    original.map(f=>({...f,filename:f.filename.replace('alice-cat','a--b')})),
    original.map(f=>({...f,filename:f.filename.replace('1.0.0','01.0.0')})),
    [original[0],{...original[1],filename:original[1].filename+'/child'}],
    [original[0],{...original[1],filename:original[1].filename.replace('alice-cat','bob-cat')}],
  ]) assert.throws(()=>classify(files));
});
test('companion captured Git objects reject aliases, links, truncation and oversize before writing',async()=>sandbox(async()=>{
  for(const mutate of [f=>f.trees[1].tree[0].mode='120000', f=>f.trees[2].truncated=true,
    f=>f.trees[3].tree[1].mode='100755', f=>f.trees[3].tree[1].mode='120000',
    f=>f.trees[3].tree[1].size=67108865, f=>f.trees[3].tree[1].sha='f'.repeat(40),
    f=>f.blobs[0].size++, f=>f.blobs[0].encoding='utf8', f=>f.options.author='bob',
    f=>f.options.head='main', f=>f.trees[3].tree.push({path:'execute.js'}),
  ]) {const f=fixture();mutate(f);await assert.rejects(companionSubmission(f.github,f.options,f.files));}
}));
test('namespace ownership and increasing versions are enforced from trusted base history',async()=>sandbox(async()=>{
  await mkdir('pets/alice-cat/0.9.0',{recursive:true});
  await writeFile('pets/alice-cat/0.9.0/entry.json',JSON.stringify({owner:'bob'}));
  let f=fixture();await assert.rejects(companionSubmission(f.github,f.options,f.files),/another author/);
  await writeFile('pets/alice-cat/0.9.0/entry.json',JSON.stringify({owner:'alice'}));
  await writeFile('companion-policy.json',JSON.stringify({pets:{'alice-cat':{owner:'bob'}},adapters:{}}));
  f=fixture();await assert.rejects(companionSubmission(f.github,f.options,f.files),/Reserved identity/);
  await writeFile('companion-policy.json',JSON.stringify({pets:{},adapters:{}}));
  await mkdir('pets/alice-cat/2.0.0');await writeFile('pets/alice-cat/2.0.0/entry.json','{"owner":"alice"}');
  f=fixture();await assert.rejects(companionSubmission(f.github,f.options,f.files),/advance/);
}));
test('SemVer ordering handles arbitrary precision and prerelease ordering without floating-point loss',()=>{
  for(const [a,b] of [['1.0.0','1.0.0-rc.1'],['1.0.0-alpha.10','1.0.0-alpha.2'],['1.0.0-b','1.0.0-999'],['1.0.0-a.1','1.0.0-a'],['9007199254740993.0.0','9007199254740992.0.0']]) {assert(newer(a,b));assert(!newer(b,a));}
  assert(!newer('1.0.0','1.0.0'));
});
