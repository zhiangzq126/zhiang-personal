"""Import regression tests use isolated libraries, never the user's collection."""
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

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M0 0L10 0L10 10Z" fill="#ff6600"/></svg>'


class WebImportTests(unittest.TestCase):
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
        self.service = ImportService(self.root)

    def item(self, **updates):
        row = dict(filename='Example.svg', data=base64.b64encode(SVG).decode(), name='Example',
                   provider='example', category='数据库', aliases=['示例库'], kind='product', style='橙色',
                   source='test fixture', note='', action='new', make_default=False)
        row.update(updates)
        return row

    def request(self, *rows, status='ready'):
        return dict(items=list(rows), revision=self.service.inspect({'items': list(rows)})['revision'],
                    request_id=str(uuid.uuid4()), source_name='test fixture', status=status)

    def initial(self):
        return self.service.commit(self.request(self.item()))['items'][0]

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_inspection_is_read_only_and_previews_normalized_svg(self):
        before = self.snapshot()
        checked = self.service.inspect({'items': [self.item()]})
        self.assertTrue(checked['items'][0]['preview'].startswith('data:image/svg+xml;base64,'))
        self.assertEqual(self.snapshot(), before)

    def test_ready_import_persists_metadata_source_and_valid_catalog(self):
        response = self.initial()
        catalog = read_json(self.root / 'catalog/index.json')
        self.assertEqual(response['action'], 'created')
        self.assertEqual(catalog['products'][0]['aliases'], ['Example', '示例库'])
        self.assertEqual(catalog['products'][0]['default_variant'], response['variant_id'])
        self.assertEqual(len(read_json(self.root / 'catalog/sources.json')['files']), 1)
        self.assertTrue(validate(root=self.root)['ok'])

    def test_pending_has_no_default_and_cannot_request_preference(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '待确认'):
            self.service.commit(self.request(self.item(make_default=True), status='pending'))
        self.assertEqual(self.snapshot(), before)
        self.service.commit(self.request(self.item(), status='pending'))
        self.assertIsNone(read_json(self.root / 'catalog/index.json')['products'][0]['default_variant'])
        self.assertTrue(validate(root=self.root)['ok'])

    def test_exact_and_alias_matches_block_silent_duplicate_creation(self):
        self.initial()
        row = self.item(name='Unrelated', aliases=[], data=base64.b64encode(SVG.replace(b'<svg ', b'<svg class="x" ')).decode())
        checked = self.service.inspect({'items': [row]})
        self.assertEqual(checked['items'][0]['matches'][0]['reasons'], ['exact'])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '重复候选'):
            self.service.commit(self.request(row))
        self.assertEqual(self.snapshot(), before)
        row = self.item(name='示例库', aliases=[], data=base64.b64encode(SVG.replace(b'#ff6600', b'#0099ff')).decode())
        self.assertEqual(self.service.inspect({'items': [row]})['items'][0]['matches'][0]['reasons'], ['name'])

    def test_same_product_exact_reuses_variant_and_records_provenance(self):
        first = self.initial()
        row = self.item(action='link', target=first['product_id'], make_default=True)
        result = self.service.commit(self.request(row))['items'][0]
        catalog = read_json(self.root / 'catalog/index.json')
        self.assertEqual(result['action'], 'reused')
        self.assertEqual(len(catalog['products']), 1)
        self.assertEqual(len(catalog['variants']), 1)
        self.assertEqual(len(catalog['variants'][0]['origins']), 2)
        self.assertEqual(len(list((self.root / 'assets').rglob('*.svg'))), 1)
        self.assertTrue(validate(root=self.root)['ok'])

    def test_new_variant_preserves_default_unless_requested(self):
        first = self.initial()
        row = self.item(action='link', target=first['product_id'], name='Alternative upload name',
                        style='蓝色', data=base64.b64encode(SVG.replace(b'#ff6600', b'#0099ff')).decode())
        second = self.service.commit(self.request(row))['items'][0]
        catalog = read_json(self.root / 'catalog/index.json')
        self.assertEqual(catalog['products'][0]['name'], 'Example')
        self.assertEqual(catalog['products'][0]['default_variant'], first['variant_id'])
        self.assertEqual(read_json(self.root / 'catalog/preferences.json')['defaults'], {})
        self.service.commit(self.request({**row, 'make_default': True}))
        self.assertEqual(read_json(self.root / 'catalog/preferences.json')['defaults'][first['product_id']], second['variant_id'])

    def test_pending_link_never_demotes_ready_product_or_adds_unconfirmed_alias(self):
        first = self.initial()
        row = self.item(action='link', target=first['product_id'], aliases=['Unverified alias'], data=base64.b64encode(SVG.replace(b'#ff6600', b'#0099ff')).decode())
        result = self.service.commit(self.request(row, status='pending'))['items'][0]
        catalog = read_json(self.root / 'catalog/index.json')
        self.assertEqual(catalog['products'][0]['status'], 'ready')
        self.assertEqual(result['status'], 'pending')
        self.assertNotIn('Unverified alias', catalog['products'][0]['aliases'])
        self.assertEqual(catalog['products'][0]['default_variant'], first['variant_id'])

    def test_distinct_product_can_share_asset_without_identity_merge(self):
        self.initial()
        self.service.commit(self.request(self.item(name='Different service', distinct=True)))
        self.assertEqual(len(read_json(self.root / 'catalog/index.json')['products']), 2)
        self.assertEqual(len(list((self.root / 'assets').rglob('*.svg'))), 1)

    def test_batch_duplicate_requires_decision_and_all_or_nothing(self):
        rows = [self.item(), self.item(filename='Copy.svg')]
        self.assertEqual(self.service.inspect({'items': rows})['items'][0]['batch_matches'], [1])
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '重复候选'):
            self.service.commit(self.request(*rows))
        self.assertEqual(self.snapshot(), before)
        rows[1]['action'] = 'skip'
        self.service.commit(self.request(*rows))
        self.assertEqual(len(read_json(self.root / 'catalog/index.json')['products']), 1)

    def test_invalid_svg_and_paths_are_rejected_and_skippable(self):
        for row in [self.item(filename='../escape.svg'), self.item(data=base64.b64encode(SVG.replace(b'</svg>', b'<script>alert(1)</script></svg>')).decode()), self.item(data='invalid base64')]:
            with self.subTest(row=row):
                self.assertIn('error', self.service.inspect({'items': [row]})['items'][0])
                with self.assertRaises(ValueError):
                    self.service.commit(self.request(row))
        self.service.commit(self.request(self.item(), self.item(data='bad', action='skip')))

    def test_stale_revision_and_retries(self):
        request = self.request(self.item())
        original = self.service.commit(request)
        before = self.snapshot()
        self.assertEqual(self.service.commit(request), original)
        self.assertEqual(self.snapshot(), before)
        stale = copy.deepcopy(request)
        stale['request_id'] = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, '已更新'):
            self.service.commit(stale)
        request['source_name'] = 'changed'
        with self.assertRaisesRegex(ValueError, '已变更'):
            self.service.commit(request)

    def test_provider_mismatch_and_conflicting_defaults_are_rejected(self):
        first = self.initial()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '厂商'):
            self.service.commit(self.request(self.item(action='link', target=first['product_id'], provider='wrong')))
        one = self.item(action='link', target=first['product_id'], make_default=True)
        two = {**one, 'data': base64.b64encode(SVG.replace(b'#ff6600', b'#0099ff')).decode()}
        with self.assertRaisesRegex(ValueError, '只能选择一个'):
            self.service.commit(self.request(one, two))
        self.assertEqual(self.snapshot(), before)

    def test_save_failure_rolls_back_catalog_sources_and_assets(self):
        before = self.snapshot()
        with patch('iconlib.validate', return_value={'ok': False, 'errors': ['test failure']}):
            with self.assertRaisesRegex(ValueError, '入库校验失败'):
                self.service.commit(self.request(self.item()))
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
