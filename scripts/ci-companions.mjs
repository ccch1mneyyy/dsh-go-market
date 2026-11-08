/** Decode only a two-file, immutable data submission. Never execute PR scripts. */
import { readFile, readdir, lstat } from 'node:fs/promises';
const SHA = /^[0-9a-f]{40}$/;
const ID = /^(?!user-)[a-z0-9]+(?:-[a-z0-9]+)*$/;
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][a-zA-Z0-9-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][a-zA-Z0-9-]*))*)?$/;
const blobCap = { 'entry.json':16384, 'adapter.json':262144, 'pack.zip':67108864 };
export function newer(a, b) {
  const split = v => { const i=v.indexOf('-'); return [v.slice(0,i<0?undefined:i).split('.').map(BigInt), i<0?null:v.slice(i+1).split('.')]; };
  const [aa,ap]=split(a), [bb,bp]=split(b);
  for(let i=0;i<3;i++) if(aa[i]!==bb[i]) return aa[i]>bb[i];
  if(!ap || !bp) return !ap && !!bp;
  for(let i=0;i<Math.max(ap.length,bp.length);i++) {
    if(ap[i]===undefined || bp[i]===undefined) return bp[i]===undefined;
    if(ap[i]===bp[i]) continue;
    const an=/^[0-9]+$/.test(ap[i]), bn=/^[0-9]+$/.test(bp[i]);
    return an&&bn ? BigInt(ap[i])>BigInt(bp[i]) : an!==bn ? !an : ap[i]>bp[i];
  }
  return false;
}
const fail = (why) => { throw new Error(why); };
export function classify(files) {
  if (!Array.isArray(files) || files.length !== 2 || files.some(f=>f.status!=='added'))
    fail('Companion submission requires exactly two NEW regular files in one immutable version directory');
  const parts = files[0].filename.split('/');
  const [kind,id,version] = parts;
  if (parts.length !== 4 || !['pets','adapters'].includes(kind) || !VERSION.test(version) || version.length>80 ||
      (kind==='pets' ? id.length>40 || !ID.test(id) : !/^[0-9a-f]{64}$/.test(id))) fail('Invalid companion path');
  const allowed = kind==='pets' ? ['entry.json','pack.zip'] : ['entry.json','adapter.json'];
  if (files.some(f=>f.filename.split('/').length!==4 || f.filename.split('/').slice(0,3).join('/')!==`${kind}/${id}/${version}`) ||
      new Set(files.map(f=>f.filename.split('/')[3])).size!==2 ||
      files.some(f=>!allowed.includes(f.filename.split('/')[3]))) fail('Unexpected companion file');
  return {kind,id,version,paths:files.map(f=>f.filename)};
}
export async function companionSubmission(github, options, files) {
  const {repository,headRepository,base,head,author} = options;
  if(!SHA.test(base)||!SHA.test(head)) fail('Expected immutable SHAs');
  const identity = classify(files);
  const {data:commit}=await github.rest.git.getCommit({...headRepository,commit_sha:head});
  if(commit.sha!==head) fail('Unexpected head commit');
  let tree=commit.tree.sha;
  for(const path of [identity.kind,identity.id,identity.version]) {
    const {data:t}=await github.rest.git.getTree({...headRepository,tree_sha:tree});
    if(t.truncated) fail('Truncated tree');
    const dir=t.tree.find(e=>e.path===path);
    if(dir?.type!=='tree'||dir.mode!=='040000') fail('Expected regular directory');
    tree=dir.sha;
  }
  const {data:t}=await github.rest.git.getTree({...headRepository,tree_sha:tree});
  if(t.truncated||t.tree.length!==2) fail('Unexpected version directory');
  const writes=[];
  for(const file of files) {
    const name=file.filename.split('/').at(-1), entry=t.tree.find(e=>e.path===name), cap=blobCap[name];
    if(entry?.type!=='blob'||entry.mode!=='100644'||entry.sha!==file.sha||!Number.isSafeInteger(entry.size)||entry.size>cap) fail('Expected bounded regular blob');
    const {data:b}=await github.rest.git.getBlob({...headRepository,file_sha:entry.sha});
    if(b.sha!==entry.sha||b.encoding!=='base64'||b.size!==entry.size||b.size>cap) fail('Invalid blob');
    const bytes=Buffer.from(b.content,'base64');
    if(bytes.length!==b.size) fail('Invalid blob length');
    writes.push({path:file.filename,bytes});
  }
  const meta=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(writes.find(w=>w.path.endsWith('/entry.json')).bytes));
  if(!author || meta.owner!==author.toLowerCase()) fail('Submission owner must match PR author; maintainer-assisted submissions need manual review');
  const history=`${identity.kind}/${identity.id}`;
  const previous=await readdir(history,{withFileTypes:true}).catch(e=>{if(e.code==='ENOENT')return [];throw e;});
  for(const entry of previous) {
    if(!VERSION.test(entry.name)) continue;
    if(!entry.isDirectory() || (await lstat(history+'/'+entry.name)).isSymbolicLink()) fail('Invalid historical directory');
    if(!newer(identity.version,entry.name)) fail('New release must advance the existing version; released versions are immutable');
    const oldMeta=JSON.parse(await readFile(`${history}/${entry.name}/entry.json`,'utf8'));
    if(oldMeta.owner!==meta.owner) fail('Existing identity belongs to another author');
  }
  const policy=JSON.parse(await readFile('companion-policy.json','utf8'));
  const owner=policy[identity.kind]?.[identity.id]?.owner;
  if(owner && owner!==meta.owner) fail('Reserved identity belongs to another author');
  return {writes,companion:identity};
}
