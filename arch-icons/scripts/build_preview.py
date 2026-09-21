from library import ROOT,load_catalog,read_json,write_json
import json,collections

def build(root=ROOT):
 c=load_catalog(root);prefs=read_json(root/'catalog/preferences.json',{'defaults':{}})
 # A JS data file works through file:// as well as the optional local server.
 payload={'catalog':c,'preferences':prefs,'root_path':'.'}
 text=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
 (root/'previews/data.js').write_text('window.ICON_LIBRARY='+text+';\n')
 byhash=collections.defaultdict(list)
 for v in c['variants']:byhash[v['asset']['sha256']].append(v['id'])
 write_json(root/'reports/duplicates.json',{'rule':'Share identical normalized assets; keep semantic identities and styles separate. No original deleted.','shared_assets':[{'sha256':h,'variant_ids':ids} for h,ids in byhash.items() if len(ids)>1],'merged_source_origins':[{'variant_id':v['id'],'origins':v['origins']} for v in c['variants'] if len(v['origins'])>1]})
 return len(c['products'])
if __name__=='__main__':print('Preview data built:',build(),'entries')
