import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectNameTests(unittest.TestCase):
    def env(self, **values):
        env = {k: v for k, v in os.environ.items() if k not in ('ARCH_ICONS_ROOT', 'ICON_PERSONAL_ROOT')}
        return {**env, **values}

    def test_environment_precedence_and_legacy_support(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / 'old root'
            new = Path(temp) / 'new root'
            cases = [({}, ROOT), ({'ICON_PERSONAL_ROOT': str(old)}, old),
                     ({'ARCH_ICONS_ROOT': str(new)}, new),
                     ({'ICON_PERSONAL_ROOT': str(old), 'ARCH_ICONS_ROOT': str(new)}, new)]
            for variables, expected in cases:
                with self.subTest(variables=variables):
                    p = subprocess.run([sys.executable, '-c', 'import library; print(library.ROOT)'],
                                       cwd=ROOT/'scripts', env=self.env(**variables), capture_output=True, text=True)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(Path(p.stdout.strip()), expected.resolve())

    def test_both_skill_entries_resolve_same_svg(self):
        results = []
        for name in ('arch-icons', 'icon-personal'):
            for variables in ({}, {'ARCH_ICONS_ROOT': str(ROOT)}, {'ICON_PERSONAL_ROOT': str(ROOT)}):
                p = subprocess.run([sys.executable, str(ROOT/'skills'/name/'scripts/icon_query.py'),
                                    'resolve', 'MySQL', '--json'], env=self.env(**variables), capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
                result = json.loads(p.stdout)
                self.assertEqual(result['status'], 'resolved')
                results.append((result['product_id'], result['variant_id'], result['sha256']))
        self.assertEqual(len(set(results)), 1)


if __name__ == '__main__':
    unittest.main()
