// Reviews modify only an isolated fixture, never the real collection.
const fs=require('fs'),path=require('path'),os=require('os'),{spawn,execFileSync}=require('child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'icon-review-e2e-'));
const env={...process.env,ARCH_ICONS_ROOT:temp,PYTHONPATH:path.join(root,'scripts')};
const assert=(x,m)=>{if(!x)throw Error(m)};
let server,browser;
(async()=>{
 fs.cpSync(path.join(root,'previews'),path.join(temp,'previews'),{recursive:true});fs.mkdirSync(path.join(temp,'catalog'),{recursive:true});
 fs.copyFileSync(path.join(root,'catalog/schema.json'),path.join(temp,'catalog/schema.json'));
 for(const [name,data] of Object.entries({'index':{schema_version:1,products:[],variants:[]},'preferences':{schema_version:1,defaults:{}},'sources':{schema_version:1,files:[]}}))fs.writeFileSync(path.join(temp,'catalog',name+'.json'),JSON.stringify(data));
 const seed=JSON.parse(execFileSync('python3',['-c',`
import json,base64,uuid
from web_import import ImportService
s=ImportService()
def add(name,color,status='pending',target=None):
 raw=('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect x="4" y="4" width="32" height="32" rx="6" fill="'+color+'"/></svg>').encode()
 row={'filename':name+'.svg','data':base64.b64encode(raw).decode(),'name':name,'provider':'example','category':'待分类','aliases':[name],'kind':'product','style':color,'action':'link' if target else 'new','target':target,'distinct':True}
 return s.commit({'items':[row],'revision':s.inspect({'items':[row]})['revision'],'request_id':str(uuid.uuid4()),'source_name':'review fixture','status':status})['items'][0]
ready=add('Ready Reference','#ff8800','ready')
alpha=add('Alpha','#ff8800')
beta=add('Beta','#33aa66')
beta2=add('Beta','#4488ff',target=beta['product_id'])
gamma=add('Gamma','#884488')
delta=add('Delta','#224488')
print(json.dumps(dict(ready=ready,alpha=alpha,beta=beta,beta2=beta2,gamma=gamma,delta=delta)))
`],{env,encoding:'utf8'}));
 server=spawn('python3',[path.join(root,'scripts/iconlib.py'),'serve','--port','0'],{env,stdio:['ignore','pipe','pipe']});
 const base=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Server timeout')),10000);server.stdout.on('data',b=>{text+=b;const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});server.on('error',reject);});
 browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('dialog',d=>d.accept());
 await page.goto(base+'/previews/index.html');await page.waitForSelector('.icon-card');
 assert((await page.locator('#open-review').textContent()).includes('4'),'Queue count on entry');
 await page.locator('#open-review').click();await page.waitForFunction(()=>document.getElementById('review-name').textContent==='Alpha'&&!document.getElementById('review-approve').disabled);
 assert(await page.locator('#review-list button').count()===4,'All pending entries in one queue');
 assert((await page.locator('#review-matches').textContent()).includes('图形完全相同'),'Duplicate comparison');
 await page.locator('#review-approve').click();assert((await page.locator('#review-status').textContent()).includes('审核依据'),'Review note required');
 await page.locator('#review-skip').click();assert(await page.locator('#review-name').textContent()==='Beta','Skip advances without mutation');
 assert(await page.locator('#review-variants [data-approve]:checked').count()===0,'Multi-variant review requires explicit selection');
 await page.locator('#review-variants img').first().evaluate(i=>i.decode());
 await page.screenshot({path:path.join(root,'reports/review-desktop.png')});
 assert(await page.locator('#review-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),'Desktop review layout');
 await page.locator('#review-product-name').fill('Corrected Beta');await page.locator('#review-product-provider').fill('opensource');await page.locator('#review-category').fill('数据库');await page.locator('#review-aliases').fill('BetaDB, 准确名称');
 await page.locator('[data-approve]').first().check();await page.locator('[data-style]').first().fill('绿色版');await page.locator('#review-default').selectOption(seed.beta.variant_id);await page.locator('#review-note').fill('已核对来源，确认首个图形，其他继续核实。');
 await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('已确认'));
 assert(await page.locator('#review-name').textContent()==='Gamma','Successful partial review advances to next entry');
 let c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))),p=c.products.find(p=>p.name==='Corrected Beta');
 assert(p.id.startsWith('opensource/')&&p.status==='ready','Identity correction and approval persisted');assert(c.variants.filter(v=>v.product_id===p.id&&v.status==='pending').length===1,'Unselected variant stays pending');
 assert(await page.locator('#review-list button').count()===4,'Partially-reviewed product remains in queue');
 const betaId=p.id,betaDefault=p.default_variant;
 // Save metadata without enabling; mobile review and source preview.
 await page.locator('#review-category').fill('继续核实');await page.locator('#review-note').fill('暂未确认产品身份');await page.locator('#review-save').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('已保存修改'));
 c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json')));assert(c.products.find(p=>p.name==='Gamma').status==='pending','Save does not approve');
 await page.setViewportSize({width:390,height:844});await page.locator('#review-editor').evaluate(n=>n.scrollTop=0);
 assert(await page.locator('#review-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),'Mobile review layout');await page.screenshot({path:path.join(root,'reports/review-mobile.png')});
 await page.setViewportSize({width:1440,height:1000});
 // Link a duplicate to the ready product, preserving source provenance and default.
 await page.locator(`[data-review-product="${seed.alpha.product_id}"]`).click();await page.locator('#review-matches button').click();await page.locator('#review-note').fill('已核实与 Ready Reference 属于同一产品。');
 await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('已确认'));
 c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json')));assert(!c.products.some(p=>p.id===seed.alpha.product_id),'Merged pending identity removed from active catalog');assert(c.variants.find(v=>v.id===seed.ready.variant_id).origins.length===2,'Origins retained');
 assert(c.products.find(p=>p.id===seed.ready.product_id).default_variant===seed.ready.variant_id,'Target default preserved');
 // Ready product identity is locked, but its remaining pending variant can be reviewed.
 await page.locator(`[data-review-product="${betaId}"]`).click();assert(await page.locator('#review-product-name').isDisabled(),'Ready identity locked');
 assert(await page.locator('#review-variants [data-approve][data-ready="true"]').isDisabled(),'Ready variant is read-only');
 await page.locator('#review-note').fill('第二个图形已核对，是同一产品的蓝色变体。');await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('已确认'));
 c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json')));assert(c.products.find(p=>p.id===betaId).default_variant===betaDefault,'Additional approval preserves default');
 assert(await page.locator('#review-list button').count()===2,'Queue shrinks after completion');
 // Review direct from details, search filters, and stale edits cannot overwrite newer state.
 await page.locator('#review-close').click();await page.locator('#pending').check();await page.locator(`[data-product="${seed.delta.product_id}"]`).click();await page.locator('#review-current').click();await page.waitForFunction(()=>document.getElementById('review-name').textContent==='Delta');
 await page.locator('#review-search').fill('Gamma');assert(await page.locator('#review-list button').count()===1,'Queue search');await page.locator('#review-search').fill('');
 await page.locator('#review-note').fill('已核对来源');
 const preferences=JSON.parse(fs.readFileSync(path.join(temp,'catalog/preferences.json')));preferences.defaults[seed.ready.product_id]=seed.ready.variant_id;fs.writeFileSync(path.join(temp,'catalog/preferences.json'),JSON.stringify(preferences));
 await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.includes('已更新'));
 assert(JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))).products.find(p=>p.name==='Gamma').status==='pending','Stale request made no mutation');
 await page.locator('#review-refresh').click();await page.waitForFunction(()=>!document.getElementById('review-refresh').disabled);
 const denied=await page.request.post(base+'/api/review/commit',{data:{},headers:{Origin:'https://outside.example'}});assert(denied.status()===403,'Cross-origin review rejected');
 assert(JSON.parse(execFileSync('python3',[path.join(root,'scripts/iconlib.py'),'validate','--json'],{env,encoding:'utf8'})).ok,'Reviewed catalog validates');
 // Delete preview is explicit; cancelling leaves files untouched, confirming recycles only unused assets.
 await page.locator(`[data-review-product="${seed.gamma.product_id}"]`).click();
 await page.locator('#review-action').selectOption('delete');
 assert(await page.locator('#review-delete-info').isVisible(),'Delete impact explanation');
 assert(await page.locator('#review-metadata').isHidden(),'Identity editing hidden during deletion');
 assert(await page.locator('#review-default-label').isHidden(),'Cannot set default while deleting');
 assert(await page.locator('#review-save').isDisabled(),'Save-pending disabled for delete mode');
 await page.locator('#review-approve').click();assert((await page.locator('#review-status').textContent()).includes('有误原因'),'Deletion requires a reason');
 await page.locator('#review-note').fill('确认素材有误，清理此图形');
 const beforeDelete=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))),asset=beforeDelete.variants.find(v=>v.id===seed.gamma.variant_id).asset.path;
 let deletionPrompt='';page.removeAllListeners('dialog');page.once('dialog',async d=>{deletionPrompt=d.message();await d.dismiss();});
 await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.includes('已取消删除'));
 assert(deletionPrompt.includes('1 个待确认图形')&&deletionPrompt.includes('原始来源文件'),'Specific delete confirmation');
 assert(JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))).products.some(p=>p.id===seed.gamma.product_id),'Cancel preserves catalog');
 assert(fs.existsSync(path.join(temp,asset)),'Cancel preserves asset');
 await page.locator('#review-delete-info').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'reports/review-delete.png')});
 page.on('dialog',d=>d.accept());await page.locator('#review-approve').click();await page.waitForFunction(()=>document.getElementById('review-status').textContent.startsWith('已清理'));
 assert(!JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))).products.some(p=>p.id===seed.gamma.product_id),'Deleted item removed');
 assert(!fs.existsSync(path.join(temp,asset)),'Unused asset removed from assets');
 const receipts=fs.readdirSync(path.join(temp,'reports/web-reviews')).map(f=>JSON.parse(fs.readFileSync(path.join(temp,'reports/web-reviews',f))));
 const deletion=receipts.find(r=>r.result.action==='delete');assert(fs.existsSync(path.join(temp,deletion.result.recovery_path,asset)),'Asset is recoverable');
 assert(await page.locator('#review-list button').count()===1,'Delete advances and updates queue');
 assert(JSON.parse(execFileSync('python3',[path.join(root,'scripts/iconlib.py'),'validate','--json'],{env,encoding:'utf8'})).ok,'Catalog validates after delete');
 await page.goto('file://'+path.join(temp,'previews/index.html'));await page.locator('#open-review').click();await page.waitForFunction(()=>document.getElementById('review-connection').textContent.includes('只能浏览'));assert(await page.locator('#review-approve').isDisabled(),'Offline review is read-only');
 assert(errors.length===0,'JS errors: '+errors.join(','));
 fs.writeFileSync(path.join(root,'reports/review-browser-validation.json'),JSON.stringify({ok:true,flows:['review queue','search','skip','metadata correction','provider correction','partial approval','save pending','merge duplicate','preserve sources and default','pending variants of ready products','detail entry','stale protection','offline read-only','desktop/mobile','delete scope preview','cancel deletion','delete and recycle unused asset'],errors},null,2)+'\n');
 console.log('Review browser checks passed; real collection unchanged.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)server.kill();fs.rmSync(temp,{recursive:true,force:true});});
