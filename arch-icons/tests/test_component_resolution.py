import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import iconlib


class ComponentResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = iconlib.load_catalog()

    def resolve(self, query, catalog=None, **kwargs):
        return iconlib.resolve(query, catalog=catalog or self.catalog, preferences={'defaults': {}}, **kwargs)

    def test_canonical_names_and_aliases(self):
        for query, name, pid in [('Kafka', 'Apache Kafka', 'aliyun/alibabamq-for-apache-kafka'),
                                 ('Apache Kafka', 'Apache Kafka', 'aliyun/alibabamq-for-apache-kafka'),
                                 ('ES', 'Elasticsearch', 'aliyun/elasticsearch'),
                                 ('Elastic Search', 'Elasticsearch', 'aliyun/elasticsearch'),
                                 ('MySQL', 'MySQL', 'aliyun/rds-mysql'),
                                 ('Redis', 'Redis', 'aliyun/redis')]:
            with self.subTest(query=query):
                result = self.resolve(query)
                self.assertEqual(result['status'], 'resolved')
                self.assertEqual(result['display_name'], name)
                self.assertEqual(result['product_id'], pid)
                self.assertEqual(result['requested_component']['name'], name)
                self.assertEqual(result['match_type'], 'vendor_svg_reuse')
                self.assertIn('不表示部署在阿里云', result['diagnostic']['message'])
        es = iconlib.search('ES', catalog=self.catalog)
        self.assertTrue(es)
        self.assertTrue(all(p['id'] in iconlib.component_for('ES')['vendor_product_ids'] for p in es))

    def test_independent_wins_even_with_other_vendor_exact_alias(self):
        self.assertEqual(self.resolve('MongoDB')['product_id'], 'opensource/mongodb')
        c = copy.deepcopy(self.catalog)
        original = next(p for p in c['products'] if p['id'] == 'aliyun/elasticsearch')
        independent = {**original, 'id': 'opensource/elasticsearch', 'name': 'Elasticsearch',
                       'provider': 'opensource', 'aliases': ['Elasticsearch'], 'default_variant': 'opensource/elasticsearch@test'}
        variant = copy.deepcopy(next(v for v in c['variants'] if v['id'] == original['default_variant']))
        variant.update(id=independent['default_variant'], product_id=independent['id'])
        c['products'].append(independent)
        c['variants'].append(variant)
        self.assertEqual(self.resolve('ES', c)['product_id'], independent['id'])
        independent['status'] = 'pending'
        self.assertEqual(self.resolve('ES', c)['status'], 'pending_review')

    def test_explicit_provider_and_product_are_respected(self):
        self.assertEqual(self.resolve('Kafka', provider='huawei')['provider'], 'huawei')
        self.assertEqual(self.resolve('ES', provider='tencent')['provider'], 'tencent')
        result = self.resolve('aliyun/elasticsearch')
        self.assertEqual(result['match_type'], 'exact_product')
        self.assertNotIn('requested_component', result)
        self.assertEqual(self.resolve('ES', provider='jdcloud')['status'], 'not_found')

    def test_diagnostics_distinguish_failure_reasons(self):
        c = copy.deepcopy(self.catalog)
        c['products'] = [p for p in c['products'] if p['id'] != 'aliyun/elasticsearch']
        self.assertEqual(self.resolve('ES', c)['status'], 'vendor_only')
        self.assertEqual(self.resolve('京东云')['status'], 'not_found')
        self.assertEqual(self.resolve('ECS')['status'], 'ambiguous')
        p = next(p for p in c['products'] if p['id'] == 'aliyun/rds-mysql')
        p['status'] = 'pending'
        self.assertEqual(self.resolve('MySQL', c)['status'], 'pending_review')
        for query in ['ES', '京东云', 'ECS', 'MySQL']:
            result = self.resolve(query, c)
            self.assertTrue(result['diagnostic']['message'])
            self.assertEqual(result['diagnostic']['code'], result['status'])

    def test_reuse_still_respects_variant_preferences_and_integrity(self):
        p = next(p for p in self.catalog['products'] if p['id'] == 'aliyun/redis')
        variants = [v for v in self.catalog['variants'] if v['product_id'] == p['id'] and v['status'] == 'ready']
        selected = variants[-1]
        prefs = {'defaults': {p['id']: selected['id']}}
        result = iconlib.resolve('Redis', catalog=self.catalog, preferences=prefs)
        self.assertEqual(result['variant_id'], selected['id'])
        self.assertEqual(result['selection'], 'user_preference')
        self.assertEqual(prefs, {'defaults': {p['id']: selected['id']}})
        result = iconlib.resolve('Redis', catalog=self.catalog, preferences=prefs, variant_id=p['default_variant'])
        self.assertEqual(result['selection'], 'explicit_variant')
        self.assertEqual(self.resolve('Redis', variant_id='missing')['status'], 'invalid_variant')
        c = copy.deepcopy(self.catalog)
        v = next(v for v in c['variants'] if v['id'] == p['default_variant'])
        v['asset']['sha256'] = '0' * 64
        self.assertEqual(self.resolve('Redis', c)['status'], 'asset_integrity_error')


if __name__ == '__main__':
    unittest.main()
