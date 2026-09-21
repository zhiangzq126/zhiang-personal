#!/usr/bin/env python3
"""Local icon search, resolution, preferences, import, validation and viewer."""
from pathlib import Path
import argparse,json,sys,re,collections,base64,xml.etree.ElementTree as ET,shutil,threading
from library import ROOT,read_json,write_json,sha,slug,norm,clean,store_svg,safe_path,load_catalog,save_catalog,selected_variant,check_schema,review_queue
PROVIDERS={'aliyun':'阿里云','aws':'AWS','opensource':'开源组件','tencent':'腾讯云','huawei':'华为云','generic':'通用组件','status':'状态符号','unclassified':'待分类'}
LOCK=threading.RLock()
CONTRACT_VERSION=2
INDEPENDENT_PROVIDERS={'opensource','generic','status'}
def component_for(query):
 config=read_json(ROOT/'catalog/component-mappings.json',{'schema_version':1,'components':[]})
 if config.get('schema_version')!=1:raise ValueError('Unsupported component mappings version')
 return next((x for x in config['components'] if norm(query) in {norm(t) for t in [x['name'],*x['aliases']]}),None)

def search(query,provider=None,include_pending=False,limit=20,catalog=None):
 c=catalog or load_catalog();q=norm(query);out=[];component=component_for(query)
 for p in c['products']:
  if provider and p['provider']!=provider:continue
  if not include_pending and p['status']!='ready':continue
  terms=[p['id'],p['name']]+p['aliases'];normalized=[norm(x) for x in terms]
  if component:
   independent=p['provider'] in INDEPENDENT_PROVIDERS and (p['id']==component['id'] or bool(set(normalized)&{norm(t) for t in [component['name'],*component['aliases']]}))
   if independent or p['id'] in component['vendor_product_ids']:
    out.append({**p,'score':800 if independent else 700,'component_name':component['name'],'variant_count':sum(v['product_id']==p['id'] for v in c['variants'])})
   continue
  score=1000 if query.casefold()==p['id'].casefold() else 800 if q and q in normalized else 400 if q and any(q in x for x in normalized) else 0
  if not query.strip():score=1
  if not score:
   tokens=[norm(t) for t in re.split(r'\s+',query.strip()) if norm(t)]
   if tokens and all(any(t in x for x in normalized) for t in tokens):score=200
  if score:out.append({**p,'score':score,'variant_count':sum(v['product_id']==p['id'] for v in c['variants'])})
 out.sort(key=lambda p:(-p['score'],p['id']))
 return out[:limit]

