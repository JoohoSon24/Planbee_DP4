/* Live LLM token usage + OpenRouter remaining credit, polled from GET /llm/usage. */
(function () {
  'use strict';
  function t(ko,en){return document.documentElement.getAttribute('data-lang')==='en'?en:ko;}
  var POLL_MS=3000, top=document.querySelector('.top');if(!top)return;
  var wrap=document.createElement('div');wrap.className='llm-usage';
  wrap.innerHTML='<button type="button" class="btn sm llm-usage-chip" aria-expanded="false" aria-controls="llm-usage-panel">'+t('토큰 —','Tokens —')+'</button>'+
    '<div class="llm-usage-panel" id="llm-usage-panel" role="dialog" aria-label="'+t('LLM 토큰 사용량','LLM token usage')+'" hidden></div>';
  top.appendChild(wrap);
  var chip=wrap.querySelector('.llm-usage-chip'), panel=wrap.querySelector('.llm-usage-panel'), last=null, timer=null;
  function E(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function k(n){n=Number(n)||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'k':n.toLocaleString();}
  function usd(n){return n==null?'—':'$'+Number(n).toFixed(Number(n)<1?4:2);}
  function credit(c){
    if(!c)return '';
    if(!c.available)return t('남은 크레딧 조회 실패','Credit lookup failed');
    return c.limit==null?t('한도 없음 · 키 사용 ','No limit · key usage ')+usd(c.usage):t('남은 ','Left ')+usd(c.remaining)+' / '+usd(c.limit);
  }
  function level(c){
    if(!c||!c.available||c.limit==null||!c.limit)return '';
    var r=c.remaining/c.limit;return r<=0.1?'crit':r<=0.25?'warn':'';
  }
  function rows(map){
    var keys=Object.keys(map||{}).sort(function(a,b){return map[b].total_tokens-map[a].total_tokens;});
    if(!keys.length)return '<tr><td colspan="5" class="muted">'+t('아직 호출 없음','No calls yet')+'</td></tr>';
    return keys.map(function(key){var v=map[key];return '<tr><td>'+E(key)+'</td><td class="n">'+v.calls+'</td><td class="n">'+k(v.prompt_tokens)+'</td><td class="n">'+k(v.completion_tokens)+'</td><td class="n">'+usd(v.cost)+'</td></tr>';}).join('');
  }
  function render(s){
    last=s;var u=s.total, c=s.credit;
    chip.classList.remove('warn','crit');
    if(s.mode!=='live'){chip.textContent=t('Mock · 토큰 사용 없음','Mock · no token use');}
    else{
      chip.textContent=t('토큰 ','Tokens ')+k(u.total_tokens)+t(' · 호출 ',' · calls ')+u.calls+' · '+usd(u.cost)+(c?' · '+credit(c):'');
      var lv=level(c);if(lv)chip.classList.add(lv);
    }
    if(panel.hidden)return;
    var head='<div class="llm-usage-h"><strong>'+t('LLM 사용량','LLM usage')+'</strong><span class="muted">'+E(s.mode==='live'?(s.model||'live'):'mock')+' · '+t(E(new Date(s.since).toLocaleTimeString())+'부터','since '+E(new Date(s.since).toLocaleTimeString()))+'</span></div>';
    var sum='<div class="llm-usage-sum"><div><b>'+k(u.total_tokens)+'</b><span>'+t('전체 토큰','Total tokens')+'</span></div><div><b>'+k(u.prompt_tokens)+'</b><span>'+t('입력','Input')+'</span></div><div><b>'+k(u.completion_tokens)+'</b><span>'+t('출력','Output')+'</span></div><div><b>'+usd(u.cost)+'</b><span>'+t('이번 실행 비용','Cost this run')+'</span></div></div>';
    var cr=s.mode!=='live'?'<p class="muted">'+t('Mock 모드는 OpenRouter를 부르지 않습니다.','Mock mode does not call OpenRouter.')+'</p>':!c?'<p class="muted">'+t('OPENROUTER_API_KEY가 없어 남은 크레딧을 조회할 수 없습니다.','No OPENROUTER_API_KEY, so remaining credit cannot be checked.')+'</p>':
      !c.available?'<p class="muted">'+t('남은 크레딧 조회 실패','Credit lookup failed')+' ('+E(c.error)+')</p>':
      '<p>'+E(credit(c))+(c.usage_daily!=null?t(' · 오늘 사용 ',' · today ')+usd(c.usage_daily):'')+(c.limit_reset?t(' · 한도 리셋 ',' · limit resets ')+E(c.limit_reset):'')+'<br><span class="muted">'+t('OpenRouter 키 기준 · '+E(new Date(c.checked_at).toLocaleTimeString())+' 조회 (15초 캐시)','OpenRouter key · checked '+E(new Date(c.checked_at).toLocaleTimeString())+' (15s cache)')+'</span></p>'+
      (c.limit?'<div class="llm-usage-bar '+level(c)+'"><i style="width:'+Math.max(0,Math.min(100,100*c.remaining/c.limit)).toFixed(1)+'%"></i></div>':'');
    var table=function(title,map){return '<table><caption>'+title+'</caption><tr><th></th><th>'+t('호출','Calls')+'</th><th>'+t('입력','Input')+'</th><th>'+t('출력','Output')+'</th><th>'+t('비용','Cost')+'</th></tr>'+rows(map)+'</table>';};
    var recent=(s.recent||[]).slice(0,8).map(function(r){return '<li><span>'+E(new Date(r.t).toLocaleTimeString())+' · '+E(r.kind)+'</span><span class="n">'+k(r.prompt_tokens)+' → '+k(r.completion_tokens)+' · '+usd(r.cost)+'</span></li>';}).join('');
    panel.innerHTML=head+sum+cr+table(t('호출 종류별','By call type'),s.by_kind)+table(t('모델별','By model'),s.by_model)+
      (recent?'<div class="llm-usage-recent"><strong>'+t('최근 호출','Recent calls')+'</strong><ul>'+recent+'</ul></div>':'')+
      (s.missing_usage?'<p class="muted">'+t('usage가 없던 응답 '+s.missing_usage+'건은 토큰 0으로 셌습니다.',s.missing_usage+' replies without usage were counted as 0 tokens.')+'</p>':'')+
      '<div class="llm-usage-foot"><button type="button" class="btn sm" id="llm-usage-reset">'+t('집계 초기화','Reset counts')+'</button><span class="muted">'+t((POLL_MS/1000)+'초마다 갱신','updates every '+(POLL_MS/1000)+'s')+'</span></div>';
    document.getElementById('llm-usage-reset').onclick=async function(){await fetch('/llm/usage/reset',{method:'POST'});poll();};
  }
  async function poll(){
    try{var res=await fetch('/llm/usage');if(res.ok)render(await res.json());else chip.textContent=t('토큰 조회 실패 (','Token lookup failed (')+res.status+')';}
    catch(err){chip.textContent=t('토큰 조회 실패','Token lookup failed');}
  }
  function schedule(){clearInterval(timer);if(document.visibilityState==='visible'){poll();timer=setInterval(poll,POLL_MS);}}
  chip.onclick=function(){panel.hidden=!panel.hidden;chip.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden&&last)render(last);};
  document.addEventListener('click',function(e){if(!panel.hidden&&!wrap.contains(e.target)){panel.hidden=true;chip.setAttribute('aria-expanded','false');}});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!panel.hidden){panel.hidden=true;chip.setAttribute('aria-expanded','false');chip.focus();}});
  document.addEventListener('visibilitychange',schedule);
  document.addEventListener('pb-language',function(){if(last)render(last);});
  schedule();
})();
