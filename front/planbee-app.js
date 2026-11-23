/* Persistent API integration for the Plan Bee channel + milestone board. */
(function () {
  'use strict';
  var V=window.PlanBeeView, E=V.esc, state=null, run=null, runtime={}, busy=false, automatic=false, preview=null, refs=[], booted=false;
  var viewerRole='pm';try{viewerRole=localStorage.getItem('pb-viewer-role')||'pm';}catch(err){}
  var feed=document.getElementById('feed'), input=document.getElementById('change-input'), top=document.querySelector('.top');

  /* ---------- language ---------- */
  function lang(){return document.documentElement.getAttribute('data-lang')==='en'?'en':'ko';}
  function t(ko,en){return lang()==='en'?en:ko;}
  function roleName(r){return lang()==='en'&&window.PlanBeeRoleEn?window.PlanBeeRoleEn(r):r;}
  function scenarioTitle(x){return lang()==='en'&&window.PlanBeeTitleEn?window.PlanBeeTitleEn(x):x;}
  // Server-made Hive/system messages arrive in Korean with a stable action code: translate by code.
  var HIVE_EN={
    TASK_IDENTIFIED:function(){return 'Read the issue and identified the relevant task. See the agenda for its owner and title.';},
    ISSUE:function(){return 'Issue received. Designing new milestone plans that fit the deadline first.';},
    ESTIMATE:function(m){var d=(m.reason.match(/([0-9.]+)일/)||[])[1];return 'Read the issue and re-estimated this task to '+(d||'?')+' days.';},
    CANDIDATES:function(m){var n=(m.reason.match(/(\d+)개/)||[])[1];return 'Prepared '+(n||'')+' new plans that passed Hive schedule checks.';},
    SUPPLEMENT:function(){return 'A new public condition came up. Adding alternatives once while keeping existing candidates.';},
    SUPPLEMENT_FAILED:function(){return 'Supplementary generation failed. Keeping verified candidates and re-assessing.';},
    INVITE:function(m){return 'Inviting '+label(m.recipient)+' because of a direct question.';},
    PM_OPTIONS:function(m){var n=(m.reason.match(/(\d+)개/)||[])[1];return 'Narrowed down to '+(n||'')+' plans. The PM decides; nothing is applied automatically.';},
    CONFIRM:function(){return 'PM choice received. Waiting for personal confirmation.';},
    APPLIED:function(){return 'PM choice and member consent confirmed; passed the final deadline check and applied to the board.';},
    REJECT:function(){return 'A member rejected the chosen plan. Not applied; back to the PM list.';},
    END:function(m){var code=(m.reason.match(/([a-z_]+)/)||[])[1];return 'Negotiation ended'+(code?' ('+code+')':'')+'. Unagreed changes are not applied; the situation goes to the PM.';}
  };
  var TITLE_EN={'원 업무 전체 유지·양도':'Keep or transfer the whole task','Task에 명시된 산출물 분담':'Split as stated in the task','선택 범위의 후속 milestone 이관':'Defer optional scope to a later milestone','중간 산출물과 최종 반영의 단계별 재설계':'Staged redesign: interim and final delivery','현재 milestone 계획 유지':'Keep the current milestone plan'};
  function planTitle(x){return lang()==='en'&&TITLE_EN[x]?TITLE_EN[x]:x;}
  function hiveText(m){return lang()==='en'&&HIVE_EN[m.response]?HIVE_EN[m.response](m):m.reason;}

  /* ---------- chrome ---------- */
  var tools=document.createElement('div');tools.className='backend-tools';
  tools.innerHTML='<label><span data-t="scenario"></span> <select id="demo-select"></select></label><label class="viewer-select-label"><span data-t="myRole"></span> <select id="viewer-select"></select></label>';
  top.appendChild(tools);
  var stage=document.createElement('div');stage.className='backend-stage';stage.setAttribute('role','status');stage.id='backend-stage';
  document.querySelector('.chan .pane-h').after(stage);
  var controls=document.createElement('div');controls.className='backend-controls';
  controls.innerHTML='<button id="continue-run" class="btn sm" data-t="continue"></button><button id="pause-run" class="btn sm" data-t="pause"></button><button id="current-board" class="btn sm" data-t="currentBoard"></button><button id="next-day" class="btn sm" data-t="nextDay"></button>';
  stage.after(controls);
  var UI={scenario:['시나리오','Scenario'],myRole:['내 역할','My role'],continue:['계속 진행','Continue'],pause:['일시정지','Pause'],currentBoard:['현재 보드','Current board'],nextDay:['다음 날로 ▶','Next day ▶']};
  function defaultPlaceholder(){return t('무엇이 바뀌었나요? 업무를 고르지 않고 자유롭게 적어 주세요.','What changed? Describe it freely; the team will identify the task.');}
  function helpText(){return t('Ctrl / ⌘ + Enter 보내기 · 빈 입력창에서 Tab 예시 입력','Ctrl / ⌘ + Enter: send · Tab in an empty box: insert example');}
  function chrome(){
    document.querySelectorAll('[data-t]').forEach(function(n){var v=UI[n.dataset.t];if(v)n.textContent=t(v[0],v[1]);});
    document.getElementById('demo-select').setAttribute('aria-label',t('시나리오','Scenario'));
    document.getElementById('viewer-select').setAttribute('aria-label',t('현재 사용자 역할','Current user role'));
    document.querySelector('.chan .pane-h h2').textContent=t('# 팀 협의','# Team negotiation');
    var sugg=document.getElementById('sugg');if(sugg)sugg.innerHTML='';
    input.setAttribute('aria-label',t('업무 변경 이슈','Task change issue'));
  }
  input.setAttribute('aria-describedby','composer-help');
  var help=document.createElement('div');help.id='composer-help';help.className='composer-help';document.getElementById('form').after(help);
  function setLanguage(code){
    code=code==='en'?'en':'ko';V.language(code);
    document.querySelectorAll('.langs [data-lang]').forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.lang===code));});
    if(state)draw();else{chrome();input.placeholder=defaultPlaceholder();help.textContent=helpText();}
    document.dispatchEvent(new CustomEvent('pb-language'));
  }
  chrome();input.placeholder=defaultPlaceholder();help.textContent=helpText();
  try{var savedLang=localStorage.getItem('pb-lang');if(savedLang==='en'||savedLang==='ko')setLanguage(savedLang);}catch(err){}
  input.addEventListener('keydown',function(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing){e.preventDefault();document.getElementById('form').requestSubmit();}});
  // Tab in an empty box inserts the scenario's first issue as an example (any other text works too).
  input.addEventListener('keydown',function(e){
    var example=state&&state.demo&&state.demo.issue_example;
    if(e.key!=='Tab'||e.shiftKey||e.isComposing||input.value.trim()||!example)return;
    e.preventDefault();
    input.value=example;input.dispatchEvent(new Event('input'));input.setSelectionRange(example.length,example.length);status();
  });
  input.addEventListener('input',function(){input.style.height='auto';input.style.height=Math.min(240,Math.max(112,input.scrollHeight))+'px';});
  document.querySelector('.sprint').textContent=t('서버 연결 중','Connecting to server');
  var tip=document.getElementById('tip');if(tip)tip.hidden=true;
  function label(pid){var p=state&&state.people.find(function(p){return p.id===pid;});return p?p.name:pid==='hive'?'Hive':pid==='pm'?'PM':pid||t('팀','Team');}
  function fmt(n){return Number(Number(n).toFixed(2));}

  /* ---------- robust API ---------- */
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  async function api(path,body,opts){
    opts=opts||{};var tries=body===undefined?3:(opts.retry||1),last;
    for(var i=0;i<tries;i++){
      var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},opts.timeout||(body===undefined?20000:180000));
      try{
        var res=await fetch(path,{method:body===undefined?'GET':'POST',signal:ctl.signal,cache:'no-store',headers:{'Content-Type':'application/json','X-Planbee-Role':viewerRole},body:body===undefined?undefined:JSON.stringify(body)});
        var text=await res.text(),result=null;try{result=text?JSON.parse(text):{};}catch(err){result=null;}
        if(res.ok&&result)return result;
        var detail=result&&result.detail;
        last=new Error(typeof detail==='string'?detail:detail?JSON.stringify(detail):res.status>=500?t('서버가 준비 중이거나 일시 오류입니다 ('+res.status+'). 잠시 후 다시 시도합니다.','The server is starting or had a temporary error ('+res.status+'). Retrying shortly.'):t('요청 실패 ('+res.status+')','Request failed ('+res.status+')'));
        last.status=res.status;
        if(res.status<500)throw last;
      }catch(err){
        if(err.status&&err.status<500)throw err;
        last=err.name==='AbortError'?new Error(t('서버 응답이 늦습니다. 연결을 다시 시도합니다.','The server is slow to respond. Retrying.')):err;
      }finally{clearTimeout(timer);}
      if(i<tries-1)await sleep(1500*(i+1));
    }
    throw last;
  }
  function error(err){var box=document.getElementById('backend-error');if(!box){box=document.createElement('div');box.id='backend-error';box.className='backend-error';stage.after(box);}box.textContent=err.message;}
  function clearError(){var box=document.getElementById('backend-error');if(box)box.remove();}
  async function act(fn){if(busy)return;busy=true;clearError();status();try{await fn();}catch(err){automatic=false;error(err);}finally{busy=false;status();}}

  /* ---------- status line ---------- */
  var ACTIVE=['running','awaiting_pm_selection','waiting_confirm','waiting_pm'];
  function status(){
    var names={candidate_generate:t('후보 생성·검증','Generating and verifying plans'),candidate_assess:t('각자 카드로 평가','Members assess by card'),candidate_discuss:t('공개 토론','Open discussion'),candidate_rank:t('최종 평가·당사자 동의','Final assessment and consent'),candidate_pm:t('PM 결정','PM decision'),candidate_confirm:t('본인 확인','Personal confirmation'),candidate_failed:t('PM 검토','PM review'),done:t('완료','Done')};
    var budget=run&&run.llm_budget,active=!!(run&&ACTIVE.includes(run.status));
    var line=!booted?t('서버에 연결하는 중…','Connecting to the server…'):active?(names[run.step]||run.step)+(run.round?' · '+t('라운드 '+run.round,'round '+run.round):'')+(run.assessment_progress&&/assess|rank/.test(run.step)?' · '+run.assessment_progress.completed+'/'+run.assessment_progress.total:''):t('새 이슈를 기다리는 중','Waiting for a new issue');
    var next=!booted?'':!active?t('무엇이 바뀌었는지 보내세요. LLM이 관련 업무를 찾습니다.','Send what changed. The LLM will identify the relevant task.'):run.status==='awaiting_pm_selection'?t('추천 계획을 비교하고 PM이 결정하세요.','Compare the recommended plans; the PM decides.'):run.status==='waiting_pm'?t('PM이 상황을 확인하고 다음 조치를 정하세요.','The PM reviews the situation and decides the next step.'):run.status==='waiting_confirm'?t('본인 확인 대기 중입니다.','Waiting for personal confirmation.'):automatic?t('팀이 협의하고 있습니다…','The team is negotiating…'):t('일시정지 상태입니다. 계속 진행을 누르세요.','Paused. Press Continue.');
    stage.innerHTML='<strong>'+E(line)+'</strong>'+(busy?'<span class="stage-busy"> · '+E(t('처리 중','working'))+'</span>':'')+'<span class="stage-meta">'+E(runtime.llm_mode||'')+(budget&&active?' · '+E(t('호출 ','calls '))+budget.used+'/'+budget.max:'')+'</span>'+(next?'<div class="next-action">'+E(next)+(run&&['awaiting_pm_selection','waiting_pm'].includes(run.status)?' <button type="button" class="btn sm" id="jump-decision">'+E(t('바로 보기 ↓','Jump to it ↓'))+'</button>':'')+'</div>':'');
    var jump=document.getElementById('jump-decision');if(jump)jump.onclick=function(){var target=feed.querySelector('.decision-anchor');if(target)target.scrollIntoView({behavior:'smooth',block:'start'});};
    stage.setAttribute('aria-busy',busy?'true':'false');
    document.getElementById('continue-run').disabled=busy||!run||run.status!=='running'||automatic;
    document.getElementById('pause-run').disabled=!automatic;
    document.getElementById('demo-select').disabled=busy||!booted;
    document.getElementById('viewer-select').disabled=busy||!booted;
    document.getElementById('next-day').disabled=busy||!booted||active||!state||state.now>=state.week_end;
    var sendBlock=busy||!booted?'':active?t('진행 중인 협의가 끝나야 새 이슈를 보낼 수 있습니다.','Finish the current negotiation before sending a new issue.'):'';
    var sendBtn=document.querySelector('#form button');sendBtn.disabled=busy||!booted||!!sendBlock;sendBtn.title=sendBlock;
    help.textContent=sendBlock||helpText();help.classList.toggle('blocked',!!sendBlock);
    document.getElementById('reset').disabled=busy||!booted;
    feed.querySelectorAll('button').forEach(function(b){b.disabled=busy||!!(b.dataset.requiredRole&&viewerRole!==b.dataset.requiredRole);});
  }

  /* ---------- data + drawing ---------- */
  var refreshSeq=0;
  async function refresh(loadRun){
    var my=++refreshSeq;
    var s=await api('/state'),r=loadRun?(await api('/candidate-runs'))[0]||null:run;
    if(my!==refreshSeq)return;   // a newer refresh already drew
    if(state&&state.demo&&s.demo&&state.demo.id!==s.demo.id)refs=[];
    state=s;if(loadRun)run=r;booted=true;draw();
  }
  function draw(){
    chrome();
    if(viewerRole!=='pm'&&!state.people.some(function(p){return viewerRole==='person:'+p.id;}))viewerRole='pm';
    state.viewer_role=viewerRole;
    var roles=document.getElementById('viewer-select');roles.innerHTML='<option value="pm">PM</option>'+state.people.map(function(p){return '<option value="person:'+E(p.id)+'">'+E(p.name)+' · '+E(roleName(p.role))+'</option>';}).join('');roles.value=viewerRole;
    document.querySelector('.sprint').textContent=scenarioTitle(state.demo.title)+' · '+(lang()==='en'?'day '+fmt(state.now):state.now_label);
    document.querySelector('.badge').textContent=(runtime.llm_mode||'').toUpperCase();
    var demo=document.getElementById('demo-select');demo.innerHTML=state.demo.catalog.map(function(d){return '<option value="'+E(d.id)+'"'+(d.id===state.demo.id?' selected':'')+'>'+E(scenarioTitle(d.title))+'</option>';}).join('');
    var src=state.tasks[state.demo.source_task];
    input.placeholder=state.demo.issue_example&&src&&src.kind!=='done'?state.demo.issue_example+t('\n\n(빈 입력창에서 Tab: 이 예시 입력 · 다른 내용도 자유롭게)','\n\n(Tab in an empty box inserts this example · any other text works too)'):defaultPlaceholder();
    paintRefs();
    V.render(state,preview&&preview.board,!!preview);paint();status();syncHeight();
  }

  /* ---------- references (quotes) ---------- */
  // References are optional shared context, never a forced issue-task selection.
  function refLabel(r){
    if(r.type==='t'){var x=state&&state.tasks[r.id];return t('업무 ','Task ')+(x?x.title:r.id);}
    if(r.type==='p')return t('사람 ','Person ')+label(r.id);
    var h=state&&state.hand[r.id];return 'Handoff '+(h?((state.tasks[h.from]||{}).title||h.from)+' → '+((state.tasks[h.to]||{}).title||h.to):r.id);
  }
  function paintRefs(){
    var q=document.getElementById('quotes');if(!q)return;
    q.hidden=!refs.length;
    q.innerHTML=(refs.length?'<button type="button" class="btn sm" data-clear-refs>'+E(t('참조 모두 비우기','Clear references'))+'</button>':'')+refs.map(function(r,i){return '<span class="ref-chip" title="'+E(t('보낼 때 이슈의 참고 정보로 함께 전달됩니다.','Sent as optional context with the issue.'))+'">'+E(refLabel(r))+'<button type="button" class="ref-x" data-ref="'+i+'" aria-label="'+E(t('참조 빼기','Remove reference'))+'">×</button></span>';}).join('');
  }
  document.getElementById('quotes').addEventListener('click',function(e){if(e.target.closest('[data-clear-refs]')){refs=[];paintRefs();return;}var b=e.target.closest('[data-ref]');if(!b)return;refs.splice(Number(b.dataset.ref),1);paintRefs();});
  window.PlanBeeApp={quote:function(type,id){
    if(!state||!((type==='t'&&state.tasks[id])||(type==='p'&&state.people.some(function(p){return p.id===id;}))||(type==='h'&&state.hand[id])))return;
    if(!refs.some(function(r){return r.type===type&&r.id===id;}))refs.push({type:type,id:id});
    paintRefs();status();input.focus();
  }};
  function issueWithRefs(text){
    var extra=refs.map(function(r){return refLabel(r)+' ['+r.id+']';});
    return extra.length?text+'\n\n'+t('참조: ','References: ')+extra.join(', '):text;
  }

  /* ---------- feed: readable MAS discussion ---------- */
  var SPEECH={QUESTION:['질문','Question','t-cond'],ANSWER:['답변','Answer','t-ok'],PREFER:['선호','Prefers','t-ok'],REJECT:['반대','Objects','t-no'],CONDITION:['조건','Condition','t-cond'],PASS:['의견 없음','No comment','t-flat']};
  var CONSENT={ACCEPT:['동의','Accept','t-ok'],REJECT:['거절','Reject','t-no'],NEEDS_INPUT:['본인 확인 필요','Needs confirmation','t-cond'],AUTO_CONFIRM:['자동 승인','Auto-approved','t-ok']};
  var NOISE=['REPEAT_SKIPPED','SCHEMA_REPAIR','ASSESSMENT_REPAIR','SPEECH_REPAIR','TEMPLATE_DROPPED','REPAIR_REQUEST'];
  var STAGES={interpret:['1 · 이슈 해석','1 · Reading the issue'],generate:['2 · 후보 생성 · Hive 검증','2 · Plan generation · Hive checks'],assess:['3 · 각자 위임카드로 평가','3 · Each member assesses by card'],discuss:['4 · 공개 토론','4 · Open discussion'],rank:['5 · 토론 후 최종 평가','5 · Final assessment'],consent:['6 · 후보별 당사자 동의','6 · Consent per plan'],decide:['7 · PM 결정','7 · PM decision']};
  function badge(def){return '<span class="rt '+def[2]+'">'+E(t(def[0],def[1]))+'</span>';}
  function candNo(id){var i=(run.candidates||[]).findIndex(function(c){return c.id===id;});return i<0?null:i+1;}
  function candChip(id){var n=id&&candNo(id);return n?'<button type="button" class="cand-chip" data-preview="'+E(id)+'">'+E(t('후보 '+n,'Plan '+n))+'</button>':'';}
  function participants(){
    // Everyone who actually took part: assigned participants, affected members, and anyone who spoke or was invited.
    var ids=(run.participants||[]).concat((run.candidates||[]).reduce(function(a,c){return a.concat(c.affected||[]);},[]));
    (run.public_history||[]).forEach(function(m){if(m.requester&&m.requester!=='hive'&&m.requester!=='pm')ids.push(m.requester);if(m.response==='INVITE'&&m.recipient)ids.push(m.recipient);});
    ids=state.people.map(function(p){return p.id;}).filter(function(id){return ids.includes(id);});
    if(!ids.length)ids=state.people.map(function(p){return p.id;});
    return ids.map(label).join(', ');
  }
  function feedHTML(){
    var task=state.tasks[run.task]||{};
    var html='<div class="agenda"><div class="agenda-h"><span class="av hive" aria-hidden="true"></span><b>'+E(t('Hive · 안건','Hive · Agenda'))+'</b><span class="rt t-flat">'+E(run.phase==='deadline'?t('기한 회복','Deadline recovery'):t('공정성 재분담','Fairness rebalance'))+'</span></div>'+
      '<p class="agenda-task">'+E(task.title||run.task||t('업무 확인 필요','Task needs clarification'))+' <small>'+E(t('담당 ','owner ')+label(task.who))+'</small></p><p class="agenda-issue">'+E(run.issue)+'</p>'+
      '<p class="agenda-who">'+E(t('참석: ','Participants: '))+E(participants())+' · '+E(t('결정: PM','Decision: PM'))+'</p></div>';
    var cur=null,noise=0,assessed=[],ranked=[],afterRank=false;
    function sys(text){return '<div class="sys-line">'+E(text)+'</div>';}
    function flush(){
      if(assessed.length){html+=sys(t(assessed.join(', ')+' — 각자 위임카드와 일정으로 후보를 평가했어요.',assessed.join(', ')+' — assessed the plans with their own cards and schedules.'));assessed=[];}
      if(ranked.length){html+=sys(t(ranked.join(', ')+' — 토론 내용을 반영해 최종 평가했어요.',ranked.join(', ')+' — updated their assessment with the discussion.'));ranked=[];}
      if(noise){html+=sys(t('응답 형식 보정 '+noise+'회 (자동)',noise+' automatic format repair(s)'));noise=0;}
    }
    function open(key,extra){if(cur===key+(extra||''))return;flush();cur=key+(extra||'');html+='<div class="stage-div"><span>'+E(t(STAGES[key][0],STAGES[key][1]))+(extra?E(' · '+t('라운드 '+extra,'round '+extra)):'')+'</span></div>';}
    (run.public_history||[]).forEach(function(m){
      var a=m.response,who=m.requester;
      if(a==='RANK')afterRank=true;
      if(a==='ISSUE')return;   // the agenda card already shows it
      if(NOISE.includes(a)){noise++;return;}
      var key=a==='ESTIMATE'?'interpret':['CANDIDATES','SUPPLEMENT','SUPPLEMENT_FAILED'].includes(a)?'generate':a==='ASSESS'?'assess':a==='RANK'?'rank':
        (afterRank&&['ACCEPT','REJECT','NEEDS_INPUT'].includes(a)&&who!=='hive'&&who!=='pm')?'consent':
        (['PM_OPTIONS','SELECT','REVISE','CONFIRM','AUTO_CONFIRM','APPLIED','END','CLOSE','CONSTRAINT_REVIEW'].includes(a)||who==='pm'||(who==='hive'&&a==='REJECT'))?'decide':
        (SPEECH[a]||a==='INVITE')?'discuss':null;
      if(key)open(key,key==='discuss'?(m.round||1):'');
      if(a==='ASSESS'){assessed.push(label(who));return;}
      if(a==='RANK'){ranked.push(label(who));return;}
      if(who==='hive'){html+='<div class="msg in hive-line"><div class="av hive"></div><div><p>'+E(hiveText(m))+(m.candidate_id?' '+candChip(m.candidate_id):'')+'</p></div></div>';return;}
      if(key==='consent'||a==='AUTO_CONFIRM'){html+='<div class="consent-row"><b>'+E(label(who))+'</b>'+candChip(m.candidate_id)+badge(CONSENT[a])+'<span class="basis">'+E(t('근거: ','Basis: ')+(m.reason||'-'))+'</span></div>';return;}
      if(a==='PASS'){html+=sys(label(who)+' · '+t('추가 의견 없음','no further comment'));return;}
      var sp=SPEECH[a],pm=who==='pm';
      var tag=sp?badge(sp):a==='ESTIMATE'?badge(['견적 변경','Re-estimate','t-cond']):a==='CONSTRAINT_REVIEW'?badge(['제약 검토','Constraint review','t-cond']):pm?badge([{SELECT:'선택',REJECT:'모두 반려',REVISE:'수정 요청',CLOSE:'확인'}[a]||a,{SELECT:'Chose',REJECT:'Rejected all',REVISE:'Revision',CLOSE:'Acknowledged'}[a]||a,'t-flat']):'';
      var text=a==='ESTIMATE'&&lang()==='en'?HIVE_EN.ESTIMATE(m):m.reason;
      html+='<div class="msg in"><div class="av '+(pm?'pm':'proxy')+'">'+E(label(who).slice(0,1))+'</div><div><div class="meta"><b>'+E(label(who))+(pm?'':' · Proxy')+'</b>'+tag+(m.recipient?'<small>→ '+E(label(m.recipient))+'</small>':'')+candChip(m.candidate_id)+'</div><p>'+E(text)+'</p></div></div>';
    });
    flush();
    return html;
  }
  function candidateCard(c,isFinal){
    var number=candNo(c.id);
    var html='<article class="candidate-card candidate-compact" data-card="'+E(c.id)+'"><div class="candidate-row"><div><h3>'+E(t('후보 ','Plan '))+number+' · '+E(planTitle(c.title))+'</h3><span class="candidate-meta">'+Object.keys(c.consents||{}).map(function(pid){var a=c.consents[pid];return E(label(pid))+' '+E({ACCEPT:a.auto_confirmed?t('자동 승인','auto-approved'):t('동의','accept'),REJECT:t('거절','reject'),NEEDS_INPUT:t('확인 필요','to confirm')}[a.action]||a.action);}).join(' · ')+'</span></div><div class="candidate-actions"><button class="btn sm" data-preview="'+E(c.id)+'">'+E(t('보드에서 보기','Show on board'))+'</button>';
    if(isFinal&&run.status==='awaiting_pm_selection')html+=viewerRole==='pm'?'<button class="btn go sm" data-required-role="pm" data-select="'+E(c.id)+'">'+E(t('이 안으로 결정','Choose this plan'))+'</button>':'<button class="btn sm" data-switch-role="pm">'+E(t('PM으로 전환해 결정','Switch to PM to decide'))+'</button>';
    html+='</div></div>';
    if((c.plan_actions||[]).length)html+='<p class="candidate-meta">'+c.plan_actions.map(function(a){return E((state.tasks[a.task]||{}).title||a.task)+' · '+E(a.kind==='defer'?t(a.milestone+'로 이관','deferred to '+a.milestone):a.kind==='omit'?t('선택 검증 생략','optional check skipped'):t('임시 / 최종 단계로 분해','split into interim / final'));}).join(' · ')+'</p>';
    return html+'</article>';
  }
  function paint(){
    var open=new Set(Array.from(feed.querySelectorAll('details[open][data-open]')).map(function(n){return n.dataset.open;}));var atEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<90,scroll=feed.scrollTop;
    if(!booted){feed.innerHTML='<div class="backend-empty">'+E(t('서버에 연결하는 중입니다… 처음 접속이면 서버가 깨어나는 데 1분 정도 걸릴 수 있어요.','Connecting… On a first visit the server may take about a minute to wake up.'))+'</div>';return;}
    if(!run){feed.innerHTML='<div class="backend-empty">'+E(t('무엇이 바뀌었는지 자유롭게 적어 보내세요. LLM이 관련 업무를 찾습니다. Hive가 안건을 열고, 관련 팀원의 Proxy들이 각자의 위임카드로 협의한 뒤 PM에게 계획 1~3개를 올립니다.','Describe what changed; the LLM identifies the relevant task. Hive opens an agenda, the related members\' proxies negotiate with their own delegation cards, and 1–3 plans go to the PM.'))+'</div>';return;}
    var html=feedHTML(),finals=run.final_candidates||[];
    if(run.status==='awaiting_pm_selection'){
      html+='<div class="backend-empty decision-anchor"><strong>'+E(t('PM 결정','PM decision'))+'</strong> · '+E(t('선택하기 전에는 보드에 적용되지 않아요.','Nothing is applied until you choose.'))+'</div>';
      html+='<div class="candidate-list">'+run.candidates.filter(function(c){return finals.includes(c.id);}).map(function(c){return candidateCard(c,true);}).join('')+'</div>';
      var others=run.candidates.filter(function(c){return !finals.includes(c.id);});
      if(others.length)html+='<details data-open="others"><summary>'+E(t('추천에서 빠진 검증 후보 '+others.length+'개','Other verified plans ('+others.length+')'))+'</summary><div class="candidate-list">'+others.map(function(c){return candidateCard(c,false);}).join('')+'</div></details>';
      if(viewerRole==='pm')html+='<div class="candidate-actions"><button class="btn sm" data-pm-action="reject" data-required-role="pm">'+E(t('모두 반려','Reject all'))+'</button><button class="btn sm" data-pm-action="revise" data-required-role="pm">'+E(t('수정 요청','Request revision'))+'</button></div>';
    }
    (state.pending_confirms||[]).forEach(function(c){
      html+='<article class="candidate-card decision-anchor"><h3>'+E(t(label(c.who)+' 본인 확인',label(c.who)+' · confirmation'))+'</h3>';
      if(viewerRole==='person:'+c.who)html+='<div class="candidate-actions"><button class="btn go sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="true">'+E(t('동의','Accept'))+'</button><button class="btn sm" data-required-role="person:'+E(c.who)+'" data-confirm="'+c.id+'" data-ok="false">'+E(t('거절','Reject'))+'</button></div>';
      else html+='<button class="btn sm" data-switch-role="person:'+E(c.who)+'">'+E(t(label(c.who)+'로 전환','Switch to '+label(c.who)))+'</button>';
      html+='</article>';
    });
    if(run.status==='waiting_pm')html+='<article class="candidate-card decision-anchor"><h3>'+E(t('합의된 계획이 없어 PM에게 넘어왔어요','No agreed plan · handed to the PM'))+'</h3><p class="candidate-meta">'+E(t('종료 사유: ','Reason: ')+((run.pm_handoff&&run.pm_handoff.summary&&run.pm_handoff.summary.termination)||run.termination||''))+' · '+E(t('미합의 변경은 적용하지 않아요.','Unagreed changes are not applied.'))+'</p>'+(viewerRole==='pm'?'<button class="btn sm" data-required-role="pm" data-close-run>'+E(t('확인 · 현재 배분 유지','Acknowledge · keep current allocation'))+'</button>':'<button class="btn sm" data-switch-role="pm">'+E(t('PM으로 전환','Switch to PM'))+'</button>')+'</article>';
    if(run.clarification)html+='<div class="backend-error" role="status">'+E(run.clarification)+'</div>';
    if(run.status==='done'&&!run.clarification)html+='<div class="backend-empty">'+E(run.termination==='applied'?t('선택한 계획을 최종 검증 후 보드에 적용했어요.','The chosen plan passed final checks and was applied.'):t('현재 배분을 유지했어요.','The current allocation was kept.'))+' '+E(t('다음 이슈를 보내거나 다음 날로 넘어가세요.','Send the next issue or move to the next day.'))+'</div>';
    feed.innerHTML=html;
    feed.querySelectorAll('details[data-open]').forEach(function(d){d.open=open.has(d.dataset.open);});
    feed.scrollTop=atEnd?feed.scrollHeight:scroll;
  }

  /* ---------- run loop ---------- */
  var looping=false;
  async function loop(){
    if(looping)return;looping=true;var failures=0;
    try{
      while(automatic&&run&&run.status==='running'){
        busy=true;status();
        try{run=await api('/runs/'+run.id+'/advance',{},{retry:2});preview=null;await refresh(false);failures=0;clearError();}
        catch(err){failures++;error(err);if(failures>=3)automatic=false;else await sleep(2000*failures);}
        finally{busy=false;status();}
        if(!automatic)break;await sleep(100);
      }
    }finally{looping=false;automatic=false;}
    await afterRound();status();
  }
  // When a negotiation round finishes, time moves on: advance one working day (until the milestone deadline).
  var dayDoneFor=null;
  async function afterRound(){
    if(!run||run.status!=='done'||run.termination==='issue_needs_clarification'||dayDoneFor===run.id||!state||state.now>=state.week_end)return;
    dayDoneFor=run.id;
    try{var r=await api('/day/next',{});await refresh(false);V.toast(t('하루가 지났어요 · 완료: ','A day passed · finished: ')+(r.finished.join(', ')||t('없음','none')));}catch(err){error(err);}
  }

  /* ---------- events ---------- */
  document.getElementById('form').addEventListener('submit',function(e){e.preventDefault();var issue=input.value.trim();if(!issue)return;act(async function(){
    var shownDemo=state&&state.demo&&state.demo.id;var latest=await api('/state');
    if((latest.demo&&latest.demo.id)!==shownDemo){refs=[];await refresh(true);throw new Error(t('시나리오가 변경되어 화면을 새로 고쳤습니다. 내용을 확인한 뒤 다시 보내 주세요.','The scenario changed. The screen was refreshed; review your issue and send again.'));}
    run=await api('/candidate-runs',{issue:issueWithRefs(issue)});dayDoneFor=null;
    if(run.termination!=='issue_needs_clarification'){input.value='';input.dispatchEvent(new Event('input'));refs=[];}
    preview=null;await refresh(false);automatic=run.status==='running';}).then(loop);});
  document.getElementById('continue-run').onclick=function(){automatic=true;loop();};
  document.getElementById('pause-run').onclick=function(){automatic=false;status();};
  document.getElementById('current-board').onclick=function(){preview=null;if(state)V.render(state,null,false);};
  document.getElementById('next-day').onclick=function(){act(async function(){var r=await api('/day/next',{});await refresh(false);V.toast(t('하루가 지났어요 · 완료: ','A day passed · finished: ')+(r.finished.join(', ')||t('없음','none')));});};
  document.getElementById('demo-select').onchange=function(e){automatic=false;act(async function(){await api('/demo/select',{demo:e.target.value});run=null;preview=null;refs=[];await refresh(true);});};
  function syncHeight(){document.querySelector('.app').style.height=window.innerWidth>900?'calc(100dvh - '+Math.ceil(top.getBoundingClientRect().height)+'px)':'auto';}
  window.addEventListener('resize',syncHeight);
  async function switchRole(role){viewerRole=role;try{localStorage.setItem('pb-viewer-role',role);}catch(err){}await refresh(false);}
  document.getElementById('viewer-select').onchange=function(e){act(function(){return switchRole(e.target.value);});};
  document.getElementById('reset').onclick=function(){if(!window.confirm(t('현재 시나리오를 처음 상태로 되돌릴까요?','Reset the current scenario to its initial state?')))return;automatic=false;act(async function(){await api('/reset',{});run=null;preview=null;refs=[];await refresh(true);});};
  feed.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||busy||!run)return;
    if(b.dataset.switchRole){act(function(){return switchRole(b.dataset.switchRole);});return;}
    if(b.dataset.preview){preview=run.candidates.find(function(c){return c.id===b.dataset.preview;});if(preview)V.render(state,preview.board,true);return;}
    act(async function(){
      if(b.dataset.select){var c=run.candidates.find(function(c){return c.id===b.dataset.select;});run=await api('/runs/'+run.id+'/pm-selection',{action:'select',candidate_id:c.id,plan_hash:c.plan_hash});preview=null;await refresh(false);}
      else if(b.dataset.pmAction){var reason=window.prompt(t('반려/수정 요청 이유를 적어 주세요','Give a reason for rejecting / requesting revision'));if(!reason)return;run=await api('/runs/'+run.id+'/pm-selection',{action:b.dataset.pmAction,reason:reason});await refresh(false);if(run.status==='running')automatic=true;}
      else if(b.dataset.confirm){await api('/confirmations/'+b.dataset.confirm,{ok:b.dataset.ok==='true'});run=await api('/runs/'+run.id);await refresh(false);}
      else if(b.hasAttribute('data-close-run')){run=await api('/runs/'+run.id+'/close',{});await refresh(false);}
    }).then(function(){return automatic?loop():afterRound();});
  });
  document.querySelector('.langs').addEventListener('click',function(e){var b=e.target.closest('[data-lang]');if(b){setLanguage(b.dataset.lang);try{localStorage.setItem('pb-lang',b.dataset.lang);}catch(err){}}});
  function setTheme(mode){mode=mode==='light'?'light':'dark';V.theme(mode);document.querySelectorAll('#themes [data-mode]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.mode===mode));});try{localStorage.setItem('pb-theme',mode);}catch(err){}}
  var savedTheme;try{savedTheme=localStorage.getItem('pb-theme');}catch(err){}
  setTheme(savedTheme||document.documentElement.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'));
  document.getElementById('themes').addEventListener('click',function(e){var b=e.target.closest('[data-mode]');if(b)setTheme(b.dataset.mode);});

  /* ---------- boot: keep retrying until the server answers ---------- */
  status();paint();
  (async function boot(){
    for(var attempt=0;attempt<40;attempt++){
      try{runtime=await api('/runtime');await refresh(true);clearError();
        if(run&&run.status==='running'){automatic=true;loop();}   // resume a run left mid-way (e.g. page reload)
        return;}
      catch(err){error(new Error(t('서버 연결 재시도 중… ','Retrying the server connection… ')+'('+(attempt+1)+')'));await sleep(Math.min(8000,1500+attempt*1000));}
    }
  })();
})();