def resolve(query,provider=None,catalog=None,preferences=None,variant_id=None):
 c=catalog or load_catalog();prefs=preferences if preferences is not None else read_json(ROOT/'catalog/preferences.json',{'defaults':{}})
 explicit=next((p for p in c['products'] if p['id'].casefold()==query.casefold() and (not provider or p['provider']==provider)),None)
 found=[explicit] if explicit else search(query,provider,True,limit=len(c['products']),catalog=c)
 exact=[p for p in found if explicit or p.get('score',0)>=800]
 brief=lambda p:{'id':p['id'],'name':p['name'],'provider':p['provider'],'status':p['status']}
 messages={
  'not_found':('完全没有素材：当前查询范围内未找到相关条目。','使用卡片，可补充或导入素材。'),
  'no_exact_match':('找到了相关素材，但尚未确定准确的产品身份。','结合上下文确认候选产品，勿取搜索第一项。'),
  'vendor_only':('只有厂商版本，没有可自动复用的阿里云 SVG。','使用卡片，或由用户指定厂商图标。'),
  'needs_provider_context':('只有厂商版本，尚无已配置的组件素材映射。','使用卡片，或明确厂商/配置映射。'),
  'ambiguous':('存在歧义：匹配到多个产品身份。','确认产品或厂商后再次解析。'),
  'pending_review':('已找到条目，但仍待审核。','使用卡片，在浏览页完成审核。'),
  'invalid_variant':('指定的变体不存在或不属于所选产品。','更正变体 ID。'),
  'unusable_variant':('所选变体缺失或不可用。','检查默认变体；待审核变体需先审核。'),
  'asset_integrity_error':('素材文件缺失或摘要校验失败。','使用卡片并修复素材。')}
 def failure(status,choices=None):
  message,action=messages[status]
  return {'status':status,'fallback':'card','candidates':[brief(p) for p in (choices or [])[:8]],'diagnostic':{'code':status,'message':message,'action':action}}
 component=component_for(query) if not explicit else None
 reuse=False
 independent=[p for p in exact if p['provider'] in INDEPENDENT_PROVIDERS]
 if not provider and not explicit and independent:
  exact=independent
 elif component and not explicit:
  if provider:
   exact=[p for p in found if p['id'] in component['vendor_product_ids'] or p['id']==component['id'] or p['provider'] in INDEPENDENT_PROVIDERS]
  else:
   preferred=[p for p in found if p['id']==component['preferred_svg_product_id'] and p['provider']=='aliyun']
   if not preferred:
    if found and all(p['status']!='ready' for p in found):return failure('pending_review',found)
    return failure('vendor_only' if found else 'not_found',found)
   exact=preferred;reuse=True
 if not exact:return failure('no_exact_match' if found else 'not_found',found)
 if len(exact)>1:return failure('ambiguous',exact)
 p=exact[0]
 if p['status']!='ready':return failure('pending_review',[p])
 if not reuse and not provider and not explicit and p['provider'] not in INDEPENDENT_PROVIDERS and norm(query) in {'redis','mongodb','postgresql','postgres','mysql','elasticsearch','flink','kafka','kubernetes'}:
  return failure('needs_provider_context',[p])
 if variant_id is not None:
  v=next((v for v in c['variants'] if v['id']==variant_id and v['product_id']==p['id']),None)
  if not v:return failure('invalid_variant',[p])
 else:v=selected_variant(p,c,prefs)
 if v and v['status']=='pending':return failure('pending_review',[p])
 if not v or v['status']!='ready' or v['asset']['representation']!='vector':return failure('unusable_variant',[p])
 path=safe_path(v['asset']['path'])
 if not path.exists() or sha(path.read_bytes())!=v['asset']['sha256']:return failure('asset_integrity_error',[p])
 result={'status':'resolved','product_id':p['id'],'name':p['name'],'provider':p['provider'],'variant_id':v['id'],'style':v['style'],'asset_path':str(path),'asset_relative_path':v['asset']['path'],'sha256':v['asset']['sha256'],'representation':'vector','theme':v['theme'],'kind':p['kind'],'selection':'explicit_variant' if variant_id is not None else 'user_preference' if p['id'] in prefs.get('defaults',{}) else 'catalog_default'}
 result['display_name']=component['name'] if component and not provider else p['name']
 result['match_type']='vendor_svg_reuse' if reuse else 'independent_component' if p['provider'] in INDEPENDENT_PROVIDERS else 'exact_product'
 if component and not provider:result['requested_component']={'id':component['id'],'name':component['name']}
 result['diagnostic']={'code':result['match_type'],'message':f"缺少独立组件图标，已复用阿里云 {p['name']} 的 SVG；节点仍表示 {component['name']}，不表示部署在阿里云。" if reuse else '已找到可用图标。','action':'保留用户原标签或使用 display_name；product_id/name/provider 是素材所属产品，不改变节点部署语义。'}
 return result

def prefer(product_id,variant_id):
 with LOCK:
  c=load_catalog();p=next((p for p in c['products'] if p['id']==product_id),None)
  if not p:raise ValueError('Unknown product')
  prefs=read_json(ROOT/'catalog/preferences.json',{'schema_version':1,'defaults':{}})
  if variant_id is None:prefs['defaults'].pop(product_id,None)
  else:
   v=next((v for v in c['variants'] if v['id']==variant_id and v['product_id']==product_id),None)
   if not v or p['status']!='ready' or v['status']!='ready':raise ValueError('Default must be a ready variant of this ready product')
   prefs['defaults'][product_id]=variant_id
  write_json(ROOT/'catalog/preferences.json',prefs)
  from build_preview import build
  build()
  return prefs

