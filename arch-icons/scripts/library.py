"""Dependency-free catalog I/O, SVG normalization, and exact content deduplication."""
from pathlib import Path
import re,json,hashlib,xml.etree.ElementTree as ET,os,tempfile
ROOT=Path(os.environ.get('ARCH_ICONS_ROOT') or os.environ.get('ICON_PERSONAL_ROOT') or str(Path(__file__).resolve().parents[1])).resolve()
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
def read_json(path,default=None):
 return json.loads(Path(path).read_text()) if Path(path).exists() else default

def write_json(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.'+path.name,suffix='.tmp')
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
  os.replace(tmp,path)
 finally:
  if Path(tmp).exists():Path(tmp).unlink()

def sha(raw):return hashlib.sha256(raw).hexdigest()
def slug(s):
 s=re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')
 return s or 'unnamed'
def clean(s):
 import html
 return ' '.join(html.unescape(s or '').split())
def norm(s):return re.sub(r'[^\w]+','',clean(s).casefold())
def load_catalog(root=ROOT):return read_json(root/'catalog/index.json')
def save_catalog(c,root=ROOT):write_json(root/'catalog/index.json',c)

def review_queue(c):
 pending={v['product_id'] for v in c['variants'] if v['status']=='pending'}
 return [{'product_id':p['id'],'name':p['name'],'notes':p['notes'],
          'pending_variant_ids':[v['id'] for v in c['variants'] if v['product_id']==p['id'] and v['status']=='pending']}
         for p in c['products'] if p['status']=='pending' or p['id'] in pending]

def normalize_svg(raw):
 if len(raw)>4_000_000:raise ValueError('SVG exceeds 4 MB')
 if b'<!ENTITY' in raw.upper() or re.search(br'<!DOCTYPE[^>]*\[',raw,re.I):raise ValueError('DTD entities/internal subsets not allowed')
 raw=re.sub(br'<!DOCTYPE\s+svg\s+(?:PUBLIC|SYSTEM)\s+[^>]*>',b'',raw,flags=re.I)
 if b'<!DOCTYPE' in raw.upper():raise ValueError('Unsupported DTD')
 root=ET.fromstring(raw)
 if root.tag.split('}')[-1]!='svg':raise ValueError('Root is not SVG')
 allowed={'svg','g','defs','path','rect','circle','ellipse','line','polyline','polygon','title','desc','linearGradient','radialGradient','stop','clipPath','mask','use','symbol','text','tspan','filter','feGaussianBlur','feOffset','feComposite','feColorMatrix','feMorphology','feBlend','feFlood','feMerge','feMergeNode'}
 vb=root.get('viewBox')
 if not vb:
  dims=[]
  for k in ('width','height'):
   value=root.get(k,'');m=re.fullmatch(r'([\d.]+)(?:px)?',value)
   if not m:raise ValueError('SVG requires viewBox or numeric dimensions')
   dims.append(float(m.group(1)))
  vb=f'0 0 {dims[0]:g} {dims[1]:g}'
 box=[float(x) for x in re.split(r'[ ,]+',vb.strip())]
 import math
 if len(box)!=4 or not all(math.isfinite(x) for x in box) or min(box[2:])<=0:raise ValueError('Invalid viewBox')
 remove={'id','class','t','p-id','data-name','version','enable-background','xml:space'}
 for parent in list(root.iter()):
  for child in list(parent):
   if child.tag.split('}')[-1] in ('title','desc','metadata') or (child.tag.split('}')[-1]=='style' and not (child.text or '').strip()):parent.remove(child)
 idmap={e.get('id'):'n'+str(i) for i,e in enumerate(root.iter()) if e.get('id')}
 for e in root.iter():
  tag=e.tag.split('}')[-1]
  if tag not in allowed:raise ValueError('Unsupported SVG element: '+tag)
  e.tag='{'+NS+'}'+tag
  attrs={}
  for k,v in e.attrib.items():
   local=k.split('}')[-1]
   if local.lower().startswith('on'):raise ValueError('Event attribute is not allowed')
   if local=='href':
    if not v.startswith('#'):raise ValueError('Non-local SVG reference')
    if v[1:] not in idmap:raise ValueError('Missing href target')
    v='#'+idmap[v[1:]]
   if local=='style':
    declarations=[]
    for part in v.split(';'):
     if not part.strip():continue
     name,value=part.split(':',1);name=name.strip();value=value.strip()
     if name not in {'fill','stroke','stroke-width','opacity','fill-opacity','stroke-opacity','fill-rule','clip-rule','stroke-linecap','stroke-linejoin','stroke-miterlimit','stop-color','stop-opacity','stroke-dasharray','stroke-dashoffset','clip-path','mask-type','isolation','paint-order','overflow'}:raise ValueError('Unsupported inline style: '+name)
     declarations.append(name+':'+value)
    v=';'.join(sorted(declarations))
   if 'url(' in v:
    for target in re.findall(r'url\(([^)]+)\)',v):
     target=target.strip('\"\' ')
     if not target.startswith('#') or target[1:] not in idmap:raise ValueError('Invalid url reference')
    v=re.sub(r'url\([\"\']?#([^\)\"\']+)[\"\']?\)',lambda m:'url(#'+idmap[m.group(1)]+')',v)
   if any(t in v.lower() for t in ('javascript:','expression(','@import','https://','http://','file://')):raise ValueError('External or active attribute')
   if local=='id':attrs['id']=idmap[v];continue
   if local in remove or local.startswith('data-') or local in ('role','aria-label','aria-labelledby'):continue
   if local in ('width','height') and e is root:continue
   attrs[k]=v
  e.attrib.clear();e.attrib.update(sorted(attrs.items()))
  if e.text and not e.text.strip():e.text=None
  if e.tail and not e.tail.strip():e.tail=None
 root.set('viewBox',' '.join(f'{v:g}' for v in box));root.set('width','64');root.set('height','64');root.set('preserveAspectRatio','xMidYMid meet')
 # Prefix SVG IDs with a stable content digest to avoid collisions when inlining.
 for e in root.iter():
  attrs=dict(sorted(e.attrib.items()));e.attrib.clear();e.attrib.update(attrs)
 preliminary=ET.tostring(root,encoding='utf-8');prefix='i'+sha(preliminary)[:12]+'-'
 for e in root.iter():
  for k,v in list(e.attrib.items()):
   if k=='id':e.set(k,prefix+v)
   elif k.split('}')[-1]=='href':e.set(k,'#'+prefix+v[1:])
   elif 'url(#' in v:e.set(k,v.replace('url(#','url(#'+prefix))
  attrs=dict(sorted(e.attrib.items()));e.attrib.clear();e.attrib.update(attrs)
 raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
 return raw,box

def store_svg(raw,root=ROOT):
 normalized,box=normalize_svg(raw);digest=sha(normalized);rel='assets/'+digest[:2]+'/'+digest+'.svg'
 p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists():p.write_bytes(normalized)
 elif p.read_bytes()!=normalized:raise ValueError('Asset hash collision')
 return {'path':rel,'sha256':digest,'format':'svg','representation':'vector','bytes':len(normalized),'viewBox':box}

def safe_path(rel,root=ROOT):
 p=(root/rel).resolve()
 if not p.is_relative_to(root.resolve()):raise ValueError('Path escapes project')
 return p

def selected_variant(product,catalog,preferences=None):
 requested=(preferences or {}).get('defaults',{}).get(product['id'],product.get('default_variant'))
 candidates=[v for v in catalog['variants'] if v['product_id']==product['id']]
 variant=next((v for v in candidates if v['id']==requested),None)
 return variant

def check_schema(value,schema):
 """Validate the bounded JSON Schema vocabulary used by catalog and Agent schemas.

 This is not a general-purpose JSON Schema implementation. Unknown keywords fail
 explicitly so future schema changes cannot silently weaken validation.
 """
 errors=[]
 allowed={'$schema','$defs','$ref','oneOf','type','const','enum','properties','required','additionalProperties','items','minItems','maxItems','pattern','minLength','minimum','exclusiveMinimum'}
 def walk(x,r,path='$'):
  unknown=set(r)-allowed
  if unknown:raise ValueError('Unsupported schema keywords: '+','.join(sorted(unknown)))
  if 'oneOf' in r:
   matches=0
   for branch in r['oneOf']:
    start=len(errors);walk(x,branch,path)
    if len(errors)==start:matches+=1
    del errors[start:]
   if matches!=1:errors.append(path+': expected exactly one matching schema')
  if '$ref' in r:
   ref=r['$ref']
   if not ref.startswith('#/$defs/'):raise ValueError('Unsupported schema reference')
   return walk(x,schema['$defs'][ref.split('/')[-1]],path)
  if 'type' in r:
   types=r['type'] if isinstance(r['type'],list) else [r['type']]
   checks={'object':lambda:isinstance(x,dict),'array':lambda:isinstance(x,list),'string':lambda:isinstance(x,str),'integer':lambda:type(x)is int,'number':lambda:type(x)in(int,float),'null':lambda:x is None,'boolean':lambda:type(x)is bool}
   if not any(checks[t]() for t in types):errors.append(path+': incorrect type');return
  if 'const' in r and x!=r['const']:errors.append(path+': const mismatch')
  if 'enum' in r and x not in r['enum']:errors.append(path+': invalid enum')
  if isinstance(x,dict):
   for k in r.get('required',[]):
    if k not in x:errors.append(path+': missing '+k)
   for k,v in x.items():
    if k in r.get('properties',{}):walk(v,r['properties'][k],path+'.'+k)
    elif r.get('additionalProperties') is False:errors.append(path+': unexpected '+k)
  if isinstance(x,list):
   if len(x)<r.get('minItems',0) or len(x)>r.get('maxItems',float('inf')):errors.append(path+': invalid array length')
   if 'items' in r:
    for i,v in enumerate(x):walk(v,r['items'],path+'['+str(i)+']')
  if isinstance(x,str):
   if len(x)<r.get('minLength',0):errors.append(path+': string too short')
   if 'pattern' in r and not re.search(r['pattern'],x):errors.append(path+': pattern mismatch')
  if type(x)in(int,float):
   if 'minimum'in r and x<r['minimum']:errors.append(path+': below minimum')
   if 'exclusiveMinimum'in r and x<=r['exclusiveMinimum']:errors.append(path+': below exclusive minimum')
 walk(value,schema)
 return errors
