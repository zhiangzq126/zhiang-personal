"""Contract tests run mutations only against disposable catalogs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from library import check_schema, write_json


class AgentContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='icon contract ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, 'ARCH_ICONS_ROOT': str(self.root)}
        self.schema = json.loads((ROOT / 'docs/schemas/agent-response.schema.json').read_text())
        self.products = []
        self.variants = []
        for pid, name, status in [('test/a', 'Shared', 'ready'), ('test/b', 'Shared', 'ready'),
                                  ('test/pending', 'Pending', 'pending'), ('test/db', 'Redis', 'ready')]:
            self.products.append(dict(id=pid, provider='test', name=name, aliases=[], status=status,
                                      kind='product', category='fixture', notes=[], identity_basis='fixture',
                                      default_variant=pid+'@blue' if status == 'ready' else None))
            for color in ('blue', 'red'):
                raw = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                       '<rect width="10" height="10" fill="'+color+'"/></svg>').encode()
                digest = hashlib.sha256(raw).hexdigest()
                rel = 'assets/'+digest[:2]+'/'+digest+'.svg'
                path = self.root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                self.variants.append(dict(id=pid+'@'+color, product_id=pid, status=status, style=color,
                                          asset=dict(path=rel, sha256=digest, representation='vector', format='svg'),
                                          theme=dict(preserve_colors=True, dark_backdrop=False)))
        self.catalog = dict(schema_version=1, products=self.products, variants=self.variants)
        self.save()
        write_json(self.root/'catalog/preferences.json', {'schema_version': 1, 'defaults': {'test/a': 'test/a@red'}})

    def save(self):
        write_json(self.root/'catalog/index.json', self.catalog)

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(ROOT/'scripts/iconlib.py'), *args, '--json'],
                              env=self.env, capture_output=True, text=True)
        result = json.loads(proc.stdout)
        self.assertEqual(check_schema(result, self.schema), [], proc.stdout)
        return proc.returncode, result

    def test_precedence_and_no_writes(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.cli('resolve', 'test/a')[1]['selection'], 'user_preference')
        result = self.cli('resolve', 'test/a', '--variant', 'test/a@blue')[1]
        self.assertEqual((result['variant_id'], result['selection']), ('test/a@blue', 'explicit_variant'))
        self.assertEqual(self.cli('resolve', 'test/b')[1]['selection'], 'catalog_default')
        self.assertEqual(self.cli('resolve', 'test/a')[1]['variant_id'], 'test/a@red')
        self.cli('search', 'Shared')
        self.cli('show', 'test/a')
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_fallbacks(self):
        cases = [(('resolve', 'missing'), 'not_found'), (('resolve', 'Shared'), 'ambiguous'),
                 (('resolve', 'test/pending'), 'pending_review'), (('resolve', 'Redis'), 'needs_provider_context'),
                 (('resolve', 'test/a', '--variant', 'test/b@blue'), 'invalid_variant'),
                 (('resolve', 'test/a', '--variant', 'missing'), 'invalid_variant')]
        for args, status in cases:
            with self.subTest(status=status, args=args):
                code, result = self.cli(*args)
                self.assertEqual((code, result['status'], result['fallback']), (2, status, 'card'))
                self.assertNotIn('asset_path', result)
        self.variants[0]['status'] = 'pending'
        self.save()
        self.assertEqual(self.cli('resolve', 'test/a', '--variant', 'test/a@blue')[1]['status'], 'pending_review')

    def test_asset_corruption_and_missing(self):
        asset = self.root/self.variants[1]['asset']['path']
        asset.write_bytes(b'corrupt')
        self.assertEqual(self.cli('resolve', 'test/a')[1]['status'], 'asset_integrity_error')
        asset.unlink()
        self.assertEqual(self.cli('resolve', 'test/a')[1]['status'], 'asset_integrity_error')

    def test_query_error_and_schema_rejections(self):
        code, result = self.cli('show', 'missing')
        self.assertEqual(code, 1)
        self.assertIn('error', result)
        self.assertEqual(self.cli('search', 'missing')[1]['matches'], [])
        good = self.cli('resolve', 'test/a')[1]
        for key, value in [('contract_version', 1), ('sha256', 'bad'), ('asset_relative_path', 'sources/a.svg'),
                           ('selection', 'first_search_hit')]:
            bad = {**good, key: value}
            self.assertTrue(check_schema(bad, self.schema), key)
        bad = dict(good)
        del bad['theme']
        self.assertTrue(check_schema(bad, self.schema))
        self.assertTrue(check_schema({**good, 'error': 'conflicting result'}, self.schema))
        self.assertEqual(check_schema({**good, 'future_field': True}, self.schema), [])

    def test_portable_skill_entry(self):
        entry = self.root/'copied-skill/scripts/icon_query.py'
        entry.parent.mkdir(parents=True)
        shutil.copy2(ROOT/'skills/arch-icons/scripts/icon_query.py', entry)
        shutil.copytree(ROOT/'scripts', self.root/'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        (self.root/'docs').mkdir()
        (self.root/'docs/agent-contract.md').write_text('test fixture')
        for args, expected in [(('resolve', 'test/a'), 0), (('prefer', 'test/a', 'test/a@blue'), 1)]:
            proc = subprocess.run([sys.executable, str(entry), *args], env=self.env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, expected, proc.stdout+proc.stderr)
        self.assertEqual(json.loads((self.root/'catalog/preferences.json').read_text())['defaults']['test/a'], 'test/a@red')

    def test_consumer_payload_and_hash_recheck(self):
        shutil.copytree(ROOT/'scripts', self.root/'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT/'docs/schemas', self.root/'docs/schemas')
        spec = importlib.util.spec_from_file_location('consume_icon', ROOT/'examples/agent/consume_icon.py')
        consumer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consumer)
        code, payload = consumer.consume(self.root, 'test/a')
        self.assertEqual(code, 0)
        import base64
        raw = base64.b64decode(payload['svg_data_uri'].split(',', 1)[1])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), payload['resolved']['sha256'])
        lock_schema = json.loads((ROOT/'docs/schemas/icons-lock.schema.json').read_text())
        self.assertEqual(check_schema(payload['icons_lock'], lock_schema), [])
        self.assertEqual(consumer.consume(self.root, 'missing')[0], 2)
        from unittest.mock import patch
        response = payload['resolved']
        process = subprocess.CompletedProcess([], 0, stdout=json.dumps(response))
        (self.root/response['asset_relative_path']).write_bytes(b'changed after resolve')
        with patch.object(consumer.subprocess, 'run', return_value=process), self.assertRaisesRegex(ValueError, 'changed after resolution'):
            consumer.consume(self.root, 'test/a')


if __name__ == '__main__':
    unittest.main()
