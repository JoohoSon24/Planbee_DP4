/* Persistent API integration for the supplied Plan Bee channel + milestone board. */
(function () {
  'use strict';
  var V=window.PlanBeeView, E=V.esc, state=null, run=null, runtime={}, busy=false, automatic=false, preview=null, evaluationLink=null, evaluationError='';
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
  var support=document.createElement('div');support.className='scenario-note';support.id='scenario-support';controls.after(support);
  var DEFAULT_PLACEHOLDER='무엇이 바뀌었나요?\n예: Advanced Effects가 16h에서 32h로 늘어납니다.\n지켜야 할 마감과 필요한 도움을 함께 적어 주세요.';
  input.placeholder='무엇이 바뀌었나요?\n예: Advanced Effects가 16h에서 32h로 늘어납니다.\n지켜야 할 마감과 필요한 도움을 함께 적어 주세요.';
  input.setAttribute('aria-describedby','composer-help');
  var help=document.createElement('div');help.id='composer-help';help.className='composer-help';help.textContent='Enter 줄바꿈 · Ctrl / ⌘ + Enter 보내기 · 빈 입력창에서 Tab 예시 입력';document.getElementById('form').after(help);
  input.addEventListener('keydown',function(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing){e.preventDefault();document.getElementById('form').requestSubmit();}});
  // 입력창이 비어 있을 때 Tab: placeholder로 보이는 시나리오의 첫 이슈 예시를 그대로 채운다.
  input.addEventListener('keydown',function(e){
    var example=state&&state.demo&&state.demo.issue_example;
    if(e.key!=='Tab'||e.shiftKey||e.isComposing||input.value.trim()||!example)return;
    e.preventDefault();
    var select=document.getElementById('task-select'),source=state.demo.source_task;
    if(source&&Array.from(select.options).some(function(o){return o.value===source;}))select.value=source;
    input.value=example;input.dispatchEvent(new Event('input'));input.setSelectionRange(example.length,example.length);status();
  });
  input.addEventListener('input',function(){input.style.height='auto';input.style.height=Math.min(240,Math.max(112,input.scrollHeight))+'px';});
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
    stage.innerHTML='<strong>'+E(run?names[run.step]||run.step:'01 · 이슈 입력')+'</strong><br>'+E(runtime.llm_mode||'')+(runtime.model?' · '+E(runtime.model):'')+(run?' · '+E(({running:'진행 중',awaiting_pm_selection:'PM 선택 대기',waiting_confirm:'본인 확인 대기',waiting_pm:'PM 검토 필요',done:'완료'})[run.status]||run.status)+' · '+(run.round||0)+'라운드':'')+(run&&run.assessment_progress&&/assess|rank/.test(run.step)?' · 개인 평가 '+run.assessment_progress.completed+'/'+run.assessment_progress.total:'')+(budget?' · 호출 '+budget.used+'/'+budget.max:'')+(busy?' · 처리 중…':'');
    var next=!run?'업무를 선택하고 변경 내용을 보내세요.':run.status==='awaiting_pm_selection'?'추천 계획을 비교하고 PM이 최종 선택하세요.':run.status==='waiting_confirm'?'확인 대상자의 역할로 전환해 동의·거절하세요.':run.status==='waiting_pm'?'해결되지 않은 조건을 확인하고 PM이 다음 조치를 결정하세요.':run.status==='done'?'처리가 끝났습니다. 보드에서 결과를 확인하세요.':automatic?'팀이 계획을 검토하고 있습니다.':'일시정지 상태입니다. 계속 진행을 누르세요.';
    stage.innerHTML+='<div class="next-action">'+E(next)+(['awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run&&run.status)?' <button type="button" class="btn sm" id="jump-decision">바로 보기 ↓</button>':'')+'</div>';
    var jump=document.getElementById('jump-decision');if(jump)jump.onclick=function(){var target=feed.querySelector('.decision-anchor');if(target)target.scrollIntoView({behavior:'smooth',block:'start'});};
    stage.setAttribute('aria-busy',busy?'true':'false');
    document.getElementById('continue-run').disabled=busy||!run||run.status!=='running';
    document.getElementById('pause-run').disabled=!automatic;
    document.getElementById('demo-select').disabled=busy;
    document.getElementById('viewer-select').disabled=busy;
    document.getElementById('demo-advance').disabled=busy||!state||!state.feed_label||!!(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status));
    var sendBlock=busy?'처리 중입니다. 잠시 기다려 주세요.':!document.getElementById('task-select').value?'이 역할에는 이슈를 보낼 담당 업무가 없습니다. 담당 업무가 있는 역할이나 PM으로 전환하세요.':(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status))?'진행 중인 계획 조정이 끝나야 새 이슈를 보낼 수 있습니다. 위의 다음 행동을 먼저 처리하세요.':'';
    var sendBtn=document.querySelector('#form button');sendBtn.disabled=!!sendBlock;sendBtn.title=sendBlock;
    var help=document.getElementById('composer-help');if(help){help.textContent=sendBlock||'Enter 줄바꿈 · Ctrl / ⌘ + Enter 보내기 · 빈 입력창에서 Tab 예시 입력';help.classList.toggle('blocked',!!sendBlock);}
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
    rolePanel.innerHTML='<strong>내 역할: '+E(me?me.name+' 본인 · '+me.role:'PM · 최종 결정자')+'</strong><details><summary>역할 안내'+(card?' · 내 위임카드':'')+'</summary><p>'+(me?'내 업무 이슈를 줄글로 보내고, 내 변경안에 직접 동의·거절할 수 있습니다. 최종 후보 선택은 PM 역할에서 합니다.':'팀 이슈를 요청하고 후보를 최종 선택합니다. 개인 확인은 해당 담당자 역할로 전환해 처리하세요.')+'</p>'+(card?'<details><summary>내 위임카드 확인</summary><p>'+E(card.note||'추가 조건 없음')+'</p><p>자동 수락 '+fmt(card.auto_days)+'일 · 거절 태그 '+E((card.refuse_tags||[]).join(', ')||'없음')+'</p></details>':'')+'<small>로컬 역할 체험 · 로그인 인증 아님 · 역할 전환만으로 LLM을 호출하지 않습니다.</small></details>';
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
    input.placeholder=state.demo.issue_example?state.demo.issue_example+'\n\n(Tab 키로 이 예시 입력)':DEFAULT_PLACEHOLDER;
    support.innerHTML='<details><summary>이 시나리오에서 확인할 내용</summary><p>'+E(state.demo.engine_support||'')+'</p></details>';support.hidden=!state.demo.engine_support;
    V.render(state,preview&&preview.board,!!preview);paint();status();syncHeight();
  }
  function taskTable(board){return '<div class="candidate-table-wrap"><table><thead><tr><th>Task / milestone</th><th>담당</th><th>시작 → 완료</th></tr></thead><tbody>'+board.tasks.map(function(t){return '<tr><td>'+E(t.title)+'</td><td>'+E(label(t.who))+'</td><td>'+fmt(t.start)+' → '+fmt(t.start+t.days)+'일</td></tr>';}).join('')+'</tbody></table></div>';}
  function candidateCard(c,isFinal){
    var number=run.candidates.findIndex(function(x){return x.id===c.id;})+1;
    var html='<article class="candidate-card candidate-compact" data-card="'+E(c.id)+'"><div class="candidate-row"><div><h3>후보 '+number+'</h3><span class="candidate-meta">'+(isFinal?'팀 추천 · PM 선택 가능':'검증 통과 · 추가 당사자 검토 필요')+'</span></div><div class="candidate-actions"><button class="btn sm" data-preview="'+E(c.id)+'">보드에서 보기</button>';
    if(isFinal&&run.status==='awaiting_pm_selection')html+=viewerRole==='pm'?'<button class="btn go sm" data-required-role="pm" data-select="'+E(c.id)+'">이 안으로 결정</button>':'<button class="btn sm" data-switch-role="pm">PM으로 전환해 결정</button>';
    html+='</div></div><details data-open="plan-'+E(c.id)+'"><summary>변경 내용 · 일정 자세히</summary><p>'+E(c.title)+'</p>';
    if((c.plan_actions||[]).length)html+='<ul>'+c.plan_actions.map(function(a){return '<li>'+E((state.tasks[a.task]||{}).title||a.task)+' · '+E(a.kind==='defer'?a.milestone+'로 이관':a.kind==='omit'?'선택 검증 생략 · 본인 확인 필요':'임시 반영 / 최종 교체로 분해')+'</li>';}).join('')+'</ul>';
    html+='<p class="candidate-meta">'+Object.keys(c.consents||{}).map(function(pid){return E(label(pid))+': '+E({ACCEPT:'동의',REJECT:'거절',NEEDS_INPUT:'본인 확인 필요'}[c.consents[pid].action]);}).join(' · ')+'</p>'+taskTable(c.board)+'</details></article>';
    return html;
  }
  function paint(){
    var selectedRubric=document.getElementById('eval-rubric')?.value||'fairness',selectedPerson=document.getElementById('eval-person')?.value;
    var open=new Set(Array.from(feed.querySelectorAll('details[open][data-open]')).map(function(n){return n.dataset.open;}));var atEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<90,scroll=feed.scrollTop;
    if(!run){feed.innerHTML='<div class="backend-empty">보드에서 업무를 고르고 변경 이슈를 보내세요.<br>생성 AI와 알고리즘이 시간 안에 가능한 계획을 만들고, 각자의 카드로 토론한 뒤 PM에게 후보 1~3개를 올립니다.</div>';return;}
    var html='<details class="issue-summary" data-open="issue"><summary>요청한 이슈 · '+E(run.phase==='deadline'?'기한 회복':'공정성 재분담')+'</summary><p>'+E(run.issue)+'</p></details>';
    (run.public_history||[]).forEach(function(m){
      var hive=m.requester==='hive',pm=m.requester==='pm';html+='<div class="msg in"><div class="av '+(hive?'hive':pm?'pm':'proxy')+'">'+(hive?'':E(label(m.requester).slice(0,1)))+'</div><div><div class="meta"><b>'+E(label(m.requester))+'</b><small>'+m.round+'라운드'+(m.recipient?' → '+E(label(m.recipient)):'')+(m.candidate_id?' · 계획 '+((run.candidates||[]).findIndex(function(c){return c.id===m.candidate_id;})+1||'수정안'):'')+'</small></div><p>'+E(m.reason)+'</p></div></div>';
    });
    if(run.generation)html+='<details data-open="generation"><summary>후보 생성·검증 내역</summary><p class="candidate-meta">탐색 '+run.generation.attempted+'개 · 통과 '+run.generation.feasible+'개 · 중복 '+run.generation.duplicates+'개 · 반려 '+run.generation.rejected+'개</p><ul>'+Object.keys(run.generation.reasons||{}).slice(0,12).map(function(x){return '<li>'+E(x)+' ('+run.generation.reasons[x]+')</li>';}).join('')+'</ul></details>';
    var finals=run.final_candidates||[];
    if(run.status==='awaiting_pm_selection')html+='<div class="backend-empty decision-anchor"><strong>PM 최종 결정</strong><br>후보가 하나여도 PM 선택 전에는 적용되지 않습니다.</div>';
    if((run.candidates||[]).length)html+='<div class="candidate-list">'+run.candidates.map(function(c){return candidateCard(c,finals.includes(c.id));}).join('')+'</div>';
    if(run.status==='awaiting_pm_selection'&&viewerRole==='pm')html+='<div class="candidate-actions"><button class="btn sm" data-pm-action="reject">모두 반려</button><button class="btn sm" data-pm-action="revise">수정 요청</button></div>';

    (state.pending_confirms||[]).forEach(function(c){
      html+='<article class="candidate-card decision-anchor"><h3>'+E(label(c.who))+' 본인 확인</h3><p>'+E(c.prompt)+'</p><p class="candidate-meta">'+E(c.text)+'</p><div class="candidate-actions">';
      if(viewerRole==='person:'+c.who)html+='<button class="btn go sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="true">당사자로서 동의</button><button class="btn sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="false">거절</button>';
      else html+='<button class="btn sm" data-switch-role="person:'+E(c.who)+'">'+E(label(c.who))+' 본인으로 전환</button>';
      html+='</div></article>';
    });
    if(run.pm_handoff)html+='<article class="candidate-card decision-anchor"><h3>'+E(run.pm_handoff.message)+'</h3><details data-open="handoff"><summary>현재 상황 summary 보기</summary><p>'+E(run.pm_handoff.summary.termination)+'</p><p>검증 후보 '+run.pm_handoff.summary.candidate_count+'개 · 미합의 변경 미적용</p><ul>'+((run.pm_handoff.summary.last_messages)||[]).map(function(e){return '<li>'+E(label(e.requester)+': '+e.reason)+'</li>';}).join('')+'</ul></details>'+(run.status==='waiting_pm'?(viewerRole==='pm'?'<button class="btn sm" data-required-role="pm" data-close-run>상황 확인 · 현재 배분 유지</button>':'<button class="btn sm" data-switch-role="pm">PM으로 전환해 상황 확인</button>'):'')+'</article>';
    if(run.status==='done')html+='<div class="backend-empty">'+E(run.termination==='applied'?'PM이 선택한 계획을 최종 검증 후 적용했습니다.':'현재 배분을 유지했습니다.')+'</div>';
    if(run.shortlist&&run.shortlist.length&&['awaiting_pm_selection','waiting_confirm','done','waiting_pm'].includes(run.status))html+='<article class="evaluation-card"><h3>사람 순위와 별도 비교평가</h3><p class="candidate-meta">운영 PM 선택과 별도로 평가합니다. 새 평가자는 전용 링크에서 LLM 순위 없이 같은 후보를 비교합니다.</p><label>평가 기준 <select id="eval-rubric"><option value="fairness">공정성</option><option value="card_fit">본인 카드 적합성</option></select></label><label>역할 <select id="eval-person">'+state.people.filter(function(p){return (run.participants||[]).includes(p.id);}).map(function(p){return '<option value="'+E(p.id)+'">'+E(p.name)+'</option>';}).join('')+'</select></label><button class="btn go sm" data-create-evaluation>독립 평가 링크 생성 · 열기</button><div class="evaluation-feedback" role="status">'+(evaluationError?'<p class="backend-error">'+E(evaluationError)+'</p>':'')+(evaluationLink?'<p>평가 링크를 만들었습니다. 새 탭이 열리지 않으면 아래 버튼을 눌러 주세요.</p><a class="btn go sm" target="_blank" rel="noopener" href="'+E(evaluationLink)+'">사람 평가 화면 열기 ↗</a><input aria-label="공유할 독립 평가 링크" readonly value="'+E(location.origin+evaluationLink)+'">':'')+'</div>'+'</article>';
    feed.innerHTML=html;
    var er=document.getElementById('eval-rubric'),ep=document.getElementById('eval-person');if(er)er.value=selectedRubric;if(ep){var preferred=selectedPerson||viewerRole.replace('person:','');if(Array.from(ep.options).some(function(o){return o.value===preferred;}))ep.value=preferred;}
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
  document.getElementById('form').addEventListener('submit',function(e){e.preventDefault();var issue=input.value.trim();if(!issue)return;act(async function(){var taskId=document.getElementById('task-select').value,shownDemo=state&&state.demo&&state.demo.id;var latest=await api('/state');if(!latest.tasks[taskId]||(latest.demo&&latest.demo.id)!==shownDemo){await refresh(true);throw new Error('서버의 시나리오가 화면과 달라 이 업무를 찾을 수 없습니다(서버 재시작 또는 다른 사람이 시나리오 변경). 화면을 최신 상태로 고쳤으니 시나리오·업무를 확인한 뒤 다시 보내 주세요. 입력한 내용은 그대로 남아 있습니다.');}run=await api('/candidate-runs',{task_id:taskId,issue:issue});input.value='';input.dispatchEvent(new Event('input'));evaluationLink=null;evaluationError='';preview=null;await refresh(false);automatic=true;}).then(loop);});
  document.getElementById('continue-run').onclick=function(){automatic=true;loop();};
  document.getElementById('pause-run').onclick=function(){automatic=false;status();};
  document.getElementById('current-board').onclick=function(){preview=null;if(state)V.render(state,null,false);};
  document.getElementById('demo-select').onchange=function(e){automatic=false;act(async function(){await api('/demo/select',{demo:e.target.value});run=null;preview=null;evaluationLink=null;evaluationError='';await refresh(true);});};
  document.getElementById('demo-advance').onclick=function(){var source=state.tasks[state.demo.source_task];if(source&&viewerRole!=='pm'&&viewerRole!=='person:'+source.who){error(new Error(label(source.who)+' 역할로 전환한 뒤 예시를 입력하세요.'));return;}if(source)document.getElementById('task-select').value=source.id;input.value=state.demo.issue_example||'';input.dispatchEvent(new Event('input'));input.focus();V.toast('예시만 채웠습니다. 내용을 확인한 뒤 보내기를 누르세요.');};
  document.getElementById('task-select').onchange=status;
  function syncHeight(){document.querySelector('.app').style.height=window.innerWidth>900?'calc(100dvh - '+Math.ceil(top.getBoundingClientRect().height)+'px)':'auto';}
  window.addEventListener('resize',syncHeight);
  async function switchRole(role){viewerRole=role;try{localStorage.setItem('pb-viewer-role',role);}catch(err){}await refresh(false);}
  document.getElementById('viewer-select').onchange=function(e){act(function(){return switchRole(e.target.value);});};
  document.getElementById('reset').onclick=function(){if(!window.confirm('현재 데모를 초기 상태로 되돌릴까요?'))return;automatic=false;act(async function(){await api('/reset',{});run=null;preview=null;evaluationLink=null;await refresh(true);});};
  feed.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||busy||!run)return;
    if(b.dataset.switchRole){act(function(){return switchRole(b.dataset.switchRole);});return;}
    if(b.dataset.preview){preview=run.candidates.find(function(c){return c.id===b.dataset.preview;});V.render(state,preview.board,true);return;}
    var evaluationWindow=null;
    if(b.hasAttribute('data-create-evaluation')){
      if(!document.getElementById('eval-person').value){evaluationError='최종 평가에 참여한 역할이 없습니다. 토론 완료 후 다시 시도해 주세요.';paint();return;}
      evaluationWindow=window.open('about:blank','_blank');
      if(evaluationWindow){evaluationWindow.opener=null;evaluationWindow.document.title='평가 화면 준비 중';evaluationWindow.document.body.textContent='독립 평가 링크를 생성하고 있습니다…';}
    }
    act(async function(){
      if(b.dataset.select){var c=run.candidates.find(function(c){return c.id===b.dataset.select;});run=await api('/runs/'+run.id+'/pm-selection',{action:'select',candidate_id:c.id,plan_hash:c.plan_hash});preview=null;await refresh(false);}
      else if(b.dataset.pmAction){var reason=window.prompt('반려/수정 요청 이유를 적어 주세요');if(!reason)return;run=await api('/runs/'+run.id+'/pm-selection',{action:b.dataset.pmAction,reason:reason});await refresh(false);}
      else if(b.dataset.confirm){await api('/confirmations/'+b.dataset.confirm,{ok:b.dataset.ok==='true'});run=await api('/runs/'+run.id);await refresh(false);}
      else if(b.hasAttribute('data-close-run')){run=await api('/runs/'+run.id+'/close',{});await refresh(false);}
      else if(b.hasAttribute('data-create-evaluation')){
        evaluationError='';
        try{var rubric=document.getElementById('eval-rubric').value;var ev=await api('/runs/'+run.id+'/evaluations',{rubric:rubric,person_id:document.getElementById('eval-person').value});evaluationLink='/front/evaluation.html?id='+ev.id;if(evaluationWindow)evaluationWindow.location.replace(evaluationLink);paint();feed.querySelector('.evaluation-feedback').scrollIntoView({block:'nearest'});}
        catch(err){if(evaluationWindow)evaluationWindow.close();evaluationError='평가 링크를 만들지 못했습니다: '+err.message;paint();feed.querySelector('.evaluation-feedback').scrollIntoView({block:'nearest'});}
      }
    });
  });
  document.querySelector('.langs').addEventListener('click',function(e){var b=e.target.closest('[data-lang]');if(b){V.language(b.dataset.lang);try{localStorage.setItem('pb-lang',b.dataset.lang);}catch(err){}}});
  document.getElementById('themes').addEventListener('click',function(e){var b=e.target.closest('[data-mode]');if(b){V.theme(b.dataset.mode);try{localStorage.setItem('pb-theme',b.dataset.mode);}catch(err){}}});
  act(async function(){runtime=await api('/runtime');await refresh(true);});
})();