def validate(catalog=None,check_sources=True,root=ROOT):
 c=catalog or load_catalog(root);schema=read_json(root/'catalog/schema.json');errors=check_schema(c,schema) if schema else [];warnings=[];products={p['id']:p for p in c['products']};variants={v['id']:v for v in c['variants']};assets={}
 if len(products)!=len(c['products']):errors.append('Duplicate product IDs')
 if len(variants)!=len(c['variants']):errors.append('Duplicate variant IDs')
 mappings=read_json(root/'catalog/component-mappings.json',{'schema_version':1,'components':[]})
 if mappings.get('schema_version')!=1:errors.append('Unsupported component mappings version')
 seen_components=set();seen_aliases={}
 for mapping in mappings['components']:
  cid=mapping['id']
  if cid in seen_components:errors.append('Duplicate component mapping '+cid)
  seen_components.add(cid)
  for alias in [mapping['name'],*mapping['aliases']]:
   key=norm(alias)
   if key in seen_aliases and seen_aliases[key]!=cid:errors.append('Ambiguous component alias '+alias)
   seen_aliases[key]=cid
  preferred=mapping['preferred_svg_product_id']
  if preferred not in mapping['vendor_product_ids'] or products.get(preferred,{}).get('provider')!='aliyun':errors.append('Invalid Alibaba SVG mapping '+cid)
  for pid in mapping['vendor_product_ids']:
   if pid not in products:errors.append('Missing mapped vendor product '+pid)
 for p in products.values():
  if p['status'] not in ('ready','pending'):errors.append('Bad product status '+p['id'])
  if p['status']=='ready' and (p.get('default_variant') not in variants or variants[p['default_variant']]['product_id']!=p['id'] or variants[p['default_variant']]['status']!='ready'):errors.append('Bad default '+p['id'])
  if p['status']=='pending' and p.get('default_variant') is not None:errors.append('Pending product has default '+p['id'])
 for v in variants.values():
  if v['product_id'] not in products:errors.append('Dangling product '+v['id'])
  a=v['asset'];assets[a['path']]=a
  if not a['path'].startswith('assets/') or not a['path'].endswith('.svg') or a['representation']!='vector':errors.append('Invalid asset contract '+v['id'])
  for origin in v['origins']:
   if not safe_path(origin['path'],root).exists():errors.append('Missing source '+origin['path'])
 for rel,a in assets.items():
  try:
   p=safe_path(rel,root);raw=p.read_bytes();r=ET.fromstring(raw)
   if sha(raw)!=a['sha256']:errors.append('Digest mismatch '+rel)
   if not r.get('viewBox'):errors.append('No viewBox '+rel)
   idset={e.get('id') for e in r.iter() if e.get('id')}
   for e in r.iter():
    if e.tag.split('}')[-1] in ('script','image','foreignObject','style'):errors.append('Unsupported active/raster content '+rel)
    for k,val in e.attrib.items():
     if k.lower().startswith('on'):errors.append('Event attribute '+rel)
     if k.split('}')[-1]=='href' and (not val.startswith('#') or val[1:] not in idset):errors.append('Broken href '+rel)
     for ref in re.findall(r'url\(#([^)]+)\)',val):
      if ref not in idset:errors.append('Broken ID reference '+rel)
  except Exception as e:errors.append(rel+': '+str(e))
 prefs=read_json(root/'catalog/preferences.json',{'defaults':{}})
 for pid,vid in prefs['defaults'].items():
  if pid not in products or vid not in variants or variants[vid]['product_id']!=pid or products[pid]['status']!='ready' or variants[vid]['status']!='ready':errors.append('Invalid preference '+pid)
 if check_sources:
  for f in read_json(root/'catalog/sources.json',{'files':[]})['files']:
   try:
    if sha(safe_path(f['path'],root).read_bytes())!=f['sha256']:errors.append('Original source changed '+f['path'])
   except OSError:errors.append('Missing original '+f['path'])
 for p in products.values():
  if p['status']=='pending':warnings.append({'id':p['id'],'reason':'identity_review_pending'})
 result={'ok':not errors,'products':len(products),'variants':len(variants),'unique_assets':len(assets),'ready_products':sum(p['status']=='ready' for p in products.values()),'pending_products':len(warnings),'errors':errors,'review_items':warnings}
 return result

