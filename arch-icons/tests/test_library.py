import unittest,sys,json,tempfile,subprocess,os,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import library,iconlib
SVG=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L10 0L10 10Z" fill="#ff6600"/></svg>'
class CatalogTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.c=library.load_catalog()
 def test_provider_ambiguity(self):
  self.assertEqual(iconlib.resolve('ECS',catalog=self.c)['status'],'ambiguous')
  self.assertEqual(iconlib.resolve('ECS','aliyun',catalog=self.c)['product_id'],'aliyun/ecs')
  self.assertEqual(iconlib.resolve('ECS','aws',catalog=self.c)['product_id'],'aws/ecs')
 def test_pending_not_auto_selected(self):
  p={**self.c['products'][0],'status':'pending','default_variant':None}
  fixture={'products':[p],'variants':[]}
  self.assertEqual(iconlib.resolve(p['id'],catalog=fixture)['status'],'pending_review')
  self.assertEqual(iconlib.search(p['name'],catalog=fixture),[])
 def test_component_identity_preserved_with_vendor_svg(self):
  self.assertEqual(iconlib.resolve('Redis',catalog=self.c)['match_type'],'vendor_svg_reuse')
  self.assertEqual(iconlib.resolve('Redis',catalog=self.c)['display_name'],'Redis')
  self.assertEqual(iconlib.resolve('MongoDB',catalog=self.c)['product_id'],'opensource/mongodb')
  self.assertEqual(iconlib.resolve('aliyun/redis',catalog=self.c)['status'],'resolved')
 def test_chinese_search_and_missing(self):
  self.assertIn('aliyun/oss',[p['id'] for p in iconlib.search('对象存储','aliyun',catalog=self.c)])
  self.assertEqual(iconlib.resolve('a nonexistent product',catalog=self.c)['fallback'],'card')
 def test_preferences_resolve_same_asset(self):
  p=next(p for p in self.c['products'] if p['id']=='aliyun/ecs');other=next(v for v in self.c['variants'] if v['product_id']==p['id'] and v['id']!=p['default_variant'])
  r=iconlib.resolve(p['id'],catalog=self.c,preferences={'defaults':{p['id']:other['id']}})
  self.assertEqual(r['variant_id'],other['id']);self.assertEqual(r['selection'],'user_preference')
 def test_duplicates_keep_source_evidence(self):
  v=next(v for v in self.c['variants'] if v['product_id']=='aliyun/kms');self.assertEqual(len(v['origins']),2)
 def test_catalog_schema_rejects_invalid_status(self):
  import copy
  c=copy.deepcopy(self.c);c['products'][0]['status']='silently-approved';self.assertTrue(library.check_schema(c,library.read_json(library.ROOT/'catalog/schema.json')))
 def test_all_assets_and_sources(self):self.assertTrue(iconlib.validate(catalog=self.c)['ok'])
class NormalizationTests(unittest.TestCase):
 def test_metadata_dedup(self):
  other=SVG.replace(b'<svg ',b'<svg class="icon" t="123" ').replace(b'<path ',b'<path p-id="99" ')
  self.assertEqual(library.normalize_svg(SVG)[0],library.normalize_svg(other)[0])
 def test_idempotent_references(self):
  svg=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><title>Test</title><defs><linearGradient id="grad"><stop offset="0" stop-color="red"/></linearGradient></defs><path fill="url(#grad)" d="M0 0L10 0L10 10Z"/></svg>'
  a,_=library.normalize_svg(svg);b,_=library.normalize_svg(a);self.assertEqual(a,b);self.assertNotIn(b'url(#grad)',a)
 def test_harmless_dtd_removed(self):
  raw=b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'+SVG
  self.assertEqual(library.normalize_svg(SVG)[0],library.normalize_svg(raw)[0])
 def test_active_or_external_or_raster_rejected(self):
  for bad in [b'<script>alert(1)</script>',b'<image href="https://example.com/a.svg"/>',b'<image href="data:image/png;base64,AA=="/>',b'<path onload="alert(1)"/>',b'<use href="file:///etc/passwd"/>']:
   with self.subTest(bad=bad),self.assertRaises(ValueError):library.normalize_svg(SVG.replace(b'</svg>',bad+b'</svg>'))
  with self.assertRaises(ValueError):library.normalize_svg(b'<!DOCTYPE svg [<!ENTITY foo "bar">]>'+SVG)
 def test_distinct_color_preserved(self):self.assertNotEqual(library.normalize_svg(SVG)[0],library.normalize_svg(SVG.replace(b'#ff6600',b'#00aabb'))[0])
class ImportTests(unittest.TestCase):
 def test_idempotent_import_pending_and_review(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);(root/'catalog').mkdir();(root/'previews').mkdir()
   for name,obj in [('index.json',{'schema_version':1,'products':[],'variants':[]}),('preferences.json',{'schema_version':1,'defaults':{}}),('sources.json',{'schema_version':1,'files':[]})]:library.write_json(root/'catalog'/name,obj)
   source=root/'example.svg';source.write_bytes(SVG);env={**os.environ,'ARCH_ICONS_ROOT':str(root)}
   def cli(*args):
    result=subprocess.run([sys.executable,str(library.ROOT/'scripts/iconlib.py'),*args],env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr);return json.loads(result.stdout)
   result=cli('import',str(source),'--provider','example','--source-name','fixture');self.assertEqual(len(result['added']),1);pid=result['added'][0]
   self.assertEqual(len(cli('import',str(source),'--provider','example','--source-name','fixture')['added']),0)
   self.assertEqual(cli('search','example')['matches'],[])
   cli('review',pid,'--status','ready','--note','Test fixture identity checked')
   self.assertEqual(cli('resolve',pid)['status'],'resolved');self.assertTrue(cli('validate')['ok'])
if __name__=='__main__':unittest.main(verbosity=2)
