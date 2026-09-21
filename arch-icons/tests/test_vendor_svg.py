import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from vendor_svg import prepare_svg
from library import normalize_svg


class VendorSvgTests(unittest.TestCase):
    def test_css_specificity_and_inline_override(self):
        raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>.a{fill:red}rect{fill:green}.a{opacity:0.5}</style><rect class="a" style="fill:blue" width="10" height="10"/></svg>'
        converted,changes=prepare_svg(raw)
        normalized,_=normalize_svg(converted)
        self.assertIn(b'fill:blue;opacity:0.5',normalized)
        self.assertNotIn(b'<style',normalized)
        self.assertIn('inlined-simple-css-rules',changes)

    def test_only_namespace_metadata_entities_are_converted(self):
        for raw in [b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg/>',b'<!DOCTYPE svg [<!ENTITY x "abc">]><svg/>']:
            with self.assertRaises(ValueError):prepare_svg(raw)

    def test_css_external_references_remain_rejected(self):
        raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><style>.a{fill:url(https://example.com/x)}</style><rect class="a" width="10" height="10"/></svg>'
        with self.assertRaises(ValueError):prepare_svg(raw)

    def test_added_safe_styles_keep_idempotent_normalization(self):
        raw=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path style="stroke:red;stroke-dasharray:2 2;paint-order:stroke fill" d="M0 0L10 10"/></svg>'
        a,_=normalize_svg(raw);b,_=normalize_svg(a)
        self.assertEqual(a,b)
        self.assertIn(b'stroke-dasharray:2 2',a)


if __name__=='__main__':unittest.main()