def import_files(path,provider,source_name):
 if not re.fullmatch('[a-z][a-z0-9-]*',provider):raise ValueError('Invalid provider')
 src=Path(path).expanduser().resolve()
 if not src.exists():raise ValueError('Input path does not exist')
 files=[src] if src.is_file() else [p for p in sorted(src.rglob('*')) if p.is_file() and p.suffix.lower() in ('.svg','.png','.jpg','.jpeg','.xml','.drawio')]
 if not files:raise ValueError('No supported input files')
 c=load_catalog();manifest=read_json(ROOT/'catalog/sources.json');existing={x['path'] for x in manifest['files']};result={'added':[],'archived':[],'skipped':[]}
 digest=sha(b''.join((str(p.relative_to(src) if src.is_dir() else p.name).encode()+p.read_bytes()) for p in files))[:12]
 destbase=ROOT/'sources/imports'/(slug(source_name)+'-'+digest)
 for f in files:
  dst=destbase/(f.relative_to(src) if src.is_dir() else f.name);dst.parent.mkdir(parents=True,exist_ok=True);raw=f.read_bytes()
  if dst.exists() and dst.read_bytes()!=raw:raise ValueError('Refusing to change archived original')
  if not dst.exists():shutil.copy2(f,dst)
  rel=str(dst.relative_to(ROOT))
  if rel not in existing:manifest['files'].append({'path':rel,'sha256':sha(raw),'bytes':len(raw)});existing.add(rel)
  inputs=[]
  if f.suffix.lower()=='.svg':inputs=[(f.stem,raw)]
  elif f.suffix.lower() in ('.xml','.drawio'):
   try:
    r=ET.fromstring(raw)
    if r.tag!='mxlibrary':raise ValueError('Only mxlibrary input is supported; stencil/drawing conversion needs an adapter')
    for i,e in enumerate(json.loads(r.text)):
     d=e.get('data','')
     if not d.startswith('data:image/svg+xml'):result['archived'].append({'source':rel,'entry':e.get('title',str(i)),'reason':'not embedded SVG'});continue
     head,body=d.split(',',1)
     import urllib.parse
     inputs.append((clean(e.get('title',f.stem)),base64.b64decode(body) if ';base64' in head else urllib.parse.unquote_to_bytes(body)))
   except Exception as e:result['skipped'].append({'source':rel,'reason':str(e)})
  else:result['archived'].append({'source':rel,'reason':'Raster preserved; no fake vector conversion'})
  for name,data in inputs:
   try:a=store_svg(data)
   except Exception as e:result['skipped'].append({'source':rel,'entry':name,'reason':str(e)});continue
   pid=provider+'/import-'+slug(name)+'-'+sha(name.encode()+data)[:8];vid=pid+'@imported-'+a['sha256'][:10]
   existing_variant=next((v for v in c['variants'] if v['id']==vid),None)
   origin={'path':rel,'entry':name,'original_sha256':sha(data)}
   if existing_variant:
    if origin not in existing_variant['origins']:existing_variant['origins'].append(origin)
    result['skipped'].append({'id':pid,'reason':'already imported'});continue
   c['products'].append({'id':pid,'provider':provider,'name':name,'category':'新导入','kind':'product','aliases':[name],'status':'pending','identity_basis':'filename-or-library-label','notes':['新导入素材，需要确认产品身份后启用自动选择。'],'default_variant':None})
   c['variants'].append({'id':vid,'product_id':pid,'style':'imported','status':'pending','asset':a,'origins':[origin],'priority':10,'theme':{'preserve_colors':True,'dark_backdrop':False},'optical_scale':1.0});result['added'].append(pid)
 save_catalog(c);write_json(ROOT/'catalog/sources.json',manifest);sync_review(c)
 from build_preview import build
 build();return result

def sync_review(c):write_json(ROOT/'catalog/review-queue.json',review_queue(c))
def review(pid,status,note,name=None,aliases=None):
 c=load_catalog();p=next((p for p in c['products'] if p['id']==pid),None)
 if not p:raise ValueError('Unknown product')
 if not note.strip():raise ValueError('Review note is required')
 if name:p['name']=name
 if aliases:p['aliases']=list(dict.fromkeys(p['aliases']+aliases))
 p['status']=status;p['notes'].append('人工确认：'+note);choices=[v for v in c['variants'] if v['product_id']==pid]
 for v in choices:v['status']=status
 p['default_variant']=min(choices,key=lambda v:(v['priority'],v['id']))['id'] if status=='ready' else None
 if status=='pending':
  prefs=read_json(ROOT/'catalog/preferences.json');prefs['defaults'].pop(pid,None);write_json(ROOT/'catalog/preferences.json',prefs)
 save_catalog(c);sync_review(c)
 from build_preview import build
 build();return p

