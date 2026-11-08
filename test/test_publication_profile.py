"""Current c76 App contract, on both normalized pet output and adapter data."""
import copy
import json
import unittest

from test_companions import BASE, package
from build_companions import adapter
from pet_pack import Denied, normalize, validate, market_manifest, app_import_compatible

MOC = 'a' * 64

class PublicationProfileTests(unittest.TestCase):
    def test_current_stage_adapter_data_is_preserved_without_translation(self):
        value = {'adapter':1,'moc':MOC,
                 'params':{'ParamEyeLOpen':{'id':['EyeL','EyeL2'],'scale':-1000,'offset':1000}},
                 'emotions':{'shy':{'expression':'笑顔','face':{'ParamAngleZ':30,'眉':-1000}}},
                 'actions':{'wave':{'motion':'挥手'}},
                 'zones':[{'id':'head','from':0,'to':.3,'xFrom':-1.5,'xTo':1.5}],
                 'framing':{'zoom':.3,'y':-1},'tail':['Tail'],'pose':{'Watermark':0},'notes':'Reviewed'}
        self.assertEqual(json.loads(adapter(value,MOC)),value)

    def test_legacy_proposal_names_toggles_and_out_of_profile_values_are_rejected(self):
        for extra in [
            {'params':{'unknown':{'id':'Eye'}}}, {'params':{'ParamAngleX':{'id':[]}}},
            {'params':{'ParamAngleX':{'id':'Eye','scale':0}}},
            {'params':{'ParamAngleX':{'id':'Eye','scale':1000.1}}},
            {'emotions':{'joy':{'expression':'Smile'}}}, {'actions':{'unknown':{'motion':'Wave'}}},
            {'zones':[{'id':'ear','from':0,'to':1}]},
            {'zones':[{'id':'head','from':0,'to':1,'xFrom':.5,'xTo':-.5}]},
            {'zones':[{'id':'head','from':0,'to':1,'xFrom':-1.51}]},
            {'framing':{'zoom':.299}}, {'framing':{'zoom':3.001}}, {'framing':{'y':1.001}},
            {'pose':[]}, {'pose':{'Switch':1000.1}}, {'toggles':{'hide':['Watermark']}},
        ]:
            with self.subTest(extra=extra),self.assertRaises(Denied):
                adapter({'adapter':1,'moc':MOC,**extra},MOC)

    def test_normalized_huge_scale_cannot_bypass_current_app_import(self):
        pack=copy.deepcopy(BASE);pack['scale']=16777219
        # This authored geometry matches the old Android Float32 check, so the
        # current App scale bound is the remaining reason to reject publication.
        pack['animations']['idle']['box'].update(w=2/16777220,h=2/16777220)
        validate(pack)
        with self.assertRaises(Denied) as caught:normalize(package(pack))
        self.assertEqual(caught.exception.code,'app-import-scale')

    def test_valid_authored_fractional_numbers_can_normalize_then_pass_import(self):
        pack=copy.deepcopy(BASE);pack['scale']=1.2
        pack['animations']['idle'].update(frameW=2.4,frameH=2.4,cols=1.4)
        pack['animations']['idle']['frames']=[None,{'i':-.4,'ms':100.5}]
        with self.assertRaises(Denied):app_import_compatible(pack)
        output=normalize(package(pack))['pack'];app_import_compatible(output)
        self.assertEqual(output['scale'],1)
        self.assertEqual(output['animations']['idle']['frames'],[{'i':0,'ms':101}])

    def test_app_frame_integer_bound_and_depth_apply_to_emitted_output(self):
        pack=copy.deepcopy(BASE);pack['animations']['idle']['frames'][0]['ms']=1 << 30
        app_import_compatible(normalize(package(pack))['pack'])
        pack['animations']['idle']['frames'][0]['ms']=(1 << 30)+1
        with self.assertRaises(Denied) as caught:normalize(package(pack))
        self.assertEqual(caught.exception.code,'app-import-frames')
        pack=copy.deepcopy(BASE);nested=0
        for _ in range(60):nested=[nested]
        pack['retainedExtra']=nested
        animations,_=validate(pack)
        with self.assertRaises(Denied) as caught:market_manifest(pack,animations)
        self.assertEqual(caught.exception.code,'app-import-depth')
