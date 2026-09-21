import base64
import copy
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from library import ROOT, read_json, write_json
from iconlib import validate
from web_import import ImportService
from web_review import ReviewService

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="red"/></svg>'


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'previews').mkdir()
        for name, data in [('index', {'schema_version': 1, 'products': [], 'variants': []}),
                           ('preferences', {'schema_version': 1, 'defaults': {}}),
                           ('sources', {'schema_version': 1, 'files': []}),
                           ('schema', read_json(ROOT / 'catalog/schema.json'))]:
            write_json(self.root / 'catalog' / (name + '.json'), data)
        self.service = ReviewService(self.root)

    def add(self, name='Example', status='pending', color='red', target=None):
        row = dict(filename=name+'.svg', name=name, provider='example', category='待分类',
                   aliases=[name], kind='product', style=color, data=base64.b64encode(SVG.replace(b'red', color.encode())).decode(),
                   action='link' if target else 'new', distinct=True, target=target)
        s = ImportService(self.root)
        payload = dict(items=[row], revision=s.inspect({'items': [row]})['revision'], request_id=str(uuid.uuid4()),
                       source_name='fixture', status=status)
        return s.commit(payload)['items'][0]

    def request(self, item, **changes):
        result = dict(request_id=str(uuid.uuid4()), product_id=item['product_id'], revision=self.service.queue()['revision'],
                      action='approve', variant_ids=[item['variant_id']], metadata={}, note='原始来源已核对', styles={}, default_variant='')
        result.update(changes)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_queue_is_read_only_and_includes_ready_product_pending_variants(self):
        a = self.add(status='ready')
        self.add(color='blue', target=a['product_id'])
        before = self.snapshot()
        queue = self.service.queue()
        self.assertEqual(len(queue['items']), 1)
        self.assertEqual(queue['items'][0]['product']['status'], 'ready')
        self.assertEqual(len(queue['items'][0]['variants']), 2)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(read_json(self.root/'catalog/review-queue.json')), 1)

    def test_approve_updates_metadata_default_and_audit(self):
        a = self.add()
        self.service.commit(self.request(a, metadata={'name':'正式名称', 'category':'数据库', 'aliases':['正式名称','ExampleDB'], 'kind':'component'}))
        c = read_json(self.root/'catalog/index.json')
        self.assertEqual(c['products'][0]['name'], '正式名称')
        self.assertEqual(c['products'][0]['status'], 'ready')
        self.assertEqual(c['products'][0]['default_variant'], a['variant_id'])
        self.assertFalse(self.service.queue()['items'])
        self.assertEqual(len(list((self.root/'reports/web-reviews').glob('*.json'))), 1)
        self.assertTrue(validate(root=self.root)['ok'])

    def test_save_and_provider_correction_keep_pending_and_rekey_ids(self):
        a = self.add()
        result = self.service.commit(self.request(a, action='save', variant_ids=[], metadata={'provider':'opensource'}, note='需进一步核实'))
        c = read_json(self.root/'catalog/index.json')
        self.assertTrue(result['product_id'].startswith('opensource/'))
        self.assertEqual(c['products'][0]['status'], 'pending')
        self.assertEqual(c['variants'][0]['product_id'], result['product_id'])
        self.assertIsNone(c['products'][0]['default_variant'])
        self.assertTrue(validate(root=self.root)['ok'])

    def test_partial_approval_keeps_other_variant_pending_and_preference(self):
        a = self.add()
        b = self.add(color='blue', target=a['product_id'])
        self.service.commit(self.request(a))
        c = read_json(self.root/'catalog/index.json')
        self.assertEqual([v['status'] for v in c['variants']], ['ready', 'pending'])
        self.assertEqual(len(self.service.queue()['items']), 1)
        self.service.commit(self.request(b))
        self.assertEqual(read_json(self.root/'catalog/index.json')['products'][0]['default_variant'], a['variant_id'])
        self.assertEqual(read_json(self.root/'catalog/preferences.json')['defaults'], {})

    def test_approve_corrected_provider_maps_selected_default(self):
        a = self.add()
        result = self.service.commit(self.request(a, metadata={'provider':'generic'}, default_variant=a['variant_id']))
        prefs = read_json(self.root/'catalog/preferences.json')['defaults']
        self.assertEqual(prefs[result['product_id']], result['variant_id_map'][a['variant_id']])
        self.assertTrue(validate(root=self.root)['ok'])

    def test_duplicate_blocks_approval_without_explicit_distinct_decision(self):
        self.add(name='Existing', status='ready')
        a = self.add(name='Other')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError,'同名'):
            self.service.commit(self.request(a))
        self.assertEqual(self.snapshot(), before)
        self.service.commit(self.request(a, distinct=True))
        self.assertEqual(len(read_json(self.root/'catalog/index.json')['products']), 2)

    def test_link_reuses_asset_preserves_origins_and_existing_default(self):
        target = self.add(name='Target', status='ready')
        a = self.add(name='Duplicate')
        self.service.commit(self.request(a, action='link', target_id=target['product_id']))
        c = read_json(self.root/'catalog/index.json')
        self.assertEqual(len(c['products']), 1)
        self.assertEqual(len(c['variants']), 1)
        self.assertEqual(len(c['variants'][0]['origins']), 2)
        self.assertEqual(c['products'][0]['default_variant'], target['variant_id'])
        self.assertEqual(len(read_json(self.root/'catalog/sources.json')['files']), 2)
        self.assertTrue(validate(root=self.root)['ok'])

    def test_link_partial_keeps_source_and_can_select_new_target_default(self):
        target = self.add(name='Target', status='ready', color='green')
        a = self.add()
        b = self.add(color='blue', target=a['product_id'])
        response = self.service.commit(self.request(a, action='link', target_id=target['product_id'], default_variant=a['variant_id']))
        c = read_json(self.root/'catalog/index.json')
        self.assertEqual(len(c['products']), 2)
        self.assertEqual(next(p for p in c['products'] if p['id']==a['product_id'])['status'], 'pending')
        self.assertEqual(self.service.queue()['items'][0]['variants'][0]['id'], b['variant_id'])
        self.assertEqual(read_json(self.root/'catalog/preferences.json')['defaults'][target['product_id']],response['variant_id_map'][a['variant_id']])
        self.assertTrue(validate(root=self.root)['ok'])

    def test_ready_identity_cannot_be_silently_changed(self):
        a = self.add(status='ready')
        b = self.add(color='blue',target=a['product_id'])
        with self.assertRaisesRegex(ValueError,'身份保持不变'):
            self.service.commit(self.request(b,metadata={'provider':'other'}))

    def test_stale_revision_retry_and_invalid_variants(self):
        a = self.add()
        stale = self.request(a)
        self.add(name='Second',color='blue')
        with self.assertRaisesRegex(ValueError,'已更新'):
            self.service.commit(stale)
        with self.assertRaisesRegex(ValueError,'当前条目'):
            self.service.commit(self.request(a,variant_ids=['other@id']))
        request = self.request(a)
        result = self.service.commit(request)
        before = self.snapshot()
        self.assertEqual(self.service.commit(request),result)
        self.assertEqual(self.snapshot(),before)

    def test_missing_note_and_invalid_default_rejected(self):
        a=self.add()
        with self.assertRaisesRegex(ValueError,'依据'):
            self.service.commit(self.request(a,note=''))
        with self.assertRaisesRegex(ValueError,'默认'):
            self.service.commit(self.request(a,default_variant='invalid'))

    def test_validation_failure_rolls_back_review(self):
        a=self.add();before=self.snapshot()
        with patch('iconlib.validate',return_value={'ok':False,'errors':['fixture failure']}):
            with self.assertRaisesRegex(ValueError,'审核校验失败'):
                self.service.commit(self.request(a))
        self.assertEqual(self.snapshot(),before)

    def delete_request(self, item, **changes):
        return self.request(item, action='delete', delete_confirmed=True, note='素材有误', **changes)

    def test_delete_plan_read_only_and_exclusive_asset_recycled(self):
        a=self.add();before=self.snapshot();request=self.delete_request(a)
        plan=self.service.delete_plan(request)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(plan['variant_count'],1)
        self.assertTrue(plan['remove_product'])
        self.assertEqual(len(plan['cleanup_assets']),1)
        result=self.service.commit(request)
        rel=plan['cleanup_assets'][0]['path']
        self.assertFalse((self.root/rel).exists())
        self.assertTrue((self.root/result['recovery_path']/rel).exists())
        self.assertEqual(read_json(self.root/'catalog/index.json')['products'],[])
        manifest=read_json(self.root/'catalog/sources.json')
        self.assertEqual(len(manifest['files']),1)
        self.assertTrue((self.root/manifest['files'][0]['path']).exists())
        self.assertTrue(validate(root=self.root)['ok'])
        after=self.snapshot()
        self.assertEqual(self.service.commit(request),result)
        self.assertEqual(self.snapshot(),after)

    def test_delete_shared_asset_preserves_other_product_and_default(self):
        ready=self.add(name='Ready',status='ready');a=self.add(name='Wrong')
        request=self.delete_request(a);plan=self.service.delete_plan(request)
        self.assertEqual(len(plan['cleanup_assets']),0)
        self.assertEqual(len(plan['shared_assets']),1)
        self.service.commit(request)
        c=read_json(self.root/'catalog/index.json')
        self.assertEqual(c['products'][0]['id'],ready['product_id'])
        self.assertEqual(c['products'][0]['default_variant'],ready['variant_id'])
        self.assertTrue((self.root/c['variants'][0]['asset']['path']).exists())

    def test_delete_partial_keeps_unselected_and_existing_ready_identity(self):
        ready=self.add(status='ready');a=self.add(color='blue',target=ready['product_id'])
        self.service.commit(self.delete_request(a))
        c=read_json(self.root/'catalog/index.json')
        self.assertEqual(len(c['products']),1)
        self.assertEqual([v['id'] for v in c['variants']],[ready['variant_id']])
        self.assertEqual(c['products'][0]['default_variant'],ready['variant_id'])
        with self.assertRaises(ValueError):self.service.commit(self.delete_request(ready))

    def test_delete_requires_confirmation_and_rejects_ready_selection(self):
        a=self.add();before=self.snapshot()
        request=self.delete_request(a);request['delete_confirmed']=False
        with self.assertRaisesRegex(ValueError,'确认清理'):self.service.commit(request)
        self.assertEqual(self.snapshot(),before)
        ready=self.add(name='Ready',status='ready',color='blue')
        with self.assertRaises(ValueError):self.service.delete_plan(self.delete_request(a,variant_ids=[ready['variant_id']]))

    def test_delete_failure_restores_asset_and_catalog(self):
        a=self.add();before=self.snapshot()
        with patch('iconlib.validate',return_value={'ok':False,'errors':['failure']}):
            with self.assertRaisesRegex(ValueError,'审核校验失败'):self.service.commit(self.delete_request(a))
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main(verbosity=2)
