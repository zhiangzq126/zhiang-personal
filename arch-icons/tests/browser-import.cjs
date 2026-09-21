// End-to-end imports run against a disposable library and server.
const fs=require('fs'),path=require('path'),os=require('os'),{spawn,execFileSync}=require('child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'icon-import-e2e-'));
const env={...process.env,ARCH_ICONS_ROOT:temp,PYTHONPATH:path.join(root,'scripts')};
const svg=color=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect x="4" y="4" width="32" height="32" rx="6" fill="${color}"/></svg>`;
const upload=(name,content)=>({name,mimeType:'image/svg+xml',buffer:Buffer.from(content)});
const assert=(value,message)=>{if(!value)throw Error(message)};
let server,browser;
(async()=>{
 fs.cpSync(path.join(root,'previews'),path.join(temp,'previews'),{recursive:true});
 fs.mkdirSync(path.join(temp,'catalog'),{recursive:true});
 fs.copyFileSync(path.join(root,'catalog/schema.json'),path.join(temp,'catalog/schema.json'));
 for(const [name,data] of Object.entries({'index':{schema_version:1,products:[],variants:[]},'preferences':{schema_version:1,defaults:{}},'sources':{schema_version:1,files:[]}}))fs.writeFileSync(path.join(temp,'catalog',name+'.json'),JSON.stringify(data));
 const seed=JSON.parse(execFileSync('python3',['-c',`
import json,base64,uuid
from web_import import ImportService
s=ImportService()
def add(row):
 p={'items':[row],'revision':s.inspect({'items':[row]})['revision'],'source_name':'E2E fixture','request_id':str(uuid.uuid4()),'status':'ready'}
 return s.commit(p)['items'][0]
row={'filename':'Example.svg','data':base64.b64encode(${JSON.stringify(svg('#ee7733'))}.encode()).decode(),'name':'示例数据库','provider':'example','category':'数据库','aliases':['ExampleDB'],'kind':'product','style':'橙色','action':'new'}
a=add(row)
row.update(data=base64.b64encode(${JSON.stringify(svg('#3388ee'))}.encode()).decode(),action='link',target=a['product_id'],style='蓝色')
b=add(row)
print(json.dumps({'product':a['product_id'],'orange':a['variant_id'],'blue':b['variant_id']}))
`],{env,encoding:'utf8'}));
 server=spawn('python3',[path.join(root,'scripts/iconlib.py'),'serve','--port','0'],{env,stdio:['ignore','pipe','pipe']});
 const base=await new Promise((resolve,reject)=>{let text='';const timer=setTimeout(()=>reject(Error('Server start timeout')),10000);server.stdout.on('data',chunk=>{text+=chunk;const m=text.match(/http:\/\/127\.0\.0\.1:\d+/);if(m){clearTimeout(timer);resolve(m[0]);}});server.on('error',reject);});
 browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(base+'/previews/index.html');await page.waitForFunction(()=>document.getElementById('mode').textContent.includes('已同步'));
 await page.locator('#open-import').click();await page.waitForFunction(()=>!document.getElementById('import-files').disabled);
 await page.locator('#import-provider').selectOption('example');await page.locator('#import-category').fill('数据库');await page.locator('#import-source').fill('浏览器测试来源');
 await page.locator('#import-files').setInputFiles([upload('示例数据库.svg',svg('#3388ee')),upload('New Product.svg',svg('#9955dd'))]);
 await page.waitForSelector('.import-card[data-index="1"]');
 await page.locator('[data-index="1"] [data-field="aliases"]').fill('新产品, NewDB');
 await page.locator('[data-index="1"] [data-field="source"]').fill('测试来源说明');
 await page.locator('#import-check').click();await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('检查完成'));
 assert(await page.locator('[data-index="0"] .import-candidate').count()===1,'Exact duplicate is shown');
 assert((await page.locator('[data-index="0"] .import-candidate').textContent()).includes('图形内容完全相同'),'Exact match label');
 await page.locator('#import-ready').click();assert((await page.locator('#import-status').textContent()).includes('选择处理方式'),'Conflict requires explicit choice');
 await page.locator('[data-index="0"] .import-candidate button').click();await page.locator('#import-check').click();
 await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('检查完成'));
 await page.locator('[data-index="0"] [data-field="make_default"]').check();
 await page.locator('#import-dialog').evaluate(d=>d.scrollTop=0);
 await page.locator('.import-preview img').first().evaluate(i=>i.decode());
 await page.screenshot({path:path.join(root,'reports/import-desktop.png')});
 assert(await page.locator('#import-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),'Desktop dialog overflow');
 await page.locator('#import-ready').click();await page.waitForSelector('#import-result:not([hidden])');
 assert((await page.locator('#import-result').textContent()).includes('复用已有图形'),'Duplicate reuses variant');
 let c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json'))),prefs=JSON.parse(fs.readFileSync(path.join(temp,'catalog/preferences.json')));
 assert(c.products.length===2&&c.variants.length===3,'One new product, no duplicate variant');assert(prefs.defaults[seed.product]===seed.blue,'Preference saved');
 assert(c.products.some(p=>p.aliases.includes('新产品')),'Metadata saved');
 await page.locator('#import-result button').click();await page.waitForFunction(()=>document.getElementById('product-count').textContent==='2');
 assert(await page.locator('#providers button').filter({hasText:'example'}).count()===1,'Custom provider visible');
 // Pending import on a narrow display. Invalid SVG can be explicitly skipped.
 await page.locator('#open-import').click();await page.locator('#import-files').setInputFiles([upload('Pending.svg',svg('#55bb88')),upload('Invalid.svg','<svg><script>alert(1)</script></svg>')]);
 await page.waitForSelector('.import-card[data-index="1"]');await page.locator('#import-check').click();
 await page.waitForFunction(()=>document.getElementById('import-status').textContent.includes('需要更正'));
 assert(await page.locator('#import-ready').isDisabled(),'Invalid SVG blocks commit');
 await page.locator('[data-index="1"] [data-field="action"]').selectOption('skip');await page.locator('#import-check').click();
 await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('检查完成'));
 await page.locator('[data-index="0"] [data-field="make_default"]').check();await page.locator('#import-pending').click();
 assert((await page.locator('#import-status').textContent()).includes('不能设为默认'),'Pending preference explained');await page.locator('[data-index="0"] [data-field="make_default"]').uncheck();
 await page.setViewportSize({width:390,height:844});await page.locator('#import-dialog').evaluate(d=>d.scrollTop=0);
 assert(await page.locator('#import-dialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),'Mobile dialog overflow');
 await page.screenshot({path:path.join(root,'reports/import-mobile.png')});
 await page.locator('#import-pending').click();await page.waitForSelector('#import-result:not([hidden])');
 c=JSON.parse(fs.readFileSync(path.join(temp,'catalog/index.json')));const pending=c.products.find(p=>p.name==='Pending');assert(pending.status==='pending'&&pending.default_variant===null,'Pending is not enabled');
 await page.locator('#import-result button').click();await page.waitForFunction(()=>document.getElementById('product-count').textContent==='3');
 // Name matching with different vector content, and an editable correction.
 await page.setViewportSize({width:1440,height:1000});await page.locator('#open-import').click();await page.locator('#import-files').setInputFiles(upload('ExampleDB.svg',svg('#775511')));
 await page.waitForSelector('.import-card');await page.locator('#import-check').click();await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('检查完成'));
 assert((await page.locator('.import-candidate').textContent()).includes('名称或别名匹配'),'Alias matching shown');
 await page.locator('[data-field="name"]').fill('Corrected service');assert(await page.locator('#import-ready').isDisabled(),'Editing invalidates old check');
 await page.locator('#import-check').click();await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('检查完成'));
 assert(await page.locator('.import-candidate').count()===0,'Corrected name clears match');await page.locator('#import-close').click();
 const denied=await page.request.post(base+'/api/import/check',{data:{items:[]},headers:{Origin:'https://outside.example'}});assert(denied.status()===403,'Cross-origin write denied');
 const validated=JSON.parse(execFileSync('python3',[path.join(root,'scripts/iconlib.py'),'validate','--json'],{env,encoding:'utf8'}));assert(validated.ok,'Imported library validates');
 await page.goto('file://'+path.join(temp,'previews/index.html'));await page.locator('#open-import').click();await page.waitForFunction(()=>document.getElementById('import-connection').textContent.includes('需要本地服务'));
 assert(await page.locator('#import-files').isDisabled(),'Offline import explains service requirement');assert(!errors.length,'Browser JS errors: '+errors.join(','));
 fs.writeFileSync(path.join(root,'reports/import-browser-validation.json'),JSON.stringify({ok:true,flows:['batch SVG upload','metadata','exact deduplication','alias detection','identity correction','link existing','default preference','pending','invalid SVG skip','desktop/mobile','offline guidance','same-origin','catalog validation'],errors},null,2)+'\n');
 console.log('Import browser checks passed (isolated fixture; real library unchanged).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();if(server)server.kill();fs.rmSync(temp,{recursive:true,force:true});});
