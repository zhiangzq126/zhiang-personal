const fs=require('fs');
const path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const root=path.resolve(__dirname,'..'),base=process.env.ICON_PREVIEW_URL||'http://127.0.0.1:63586';
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let savedPreferences=null;
 const assert=(x,m)=>{if(!x)throw Error(m)};
 try{
  await page.goto(base+'/previews/index.html');await page.waitForFunction(()=>document.getElementById('mode').textContent.includes('已同步'));
  assert(await page.locator('.icon-card').count()===60,'Initial pagination');
  await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width&&r.top<innerHeight&&r.bottom>0;}).map(i=>i.decode()));});
  await page.screenshot({animations:'disabled',path:path.join(root,'reports/browser-desktop.png'),fullPage:false});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Desktop overflow');
  await page.locator('#search').fill('ECS');
  assert(await page.locator('[data-product="aliyun/ecs"]').count()===1,'Alibaba ECS search');
  assert(await page.locator('[data-product="aws/ecs"]').count()===1,'AWS ECS search');
  await page.locator('[data-product="aliyun/ecs"]').click();
  assert(await page.locator('#details').isVisible(),'Details opens');
  assert(await page.locator('#variants .variant').count()>=2,'Variants available');
  const before=await (await page.request.get(base+'/api/preferences')).json();savedPreferences=before;
  const options=await page.locator('#variants .variant').evaluateAll(es=>es.map(e=>({id:e.dataset.variant,selected:e.classList.contains('selected')})));
  const choice=options.find(x=>!x.selected);
  await page.locator(`[data-variant="${choice.id}"]`).click();await page.locator('#prefer').click();
  await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('已保存'));
  const after=await (await page.request.get(base+'/api/preferences')).json();assert(after.defaults['aliyun/ecs']===choice.id,'Preference persisted');
  const {execFileSync}=require('child_process');
  const resolved=JSON.parse(execFileSync('python3',[path.join(root,'scripts/iconlib.py'),'resolve','aliyun/ecs','--json'],{encoding:'utf8'}));assert(resolved.variant_id===choice.id,'CLI follows viewer preference');
  await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width&&r.top<innerHeight&&r.bottom>0;}).map(i=>i.decode()));});
  await page.screenshot({animations:'disabled',path:path.join(root,'reports/browser-variants.png'),fullPage:false});
  // Restore the user's original setting, including an existing override.
  await page.evaluate(async ({vid})=>{const r=await fetch('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_id:'aliyun/ecs',variant_id:vid})});if(!r.ok)throw Error('Restore preference failed')},{vid:before.defaults['aliyun/ecs']||null});
  await page.reload();await page.waitForFunction(()=>document.getElementById('mode').textContent.includes('已同步'));await page.locator('#theme').click();
  await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width&&r.top<innerHeight&&r.bottom>0;}).map(i=>i.decode()));});
  await page.screenshot({animations:'disabled',path:path.join(root,'reports/browser-dark.png'),fullPage:false});
  await page.locator('#search').fill('Flink');assert(await page.locator('[data-product="unclassified/flink-file"]').count()===0,'Pending hidden');
  await page.locator('#pending').check();assert(await page.locator('[data-product="unclassified/flink-file"]').count()===1,'Pending visible');
  await page.locator('[data-product="unclassified/flink-file"]').click();assert(await page.locator('#prefer').isDisabled(),'Pending cannot be default');await page.locator('#close').click();
  await page.locator('#clear').click();await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow');
  await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width&&r.top<innerHeight&&r.bottom>0;}).map(i=>i.decode()));});
  await page.screenshot({animations:'disabled',path:path.join(root,'reports/browser-mobile.png'),fullPage:false});
  // All catalog SVGs decode successfully in Chromium, not only the first page.
  const imageFailures=await page.evaluate(async()=>{const paths=[...new Set(window.ICON_LIBRARY.catalog.variants.map(v=>'../'+v.asset.path))];const failures=[];let n=0;async function worker(){while(n<paths.length){const p=paths[n++];try{const i=new Image();i.src=p;await i.decode();if(!i.naturalWidth||!i.naturalHeight)failures.push(p);}catch{failures.push(p);}}}await Promise.all(Array.from({length:4},worker));return failures;});assert(imageFailures.length===0,'SVG decode failures: '+imageFailures.join(','));
  await page.goto('file://'+path.join(root,'previews/index.html'));await page.waitForSelector('.icon-card');assert(await page.locator('.icon-card').count()===60,'Offline preview');
  assert(errors.length===0,'Browser JS errors '+errors.join(','));
  const result={ok:true,desktop:'1440x1000',mobile:'390x844',svg_decode_failures:imageFailures,shared_preferences:'viewer → preferences.json → CLI verified, original preference restored',offline_preview:true,javascript_errors:errors};
  fs.writeFileSync(path.join(root,'reports/browser-validation.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{
  try{if(savedPreferences){const {execFileSync}=require('child_process');const vid=savedPreferences.defaults['aliyun/ecs'];execFileSync('python3',[path.join(root,'scripts/iconlib.py'),'prefer','aliyun/ecs',...(vid?[vid]:['--reset'])],{stdio:'pipe'});}}finally{await browser.close();}
 }
})().catch(e=>{console.error(e);process.exit(1)});
