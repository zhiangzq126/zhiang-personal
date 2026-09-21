"""Bounded compatibility conversion for the reviewed Tencent/Huawei icon packs."""
import re
import xml.etree.ElementTree as ET
from library import normalize_svg


def prepare_svg(raw, filename=''):
    try:
        normalize_svg(raw)
        return raw, []
    except ValueError:
        pass
    changes=[]
    s=raw.decode('utf-8-sig')
    subset=re.search(r'<!DOCTYPE[^\[]*\[([\s\S]*?)\]>',s)
    if subset:
        declarations=re.findall(r'<!ENTITY\s+(ns_\w+)\s+"(http://ns\.adobe\.com/[\w./]+)"\s*>',subset[1])
        remainder=re.sub(r'<!ENTITY\s+ns_\w+\s+"http://ns\.adobe\.com/[\w./]+"\s*>','',subset[1]).strip()
        if not declarations or remainder:raise ValueError('Only reviewed Adobe namespace declarations can be expanded')
        s=s.replace(subset[0],'')
        for name,value in declarations:s=s.replace('&'+name+';',value)
        changes.append('expanded-adobe-namespace-metadata')
    root=ET.fromstring(s)
    rules=[]
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.split('}')[-1]!='style':continue
            css=child.text or ''
            css=re.sub(r'/\*[\s\S]*?\*/','',css)
            if re.sub(r'[^{}]+\{[^{}]*\}','',css).strip():raise ValueError('Unsupported CSS rule')
            for selectors,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css):
                for selector in selectors.split(','):
                    selector=selector.strip()
                    if not re.fullmatch(r'\.[\w-]+|[A-Za-z]+',selector):raise ValueError('Unsupported CSS selector: '+selector)
                    rules.append((selector,body))
            parent.remove(child)
    if rules:changes.append('inlined-simple-css-rules')
    def declarations(body):
        out={}
        for part in body.split(';'):
            if not part.strip():continue
            key,value=part.split(':',1)
            if '!important' in value:raise ValueError('Unsupported important declaration')
            out[key.strip()]=value.strip()
        return out
    for node in root.iter():
        matched={}
        for selector,body in sorted(rules,key=lambda r:r[0].startswith('.')):
            if (selector.startswith('.') and selector[1:] in node.get('class','').split()) or selector==node.tag.split('}')[-1]:
                matched.update(declarations(body))
        matched.update(declarations(node.get('style','')))
        if 'enable-background' in matched:
            if 'BackgroundImage' in s or 'BackgroundAlpha' in s:raise ValueError('Background-dependent filter requires review')
            del matched['enable-background'];changes.append('removed-unused-enable-background')
        if '-inkscape-stroke' in matched:
            del matched['-inkscape-stroke'];changes.append('removed-inkscape-editor-property')
        if matched:node.set('style',';'.join(k+':'+v for k,v in matched.items()))
        else:node.attrib.pop('style',None)
    if filename=='设备安全.svg':
        for node in root.iter():
            if node.get('mask')=='url(#mask0_1885_87487)':
                node.set('mask','url(#mask0_1885_8747)');changes.append('repaired-dangling-mask-reference-needs-review')
    converted=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    normalize_svg(converted)
    return converted,list(dict.fromkeys(changes))
