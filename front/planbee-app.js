/* Persistent API integration for the supplied Plan Bee channel + milestone board. */
(function () {
  'use strict';
  var V=window.PlanBeeView, E=V.esc, state=null, run=null, runtime={}, busy=false, automatic=false, preview=null, evaluationLink=null;
  var viewerRole='pm';try{viewerRole=localStorage.getItem('pb-viewer-role')||'pm';}catch(err){}
  var feed=document.getElementById('feed'), input=document.getElementById('change-input');
  var top=document.querySelector('.top'), tools=document.createElement('div');tools.className='backend-tools';
  tools.innerHTML='<label>시나리오 <select id="demo-select" aria-label="시나리오"></select></label><a id="scenario-link" class="btn sm" target="_blank" rel="noopener">시나리오 설명</a><button id="demo-advance" class="btn sm">예시 이슈 채우기</button><a class="btn sm" href="/index.html">기존 화면</a>';
  top.appendChild(tools);
  var roleTools=document.createElement('label');roleTools.className='viewer-select-label';roleTools.innerHTML='내 역할 <select id="viewer-select" aria-label="현재 사용자 역할"></select>';top.appendChild(roleTools);
  var rolePanel=document.createElement('div');rolePanel.className='viewer-panel';rolePanel.id='viewer-panel';document.querySelector('.chan .pane-h').after(rolePanel);
  document.querySelector('.chan .pane-h h2').textContent='# 후보 생성 · 팀 토론';
  var stage=document.createElement('div');stage.className='backend-stage';stage.setAttribute('role','status');stage.id='backend-stage';
  document.querySelector('.chan .pane-h').after(stage);
  var controls=document.createElement('div');controls.className='backend-controls';
  controls.innerHTML='<label>이슈 업무 <select id="task-select" class="task-select" aria-label="이슈 업무"></select></label><button id="continue-run" class="btn sm">계속 진행</button><button id="pause-run" class="btn sm">다음 단계에서 일시정지</button><button id="current-board" class="btn sm">현재 보드</button>';
  stage.after(controls);
  var support=document.createElement('div');support.className='backend-empty';support.id='scenario-support';controls.after(support);
  input.placeholder='선택한 업무에서 바뀐 점이나 해결할 이슈를 적어 주세요';
  document.querySelector('.sprint').textContent='서버 연결 중';
  document.querySelector('.badge').textContent='API';
  document.getElementById('sugg').innerHTML='<span class="sl">실제 후보 생성 → 카드 기반 토론 → PM 최종 선택</span>';
  document.getElementById('tip-ok').onclick=function(){document.getElementById('tip').hidden=true;};
  function label(pid){var p=state&&state.people.find(function(p){return p.id===pid;});return p?p.name:pid==='hive'?'Hive':pid==='pm'?'PM':pid||'팀';}
  function fmt(n){return Number(Number(n).toFixed(2));}
  async function api(path,body){
    var res=await fetch(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Planbee-Role':viewerRole},body:body===undefined?undefined:JSON.stringify(body)});
    var result=await res.json();if(!res.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail||result));return result;
  }
  function error(err){var box=document.getElementById('backend-error');if(!box){box=document.createElement('div');box.id='backend-error';box.className='backend-error';stage.after(box);}box.textContent=err.message;}
  function clearError(){var box=document.getElementById('backend-error');if(box)box.remove();}
  async function act(fn){if(busy)return;busy=true;clearError();status();try{await fn();}catch(err){automatic=false;error(err);}finally{busy=false;status();}}
  function status(){
    feed.querySelectorAll('button').forEach(function(button){button.disabled=busy;});
    var names={candidate_generate:'02 · 시간 안에 가능한 새 milestone 설계',candidate_assess:'03 · 각자 카드로 후보 비교',candidate_discuss:'03 · 공정성 discussion',candidate_rank:'03 · 최종 순위·당사자 의사 확인',candidate_pm:'04 · PM 최종 결정',candidate_confirm:'04 · 당사자 본인 확인',candidate_failed:'PM 상황 전달',done:'완료'};
    var budget=run&&run.llm_budget;
    stage.innerHTML='<strong>'+E(run?names[run.step]||run.step:'01 · 이슈 입력')+'</strong><br>'+E(runtime.llm_mode||'')+(runtime.model?' · '+E(runtime.model):'')+(run?' · '+E(run.status)+' · '+(run.round||0)+'라운드':'')+(run&&run.assessment_progress&&/assess|rank/.test(run.step)?' · 개인 평가 '+run.assessment_progress.completed+'/'+run.assessment_progress.total:'')+(budget?' · 호출 '+budget.used+'/'+budget.max:'')+(busy?' · 처리 중…':'');
    stage.setAttribute('aria-busy',busy?'true':'false');
    document.getElementById('continue-run').disabled=busy||!run||run.status!=='running';
    document.getElementById('pause-run').disabled=!automatic;
    document.getElementById('demo-select').disabled=busy;
    document.getElementById('viewer-select').disabled=busy;
    document.getElementById('demo-advance').disabled=busy||!state||!state.feed_label||!!(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status));
    document.querySelector('#form button').disabled=busy||!document.getElementById('task-select').value||!!(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status));
    document.getElementById('reset').disabled=busy;
    feed.querySelectorAll('[data-required-role]').forEach(function(b){b.disabled=busy||viewerRole!==b.dataset.requiredRole;});
  }
  async function refresh(loadRun){
    state=await api('/state');
    if(viewerRole!=='pm'&&!state.people.some(function(p){return viewerRole==='person:'+p.id;}))viewerRole='pm';
    state.viewer_role=viewerRole;
    var roles=document.getElementById('viewer-select');roles.innerHTML='<option value="pm">PM · 최종 결정자</option>'+state.people.map(function(p){return '<option value="person:'+E(p.id)+'">'+E(p.name)+' · '+E(p.role)+' 담당자</option>';}).join('');roles.value=viewerRole;
    var me=state.people.find(function(p){return viewerRole==='person:'+p.id;});
    var card=me&&(state.cards||[]).find(function(c){return c.who===me.id;});
    rolePanel.innerHTML='<strong>현재 내 역할: '+E(me?me.name+' 본인 · '+me.role:'PM · 최종 결정자')+'</strong><p>'+(me?'내 업무 이슈를 줄글로 보내고, 내 변경안에 직접 동의·거절할 수 있습니다. 최종 후보 선택은 PM 역할에서 합니다.':'팀 이슈를 요청하고 후보를 최종 선택합니다. 개인 확인은 해당 담당자 역할로 전환해 처리하세요.')+'</p>'+(card?'<details><summary>내 위임카드 확인</summary><p>'+E(card.note||'추가 조건 없음')+'</p><p>자동 수락 '+fmt(card.auto_days)+'일 · 거절 태그 '+E((card.refuse_tags||[]).join(', ')||'없음')+'</p></details>':'')+'<small>로컬 역할 체험 · 로그인 인증 아님 · 역할 전환만으로 LLM을 호출하지 않습니다.</small>';
    if(loadRun){var runs=await api('/candidate-runs');run=runs[0]||null;}
    document.querySelector('.sprint').textContent=state.demo.title;
    document.querySelector('.badge').textContent=(runtime.llm_mode||'').toUpperCase();
    var demo=document.getElementById('demo-select');demo.innerHTML=state.demo.catalog.map(function(d){return '<option value="'+E(d.id)+'"'+(d.id===state.demo.id?' selected':'')+'>'+E(d.title)+'</option>';}).join('');
    document.getElementById('scenario-link').href='/scenario.html?demo='+encodeURIComponent(state.demo.id);
    var select=document.getElementById('task-select'),old=select.value;
    select.innerHTML=Object.values(state.tasks).filter(function(t){return !t.cut&&!['done','milestone','prop'].includes(t.kind)&&(viewerRole==='pm'||viewerRole==='person:'+t.who);}).map(function(t){return '<option value="'+E(t.id)+'">'+E(label(t.who)+' · '+t.title)+'</option>';}).join('');
    if(Array.from(select.options).some(function(o){return o.value===old;}))select.value=old;
    if(run&&Array.from(select.options).some(function(o){return o.value===run.task;}))select.value=run.task;
    if(!run&&state.demo.source_task&&Array.from(select.options).some(function(o){return o.value===state.demo.source_task;}))select.value=state.demo.source_task;
    support.textContent=state.demo.engine_support||'';support.hidden=!state.demo.engine_support;
    V.render(state,preview&&preview.board,!!preview);paint();status();syncHeight();
  }
  function taskTable(board){return '<div class="candidate-table-wrap"><table><thead><tr><th>Task / milestone</th><th>담당</th><th>시작 → 완료</th></tr></thead><tbody>'+board.tasks.map(function(t){return '<tr><td>'+E(t.title)+'</td><td>'+E(label(t.who))+'</td><td>'+fmt(t.start)+' → '+fmt(t.start+t.days)+'일</td></tr>';}).join('')+'</tbody></table></div>';}
  function candidateCard(c,isFinal){
    var r=run,consents=c.consents||{};
    var html='<article class="candidate-card" data-card="'+E(c.id)+'"><h3>'+E(c.title)+'</h3><div class="candidate-meta">'+E(c.operator)+' · '+E(c.id.slice(0,10))+' · Hive 전체 제약 검증 통과<br>'+E(c.basis)+'</div>';
    var operatorNames={baseline:'현재 계획 유지',split:'독립 업무 분할',transfer:'전체 업무 배치',compose:'업무 이동과 재배치',move:'다른 업무 일정 이동',collaborate:'지원 업무를 포함한 협업'};
    var changes=(c.schedule_changes||[]).map(function(change){var task=state.tasks[change.task];var title=task?task.title:change.task;var parts=[];if(change.who&&task&&change.who!==task.who)parts.push(label(task.who)+' → '+label(change.who));if(change.start!==undefined&&change.start!==null)parts.push('시작 '+fmt(change.start)+'일');if(change.support)change.support.forEach(function(help){parts.push(label(help.who)+' 지원 '+fmt(help.days)+'일 · '+help.what);});return '<li>'+E(title)+' · '+E(parts.join(' / '))+'</li>';});
    html+='<p class="candidate-meta">'+E(operatorNames[c.operator]||c.operator)+'</p>'+(changes.length?'<strong>함께 바뀌는 업무</strong><ul>'+changes.join('')+'</ul>':'');
    var actions=c.plan_actions||[];
    if(actions.length)html+='<strong>범위·중간 산출물 변경</strong><ul>'+actions.map(function(a){var title=(state.tasks[a.task]||{}).title||a.task;return '<li>'+E(title)+' · '+E(a.kind==='defer'?(a.milestone+'로 이관 · 원 업무량 보존'):a.kind==='omit'?'동일 항목 최종 검증 유지 · 선택 중간 검증 생략 · 본인 Confirm 필요':'중간 산출물/최종 반영 분해')+'<br><small>'+E(a.basis)+'</small></li>';}).join('')+'</ul>';
    if((c.board.deferred||[]).length)html+='<p class="candidate-meta">후속 milestone: '+c.board.deferred.map(function(t){return E(label(t.who)+' · '+t.title+' '+t.days+'일 → '+t.to);}).join(' / ')+'</p>';
    var milestones=c.board.milestones||[];
    if(milestones.length)html+='<details data-open="milestones-'+E(c.id)+'"><summary>이 계획의 milestone '+milestones.length+'개</summary><ul>'+milestones.map(function(m){return '<li>'+E(m.title)+' · '+E(label(m.who))+' · '+fmt(m.end)+'일 완료</li>';}).join('')+'</ul></details>';
    html+='<ul>'+c.allocations.map(function(a){return '<li>'+E(label(a.who))+' · '+E(a.title)+' · '+fmt(a.days)+'일 <small>'+E(a.what)+'</small></li>';}).join('')+'</ul>';
    html+='<div class="candidate-meta">'+Object.keys(consents).map(function(p){var a=consents[p];return E(label(p))+': '+E({ACCEPT:'동의',REJECT:'거절',NEEDS_INPUT:'본인 확인 필요'}[a.action]||a.action);}).join(' · ')+'</div>';
    html+='<details data-open="plan-'+E(c.id)+'"><summary>새 milestone · 전체 Task 일정 보기</summary>'+taskTable(c.board)+'<div class="candidate-meta">부담 분산 참고값 '+fmt(c.board.fairness.variance)+' · 자동 선택 기준 아님</div></details>';
    html+='<div class="candidate-actions"><button class="btn sm" data-preview="'+E(c.id)+'">보드에서 비교</button>';
    if(isFinal&&r.status==='awaiting_pm_selection')html+=viewerRole==='pm'?'<button class="btn go sm" data-required-role="pm" data-select="'+E(c.id)+'">이 계획으로 최종 결정</button>':'<button class="btn sm" data-switch-role="pm">PM으로 전환해 최종 선택</button>';
    return html+'</div></article>';
  }
  function paint(){
    var open=new Set(Array.from(feed.querySelectorAll('details[open][data-open]')).map(function(n){return n.dataset.open;}));var atEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<90,scroll=feed.scrollTop;
    if(!run){feed.innerHTML='<div class="backend-empty">보드에서 업무를 고르고 변경 이슈를 보내세요.<br>생성 AI와 알고리즘이 시간 안에 가능한 계획을 만들고, 각자의 카드로 토론한 뒤 PM에게 후보 1~3개를 올립니다.</div>';return;}
    var html='<div class="backend-empty"><strong>'+E(run.issue)+'</strong><br>Run '+run.id+' · '+E(run.phase==='deadline'?'기한 회복':'공정성 재분담')+'</div>';
    (run.public_history||[]).forEach(function(m){
      var hive=m.requester==='hive',pm=m.requester==='pm';html+='<div class="msg in"><div class="av '+(hive?'hive':pm?'pm':'proxy')+'">'+(hive?'':E(label(m.requester).slice(0,1)))+'</div><div><div class="meta"><b>'+E(label(m.requester))+'</b><small>'+m.round+'라운드'+(m.recipient?' → '+E(label(m.recipient)):'')+(m.candidate_id?' · '+E(m.candidate_id.slice(0,10)):'')+'</small></div><p>'+E(m.reason)+'</p></div></div>';
    });
    if(run.generation)html+='<details data-open="generation"><summary>후보 생성·검증 내역</summary><p class="candidate-meta">탐색 '+run.generation.attempted+'개 · 통과 '+run.generation.feasible+'개 · 중복 '+run.generation.duplicates+'개 · 반려 '+run.generation.rejected+'개</p><ul>'+Object.keys(run.generation.reasons||{}).slice(0,12).map(function(x){return '<li>'+E(x)+' ('+run.generation.reasons[x]+')</li>';}).join('')+'</ul></details>';
    var finals=run.final_candidates||[];
    if(run.status==='awaiting_pm_selection')html+='<div class="backend-empty"><strong>PM 최종 결정</strong><br>후보가 하나여도 PM 선택 전에는 적용되지 않습니다.</div>';
    finals.forEach(function(id){var c=run.candidates.find(function(c){return c.id===id;});if(c)html+=candidateCard(c,true);});
    if(run.status==='awaiting_pm_selection'&&viewerRole==='pm')html+='<div class="candidate-actions"><button class="btn sm" data-pm-action="reject">모두 반려</button><button class="btn sm" data-pm-action="revise">수정 요청</button></div>';
    if((run.candidates||[]).length)html+='<details data-open="pool"><summary>전체 검증 후보 '+run.candidates.length+'개</summary>'+run.candidates.filter(function(c){return !finals.includes(c.id);}).map(function(c){return candidateCard(c,false);}).join('')+'</details>';
    (state.pending_confirms||[]).forEach(function(c){
      html+='<article class="candidate-card"><h3>'+E(label(c.who))+' 본인 확인</h3><p>'+E(c.prompt)+'</p><p class="candidate-meta">'+E(c.text)+'</p><div class="candidate-actions">';
      if(viewerRole==='person:'+c.who)html+='<button class="btn go sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="true">당사자로서 동의</button><button class="btn sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="false">거절</button>';
      else html+='<button class="btn sm" data-switch-role="person:'+E(c.who)+'">'+E(label(c.who))+' 본인으로 전환</button>';
      html+='</div></article>';
    });
    if(run.pm_handoff)html+='<article class="candidate-card"><h3>'+E(run.pm_handoff.message)+'</h3><details data-open="handoff"><summary>현재 상황 summary 보기</summary><p>'+E(run.pm_handoff.summary.termination)+'</p><p>검증 후보 '+run.pm_handoff.summary.candidate_count+'개 · 미합의 변경 미적용</p><ul>'+((run.pm_handoff.summary.last_messages)||[]).map(function(e){return '<li>'+E(label(e.requester)+': '+e.reason)+'</li>';}).join('')+'</ul></details>'+(run.status==='waiting_pm'?(viewerRole==='pm'?'<button class="btn sm" data-required-role="pm" data-close-run>상황 확인 · 현재 배분 유지</button>':'<button class="btn sm" data-switch-role="pm">PM으로 전환해 상황 확인</button>'):'')+'</article>';
    if(run.status==='done')html+='<div class="backend-empty">'+E(run.termination==='applied'?'PM이 선택한 계획을 최종 검증 후 적용했습니다.':'현재 배분을 유지했습니다.')+'</div>';
    if(run.shortlist&&run.shortlist.length&&['awaiting_pm_selection','waiting_confirm','done','waiting_pm'].includes(run.status))html+='<article class="evaluation-card"><h3>사람 순위와 별도 비교평가</h3><p class="candidate-meta">운영 PM 선택과 별도로 평가합니다. 새 평가자는 전용 링크에서 LLM 순위 없이 같은 후보를 비교합니다.</p><label>평가 기준 <select id="eval-rubric"><option value="fairness">공정성</option><option value="card_fit">본인 카드 적합성</option></select></label><label>역할 <select id="eval-person">'+state.people.map(function(p){return '<option value="'+E(p.id)+'">'+E(p.name)+'</option>';}).join('')+'</select></label><button class="btn sm" data-create-evaluation>독립 평가 링크 생성</button>'+(evaluationLink?'<a class="btn sm" target="_blank" href="'+E(evaluationLink)+'">사람 평가 화면 열기</a>':'')+'</article>';
    feed.innerHTML=html;
    feed.querySelectorAll('details[data-open]').forEach(function(d){d.open=open.has(d.dataset.open);});
    feed.scrollTop=atEnd?feed.scrollHeight:scroll;
    feed.querySelectorAll('button').forEach(function(b){b.disabled=busy;});
  }
  async function loop(){
    while(automatic&&run&&run.status==='running'){
      await act(async function(){run=await api('/runs/'+run.id+'/advance',{});preview=null;await refresh(false);});
      if(!automatic)break;await new Promise(function(r){setTimeout(r,100);});
    }
    automatic=false;status();
  }
  window.PlanBeeApp={quote:function(type,id){if(type==='t')document.getElementById('task-select').value=id;var q=document.getElementById('quotes');q.hidden=false;q.textContent='참조: '+id;input.focus();}};
  document.getElementById('form').addEventListener('submit',function(e){e.preventDefault();var issue=input.value.trim();if(!issue)return;act(async function(){run=await api('/candidate-runs',{task_id:document.getElementById('task-select').value,issue:issue});input.value='';evaluationLink=null;preview=null;await refresh(false);automatic=true;}).then(loop);});
  document.getElementById('continue-run').onclick=function(){automatic=true;loop();};
  document.getElementById('pause-run').onclick=function(){automatic=false;status();};
  document.getElementById('current-board').onclick=function(){preview=null;if(state)V.render(state,null,false);};
  document.getElementById('demo-select').onchange=function(e){automatic=false;act(async function(){await api('/demo/select',{demo:e.target.value});run=null;preview=null;await refresh(true);});};
  document.getElementById('demo-advance').onclick=function(){var source=state.tasks[state.demo.source_task];if(source&&viewerRole!=='pm'&&viewerRole!=='person:'+source.who){error(new Error(label(source.who)+' 역할로 전환한 뒤 예시를 입력하세요.'));return;}if(source)document.getElementById('task-select').value=source.id;input.value=state.demo.issue_example||'';input.focus();V.toast('예시만 채웠습니다. 내용을 확인한 뒤 보내기를 누르세요.');};
  document.getElementById('task-select').onchange=status;
  function syncHeight(){document.querySelector('.app').style.height=window.innerWidth>900?'calc(100dvh - '+Math.ceil(top.getBoundingClientRect().height)+'px)':'auto';}
  window.addEventListener('resize',syncHeight);
  async function switchRole(role){viewerRole=role;try{localStorage.setItem('pb-viewer-role',role);}catch(err){}await refresh(false);}
  document.getElementById('viewer-select').onchange=function(e){act(function(){return switchRole(e.target.value);});};
  document.getElementById('reset').onclick=function(){if(!window.confirm('현재 데모를 초기 상태로 되돌릴까요?'))return;automatic=false;act(async function(){await api('/reset',{});run=null;preview=null;evaluationLink=null;await refresh(true);});};
  feed.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||busy||!run)return;
    if(b.dataset.switchRole){act(function(){return switchRole(b.dataset.switchRole);});return;}
    if(b.dataset.preview){preview=run.candidates.find(function(c){return c.id===b.dataset.preview;});V.render(state,preview.board,true);return;}
    act(async function(){
      if(b.dataset.select){var c=run.candidates.find(function(c){return c.id===b.dataset.select;});run=await api('/runs/'+run.id+'/pm-selection',{action:'select',candidate_id:c.id,plan_hash:c.plan_hash});preview=null;await refresh(false);}
      else if(b.dataset.pmAction){var reason=window.prompt('반려/수정 요청 이유를 적어 주세요');if(!reason)return;run=await api('/runs/'+run.id+'/pm-selection',{action:b.dataset.pmAction,reason:reason});await refresh(false);}
      else if(b.dataset.confirm){await api('/confirmations/'+b.dataset.confirm,{ok:b.dataset.ok==='true'});run=await api('/runs/'+run.id);await refresh(false);}
      else if(b.hasAttribute('data-close-run')){run=await api('/runs/'+run.id+'/close',{});await refresh(false);}
      else if(b.hasAttribute('data-create-evaluation')){var rubric=document.getElementById('eval-rubric').value;var ev=await api('/runs/'+run.id+'/evaluations',{rubric:rubric,person_id:document.getElementById('eval-person').value});evaluationLink='/front/evaluation.html?id='+ev.id;paint();}
    });
  });
  document.querySelector('.langs').addEventListener('click',function(e){var b=e.target.closest('[data-lang]');if(b){V.language(b.dataset.lang);try{localStorage.setItem('pb-lang',b.dataset.lang);}catch(err){}}});
  document.getElementById('themes').addEventListener('click',function(e){var b=e.target.closest('[data-mode]');if(b){V.theme(b.dataset.mode);try{localStorage.setItem('pb-theme',b.dataset.mode);}catch(err){}}});
  act(async function(){runtime=await api('/runtime');await refresh(true);});
})();
