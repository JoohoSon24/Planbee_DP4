/* Live LLM token usage + OpenRouter remaining credit, polled from GET /llm/usage. */
(function () {
  'use strict';
  var POLL_MS=3000, top=document.querySelector('.top');if(!top)return;
  var wrap=document.createElement('div');wrap.className='llm-usage';
  wrap.innerHTML='<button type="button" class="btn sm llm-usage-chip" aria-expanded="false" aria-controls="llm-usage-panel">토큰 —</button>'+
    '<div class="llm-usage-panel" id="llm-usage-panel" role="dialog" aria-label="LLM 토큰 사용량" hidden></div>';
  top.appendChild(wrap);
  var chip=wrap.querySelector('.llm-usage-chip'), panel=wrap.querySelector('.llm-usage-panel'), last=null, timer=null;
  function E(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function k(n){n=Number(n)||0;return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e4?(n/1e3).toFixed(1)+'k':n.toLocaleString();}
  function usd(n){return n==null?'—':'$'+Number(n).toFixed(Number(n)<1?4:2);}
  function credit(c){
    if(!c)return '';
    if(!c.available)return '남은 크레딧 조회 실패';
    return c.limit==null?'한도 없음 · 키 사용 '+usd(c.usage):'남은 '+usd(c.remaining)+' / '+usd(c.limit);
  }
  function level(c){
    if(!c||!c.available||c.limit==null||!c.limit)return '';
    var r=c.remaining/c.limit;return r<=0.1?'crit':r<=0.25?'warn':'';
  }
  function rows(map){
    var keys=Object.keys(map||{}).sort(function(a,b){return map[b].total_tokens-map[a].total_tokens;});
    if(!keys.length)return '<tr><td colspan="5" class="muted">아직 호출 없음</td></tr>';
    return keys.map(function(key){var v=map[key];return '<tr><td>'+E(key)+'</td><td class="n">'+v.calls+'</td><td class="n">'+k(v.prompt_tokens)+'</td><td class="n">'+k(v.completion_tokens)+'</td><td class="n">'+usd(v.cost)+'</td></tr>';}).join('');
  }
  function render(s){
    last=s;var t=s.total, c=s.credit;
    chip.classList.remove('warn','crit');
    if(s.mode!=='live'){chip.textContent='Mock · 토큰 사용 없음';}
    else{
      chip.textContent='토큰 '+k(t.total_tokens)+' · 호출 '+t.calls+' · '+usd(t.cost)+(c?' · '+credit(c):'');
      var lv=level(c);if(lv)chip.classList.add(lv);
    }
    if(panel.hidden)return;
    var head='<div class="llm-usage-h"><strong>LLM 사용량</strong><span class="muted">'+E(s.mode==='live'?(s.model||'live'):'mock')+' · '+E(new Date(s.since).toLocaleTimeString())+'부터</span></div>';
    var sum='<div class="llm-usage-sum"><div><b>'+k(t.total_tokens)+'</b><span>전체 토큰</span></div><div><b>'+k(t.prompt_tokens)+'</b><span>입력</span></div><div><b>'+k(t.completion_tokens)+'</b><span>출력</span></div><div><b>'+usd(t.cost)+'</b><span>이번 실행 비용</span></div></div>';
    var cr=s.mode!=='live'?'<p class="muted">Mock 모드는 OpenRouter를 부르지 않습니다.</p>':!c?'<p class="muted">OPENROUTER_API_KEY가 없어 남은 크레딧을 조회할 수 없습니다.</p>':
      !c.available?'<p class="muted">남은 크레딧 조회 실패 ('+E(c.error)+')</p>':
      '<p>'+E(credit(c))+(c.usage_daily!=null?' · 오늘 사용 '+usd(c.usage_daily):'')+(c.limit_reset?' · 한도 리셋 '+E(c.limit_reset):'')+'<br><span class="muted">OpenRouter 키 기준 · '+E(new Date(c.checked_at).toLocaleTimeString())+' 조회 (15초 캐시)</span></p>'+
      (c.limit?'<div class="llm-usage-bar '+level(c)+'"><i style="width:'+Math.max(0,Math.min(100,100*c.remaining/c.limit)).toFixed(1)+'%"></i></div>':'');
    var table=function(title,map){return '<table><caption>'+title+'</caption><tr><th></th><th>호출</th><th>입력</th><th>출력</th><th>비용</th></tr>'+rows(map)+'</table>';};
    var recent=(s.recent||[]).slice(0,8).map(function(r){return '<li><span>'+E(new Date(r.t).toLocaleTimeString())+' · '+E(r.kind)+'</span><span class="n">'+k(r.prompt_tokens)+' → '+k(r.completion_tokens)+' · '+usd(r.cost)+'</span></li>';}).join('');
    panel.innerHTML=head+sum+cr+table('호출 종류별',s.by_kind)+table('모델별',s.by_model)+
      (recent?'<div class="llm-usage-recent"><strong>최근 호출</strong><ul>'+recent+'</ul></div>':'')+
      (s.missing_usage?'<p class="muted">usage가 없던 응답 '+s.missing_usage+'건은 토큰 0으로 셌습니다.</p>':'')+
      '<div class="llm-usage-foot"><button type="button" class="btn sm" id="llm-usage-reset">집계 초기화</button><span class="muted">'+(POLL_MS/1000)+'초마다 갱신</span></div>';
    document.getElementById('llm-usage-reset').onclick=async function(){await fetch('/llm/usage/reset',{method:'POST'});poll();};
  }
  async function poll(){
    try{var res=await fetch('/llm/usage');if(res.ok)render(await res.json());else chip.textContent='토큰 조회 실패 ('+res.status+')';}
    catch(err){chip.textContent='토큰 조회 실패';}
  }
  function schedule(){clearInterval(timer);if(document.visibilityState==='visible'){poll();timer=setInterval(poll,POLL_MS);}}
  chip.onclick=function(){panel.hidden=!panel.hidden;chip.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden&&last)render(last);};
  document.addEventListener('click',function(e){if(!panel.hidden&&!wrap.contains(e.target)){panel.hidden=true;chip.setAttribute('aria-expanded','false');}});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!panel.hidden){panel.hidden=true;chip.setAttribute('aria-expanded','false');chip.focus();}});
  document.addEventListener('visibilitychange',schedule);
  schedule();
})();
