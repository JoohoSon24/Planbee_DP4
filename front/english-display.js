/* English presentation for dynamic board, drawer, guide and evaluation text.
   Translations never rewrite API state, cards, identifiers, links or typed drafts. */
(function(){
  'use strict';
  var cache=new Map(),failed=new Set(),records=new Map(),attrs=new Map(),pending=new Set(),busy=false,scheduled=false;
  function en(){return document.documentElement.getAttribute('data-lang')==='en';}
  function korean(s){return /[가-힣]/.test(s||'');}
  function display(s){return cache.get(s)||(failed.has(s)?'Translation unavailable':'Translating…');}
  async function resolve(texts){
    var missing=Array.from(new Set(texts)).filter(function(s){return korean(s)&&!cache.has(s);});
    if(missing.length){
      var r=await fetch('/display-translations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts:missing})});
      if(!r.ok)throw Error('English translation unavailable');
      (await r.json()).items.forEach(function(x){cache.set(x.source,x.text);failed.delete(x.source);});
    }
    return texts.map(function(s){return cache.get(s)||s;});
  }
  function queue(s){if(!cache.has(s)&&!failed.has(s))pending.add(s);}
  function excluded(el){return !el||!!el.closest('script,style,textarea,.i-ko,[data-no-translate]');}
  function scan(){
    if(!document.body)return;
    var language=en()?'en':'ko';if(document.documentElement.lang!==language)document.documentElement.lang=language;
    records.forEach(function(r,n){if(!n.isConnected){records.delete(n);return;}if(!en()&&n.data===r.shown){n.data=r.source;records.delete(n);}});
    attrs.forEach(function(map,el){if(!el.isConnected){attrs.delete(el);return;}if(!en()){map.forEach(function(r,k){if(el.getAttribute(k)===r.shown)el.setAttribute(k,r.source);});attrs.delete(el);}});
    document.querySelectorAll('img[src*="/board"]').forEach(function(img){if(img.hidden!==en())img.hidden=en();});
    if(!en()){if(notice&&!notice.hidden)notice.hidden=true;return;}
    var walker=document.createTreeWalker(document.documentElement,NodeFilter.SHOW_TEXT),node;
    while((node=walker.nextNode())){
      var el=node.parentElement;if(excluded(el)||el.closest('[hidden]'))continue;
      var old=records.get(node),source=old&&node.data===old.shown?old.source:node.data;
      if(!korean(source))continue;
      queue(source);var shown=display(source);records.set(node,{source:source,shown:shown});if(node.data!==shown)node.data=shown;
    }
    document.querySelectorAll('[placeholder],[title],[aria-label]').forEach(function(el){
      if(el.closest('.i-ko,script,style,[data-no-translate]'))return;
      ['placeholder','title','aria-label'].forEach(function(k){
        var value=el.getAttribute(k);if(value===null)return;
        var map=attrs.get(el)||new Map(),old=map.get(k),source=old&&value===old.shown?old.source:value;
        if(!korean(source))return;queue(source);var shown=display(source);map.set(k,{source:source,shown:shown});attrs.set(el,map);if(value!==shown)el.setAttribute(k,shown);
      });
    });
    var show=failed.size>0;if(notice.hidden===show)notice.hidden=!show;
    pump();
  }
  async function pump(){
    if(busy||!en()||!pending.size)return;
    busy=true;var batch=[],size=0;
    pending.forEach(function(s){if(batch.length<24&&size+s.length<=12000){batch.push(s);size+=s.length;}});
    batch.forEach(function(s){pending.delete(s);});
    if(!batch.length){pending.forEach(function(s){failed.add(s);});pending.clear();busy=false;scan();return;}
    try{await resolve(batch);}catch(e){batch.forEach(function(s){failed.add(s);});}
    finally{busy=false;scan();}
  }
  function schedule(){if(scheduled)return;scheduled=true;queueMicrotask(function(){scheduled=false;scan();});}
  var notice=document.createElement('div');notice.className='english-status';notice.hidden=true;notice.style.cssText='position:fixed;bottom:12px;left:12px;z-index:9999;background:#243044;color:white;padding:8px 12px;border-radius:8px;font:12px system-ui';notice.append('Some text could not be translated. ');var retry=document.createElement('button');retry.type='button';retry.textContent='Retry English';retry.onclick=function(){failed.clear();scan();};notice.append(retry);document.body.append(notice);
  // Fixed seed English (seed/<demo>/en.yaml): exact pairs, no model call, no flicker.
  function seed(map){Object.keys(map||{}).forEach(function(k){cache.set(k,map[k]);failed.delete(k);});schedule();}
  window.PlanBeeEnglish={resolve:resolve,seed:seed,retry:function(){failed.clear();scan();}};
  var language=document.documentElement.getAttribute('data-lang');
  if(!language){try{language=localStorage.getItem('pb-lang');}catch(e){}document.documentElement.setAttribute('data-lang',language==='en'?'en':'ko');}
  new MutationObserver(schedule).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['data-lang','title','placeholder','aria-label','hidden']});
  document.addEventListener('pb-language',scan);
  scan();
})();
