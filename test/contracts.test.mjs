import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import Ajv from 'ajv/dist/2020.js';
const ajv=new Ajv();
ajv.addFormat('date-time',s=>/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(s)&&Number.isFinite(Date.parse(s)));
const schemas=Object.fromEntries(['pets','adapters'].map(k=>[k,ajv.compile(JSON.parse(readFileSync(new URL(`../schema/${k}-index.schema.json`,import.meta.url))))]));
const hash='a'.repeat(64), moc='b'.repeat(64), id='author-cat', ver='1.0.0', prefix=`/market/pets/${id}/${ver}/`;
const author={author:'作者',license:'CC0-1.0',source:'https://example.org/source',version:ver,minApp:'1.0.13'};
const asset=ext=>({url:prefix+hash+'.'+ext,sha256:hash,size:123});
const pet={...author,id,title:{zh:'猫',en:'Cat'},...asset('zip'),preview:{png:asset('png'),gif:asset('gif')},pixelArt:true,risk:{level:'low',flags:['data-only','maintainer-reviewed']},blockedVersions:[]};
const adapter={...author,moc,url:`/market/adapters/${moc}/${hash}.json`,sha256:hash,size:123};
const catalog=(kind,row)=>({schema:1,generatedAt:'2026-11-07T19:00:00Z',[kind]:[row],withdrawn:[]});
test('JSON schemas accept both catalogue examples and exact SemVer prereleases',()=>{
 for(const [kind,row] of [['pets',pet],['adapters',adapter]]) {
  assert(schemas[kind](catalog(kind,row)),JSON.stringify(schemas[kind].errors));
  assert(schemas[kind](catalog(kind,{...row,version:'2.0.0-rc.1'})));
 }
});
test('JSON schemas reject format drift and encode resource bounds',()=>{
 for(const v of ['1x0x0','01.0.0','1.0.0-01','1.0.0+build']) assert(!schemas.pets(catalog('pets',{...pet,version:v})));
 assert(!schemas.pets(catalog('pets',{...pet,title:{zh:'x'.repeat(121),en:'Cat'}})));
 assert(!schemas.pets(catalog('pets',{...pet,preview:{...pet.preview,png:{...pet.preview.png,size:4194305}}})));
 for(const generatedAt of ['2026-11-07T19:00:00.1Z','2026-11-07T19:00:00.123456Z','2026-11-07T19:00:00+00:00']) assert(!schemas.pets({...catalog('pets',pet),generatedAt}));
 assert(!schemas.pets({...catalog('pets',pet),pets:Array(1001).fill(pet)}));
 assert(!schemas.adapters({...catalog('adapters',adapter),withdrawn:Array(4001).fill({moc,version:ver,reason:'withdrawn'})}));
 assert(!schemas.adapters(catalog('adapters',{...adapter,url:`/market/adapters/${moc}/1.0.0/${hash}.json`})));
 assert(!schemas.pets(catalog('pets',{...pet,risk:{level:'high',flags:[]}})));
});
// Optional interoperation evidence: validates real catalogue output from Python,
// without requiring network access or committing anyone's artwork to the repo.
if(process.env.COMPANION_CONTRACT_DIST) test('Python builder output validates against JSON schemas',()=>{
 for(const kind of ['pets','adapters']) {
  const value=JSON.parse(readFileSync(`${process.env.COMPANION_CONTRACT_DIST}/${kind}.json`));
  assert(schemas[kind](value),JSON.stringify(schemas[kind].errors));
 }
});

test('committed examples are actual Python builder catalogues conforming to schema',()=>{
 for(const kind of ['pets','adapters']) {
  const value=JSON.parse(readFileSync(new URL(`./fixtures/${kind}-index.example.json`,import.meta.url)));
  assert(schemas[kind](value),JSON.stringify(schemas[kind].errors));
 }
});
