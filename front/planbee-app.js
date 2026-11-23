/* Persistent API integration for the supplied Plan Bee channel + milestone board. */
(function () {
  'use strict';
  function lang(){return document.documentElement.getAttribute('data-lang')==='en'?'en':'ko';}
  function t(ko,en){return lang()==='en'?en:ko;}
  // Server-made Hive/system messages arrive in Korean with a stable action code: translate by code.
  var HIVE_EN={
    ISSUE:function(){return 'Issue received. Designing new milestone plans that fit the deadline first.';},
    ESTIMATE:function(m){var d=(m.reason.match(/([0-9.]+)일/)||[])[1];return 'Read the issue and re-estimated this task to '+(d||'?')+' days.';},
    CANDIDATES:function(m){var n=(m.reason.match(/(\d+)개/)||[])[1];return 'Prepared '+(n||'')+' new milestone plans that passed schedule checks. Each member now compares them with their own card.';},
    TEMPLATE_DROPPED:function(m){var n=m.reason.match(/(\d+)개/g)||[];return 'Dropped '+(n[0]||'').replace('개','')+' malformed plan structures; building candidates from the remaining '+(n[1]||'').replace('개','')+' and the default structures stated in the task.';},
    SCHEMA_REPAIR:function(){return 'The generation reply had a format error. Sending the field errors back once; no unlimited retries.';},
    REPAIR_REQUEST:function(){return 'No plan passed with the current structures. Asking once for a new structure based on the constraint violations.';},
    ASSESSMENT_REPAIR:function(){return 'An assessment referred to unknown candidates. Asking once again with the exact candidate list.';},
    SPEECH_REPAIR:function(){return 'A message pointed to a candidate outside the discussion list. Asking once again with the exact candidate IDs.';},
    INVITE:function(m){return 'Inviting '+label(m.recipient)+' to the discussion because of a direct question.';},
    REPEAT_SKIPPED:function(m){return 'Skipping a repeated identical message.';},
    SUPPLEMENT:function(){return 'A new public condition came up. Adding alternatives once while keeping existing candidates.';},
    SUPPLEMENT_FAILED:function(){return 'Supplementary generation failed due to a model reply error. Keeping verified candidates and re-assessing with the new condition. Earlier acceptances are not reused.';},
    PM_OPTIONS:function(m){var n=(m.reason.match(/(\d+)개/)||[])[1];return 'Narrowed down to '+(n||'')+' candidates. The PM makes the final decision; nothing is applied automatically, even with one candidate.';},
    CONFIRM:function(){return 'PM choice received. Applying after personal confirmation from members whose delegation does not cover it.';},
    APPLIED:function(){return 'PM choice and member consent confirmed; passed the final deadline check and applied to the new milestone board.';},
    REJECT:function(){return 'A member rejected the chosen plan. Not applied; returning to the PM candidate list.';},
    END:function(m){var code=(m.reason.match(/([a-z_]+)/)||[])[1];return 'Negotiation ended'+(code?' ('+code+')':'')+'. Unagreed changes are not applied; the situation goes to the PM.';}
  };
  var PROXY_EN={'제 위임 범위와 일정으로 후보들을 비교했어요.':'I compared the candidates with my delegation and schedule.','토론 조건을 반영해서 제 최종 선호를 정리했어요.':'I updated my final preference with the discussion conditions.','현재 상황을 확인했습니다. 미합의 변경은 적용하지 않습니다.':'I reviewed the situation. Unagreed changes are not applied.'};
  var TITLE_EN={'원 업무 전체 유지·양도':'Keep or transfer the whole task','Task에 명시된 산출물 분담':'Split as stated in the task','선택 범위의 후속 milestone 이관':'Defer optional scope to a later milestone','중간 산출물과 최종 반영의 단계별 재설계':'Staged redesign: interim and final delivery','현재 milestone 계획 유지':'Keep the current milestone plan'};
  function planTitle(x){return lang()==='en'&&TITLE_EN[x]?TITLE_EN[x]:x;}
  function messageText(m){
    if(lang()!=='en')return m.reason;
    if(m.requester==='hive'&&HIVE_EN[m.response])return HIVE_EN[m.response](m);
    if(m.response==='ESTIMATE')return HIVE_EN.ESTIMATE(m);
    return PROXY_EN[m.reason]||m.reason;
  }
  var V=window.PlanBeeView, E=V.esc, state=null, run=null, runtime={}, busy=false, automatic=false, preview=null, evaluationLink=null, evaluationError='';
  var viewerRole='pm';try{viewerRole=localStorage.getItem('pb-viewer-role')||'pm';}catch(err){}
  var feed=document.getElementById('feed'), input=document.getElementById('change-input');
  var top=document.querySelector('.top'), tools=document.createElement('div');tools.className='backend-tools';
  tools.innerHTML='<label><span data-t="scenario"></span> <select id="demo-select"></select></label><a id="scenario-link" class="btn sm" target="_blank" rel="noopener" data-t="scenarioDoc"></a><button id="demo-advance" class="btn sm" data-t="fillExample"></button><a class="btn sm" href="/index.html" data-t="oldView"></a>';
  top.appendChild(tools);
  var roleTools=document.createElement('label');roleTools.className='viewer-select-label';roleTools.innerHTML='<span data-t="myRole"></span> <select id="viewer-select"></select>';top.appendChild(roleTools);
  var rolePanel=document.createElement('div');rolePanel.className='viewer-panel';rolePanel.id='viewer-panel';document.querySelector('.chan .pane-h').after(rolePanel);
  var stage=document.createElement('div');stage.className='backend-stage';stage.setAttribute('role','status');stage.id='backend-stage';
  document.querySelector('.chan .pane-h').after(stage);
  var controls=document.createElement('div');controls.className='backend-controls';
  controls.innerHTML='<label><span data-t="issueTask"></span> <select id="task-select" class="task-select"></select></label><button id="continue-run" class="btn sm" data-t="continue"></button><button id="pause-run" class="btn sm" data-t="pause"></button><button id="current-board" class="btn sm" data-t="currentBoard"></button>';
  stage.after(controls);
  var support=document.createElement('div');support.className='scenario-note';support.id='scenario-support';controls.after(support);
  var UI={scenario:['시나리오','Scenario'],scenarioDoc:['시나리오 설명','Scenario details'],fillExample:['예시 이슈 채우기','Fill example issue'],oldView:['기존 화면','Previous view'],
    myRole:['내 역할','My role'],issueTask:['이슈 업무','Issue task'],continue:['계속 진행','Continue'],pause:['다음 단계에서 일시정지','Pause at next step'],currentBoard:['현재 보드','Current board']};
  function defaultPlaceholder(){return t('무엇이 바뀌었나요?\n예: Advanced Effects가 16h에서 32h로 늘어납니다.\n지켜야 할 마감과 필요한 도움을 함께 적어 주세요.','What changed?\nExample: Advanced Effects grows from 16h to 32h.\nInclude the deadline to keep and the help you need.');}
  function helpText(){return t('Enter 줄바꿈 · Ctrl / ⌘ + Enter 보내기 · 빈 입력창에서 Tab 예시 입력','Enter: new line · Ctrl / ⌘ + Enter: send · Tab in an empty box: insert example');}
  function chrome(){
    document.querySelectorAll('[data-t]').forEach(function(n){var v=UI[n.dataset.t];if(v)n.textContent=t(v[0],v[1]);});
    document.getElementById('demo-select').setAttribute('aria-label',t('시나리오','Scenario'));
    document.getElementById('viewer-select').setAttribute('aria-label',t('현재 사용자 역할','Current user role'));
    document.getElementById('task-select').setAttribute('aria-label',t('이슈 업무','Issue task'));
    document.querySelector('.chan .pane-h h2').textContent=t('# 후보 생성 · 팀 토론','# Plan candidates · team discussion');
    document.getElementById('sugg').innerHTML='<span class="sl">'+E(t('실제 후보 생성 → 카드 기반 토론 → PM 최종 선택','Real candidate generation → card-based discussion → PM final choice'))+'</span>';
    input.setAttribute('aria-label',t('업무 변경 이슈','Task change issue'));
  }
  // Apply the language to <html> (static i-ko/i-en spans), the toggle state, and every JS-drawn text.
  function setLanguage(code){
    code=code==='en'?'en':'ko';V.language(code);
    document.querySelectorAll('.langs [data-lang]').forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.lang===code));});
    if(state)draw();else{chrome();input.placeholder=defaultPlaceholder();}
    var h=document.getElementById('composer-help');if(h&&!h.classList.contains('blocked'))h.textContent=helpText();
    document.dispatchEvent(new CustomEvent('pb-language'));
  }
  chrome();
  input.placeholder=defaultPlaceholder();
  input.setAttribute('aria-describedby','composer-help');
  var help=document.createElement('div');help.id='composer-help';help.className='composer-help';help.textContent=helpText();document.getElementById('form').after(help);
  try{var savedLang=localStorage.getItem('pb-lang');if(savedLang==='en'||savedLang==='ko')setLanguage(savedLang);}catch(err){}
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
  document.querySelector('.sprint').textContent=t('서버 연결 중','Connecting to server');
  document.querySelector('.badge').textContent='API';
  document.getElementById('tip-ok').onclick=function(){document.getElementById('tip').hidden=true;};
  function label(pid){var p=state&&state.people.find(function(p){return p.id===pid;});return p?p.name:pid==='hive'?'Hive':pid==='pm'?'PM':pid||t('팀','Team');}
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
    var names={candidate_generate:t('02 · 시간 안에 가능한 새 milestone 설계','02 · Designing milestone plans that fit the deadline'),candidate_assess:t('03 · 각자 카드로 후보 비교','03 · Each member compares candidates by card'),candidate_discuss:t('03 · 공정성 discussion','03 · Fairness discussion'),candidate_rank:t('03 · 최종 순위·당사자 의사 확인','03 · Final ranking and member consent'),candidate_pm:t('04 · PM 최종 결정','04 · PM final decision'),candidate_confirm:t('04 · 당사자 본인 확인','04 · Personal confirmation'),candidate_failed:t('PM 상황 전달','Handed to PM'),done:t('완료','Done')};
    var budget=run&&run.llm_budget;
    stage.innerHTML='<strong>'+E(run?names[run.step]||run.step:t('01 · 이슈 입력','01 · Enter an issue'))+'</strong><br>'+E(runtime.llm_mode||'')+(runtime.model?' · '+E(runtime.model):'')+(run?' · '+E(({running:t('진행 중','Running'),awaiting_pm_selection:t('PM 선택 대기','Waiting for PM choice'),waiting_confirm:t('본인 확인 대기','Waiting for confirmation'),waiting_pm:t('PM 검토 필요','PM review needed'),done:t('완료','Done')})[run.status]||run.status)+' · '+t((run.round||0)+'라운드','round '+(run.round||0)):'')+(run&&run.assessment_progress&&/assess|rank/.test(run.step)?' · '+t('개인 평가 ','assessments ')+run.assessment_progress.completed+'/'+run.assessment_progress.total:'')+(budget?' · '+t('호출 ','calls ')+budget.used+'/'+budget.max:'')+(busy?' · '+t('처리 중…','working…'):'');
    var next=!run?t('업무를 선택하고 변경 내용을 보내세요.','Pick a task and send what changed.'):run.status==='awaiting_pm_selection'?t('추천 계획을 비교하고 PM이 최종 선택하세요.','Compare the recommended plans; the PM makes the final choice.'):run.status==='waiting_confirm'?t('확인 대상자의 역할로 전환해 동의·거절하세요.','Switch to the member who must confirm, then accept or reject.'):run.status==='waiting_pm'?t('해결되지 않은 조건을 확인하고 PM이 다음 조치를 결정하세요.','Review the open conditions; the PM decides the next step.'):run.status==='done'?t('처리가 끝났습니다. 보드에서 결과를 확인하세요.','Finished. Check the result on the board.'):automatic?t('팀이 계획을 검토하고 있습니다.','The team is reviewing the plans.'):t('일시정지 상태입니다. 계속 진행을 누르세요.','Paused. Press Continue.');
    stage.innerHTML+='<div class="next-action">'+E(next)+(['awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run&&run.status)?' <button type="button" class="btn sm" id="jump-decision">'+E(t('바로 보기 ↓','Jump to it ↓'))+'</button>':'')+'</div>';
    var jump=document.getElementById('jump-decision');if(jump)jump.onclick=function(){var target=feed.querySelector('.decision-anchor');if(target)target.scrollIntoView({behavior:'smooth',block:'start'});};
    stage.setAttribute('aria-busy',busy?'true':'false');
    document.getElementById('continue-run').disabled=busy||!run||run.status!=='running';
    document.getElementById('pause-run').disabled=!automatic;
    document.getElementById('demo-select').disabled=busy;
    document.getElementById('viewer-select').disabled=busy;
    document.getElementById('demo-advance').disabled=busy||!state||!state.feed_label||!!(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status));
    var sendBlock=busy?'':!document.getElementById('task-select').value?t('이 역할에는 이슈를 보낼 담당 업무가 없습니다. 담당 업무가 있는 역할이나 PM으로 전환하세요.','This role has no task to raise an issue on. Switch to a role that owns a task, or to PM.'):(run&&['running','awaiting_pm_selection','waiting_confirm','waiting_pm'].includes(run.status))?t('진행 중인 계획 조정이 끝나야 새 이슈를 보낼 수 있습니다. 위의 다음 행동을 먼저 처리하세요.','A plan adjustment is in progress. Finish the next action above before sending a new issue.'):'';
    var sendBtn=document.querySelector('#form button');sendBtn.disabled=busy||!!sendBlock;sendBtn.title=sendBlock;
    var help=document.getElementById('composer-help');if(help){help.textContent=sendBlock||helpText();help.classList.toggle('blocked',!!sendBlock);}
    document.getElementById('reset').disabled=busy;
    feed.querySelectorAll('[data-required-role]').forEach(function(b){b.disabled=busy||viewerRole!==b.dataset.requiredRole;});
  }
  async function refresh(loadRun){
    state=await api('/state');
    if(loadRun){var runs=await api('/candidate-runs');run=runs[0]||null;}
    draw();
  }
  function draw(){
    chrome();
    if(viewerRole!=='pm'&&!state.people.some(function(p){return viewerRole==='person:'+p.id;}))viewerRole='pm';
    state.viewer_role=viewerRole;
    var roles=document.getElementById('viewer-select');roles.innerHTML='<option value="pm">'+E(t('PM · 최종 결정자','PM · final decision maker'))+'</option>'+state.people.map(function(p){return '<option value="person:'+E(p.id)+'">'+E(p.name)+' · '+E(lang()==='en'&&window.PlanBeeRoleEn?window.PlanBeeRoleEn(p.role):p.role)+E(t(' 담당자',' owner'))+'</option>';}).join('');roles.value=viewerRole;
    var me=state.people.find(function(p){return viewerRole==='person:'+p.id;});
    var card=me&&(state.cards||[]).find(function(c){return c.who===me.id;});
    rolePanel.innerHTML='<strong>'+E(t('내 역할: ','My role: '))+E(me?me.name+t(' 본인 · ',' (self) · ')+(lang()==='en'&&window.PlanBeeRoleEn?window.PlanBeeRoleEn(me.role):me.role):t('PM · 최종 결정자','PM · final decision maker'))+'</strong><details><summary>'+E(t('역할 안내','About this role'))+(card?E(t(' · 내 위임카드',' · my delegation card')):'')+'</summary><p>'+E(me?t('내 업무 이슈를 줄글로 보내고, 내 변경안에 직접 동의·거절할 수 있습니다. 최종 후보 선택은 PM 역할에서 합니다.','Send issues about your own tasks and accept or reject changes to your work. The final choice is made in the PM role.'):t('팀 이슈를 요청하고 후보를 최종 선택합니다. 개인 확인은 해당 담당자 역할로 전환해 처리하세요.','Raise team issues and make the final choice. Switch to a member role to handle personal confirmations.'))+'</p>'+(card?'<details><summary>'+E(t('내 위임카드 확인','View my delegation card'))+'</summary><p>'+E(card.note||t('추가 조건 없음','No extra conditions'))+'</p><p>'+E(t('자동 수락 ','Auto-accept up to '))+fmt(card.auto_days)+E(t('일 · 거절 태그 ',' days · refused tags '))+E((card.refuse_tags||[]).join(', ')||t('없음','none'))+'</p></details>':'')+'<small>'+E(t('로컬 역할 체험 · 로그인 인증 아님 · 역할 전환만으로 LLM을 호출하지 않습니다.','Local role preview · not a login · switching roles does not call the LLM.'))+'</small></details>';
    document.querySelector('.sprint').textContent=lang()==='en'&&window.PlanBeeTitleEn?window.PlanBeeTitleEn(state.demo.title):state.demo.title;
    document.querySelector('.badge').textContent=(runtime.llm_mode||'').toUpperCase();
    var demo=document.getElementById('demo-select');demo.innerHTML=state.demo.catalog.map(function(d){return '<option value="'+E(d.id)+'"'+(d.id===state.demo.id?' selected':'')+'>'+E(lang()==='en'&&window.PlanBeeTitleEn?window.PlanBeeTitleEn(d.title):d.title)+'</option>';}).join('');
    document.getElementById('scenario-link').href='/scenario.html?demo='+encodeURIComponent(state.demo.id);
    var select=document.getElementById('task-select'),old=select.value;
    select.innerHTML=Object.values(state.tasks).filter(function(t){return !t.cut&&!['done','milestone','prop'].includes(t.kind)&&(viewerRole==='pm'||viewerRole==='person:'+t.who);}).map(function(t){return '<option value="'+E(t.id)+'">'+E(label(t.who)+' · '+t.title)+'</option>';}).join('');
    if(Array.from(select.options).some(function(o){return o.value===old;}))select.value=old;
    if(run&&Array.from(select.options).some(function(o){return o.value===run.task;}))select.value=run.task;
    if(!run&&state.demo.source_task&&Array.from(select.options).some(function(o){return o.value===state.demo.source_task;}))select.value=state.demo.source_task;
    input.placeholder=state.demo.issue_example?state.demo.issue_example+t('\n\n(Tab 키로 이 예시 입력)','\n\n(Press Tab to insert this example)'):defaultPlaceholder();
    support.innerHTML='<details><summary>'+E(t('이 시나리오에서 확인할 내용','What this scenario checks'))+'</summary><p>'+E(state.demo.engine_support||'')+'</p>'+(lang()==='en'?'<p class="candidate-meta">Scenario notes, issue examples and LLM messages are written in Korean.</p>':'')+'</details>';support.hidden=!state.demo.engine_support;
    V.render(state,preview&&preview.board,!!preview);paint();status();syncHeight();
  }
  function taskTable(board){return '<div class="candidate-table-wrap"><table><thead><tr><th>Task / milestone</th><th>'+E(t('담당','Owner'))+'</th><th>'+E(t('시작 → 완료','Start → finish'))+'</th></tr></thead><tbody>'+board.tasks.map(function(x){return '<tr><td>'+E(x.title)+'</td><td>'+E(label(x.who))+'</td><td>'+fmt(x.start)+' → '+fmt(x.start+x.days)+E(t('일',' d'))+'</td></tr>';}).join('')+'</tbody></table></div>';}
  function candidateCard(c,isFinal){
    var number=run.candidates.findIndex(function(x){return x.id===c.id;})+1;
    var html='<article class="candidate-card candidate-compact" data-card="'+E(c.id)+'"><div class="candidate-row"><div><h3>'+E(t('후보 ','Candidate '))+number+'</h3><span class="candidate-meta">'+E(isFinal?t('팀 추천 · PM 선택 가능','Team pick · PM can choose'):t('검증 통과 · 추가 당사자 검토 필요','Verified · needs more member review'))+'</span></div><div class="candidate-actions"><button class="btn sm" data-preview="'+E(c.id)+'">'+E(t('보드에서 보기','Show on board'))+'</button>';
    if(isFinal&&run.status==='awaiting_pm_selection')html+=viewerRole==='pm'?'<button class="btn go sm" data-required-role="pm" data-select="'+E(c.id)+'">'+E(t('이 안으로 결정','Choose this plan'))+'</button>':'<button class="btn sm" data-switch-role="pm">'+E(t('PM으로 전환해 결정','Switch to PM to decide'))+'</button>';
    html+='</div></div><details data-open="plan-'+E(c.id)+'"><summary>'+E(t('변경 내용 · 일정 자세히','Changes · schedule details'))+'</summary><p>'+E(planTitle(c.title))+'</p>';
    if((c.plan_actions||[]).length)html+='<ul>'+c.plan_actions.map(function(a){return '<li>'+E((state.tasks[a.task]||{}).title||a.task)+' · '+E(a.kind==='defer'?t(a.milestone+'로 이관','deferred to '+a.milestone):a.kind==='omit'?t('선택 검증 생략 · 본인 확인 필요','optional check skipped · confirmation needed'):t('임시 반영 / 최종 교체로 분해','split into temporary / final replacement'))+'</li>';}).join('')+'</ul>';
    html+='<p class="candidate-meta">'+Object.keys(c.consents||{}).map(function(pid){return E(label(pid))+': '+E({ACCEPT:t('동의','accept'),REJECT:t('거절','reject'),NEEDS_INPUT:t('본인 확인 필요','needs confirmation')}[c.consents[pid].action]);}).join(' · ')+'</p>'+taskTable(c.board)+'</details></article>';
    return html;
  }
  function paint(){
    var selectedRubric=document.getElementById('eval-rubric')?.value||'fairness',selectedPerson=document.getElementById('eval-person')?.value;
    var open=new Set(Array.from(feed.querySelectorAll('details[open][data-open]')).map(function(n){return n.dataset.open;}));var atEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<90,scroll=feed.scrollTop;
    if(!run){feed.innerHTML='<div class="backend-empty">'+E(t('보드에서 업무를 고르고 변경 이슈를 보내세요.','Pick a task on the board and send a change issue.'))+'<br>'+E(t('생성 AI와 알고리즘이 시간 안에 가능한 계획을 만들고, 각자의 카드로 토론한 뒤 PM에게 후보 1~3개를 올립니다.','Generation AI and the search build plans that fit the deadline, members discuss them with their own cards, and 1–3 candidates go to the PM.'))+'</div>';return;}
    var html='<details class="issue-summary" data-open="issue"><summary>'+E(t('요청한 이슈 · ','Requested issue · '))+E(run.phase==='deadline'?t('기한 회복','deadline recovery'):t('공정성 재분담','fairness rebalance'))+'</summary><p>'+E(run.issue)+'</p></details>';
    (run.public_history||[]).forEach(function(m){
      var hive=m.requester==='hive',pm=m.requester==='pm';html+='<div class="msg in"><div class="av '+(hive?'hive':pm?'pm':'proxy')+'">'+(hive?'':E(label(m.requester).slice(0,1)))+'</div><div><div class="meta"><b>'+E(label(m.requester))+'</b><small>'+E(t(m.round+'라운드','round '+m.round))+(m.recipient?' → '+E(label(m.recipient)):'')+(m.candidate_id?' · '+E(t('계획 ','plan '))+((run.candidates||[]).findIndex(function(c){return c.id===m.candidate_id;})+1||E(t('수정안','revision'))):'')+'</small></div><p>'+E(messageText(m))+'</p></div></div>';
    });
    if(run.generation)html+='<details data-open="generation"><summary>'+E(t('후보 생성·검증 내역','Generation and verification log'))+'</summary><p class="candidate-meta">'+E(t('탐색 '+run.generation.attempted+'개 · 통과 '+run.generation.feasible+'개 · 중복 '+run.generation.duplicates+'개 · 반려 '+run.generation.rejected+'개','searched '+run.generation.attempted+' · passed '+run.generation.feasible+' · duplicates '+run.generation.duplicates+' · rejected '+run.generation.rejected))+'</p><ul>'+Object.keys(run.generation.reasons||{}).slice(0,12).map(function(x){return '<li>'+E(x)+' ('+run.generation.reasons[x]+')</li>';}).join('')+'</ul></details>';
    var finals=run.final_candidates||[];
    if(run.status==='awaiting_pm_selection')html+='<div class="backend-empty decision-anchor"><strong>'+E(t('PM 최종 결정','PM final decision'))+'</strong><br>'+E(t('후보가 하나여도 PM 선택 전에는 적용되지 않습니다.','Nothing is applied before the PM chooses, even with a single candidate.'))+'</div>';
    if((run.candidates||[]).length)html+='<div class="candidate-list">'+run.candidates.map(function(c){return candidateCard(c,finals.includes(c.id));}).join('')+'</div>';
    if(run.status==='awaiting_pm_selection'&&viewerRole==='pm')html+='<div class="candidate-actions"><button class="btn sm" data-pm-action="reject">'+E(t('모두 반려','Reject all'))+'</button><button class="btn sm" data-pm-action="revise">'+E(t('수정 요청','Request revision'))+'</button></div>';

    (state.pending_confirms||[]).forEach(function(c){
      html+='<article class="candidate-card decision-anchor"><h3>'+E(label(c.who))+E(t(' 본인 확인',' · personal confirmation'))+'</h3><p>'+E(c.prompt)+'</p><p class="candidate-meta">'+E(c.text)+'</p><div class="candidate-actions">';
      if(viewerRole==='person:'+c.who)html+='<button class="btn go sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="true">'+E(t('당사자로서 동의','Accept as owner'))+'</button><button class="btn sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="false">'+E(t('거절','Reject'))+'</button>';
      else html+='<button class="btn sm" data-switch-role="person:'+E(c.who)+'">'+E(t(label(c.who)+' 본인으로 전환','Switch to '+label(c.who)))+'</button>';
      html+='</div></article>';
    });
    if(run.pm_handoff)html+='<article class="candidate-card decision-anchor"><h3>'+E(t(run.pm_handoff.message,'Negotiation failed → handed to PM'))+'</h3><details data-open="handoff"><summary>'+E(t('현재 상황 summary 보기','View situation summary'))+'</summary><p>'+E(run.pm_handoff.summary.termination)+'</p><p>'+E(t('검증 후보 '+run.pm_handoff.summary.candidate_count+'개 · 미합의 변경 미적용',run.pm_handoff.summary.candidate_count+' verified candidates · unagreed changes not applied'))+'</p><ul>'+((run.pm_handoff.summary.last_messages)||[]).map(function(e){return '<li>'+E(label(e.requester)+': '+messageText(e))+'</li>';}).join('')+'</ul></details>'+(run.status==='waiting_pm'?(viewerRole==='pm'?'<button class="btn sm" data-required-role="pm" data-close-run>'+E(t('상황 확인 · 현재 배분 유지','Acknowledge · keep current allocation'))+'</button>':'<button class="btn sm" data-switch-role="pm">'+E(t('PM으로 전환해 상황 확인','Switch to PM to review'))+'</button>'):'')+'</article>';
    if(run.status==='done')html+='<div class="backend-empty">'+E(run.termination==='applied'?t('PM이 선택한 계획을 최종 검증 후 적용했습니다.','The PM-chosen plan passed final verification and was applied.'):t('현재 배분을 유지했습니다.','The current allocation was kept.'))+'</div>';
    if(run.shortlist&&run.shortlist.length&&['awaiting_pm_selection','waiting_confirm','done','waiting_pm'].includes(run.status))html+='<article class="evaluation-card"><h3>'+E(t('사람 순위와 별도 비교평가','Separate human-ranking evaluation'))+'</h3><p class="candidate-meta">'+E(t('운영 PM 선택과 별도로 평가합니다. 새 평가자는 전용 링크에서 LLM 순위 없이 같은 후보를 비교합니다.','Evaluated separately from the PM decision. A new rater compares the same candidates on a dedicated link without LLM rankings.'))+'</p><label>'+E(t('평가 기준','Rubric'))+' <select id="eval-rubric"><option value="fairness">'+E(t('공정성','Fairness'))+'</option><option value="card_fit">'+E(t('본인 카드 적합성','Card fit'))+'</option></select></label><label>'+E(t('역할','Role'))+' <select id="eval-person">'+state.people.filter(function(p){return (run.participants||[]).includes(p.id);}).map(function(p){return '<option value="'+E(p.id)+'">'+E(p.name)+'</option>';}).join('')+'</select></label><button class="btn go sm" data-create-evaluation>'+E(t('독립 평가 링크 생성 · 열기','Create and open rater link'))+'</button><div class="evaluation-feedback" role="status">'+(evaluationError?'<p class="backend-error">'+E(evaluationError)+'</p>':'')+(evaluationLink?'<p>'+E(t('평가 링크를 만들었습니다. 새 탭이 열리지 않으면 아래 버튼을 눌러 주세요.','Link created. If no new tab opened, use the button below.'))+'</p><a class="btn go sm" target="_blank" rel="noopener" href="'+E(evaluationLink)+'">'+E(t('사람 평가 화면 열기 ↗','Open rater screen ↗'))+'</a><input aria-label="'+E(t('공유할 독립 평가 링크','Rater link to share'))+'" readonly value="'+E(location.origin+evaluationLink)+'">':'')+'</div>'+'</article>';
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
  window.PlanBeeApp={quote:function(type,id){if(type==='t')document.getElementById('task-select').value=id;var q=document.getElementById('quotes');q.hidden=false;q.textContent=t('참조: ','Quote: ')+id;input.focus();}};
  document.getElementById('form').addEventListener('submit',function(e){e.preventDefault();var issue=input.value.trim();if(!issue)return;act(async function(){var taskId=document.getElementById('task-select').value,shownDemo=state&&state.demo&&state.demo.id;var latest=await api('/state');if(!latest.tasks[taskId]||(latest.demo&&latest.demo.id)!==shownDemo){await refresh(true);throw new Error(t('서버의 시나리오가 화면과 달라 이 업무를 찾을 수 없습니다(서버 재시작 또는 다른 사람이 시나리오 변경). 화면을 최신 상태로 고쳤으니 시나리오·업무를 확인한 뒤 다시 보내 주세요. 입력한 내용은 그대로 남아 있습니다.','The server scenario differs from this screen, so the task was not found (server restart or someone changed the scenario). The screen is now up to date; check the scenario and task, then send again. Your text is kept.'));}run=await api('/candidate-runs',{task_id:taskId,issue:issue});input.value='';input.dispatchEvent(new Event('input'));evaluationLink=null;evaluationError='';preview=null;await refresh(false);automatic=true;}).then(loop);});
  document.getElementById('continue-run').onclick=function(){automatic=true;loop();};
  document.getElementById('pause-run').onclick=function(){automatic=false;status();};
  document.getElementById('current-board').onclick=function(){preview=null;if(state)V.render(state,null,false);};
  document.getElementById('demo-select').onchange=function(e){automatic=false;act(async function(){await api('/demo/select',{demo:e.target.value});run=null;preview=null;evaluationLink=null;evaluationError='';await refresh(true);});};
  document.getElementById('demo-advance').onclick=function(){var source=state.tasks[state.demo.source_task];if(source&&viewerRole!=='pm'&&viewerRole!=='person:'+source.who){error(new Error(t(label(source.who)+' 역할로 전환한 뒤 예시를 입력하세요.','Switch to the '+label(source.who)+' role before inserting the example.')));return;}if(source)document.getElementById('task-select').value=source.id;input.value=state.demo.issue_example||'';input.dispatchEvent(new Event('input'));input.focus();V.toast(t('예시만 채웠습니다. 내용을 확인한 뒤 보내기를 누르세요.','Example inserted. Check it, then press Send.'));};
  document.getElementById('task-select').onchange=status;
  function syncHeight(){document.querySelector('.app').style.height=window.innerWidth>900?'calc(100dvh - '+Math.ceil(top.getBoundingClientRect().height)+'px)':'auto';}
  window.addEventListener('resize',syncHeight);
  async function switchRole(role){viewerRole=role;try{localStorage.setItem('pb-viewer-role',role);}catch(err){}await refresh(false);}
  document.getElementById('viewer-select').onchange=function(e){act(function(){return switchRole(e.target.value);});};
  document.getElementById('reset').onclick=function(){if(!window.confirm(t('현재 데모를 초기 상태로 되돌릴까요?','Reset the current demo to its initial state?')))return;automatic=false;act(async function(){await api('/reset',{});run=null;preview=null;evaluationLink=null;await refresh(true);});};
  feed.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||busy||!run)return;
    if(b.dataset.switchRole){act(function(){return switchRole(b.dataset.switchRole);});return;}
    if(b.dataset.preview){preview=run.candidates.find(function(c){return c.id===b.dataset.preview;});V.render(state,preview.board,true);return;}
    var evaluationWindow=null;
    if(b.hasAttribute('data-create-evaluation')){
      if(!document.getElementById('eval-person').value){evaluationError=t('최종 평가에 참여한 역할이 없습니다. 토론 완료 후 다시 시도해 주세요.','No role took part in the final assessment. Try again after the discussion.');paint();return;}
      evaluationWindow=window.open('about:blank','_blank');
      if(evaluationWindow){evaluationWindow.opener=null;evaluationWindow.document.title=t('평가 화면 준비 중','Preparing rater screen');evaluationWindow.document.body.textContent=t('독립 평가 링크를 생성하고 있습니다…','Creating the rater link…');}
    }
    act(async function(){
      if(b.dataset.select){var c=run.candidates.find(function(c){return c.id===b.dataset.select;});run=await api('/runs/'+run.id+'/pm-selection',{action:'select',candidate_id:c.id,plan_hash:c.plan_hash});preview=null;await refresh(false);}
      else if(b.dataset.pmAction){var reason=window.prompt(t('반려/수정 요청 이유를 적어 주세요','Give a reason for rejecting / requesting revision'));if(!reason)return;run=await api('/runs/'+run.id+'/pm-selection',{action:b.dataset.pmAction,reason:reason});await refresh(false);}
      else if(b.dataset.confirm){await api('/confirmations/'+b.dataset.confirm,{ok:b.dataset.ok==='true'});run=await api('/runs/'+run.id);await refresh(false);}
      else if(b.hasAttribute('data-close-run')){run=await api('/runs/'+run.id+'/close',{});await refresh(false);}
      else if(b.hasAttribute('data-create-evaluation')){
        evaluationError='';
        try{var rubric=document.getElementById('eval-rubric').value;var ev=await api('/runs/'+run.id+'/evaluations',{rubric:rubric,person_id:document.getElementById('eval-person').value});evaluationLink='/front/evaluation.html?id='+ev.id;if(evaluationWindow)evaluationWindow.location.replace(evaluationLink);paint();feed.querySelector('.evaluation-feedback').scrollIntoView({block:'nearest'});}
        catch(err){if(evaluationWindow)evaluationWindow.close();evaluationError=t('평가 링크를 만들지 못했습니다: ','Could not create the rater link: ')+err.message;paint();feed.querySelector('.evaluation-feedback').scrollIntoView({block:'nearest'});}
      }
    });
  });
  document.querySelector('.langs').addEventListener('click',function(e){var b=e.target.closest('[data-lang]');if(b){setLanguage(b.dataset.lang);try{localStorage.setItem('pb-lang',b.dataset.lang);}catch(err){}}});
  document.getElementById('themes').addEventListener('click',function(e){var b=e.target.closest('[data-mode]');if(b){V.theme(b.dataset.mode);try{localStorage.setItem('pb-theme',b.dataset.mode);}catch(err){}}});
  act(async function(){runtime=await api('/runtime');await refresh(true);});
})();
