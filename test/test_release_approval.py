"""The maintainer approves final release semantics, not only ZIP/JSON bytes."""
import copy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_companions import BASE, package
from build_companions import build
from pet_pack import canonical, Denied, normalize, sha

TIME='2026-11-08T00:00:00.000Z'
MOC='a'*64

class ReleaseApprovalTests(unittest.TestCase):
    def setup_release(self, root, kind):
        identity='author-cat' if kind=='pets' else MOC
        key='id' if kind=='pets' else 'moc'
        entry={'schema':1,key:identity,'version':'1.0.0','owner':'author','author':'Author',
               'license':'CC0-1.0','source':'https://example.org/art','minApp':'1.0.13',
               'rights':{'redistribute':True,'generalAudience':True}}
        if kind=='pets':entry['title']={'zh':'猫','en':'Cat'}
        path=root/kind/identity/'1.0.0';path.mkdir(parents=True)
        (path/'entry.json').write_bytes(canonical(entry))
        (path/('pack.zip' if kind=='pets' else 'adapter.json')).write_bytes(
            package() if kind=='pets' else canonical({'adapter':1,'moc':MOC,'notes':'Reviewed'}))
        policy={'schema':2,'pets':{},'adapters':{},'withdrawnPets':[],'withdrawnAdapters':[]}
        return identity, entry, path, policy

    def approve(self, root, kind, identity, policy):
        result,audit=build(root,root/'dist',policy,TIME)
        self.assertEqual(result[kind][kind],[])
        self.assertEqual(audit[0]['status'],'technical-ready')
        policy[kind][identity]={'owner':'author','approved':{'1.0.0':copy.deepcopy(audit[0]['approval'])}}
        return audit[0]

    def test_adapter_and_pet_metadata_changes_invalidate_prior_approval(self):
        changes={'author':'Unreviewed author','license':'MIT','source':'https://example.org/changed',
                 'minApp':'0.0.1','owner':'other','version':'2.0.0',
                 'rights':{'redistribute':False,'generalAudience':True}}
        for kind in ('pets','adapters'):
            candidates={**changes, 'id' if kind=='pets' else 'moc':'other-cat' if kind=='pets' else 'b'*64}
            if kind=='pets':
                candidates.update({'title.zh':'未审查','title.en':'Unreviewed title'})
            for field,value in candidates.items():
                with self.subTest(kind=kind,field=field), tempfile.TemporaryDirectory() as directory:
                    root=Path(directory);identity,entry,path,policy=self.setup_release(root,kind)
                    approved=self.approve(root,kind,identity,policy)
                    if field.startswith('title.'):
                        entry['title'][field.split('.')[1]]=value
                    else:entry[field]=value
                    (path/'entry.json').write_bytes(canonical(entry))
                    if kind=='pets' and field in ('author','license','source'):
                        pack=copy.deepcopy(BASE);pack[field]=value
                        (path/'pack.zip').write_bytes(package(pack=pack))
                    with self.assertRaises(Denied):build(root,root/'dist',policy,TIME)
                    # The exact old policy object was not auto-upgraded or changed.
                    self.assertEqual(policy[kind][identity]['approved']['1.0.0'],approved['approval'])

    def test_title_and_min_app_bind_even_when_normalized_artifact_is_unchanged(self):
        for kind,field,value in [('pets','title',{'zh':'另一个','en':'Another'}),
                                 ('pets','minApp','0.0.1'),('adapters','author','Another author'),
                                 ('adapters','license','MIT'),('adapters','source','https://example.org/other'),
                                 ('adapters','minApp','0.0.1')]:
            with self.subTest(kind=kind,field=field),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identity,entry,path,policy=self.setup_release(root,kind)
                old=self.approve(root,kind,identity,policy)
                entry[field]=value;(path/'entry.json').write_bytes(canonical(entry))
                # A fresh unapproved review proves the artifact itself is unchanged,
                # but its publication approval has changed.
                empty=copy.deepcopy(policy);empty[kind][identity]['approved']={}
                _,audit=build(root,root/'review-dist',empty,TIME)
                self.assertEqual(old['sha256'],audit[0]['sha256'])
                self.assertNotEqual(old['approval'],audit[0]['approval'])
                with self.assertRaises(Denied) as caught:build(root,root/'dist',policy,TIME)
                self.assertEqual(caught.exception.code,'approved-release-mismatch')

    def test_review_report_and_published_row_share_the_exact_record(self):
        for kind in ('pets','adapters'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identity,entry,path,policy=self.setup_release(root,kind)
                review=root/'review';descriptor={'kind':kind,'id':identity,'version':'1.0.0','directory':str(review)}
                result,audit=build(root,root/'dist',policy,TIME,review=descriptor)
                release=json.loads((review/'release.json').read_bytes())
                approval=json.loads((review/'approval.json').read_bytes())
                self.assertEqual(approval,{'schema':2,'releaseSha256':sha((review/'release.json').read_bytes())})
                self.assertEqual(release,audit[0]['release']);self.assertEqual(approval,audit[0]['approval'])
                self.assertEqual(result[kind][kind],[])
                policy[kind][identity]={'owner':entry['owner'],'approved':{'1.0.0':approval}}
                result,approved=build(root,root/'dist',policy,TIME,review=descriptor)
                row=copy.deepcopy(result[kind][kind][0]);row.pop('blockedVersions',None)
                self.assertEqual(row,release['entry']);self.assertEqual(approved[0]['release'],release)
                self.assertEqual(approved[0]['status'],'approved')
                files=[('pack.zip' if kind=='pets' else 'adapter.json',row)]
                if kind=='pets':files.extend((f'preview.{k}',row['preview'][k]) for k in ('png','gif'))
                for name,asset in files:
                    raw=(review/name).read_bytes()
                    self.assertEqual((sha(raw),len(raw)),(asset['sha256'],asset['size']))

    def test_json_formatting_without_semantic_change_keeps_approval(self):
        for kind in ('pets','adapters'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identity,entry,path,policy=self.setup_release(root,kind)
                old=self.approve(root,kind,identity,policy)
                (path/'entry.json').write_text(json.dumps(dict(reversed(list(entry.items()))),ensure_ascii=True,indent=4)+'\n')
                if kind=='adapters':
                    (path/'adapter.json').write_text(json.dumps({'notes':'Reviewed','moc':MOC,'adapter':1},indent=2))
                _,audit=build(root,root/'dist',policy,TIME)
                self.assertEqual(audit[0]['status'],'approved');self.assertEqual(audit[0]['approval'],old['approval'])

    def test_legacy_policy_and_single_artifact_digest_never_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);identity,entry,path,policy=self.setup_release(root,'adapters')
            old=self.approve(root,'adapters',identity,policy)
            for legacy in [1,2]:
                rejected=copy.deepcopy(policy);rejected['schema']=legacy
                rejected['adapters'][identity]['approved']['1.0.0']=old['sha256']
                with self.subTest(schema=legacy),self.assertRaises(Denied):build(root,root/'dist',rejected,TIME)
            rejected=copy.deepcopy(policy);rejected['schema']=1
            with self.assertRaises(Denied):build(root,root/'dist',rejected,TIME)

    def test_artifact_and_derived_preview_bytes_are_bound(self):
        for kind in ('pets','adapters'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identity,entry,path,policy=self.setup_release(root,kind)
                self.approve(root,kind,identity,policy)
                if kind=='adapters':
                    (path/'adapter.json').write_bytes(canonical({'adapter':1,'moc':MOC,'notes':'Changed'}))
                else:
                    pack=copy.deepcopy(BASE);pack['pixelArt']=False
                    (path/'pack.zip').write_bytes(package(pack=pack))
                with self.assertRaises(Denied) as caught:build(root,root/'dist',policy,TIME)
                self.assertEqual(caught.exception.code,'approved-release-mismatch')
        # A renderer/dependency change that affects only a derived preview must
        # also require review, even when the normalized ZIP is identical.
        for media in ('png','gif'):
            with self.subTest(preview=media),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identity,entry,path,policy=self.setup_release(root,'pets')
                self.approve(root,'pets',identity,policy)
                def changed(data):
                    result=normalize(data);result[media]+=b'changed-preview';return result
                with patch('build_companions.normalize',side_effect=changed),self.assertRaises(Denied) as caught:
                    build(root,root/'dist',policy,TIME)
                self.assertEqual(caught.exception.code,'approved-release-mismatch')

    def test_cli_failed_rebuild_uploads_current_review_and_never_reuses_old_pass_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);identity,entry,path,policy=self.setup_release(root,'adapters')
            self.approve(root,'adapters',identity,policy)
            (root/'policy.json').write_bytes(canonical(policy))
            reports=root/'reports';reports.mkdir()
            (reports/'submission.json').write_bytes(canonical({'kind':'adapters','id':identity,'version':'1.0.0'}))
            script=Path(__file__).resolve().parents[1]/'scripts/build_companions.py'
            command=[sys.executable,str(script),'--root',str(root),'--policy',str(root/'policy.json')]
            first=subprocess.run(command,cwd=root,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            before=json.loads((reports/'companions.json').read_bytes())
            self.assertTrue(before['passed'])
            old_approval=(reports/'companion-review/approval.json').read_bytes()
            entry['author']='Changed after review';(path/'entry.json').write_bytes(canonical(entry))
            changed=subprocess.run(command,cwd=root,capture_output=True,text=True)
            self.assertNotEqual(changed.returncode,0)
            failed=json.loads((reports/'companions.json').read_bytes())
            self.assertFalse(failed['passed']);self.assertEqual(failed['error']['code'],'approved-release-mismatch')
            self.assertNotIn('results',failed)
            record=json.loads((reports/'companion-review/release.json').read_bytes())
            self.assertEqual(record['entry']['author'],entry['author'])
            self.assertNotEqual((reports/'companion-review/approval.json').read_bytes(),old_approval)

    def test_trusted_withdrawal_state_does_not_reapprove_authored_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);identity,entry,path,policy=self.setup_release(root,'pets')
            old=self.approve(root,'pets',identity,policy)
            policy['withdrawnPets']=[{'id':identity,'version':'0.9.0','reason':'Retired old version'}]
            result,audit=build(root,root/'dist',policy,TIME)
            self.assertEqual(audit[0]['approval'],old['approval'])
            self.assertEqual(result['pets']['pets'][0]['blockedVersions'],['0.9.0'])
            self.assertNotIn('blockedVersions',audit[0]['release']['entry'])
            policy['withdrawnPets'].append({'id':identity,'version':'1.0.0','reason':'Withdraw current version'})
            result,audit=build(root,root/'dist',policy,TIME)
            self.assertEqual(audit[0]['status'],'withdrawn');self.assertEqual(result['pets']['pets'],[])

if __name__=='__main__':unittest.main()
