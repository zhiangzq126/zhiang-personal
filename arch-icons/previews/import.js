'use strict';
(() => {
  let items = [], inspected = null, busy = false, available = false, lastCommit = null;
  const fieldIds = ['import-files', 'import-source', 'import-provider', 'import-category', 'import-apply', 'import-check'];
  const kinds = {product:'产品与资源', brand:'厂商品牌', component:'通用组件', 'container-symbol':'边界标识', status:'状态符号'};
  const status = (s, error=false) => {$('import-status').textContent=s; $('import-status').classList.toggle('error',error);};
  function dirty(){inspected=null;lastCommit=null;buttons();status('信息已更新，请检查重复后再入库。');}
  function buttons(){
    const checked = inspected && inspected.items.some(r=>r.asset) && inspected.items.every(r=>r.skipped||!r.error);
    for(const id of fieldIds)$(id).disabled=busy||!available;
    $('import-check').disabled=busy||!available||!items.length;
    $('import-ready').disabled=busy||!checked;
    $('import-pending').disabled=busy||!checked;
    $('import-close').disabled=busy;
    $('import-items').querySelectorAll('input,select,button').forEach(n=>n.disabled=busy);
  }
  async function post(path,data){
    const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;
  }
  function providers(){
    $('import-provider').replaceChildren();$('import-providers').replaceChildren();
    for(const [id,title] of Object.entries(labels)){
      $('import-provider').add(new Option(title,id));
      $('import-providers').append(new Option(title,id));
    }
    $('import-provider').value=provider||'unclassified';
    $('import-categories').replaceChildren(...[...new Set(catalog.products.map(p=>p.category))].sort().map(c=>new Option(c,c)));
    $('import-products').replaceChildren(...catalog.products.map(p=>new Option(`${p.name} · ${labels[p.provider]||p.provider}`,p.id)));
  }
  function textField(row,key,label,value,options={}){
    const wrap=el('label','',label),input=el('input');input.type='text';input.value=value||'';
    input.dataset.field=key;input.maxLength=options.maxLength||200;
    if(options.list)input.setAttribute('list',options.list);
    if(options.placeholder)input.placeholder=options.placeholder;
    input.addEventListener('input',()=>{row[key]=key==='aliases'?input.value.split(/[,，;；\n]/).map(x=>x.trim()).filter(Boolean):input.value;dirty();});
    wrap.append(input);return wrap;
  }
  function selectField(row,key,label,choices){
    const wrap=el('label','',label),select=el('select');select.dataset.field=key;
    for(const [v,t] of Object.entries(choices))select.add(new Option(t,v));select.value=row[key];
    select.onchange=()=>{row[key]=select.value;dirty();};wrap.append(select);return wrap;
  }
  function checkbox(row,key,title,onchange){
    const wrap=el('label','import-checkbox'),input=el('input');input.type='checkbox';input.checked=!!row[key];input.dataset.field=key;
    input.onchange=()=>{row[key]=input.checked;lastCommit=null;if(onchange)onchange();};
    wrap.append(input,document.createTextNode(title));return wrap;
  }
  function link(row,p){
    row.action='link';row.target=p.id;row.provider=p.provider;row.distinct=false;row.make_default=false;
    dirty();renderItems();status('已关联 '+p.name+'。请重新检查，核对归属和重复图形。');
  }
  function renderItems(){
    $('import-items').replaceChildren();
    items.forEach((row,i)=>{
      const info=inspected?.items[i]||row.previous,card=el('article','import-card');card.dataset.index=i;
      const heading=el('div','import-card-heading');heading.append(el('strong','',`${i+1}. ${row.filename}`));
      const remove=el('button','button quiet','移除');remove.type='button';remove.onclick=()=>{items.splice(i,1);items.forEach(x=>delete x.previous);dirty();renderItems();};heading.append(remove);card.append(heading);
      const body=el('div','import-card-body'),stage=el('div','import-preview');
      if(info?.preview){const img=el('img');img.src=info.preview;img.alt=row.name+' 导入预览';stage.append(img,el('small','','此次上传'));}
      else stage.append(el('span','','检查后预览'));
      const fields=el('div','import-fields');
      fields.append(textField(row,'name','产品或组件名称 *',row.name),textField(row,'provider','厂商标识 *',row.provider,{list:'import-providers',placeholder:'如 aliyun，也可新增英文标识',maxLength:60}),textField(row,'category','分类 *',row.category,{list:'import-categories',maxLength:100}),selectField(row,'kind','用途',kinds),textField(row,'aliases','别名（逗号分隔）',row.aliases.join(', '),{maxLength:3000}),textField(row,'style','变体说明 *',row.style,{maxLength:100}),textField(row,'source','来源链接或说明',row.source,{maxLength:1000}),textField(row,'note','备注',row.note,{maxLength:1000}));
      body.append(stage,fields);card.append(body);
      if(info?.error)card.append(el('p','import-error',info.error+'。请更正文件或跳过这一项。'));
      if(info?.matches?.length){
        card.append(el('h3','','发现已有图标，请核对归属'));
        const candidates=el('div','import-candidates');
        for(const m of info.matches){
          const candidate=el('div','import-candidate');
          const v=m.variants[0];if(v)candidate.append(image(v,48));
          const text=el('div');text.append(el('strong','',m.product.name),el('small','',`${labels[m.product.provider]||m.product.provider} · ${m.reasons.includes('exact')?'图形内容完全相同':'名称或别名匹配'}${m.product.status==='pending'?' · 待确认':''}`));
          const button=el('button','button',row.target===m.product.id?'已选择此产品':'关联此产品');button.type='button';button.onclick=()=>link(row,m.product);candidate.append(text,button);candidates.append(candidate);
        }
        card.append(candidates);
      }else if(info?.asset)card.append(el('p','help','未发现库内内容相同或名称、别名匹配的条目。'));
      if(info?.batch_matches?.length)card.append(el('p','import-warning','同批次还与第 '+info.batch_matches.map(j=>j+1).join('、')+' 项存在图形或名称重复。相同产品请仅保留一项；不同产品可明确分别保留。'));
      const decisions=el('div','import-decisions'),actionLabel=el('label','','产品归属'),action=el('select');action.dataset.field='action';
      for(const [v,t] of [['','请选择处理方式'],['new','新建产品或组件'],['link','关联已有产品（复用图形或添加变体）'],['skip','跳过，不导入']])action.add(new Option(t,v));action.value=row.action;
      action.onchange=()=>{const wasSkipped=row.action==='skip';row.action=action.value;row.make_default=false;lastCommit=null;if(wasSkipped||action.value==='skip')dirty();renderItems();};actionLabel.append(action);decisions.append(actionLabel);
      if(row.action==='link'){
        const targetLabel=el('label','','关联产品（可按名称或 ID 查找）'),input=el('input');input.setAttribute('list','import-products');input.dataset.field='target';input.value=row.target||'';
        input.onchange=()=>{const p=catalog.products.find(p=>p.id===input.value);if(p)link(row,p);else{row.target=input.value;dirty();}};
        targetLabel.append(input);decisions.append(targetLabel);
        const p=catalog.products.find(p=>p.id===row.target);
        if(p){decisions.append(el('p','help',`将归入「${p.name}」；保留该产品已有名称、分类和默认图标。确认启用时会补充所填别名。${p.status==='pending'?'选择“确认并启用”也将确认此产品身份。':''}`));
          const v=selected(p);if(v){const compare=el('div','import-target');compare.append(image(v,48),el('span','','关联产品当前展示图标'));decisions.append(compare);}}
      }
      if(row.action==='new'&&(info?.matches?.length||info?.batch_matches?.length))decisions.append(checkbox(row,'distinct','我已核对：这是不同产品，保留独立条目'));
      if(row.action!=='skip')decisions.append(checkbox(row,'make_default','将此次图标设为该产品默认（仅确认并启用时可选）'));
      card.append(decisions);$('import-items').append(card);
    });buttons();
  }
  async function addFiles(files){
    if(busy||!available)return;
    const list=Array.from(files);
    if(list.some(f=>!f.name.toLowerCase().endsWith('.svg'))){status('本次仅支持 SVG，请移除其他格式后重新选择。',true);return;}
    if(items.length+list.length>50||list.some(f=>f.size>4000000)||items.reduce((s,r)=>s+r.bytes,0)+list.reduce((s,f)=>s+f.size,0)>12000000){status('最多 50 个 SVG；单个不超过 4 MB，总大小不超过 12 MB。',true);return;}
    busy=true;buttons();
    try{
      const added=await Promise.all(list.map(async f=>({filename:f.name,bytes:f.size,data:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(Error('无法读取 '+f.name));reader.readAsDataURL(f);}),name:f.name.replace(/\.svg$/i,''),provider:$('import-provider').value,category:$('import-category').value||'新导入',kind:'product',aliases:[],style:'用户导入',source:'',note:'',action:'new',target:'',distinct:false,make_default:false})));
      items.push(...added);dirty();renderItems();status(`已选择 ${items.length} 个 SVG，请补充信息后检查重复。`);
    }catch(e){status(e.message,true);}finally{busy=false;buttons();$('import-files').value='';}
  }
  function payloadItems(){return items.map(({previous,bytes,...rest})=>rest);}
  async function check(){
    busy=true;buttons();status('正在检查 SVG 和重复项…');
    try{
      inspected=await post('/api/import/check',{items:payloadItems()});lastCommit=null;
      inspected.items.forEach((r,i)=>{items[i].previous=r;if((r.matches?.length||r.batch_matches?.length)&&items[i].action==='new'&&!items[i].distinct)items[i].action='';});
      renderItems();
      const errors=inspected.items.filter(r=>r.error).length;
      status(errors?`${errors} 项需要更正或跳过，其余信息已检查。`:'检查完成。请处理重复候选，再选择确认启用或保存为待确认。',!!errors);
    }catch(e){inspected=null;status(e.message,true);}finally{busy=false;buttons();}
  }
  async function commit(state){
    if(!inspected)return;
    if(!$('import-source').value.trim()){status('请填写批次来源，方便后续追溯。',true);$('import-source').focus();return;}
    for(let i=0;i<items.length;i++){
      const r=items[i],info=inspected.items[i];
      if(r.action==='skip')continue;
      if(!r.action){status(`请为第 ${i+1} 项选择处理方式。`,true);return;}
      if(r.action==='new'&&(info.matches?.length||info.batch_matches?.length)&&!r.distinct){status(`第 ${i+1} 项存在重复，请关联已有产品，或明确确认为不同产品。`,true);return;}
      if(r.action==='link'&&!catalog.products.some(p=>p.id===r.target)){status(`请为第 ${i+1} 项选择有效的关联产品。`,true);return;}
      if(state==='pending'&&r.make_default){status('待确认图标不能设为默认，请取消“设为默认”，或选择确认并启用。',true);return;}
    }
    const base={items:payloadItems(),source_name:$('import-source').value.trim(),revision:inspected.revision,status:state};
    const fingerprint=JSON.stringify(base);
    if(!lastCommit||lastCommit.fingerprint!==fingerprint)lastCommit={fingerprint,payload:{...base,request_id:crypto.randomUUID()}};
    busy=true;buttons();status('正在入库并校验…');
    try{
      const result=await post('/api/import/commit',lastCommit.payload);
      $('import-editor').hidden=true;$('import-result').hidden=false;$('import-result').replaceChildren(el('h3','','导入完成'));
      const outcomes={created:'新建条目',variant_added:'添加变体',reused:'复用已有图形，补充来源',skipped:'已跳过'};
      for(const r of result.items)$('import-result').append(el('p','',`${r.filename}：${outcomes[r.action]}${r.status?(r.status==='ready'?' · 可供使用':' · 待确认'):''}${r.default_changed?' · 已设为默认':''}`));
      const done=el('button','button primary','完成');done.onclick=()=>$('import-dialog').close();$('import-result').append(done);
      try{await reloadCatalog();}catch{$('import-result').append(el('p','help','素材已保存。列表刷新失败，请刷新浏览页查看。'));}
      items=[];inspected=null;lastCommit=null;
    }catch(e){status('导入未完成：'+e.message+'。可更正后重新检查；网络中断时可直接重试。',true);}finally{busy=false;buttons();}
  }
  $('open-import').onclick=async()=>{
    providers();$('import-editor').hidden=false;$('import-result').hidden=true;$('import-dialog').showModal();renderItems();
    try{const r=await fetch('/api/import');const d=await r.json();available=r.ok&&d.version===1;}catch{available=false;}
    $('import-connection').textContent=available?'在本地整理素材。检查和预览不会入库，点击保存后才会写入图标库。':'导入需要本地服务。请双击“打开图标库.command”后，在新打开的页面操作；已运行的旧服务请关闭后重新启动。';buttons();
  };
  $('import-close').onclick=()=>$('import-dialog').close();
  $('import-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  $('import-files').onchange=e=>addFiles(e.target.files);
  $('import-drop').ondragover=e=>{e.preventDefault();if(!busy)$('import-drop').classList.add('dragging');};
  $('import-drop').ondragleave=()=>$('import-drop').classList.remove('dragging');
  $('import-drop').ondrop=e=>{e.preventDefault();$('import-drop').classList.remove('dragging');addFiles(e.dataTransfer.files);};
  $('import-apply').onclick=()=>{for(const r of items){r.provider=$('import-provider').value;r.category=$('import-category').value;}dirty();renderItems();};
  $('import-source').oninput=()=>{lastCommit=null;};
  $('import-check').onclick=check;$('import-ready').onclick=()=>commit('ready');$('import-pending').onclick=()=>commit('pending');
})();
