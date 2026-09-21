'use strict';
(() => {
  let queue=[],targets=[],revision='',active=null,busy=false,available=false,dirty=false,lastRequest=null;
  const $r=$;
  const metadataIds=['review-product-name','review-product-provider','review-category','review-kind','review-aliases'];
  const say=(text,error=false)=>{$r('review-status').textContent=text;$r('review-status').classList.toggle('error',error);};
  const mark=()=>{dirty=true;lastRequest=null;};
  function filtered(){const q=normalized($r('review-search').value);return queue.filter(x=>(!$r('review-provider').value||x.product.provider===$r('review-provider').value)&&(!q||[x.product.name,x.product.id,...x.product.aliases].some(s=>normalized(s).includes(q))));}
  function controls(){
    $r('review-dialog').querySelectorAll('button,input,select,textarea').forEach(n=>n.disabled=busy);
    $r('review-save').disabled=busy||!available||!active||$r('review-action').value!=='approve';
    $r('review-approve').disabled=busy||!available||!active;
    $r('review-skip').disabled=busy||!active;
    if(active?.product.status==='ready')metadataIds.forEach(id=>$r(id).disabled=true);
  }
  function mayLeave(){return !dirty||window.confirm('当前修改尚未保存。放弃这些修改并继续？');}
  function list(){
    const entries=filtered();$r('review-total').textContent=`${queue.length} 项`;$r('review-list').replaceChildren();
    for(const x of entries){const p=x.product,button=el('button','review-queue-item'+(active?.product.id===p.id?' active':''));button.type='button';button.dataset.reviewProduct=p.id;
      const variant=x.variants.find(v=>v.status==='pending');if(variant)button.append(image(variant,36));
      const name=el('span');name.append(el('strong','',p.name),el('small','',`${labels[p.provider]||p.provider} · ${x.variants.filter(v=>v.status==='pending').length} 个待确认图形`));button.append(name);button.onclick=()=>{if(p.id!==active?.product.id&&mayLeave())select(x);};$r('review-list').append(button);}
    if(!entries.length)$r('review-list').append(el('p','help','没有匹配的待确认条目'));
  }
  function metadata(){return {name:$r('review-product-name').value.trim(),provider:$r('review-product-provider').value.trim(),category:$r('review-category').value.trim(),kind:$r('review-kind').value,aliases:$r('review-aliases').value.split(/[,，;；\n]/).map(s=>s.trim()).filter(Boolean)};}
  function picked(){return [...$r('review-variants').querySelectorAll('[data-approve]:checked')].map(n=>n.dataset.approve);}
  function defaultChoices(){
    const previous=$r('review-default').value;$r('review-default').replaceChildren(new Option('保留已有默认；新启用产品采用首个确认图形',''));
    for(const id of picked()){const v=active.variants.find(v=>v.id===id);$r('review-default').add(new Option('采用图形 '+(active.variants.indexOf(v)+1)+' · '+v.style,id));}
    if(picked().includes(previous))$r('review-default').value=previous;
  }
  function matching(){
    if(!active)return [];
    const m=metadata(),terms=new Set([m.name,...m.aliases].map(normalized).filter(Boolean));
    const variants=active.variants.filter(v=>v.status==='pending'&&(!picked().length||picked().includes(v.id)));
    const hashes=new Set(variants.map(v=>v.asset.sha256)),matches=[];
    for(const p of catalog.products){if(p.id===active.product.id)continue;const vs=allVariants.get(p.id)||[],exact=vs.filter(v=>hashes.has(v.asset.sha256)),name=[p.name,...p.aliases].some(s=>terms.has(normalized(s)));
      if(exact.length||name)matches.push({product:p,variant:exact[0]||selected(p),exact:!!exact.length});}
    return matches;
  }
  function showMatches(){
    const area=$r('review-matches');area.replaceChildren();if($r('review-action').value==='delete'){$r('review-distinct-label').hidden=true;return;}const matches=matching();
    $r('review-distinct-label').hidden=!matches.length||active?.product.status==='ready'||$r('review-action').value!=='approve';
    if(!matches.length)return;
    area.append(el('h4','','重复候选 · 核对后再确认'));
    const candidates=el('div','review-candidates');
    for(const m of matches){const card=el('div','import-candidate');card.append(image(m.variant,48));const words=el('div');words.append(el('strong','',m.product.name),el('small','',`${labels[m.product.provider]||m.product.provider} · ${m.exact?'图形完全相同':'名称或别名匹配'}${m.product.status==='pending'?' · 待确认':''}`));card.append(words);
      const b=el('button','button',m.product.status==='ready'?'关联此产品':'请先审核此产品');b.disabled=m.product.status!=='ready';b.dataset.unavailable=String(m.product.status!=='ready');b.onclick=()=>{if(m.product.status!=='ready')return;$r('review-action').value='link';$r('review-target').value=m.product.id;mark();actionChanged();};card.append(b);candidates.append(card);}
    area.append(candidates);
  }
  function targetPreview(){
    const p=targets.find(x=>x.product.id===$r('review-target').value),stage=$r('review-target-preview');stage.replaceChildren();
    if(p){const box=el('div','import-target');if(p.variant)box.append(image(p.variant,48));box.append(el('span','',`${p.product.name} · ${labels[p.product.provider]||p.product.provider} · 保留目标产品身份`));stage.append(box);}
  }
  function actionChanged(){
    const link=$r('review-action').value==='link',deleting=$r('review-action').value==='delete';
    $r('review-metadata').hidden=link||deleting;$r('review-link').hidden=!link;$r('review-delete-info').hidden=!deleting;$r('review-default-label').hidden=deleting;
    $r('review-approve').textContent=deleting?'删除所选并下一项':link?'关联所选并下一项':'确认所选并下一项';$r('review-approve').classList.toggle('danger',deleting);
    $r('review-variants').querySelectorAll('[data-selection-label]').forEach(n=>{const i=Number(n.dataset.selectionLabel),v=active.variants[i];n.textContent=`图形 ${i+1} · ${v.status==='ready'?'已可用':deleting?'本次清理':'本次确认'}`;});
    targetPreview();showMatches();controls();
  }
  function select(entry){
    active=entry||null;dirty=false;lastRequest=null;list();$r('review-form').hidden=!active;$r('review-empty').hidden=!!active;
    if(!active){controls();return;}
    const p=active.product,pending=active.variants.filter(v=>v.status==='pending');
    $r('review-name').textContent=p.name;$r('review-id').textContent=p.id;$r('review-position').textContent=`${filtered().findIndex(x=>x.product.id===p.id)+1} / ${filtered().length}`;
    $r('review-reasons').replaceChildren(el('strong','','待确认原因与历史备注'),...p.notes.map(note=>el('p','',note)));
    $r('review-product-name').value=p.name;$r('review-product-provider').value=p.provider;$r('review-category').value=p.category;$r('review-kind').value=p.kind;$r('review-aliases').value=p.aliases.join(', ');
    $r('review-note').value='';$r('review-target').value='';$r('review-distinct').checked=false;$r('review-action').value='approve';$r('review-default').value='';
    $r('review-identity-help').textContent=p.status==='ready'?'此产品已有可用图标，本次只审核新增变体，产品身份保持不变。':'名称或厂商不准确时可直接更正；移除错误别名，避免 Agent 误匹配。';
    $r('review-variants').replaceChildren();
    active.variants.forEach((v,i)=>{
      const card=el('article','review-variant');const scenes=el('div','review-scenes');
      for(const theme of ['light','dark']){const box=el('div',theme);box.append(image(v,64),el('small','',theme==='light'?'浅色背景':'深色背景'));scenes.append(box);}card.append(scenes);
      const title=el('label','import-checkbox'),check=el('input');check.type='checkbox';check.dataset.approve=v.id;check.checked=v.status==='pending'&&pending.length===1;check.disabled=v.status!=='pending';check.dataset.ready=String(v.status==='ready');
      check.onchange=()=>{mark();defaultChoices();showMatches();};const selectionLabel=el('span');selectionLabel.dataset.selectionLabel=i;title.append(check,selectionLabel);card.append(title);
      const styleLabel=el('label','','变体说明'),style=el('input');style.value=v.style;style.maxLength=100;style.dataset.style=v.id;style.disabled=v.status!=='pending';style.dataset.ready=String(v.status==='ready');style.oninput=mark;styleLabel.append(style);card.append(styleLabel);
      const origins=el('details','review-origins');origins.append(el('summary','','查看原始来源'));
      for(const o of v.origins)origins.append(el('p','',o.path+' · '+o.entry));card.append(origins);$r('review-variants').append(card);
    });
    defaultChoices();actionChanged();say('核实身份后确认；不确定的可以暂不处理。');$r('review-editor').scrollTop=0;
  }
  // Keep already-ready variants read-only even while toggling the busy state.
  const baseControls=controls;
  controls=function(){baseControls();$r('review-variants').querySelectorAll('[data-ready="true"]').forEach(n=>n.disabled=true);$r('review-matches').querySelectorAll('[data-unavailable="true"]').forEach(n=>n.disabled=true);};
  function options(){
    const selectedProvider=$r('review-provider').value;$r('review-provider').replaceChildren(new Option('全部厂商',''));
    for(const id of [...new Set(queue.map(x=>x.product.provider))])$r('review-provider').add(new Option(labels[id]||id,id));
    if([...$r('review-provider').options].some(x=>x.value===selectedProvider))$r('review-provider').value=selectedProvider;
    $r('review-providers').replaceChildren(...Object.entries(labels).map(([id,title])=>new Option(title,id)));
    $r('review-categories').replaceChildren(...[...new Set(catalog.products.map(p=>p.category))].map(c=>new Option(c,c)));
    $r('review-targets').replaceChildren(...targets.map(x=>new Option(x.product.name+' · '+(labels[x.product.provider]||x.product.provider),x.product.id)));
  }
  async function load(preferred,position=0){
    busy=true;controls();
    try{
      const response=await fetch('/api/review');if(!response.ok)throw Error('审核服务不可用');const data=await response.json();if(!Array.isArray(data.items))throw Error('审核服务不可用');
      await reloadCatalog();queue=data.items;targets=data.targets;revision=data.revision;available=true;
      $r('review-connection').textContent='逐项核对并保存。确认后 Agent 即可使用；未选图形继续待确认。';
    }catch(e){
      available=false;queue=catalog.products.map(p=>({product:p,variants:allVariants.get(p.id)||[]})).filter(x=>x.variants.some(v=>v.status==='pending'));targets=[];revision='';
      $r('review-connection').textContent='当前只能浏览。审核保存需要新版本地服务，请重新启动“打开图标库.command”。';
    }finally{busy=false;options();const entries=filtered();select(entries.find(x=>x.product.id===preferred)||entries[Math.min(position,entries.length-1)]);controls();}
  }
  async function save(action){
    if(!active||busy||!available)return;
    const selected=picked(),link=$r('review-action').value==='link'&&action!=='save',deleting=$r('review-action').value==='delete'&&action!=='save',note=$r('review-note').value.trim();
    if(deleting)action='delete';
    if(action!=='save'&&!selected.length){say(deleting?'请勾选需要清理的图形。':'请勾选本次确认的图形。',true);return;}
    if(action!=='save'&&!note){say(deleting?'请填写有误原因，再删除清理。':'请填写审核依据或备注。',true);$r('review-note').focus();return;}
    if(link&&!targets.some(x=>x.product.id===$r('review-target').value&&x.product.id!==active.product.id)){say('请选择另一个已确认产品作为关联目标。',true);return;}
    if(action==='approve'&&!link&&active.product.status==='pending'&&matching().length&&!$r('review-distinct').checked){say('存在重复候选，请关联已有产品，或勾选“确认这是独立产品”。',true);return;}
    const styles={};if(!deleting)$r('review-variants').querySelectorAll('[data-style][data-ready="false"]').forEach(n=>styles[n.dataset.style]=n.value);
    const data={product_id:active.product.id,revision,action:link?'link':action,metadata:active.product.status==='ready'?{name:active.product.name,provider:active.product.provider,category:active.product.category,kind:active.product.kind,aliases:active.product.aliases}:metadata(),variant_ids:action==='save'?[]:selected,styles,note,default_variant:(action==='save'||deleting)?'':$r('review-default').value,target_id:$r('review-target').value,distinct:$r('review-distinct').checked};
    if(deleting){
      busy=true;controls();say('正在核对删除范围…');
      try{
        const response=await fetch('/api/review/delete-plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const plan=await response.json();if(!response.ok)throw Error(plan.error||'无法核对删除范围');
        const names=selected.map(id=>'图形 '+(active.variants.findIndex(v=>v.id===id)+1)).join('、');
        const prompt=`确认清理「${plan.product_name}」的 ${names}？\n\n移除 ${plan.variant_count} 个待确认图形${plan.remove_product?'，该条目也将移出索引':''}。\n${plan.cleanup_assets.length} 份独占 SVG 移入回收区，${plan.shared_assets.length} 份共用 SVG 保留。\n原始来源文件继续归档保留。\n\n原因：${note}`;
        if(!window.confirm(prompt)){say('已取消删除，图标保持不变。');return;}
        data.delete_confirmed=true;
      }catch(e){say(e.message,true);return;}finally{busy=false;controls();}
    }
    const fingerprint=JSON.stringify(data);if(!lastRequest||lastRequest.fingerprint!==fingerprint)lastRequest={fingerprint,data:{...data,request_id:crypto.randomUUID()}};
    const entries=filtered(),oldIndex=entries.findIndex(x=>x.product.id===active.product.id),oldId=active.product.id,nextId=entries.length>1?entries[(oldIndex+1)%entries.length].product.id:undefined;
    busy=true;controls();say('正在保存审核并校验…');
    try{
      const response=await fetch('/api/review/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastRequest.data)});const result=await response.json();if(!response.ok)throw Error(result.error||'保存失败');
      dirty=false;lastRequest=null;
      await load(action==='save'?result.product_id:nextId,oldIndex);
      if(action!=='save'&&active?.product.id===oldId&&filtered().length>1){const xs=filtered();select(xs[(xs.findIndex(x=>x.product.id===oldId)+1)%xs.length]);}
      say((action==='save'?'已保存修改，仍保留待确认。':action==='delete'?`已清理 ${result.deleted_variants} 个有误图形，原始来源归档保留。`:`已确认 ${result.approved_variants} 个图形。`)+` 还剩 ${result.remaining} 项待审核。`);
    }catch(e){say(e.message+'。若是网络中断，可直接重试；状态已更新时请刷新审核列表。',true);}finally{busy=false;controls();}
  }
  window.openIconReview=async(id)=>{
    if(dirty&&!mayLeave())return;$r('review-dialog').showModal();$r('review-search').value='';$r('review-provider').value='';await load(id);
  };
  $r('open-review').onclick=()=>window.openIconReview();
  $r('review-close').onclick=()=>{if(mayLeave()){dirty=false;$r('review-dialog').close();}};
  $r('review-dialog').addEventListener('cancel',e=>{if(busy||!mayLeave())e.preventDefault();else dirty=false;});
  $r('review-refresh').onclick=()=>{if(mayLeave())load(active?.product.id);};
  for(const id of ['review-search','review-provider'])$r(id).addEventListener(id==='review-search'?'input':'change',()=>{list();if(!dirty&&!filtered().some(x=>x.product.id===active?.product.id))select(filtered()[0]);});
  for(const id of metadataIds)$r(id).addEventListener('input',()=>{mark();$r('review-distinct').checked=false;showMatches();});
  $r('review-action').onchange=()=>{mark();actionChanged();};$r('review-target').oninput=()=>{mark();targetPreview();};
  for(const id of ['review-note','review-default','review-distinct'])$r(id).addEventListener('input',mark);
  $r('review-save').onclick=()=>save('save');$r('review-approve').onclick=()=>save('approve');
  $r('review-skip').onclick=()=>{if(!mayLeave())return;const xs=filtered(),i=xs.findIndex(x=>x.product.id===active?.product.id);select(xs[(i+1)%xs.length]);say('已暂时跳过，状态保持待确认。');};
})();
