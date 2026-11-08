/** CI gate for the exact v2 release reviewed by a maintainer.
 * The publisher, review artifact and trusted policy must name the same record;
 * an old artifact-only SHA or a bare report status never grants eligibility.
 */
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { lstat, readFile } from 'node:fs/promises';
import { join } from 'node:path';

export const RELEASE_RECORD_CAP = 65536;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const hex = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const approvalV2 = value => record(value) && Object.keys(value).sort().join(',') === 'releaseSha256,schema' &&
  value.schema === 2 && hex(value.releaseSha256);
// Release v2 has fixed ASCII field names and finite integer numeric fields.
// UTF-8, sorted keys, compact JSON and the final LF match Python canonical().
export function canonicalRelease(value) {
  const sorted = value => {
    if (Array.isArray(value)) return value.map(sorted);
    if (record(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])]));
    if (value === null || typeof value === 'boolean' || typeof value === 'string' && !/[\ud800-\udfff]/u.test(value) ||
        typeof value === 'number' && Number.isSafeInteger(value)) return value;
    throw new Error('Invalid release scalar');
  };
  const text = JSON.stringify(sorted(value)) + '\n';
  if (Buffer.byteLength(text,'utf8') > RELEASE_RECORD_CAP) throw new Error('Release record too large');
  return text;
}
export function releaseApproval(release) {
  return {schema:2, releaseSha256:createHash('sha256').update(canonicalRelease(release),'utf8').digest('hex')};
}
function artifacts(release) {
  const entry = release.entry;
  return release.kind === 'pets'
    ? [['pack.zip',entry], ['preview.png',entry.preview.png], ['preview.gif',entry.preview.gif]]
    : [['adapter.json',entry]];
}
export async function readCompanionReview(directory) {
  const read = async name => {
    const path = join(directory,name), stat = await lstat(path);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > RELEASE_RECORD_CAP) throw new Error('Invalid review JSON');
    return JSON.parse(await readFile(path,'utf8'));
  };
  const release = await read('release.json'), approval = await read('approval.json'), files = {};
  if (!['pets','adapters'].includes(release.kind)) throw new Error('Invalid review kind');
  for (const [name,expected] of artifacts(release)) {
    const path = join(directory,name), stat = await lstat(path);
    const cap = name === 'pack.zip' ? 50*1024*1024 : name === 'adapter.json' ? 262144 : 4*1024*1024;
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== expected.size || stat.size > cap)
      throw new Error('Invalid review artifact');
    const digest = createHash('sha256');
    let size = 0;
    for await (const chunk of createReadStream(path)) {
      size += chunk.length;
      if (size > stat.size) throw new Error('Review artifact changed');
      digest.update(chunk);
    }
    if (size !== stat.size) throw new Error('Review artifact changed');
    files[name] = {size,sha256:digest.digest('hex')};
  }
  return {release,approval,files};
}
export function companionApproved(item, audit, policy, review) {
  if (item === null) return true; // Existing plugin submission path.
  try {
    if (!record(item) || !['pets','adapters'].includes(item.kind) || !record(audit) ||
        audit.schema !== 2 || audit.passed !== true || !Array.isArray(audit.results) || policy?.schema !== 2 ||
        !Array.isArray(policy.withdrawnPets) || !Array.isArray(policy.withdrawnAdapters))
      return false;
    const key = item.kind === 'pets' ? 'id' : 'moc';
    const matches = audit.results.filter(row => row.kind === item.kind && row[key] === item.id && row.version === item.version);
    if (matches.length !== 1) return false;
    const row = matches[0], release = row.release, permit = policy[item.kind]?.[item.id];
    const approved = permit?.approved?.[item.version];
    if (row.status !== 'approved' || !record(release) || release.schema !== 2 || release.kind !== item.kind ||
        release.entry?.[key] !== item.id || release.entry?.version !== item.version || permit?.owner !== release.owner ||
        !approvalV2(approved) || !approvalV2(row.approval) || !approvalV2(review?.approval)) return false;
    const expected = releaseApproval(release).releaseSha256;
    if (approved.releaseSha256 !== expected || row.approval.releaseSha256 !== expected ||
        review.approval.releaseSha256 !== expected || canonicalRelease(review.release) !== canonicalRelease(release) ||
        row.sha256 !== release.entry.sha256) return false;
    if (policy[item.kind === 'pets' ? 'withdrawnPets' : 'withdrawnAdapters']?.some(w => w[key] === item.id && w.version === item.version))
      return false;
    return artifacts(release).every(([name,asset]) => hex(asset.sha256) &&
      review.files?.[name]?.sha256 === asset.sha256 && review.files[name].size === asset.size);
  } catch { return false; }
}