def serve(port,open_browser=False):
 from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
 from urllib.parse import urlsplit
 class Handler(SimpleHTTPRequestHandler):
  def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
  def log_message(self,*args):pass
  def send_json(self,obj,status=200):
   raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
  def do_GET(self):
   path=urlsplit(self.path).path
   if path=='/api/import':return self.send_json({'version':1,'max_files':50,'max_bytes':12000000})
   if path=='/api/review':
    from web_review import ReviewService
    with LOCK:return self.send_json(ReviewService().queue())
   if path=='/api/preferences':return self.send_json(read_json(ROOT/'catalog/preferences.json'))
   if path=='/api/catalog':return self.send_json(load_catalog())
   if path=='/':self.path='/previews/index.html'
   super().do_GET()
  def end_headers(self):
   self.send_header('X-Content-Type-Options','nosniff');super().end_headers()
  def do_POST(self):
   if self.path not in ('/api/preferences','/api/import/check','/api/import/commit','/api/review/commit','/api/review/delete-plan'):return self.send_json({'error':'Not found'},404)
   host=self.headers.get('Host','')
   expected='http://'+host
   if host not in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)) or self.headers.get('Origin')!=expected or self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.send_json({'error':'Same-origin JSON required'},403)
   try:
    length=int(self.headers.get('Content-Length','0'))
    limit=8192 if self.path=='/api/preferences' else 18_000_000
    if length<=0 or length>limit:raise ValueError('请求过大或为空')
    self.connection.settimeout(30)
    d=json.loads(self.rfile.read(length))
    if not isinstance(d,dict):raise ValueError('请求格式不正确')
    with LOCK:
     if self.path=='/api/preferences':result=prefer(d['product_id'],d.get('variant_id'))
     elif self.path in ('/api/review/commit','/api/review/delete-plan'):
      from web_review import ReviewService
      result=ReviewService().delete_plan(d) if self.path.endswith('/delete-plan') else ReviewService().commit(d)
     else:
      from web_import import ImportService
      service=ImportService()
      result=service.inspect(d) if self.path.endswith('/check') else service.commit(d)
    self.send_json(result)
   except Exception as e:self.send_json({'error':str(e)},400)

 class LocalServer(ThreadingHTTPServer):
  request_queue_size=128
 server=LocalServer(('127.0.0.1',port),Handler);print(f'http://127.0.0.1:{server.server_port}/previews/index.html',flush=True)
 if open_browser:
  import webbrowser
  webbrowser.open(f'http://127.0.0.1:{server.server_port}/previews/index.html')
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()

def main():
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 for name in ('search','resolve'):
  p=sub.add_parser(name);p.add_argument('query');p.add_argument('--provider');p.add_argument('--json',action='store_true')
  if name=='search':p.add_argument('--include-pending',action='store_true');p.add_argument('--limit',type=int,default=20)
  else:p.add_argument('--variant',help='Use this ready variant for this call only; does not save preferences')
 p=sub.add_parser('show');p.add_argument('id');p.add_argument('--json',action='store_true')
 p=sub.add_parser('prefer');p.add_argument('product_id');p.add_argument('variant_id',nargs='?');p.add_argument('--reset',action='store_true');p.add_argument('--json',action='store_true')
 p=sub.add_parser('validate');p.add_argument('--json',action='store_true');p.add_argument('--skip-sources',action='store_true')
 p=sub.add_parser('serve');p.add_argument('--port',type=int,default=0);p.add_argument('--open',action='store_true')
 p=sub.add_parser('import');p.add_argument('path');p.add_argument('--provider',required=True);p.add_argument('--source-name',required=True);p.add_argument('--json',action='store_true')
 p=sub.add_parser('review');p.add_argument('id');p.add_argument('--status',choices=['ready','pending'],required=True);p.add_argument('--note',required=True);p.add_argument('--name');p.add_argument('--alias',action='append');p.add_argument('--json',action='store_true')
 a=parser.parse_args();code=0
 try:
  if a.command=='search':result={'query':a.query,'matches':search(a.query,a.provider,a.include_pending,max(1,a.limit))}
  elif a.command=='resolve':result=resolve(a.query,a.provider,variant_id=a.variant);code=0 if result['status']=='resolved' else 2
  elif a.command=='show':
   c=load_catalog();p=next((p for p in c['products'] if p['id']==a.id),None)
   if not p:raise ValueError('Unknown product ID')
   result={'product':p,'variants':[v for v in c['variants'] if v['product_id']==a.id]}
  elif a.command=='prefer':
   if not a.reset and not a.variant_id:raise ValueError('Specify variant_id or --reset')
   result=prefer(a.product_id,None if a.reset else a.variant_id)
  elif a.command=='validate':result=validate(check_sources=not a.skip_sources);write_json(ROOT/'reports/validation.json',result);code=0 if result['ok'] else 1
  elif a.command=='import':result=import_files(a.path,a.provider,a.source_name)
  elif a.command=='review':result=review(a.id,a.status,a.note,a.name,a.alias)
  elif a.command=='serve':return serve(a.port,a.open)
  if a.command in ('search','resolve','show'):result={'contract_version':CONTRACT_VERSION,**result}
  print(json.dumps(result,ensure_ascii=False,indent=2))
 except Exception as e:
  result={'error':str(e)}
  if a.command in ('search','resolve','show'):result={'contract_version':CONTRACT_VERSION,**result}
  print(json.dumps(result,ensure_ascii=False));code=1
 return code
if __name__=='__main__':sys.exit(main() or 0)
