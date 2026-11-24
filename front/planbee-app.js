/* Persistent API integration for the Plan Bee channel + milestone board. */
(function () {
  'use strict';
  var V=window.PlanBeeView, E=V.esc, state=null, run=null, runtime={}, busy=false, automatic=false, preview=null, refs=[], booted=false;
  var datedDraft=null;
  var viewerRole='pm';   // the PM is the only real user; teammates are represented by their cards
  var reporterRole='pm';try{reporterRole=localStorage.getItem('pb-reporter-role')||'pm';}catch(err){}
  var runHistory=[];
  var feed=document.getElementById('feed'), input=document.getElementById('change-input'), top=document.querySelector('.top');

  /* ---------- language ---------- */
  function lang(){return document.documentElement.getAttribute('data-lang')==='en'?'en':'ko';}
  function t(ko,en){return lang()==='en'?en:ko;}
  function roleName(r){return lang()==='en'&&window.PlanBeeRoleEn?window.PlanBeeRoleEn(r):r;}
  function scenarioTitle(x){return lang()==='en'&&window.PlanBeeTitleEn?window.PlanBeeTitleEn(x):x;}
  // Server-made Hive/system messages arrive in Korean with a stable action code: translate by code.
  var HIVE_EN={
    DEMO_AUTO_CONSENT:function(){return 'T4 demo: the algorithm auto-accepts member consent after one discussion round. Only the PM chooses the plan; Hive constraints still apply.';},
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
  /* a plan's name says what it does: whose work moves where, what is deferred or moved */
  function planHeadline(r,c){
    if(!c)return '';var g=state&&state.glossary_en||{},L=function(x){return lang()==='en'&&g[x]?g[x]:x;},owner=r.who||(state.tasks[r.task]||{}).who;
    var tt=function(id){var x=state.tasks[id];return x?L(x.title).split(' · ')[0]:id;};
    var bits=(c.allocations||[]).filter(function(a){return a.who&&a.who!==owner;}).map(function(a){return L(a.title||a.what||'')+' → '+label(a.who);});
    (c.plan_actions||[]).forEach(function(a){bits.push(tt(a.task)+(a.kind==='defer'?t(' 다음 스프린트로',' to next sprint'):a.kind==='omit'?t(' 제외',' dropped'):t(' 나눠 재구성',' restructured')));});
    (c.schedule_changes||[]).forEach(function(x){bits.push(tt(x.task)+' '+slot(x.start)+t('로',''));});
    return bits.length?bits.join(' · '):planTitle(c.title);}
  function hiveText(m){return msgText(m);}
  /* A message the server wrote in both languages never goes through translation. */
  function msgText(m){return lang()==='en'&&m&&m.reason_en?m.reason_en:conversationText(m&&m.reason);}

  var englishCache=new Map(),translationFailures=new Set(),translating=false;
  function conversationText(text){text=String(text||'');if(lang()!=='en'||!/[가-힣]/.test(text))return text;return englishCache.get(text)||(translationFailures.has(text)?'Translation unavailable.':'Translating…');}
  function translationItems(){
    if(!run)return [];
    var items=[{id:'issue',text:run.issue}];
    if(run.clarification)items.push({id:'clarification',text:run.clarification});
    (run.public_history||[]).forEach(function(m,i){if(!m.reason_en&&!['ISSUE','ASSESS','RANK','PASS'].includes(m.response)&&!NOISE.includes(m.response))items.push({id:'history:'+i,text:m.reason});});
    return items.filter(function(x){return x.text&&/[가-힣]/.test(x.text);});
  }
  function translationStatus(){
    var box=document.getElementById('translation-status');if(!box)return;
    var hasFailures=translationItems().some(function(x){return translationFailures.has(x.text);});
    box.hidden=lang()!=='en'||!run||(!translating&&!hasFailures);
    box.textContent=translating?'Translating conversation…':'Some messages could not be translated. ';
    if(!translating&&hasFailures){var retry=document.createElement('button');retry.type='button';retry.className='btn sm';retry.textContent='Retry translation';retry.onclick=function(){translationFailures.clear();paint();};box.append(retry);}
  }
  async function translateConversation(){
    translationStatus();if(lang()!=='en'||!run||translating)return;
    var seen=new Set(),count=0,batch=translationItems().filter(function(x){if(englishCache.has(x.text)||translationFailures.has(x.text)||seen.has(x.text))return false;seen.add(x.text);return true;}).filter(function(x){if(count+x.text.length>12000)return false;count+=x.text.length;return true;}).slice(0,12);
    if(!batch.length)return;
    var rid=run.id;translating=true;translationStatus();
    try{var response=await api('/runs/'+rid+'/translations',{keys:batch.map(function(x){return x.id;})});response.items.forEach(function(x){englishCache.set(x.source,x.text);});}
    catch(err){batch.forEach(function(x){translationFailures.add(x.text);});}
    finally{translating=false;if(lang()==='en')paint();translationStatus();if(lang()==='en')translateConversation();}
  }

  function seedGlossary(s){var g=s&&s.glossary_en;if(!g)return;Object.keys(g).forEach(function(k){englishCache.set(k,g[k]);});if(window.PlanBeeEnglish&&window.PlanBeeEnglish.seed)window.PlanBeeEnglish.seed(g);}

  /* ---------- chrome ---------- */
  var tools=document.createElement('div');tools.className='backend-tools';
  tools.innerHTML='<label><span data-t="scenario"></span> <select id="demo-select"></select></label>';
  (top.querySelector('.sp')||top.lastChild).after(tools);   // selects sit in the header, right side
  var stage=document.createElement('div');stage.className='backend-stage';stage.setAttribute('role','status');stage.id='backend-stage';
  document.querySelector('.chan .pane-h').after(stage);
  var translationBox=document.createElement('div');translationBox.id='translation-status';translationBox.className='translation-status';translationBox.setAttribute('role','status');translationBox.hidden=true;stage.after(translationBox);
  var controls=document.createElement('div');controls.className='backend-controls';
  controls.innerHTML='<button id="continue-run" class="btn sm" data-t="continue"></button><button id="pause-run" class="btn sm" data-t="pause"></button><button id="current-board" class="btn sm" data-t="currentBoard"></button><button id="previous-day" class="btn sm" data-t="previousDay"></button><button id="next-day" class="btn sm" data-t="nextDay"></button>';
  var statusRow=document.createElement('div');statusRow.className='chat-status';stage.before(statusRow);statusRow.append(stage,controls);
  /* 'back to actual board' belongs to the board it restores */
  (function(){var cb=controls.querySelector('#current-board'),bh=document.querySelector('.board .pane-h');if(cb&&bh){cb.classList.add('board-back');bh.querySelector('h2').after(cb);}})();
  var daily=document.createElement('details');daily.className='daily-issues';daily.id='daily-issues';daily.hidden=true;controls.after(daily);
  daily.addEventListener('click',function(e){var b=e.target.closest('[data-daily-issue]');if(!b||busy)return;var event=state.demo.timeline.events.find(function(x){return x.id===b.dataset.dailyIssue;});if(!event||!event.available)return;if(lang()==='en'&&window.PlanBeeEnglish){window.PlanBeeEnglish.resolve([event.text]).then(function(values){setDraft(values[0]);datedDraft={text:values[0],source:event.text};input.focus();resizeInput();}).catch(function(){error(new Error('Example translation unavailable.'));});}else{setDraft(event.text);input.focus();resizeInput();}});
  var UI={scenario:['시나리오','Scenario'],myRole:['보고자','Reported by'],continue:['계속 진행','Continue'],pause:['일시정지','Pause'],currentBoard:['실제 보드로 돌아가기','Back to actual board'],previousDay:['‹ 이전 날','‹ Prev day'],nextDay:['다음 날 ›','Next day ›']};
  function defaultPlaceholder(){return t('무엇이 바뀌었나요? 업무를 고르지 않고 자유롭게 적어 주세요.','What changed? Describe it freely; the team will identify the task.');}
  function helpText(){return t('Ctrl / ⌘ + Enter 보내기 · 빈 입력창에서 Tab 예시 입력','Ctrl / ⌘ + Enter: send · Tab in an empty box: insert example');}
  function chrome(){
    document.querySelectorAll('[data-t]').forEach(function(n){var v=UI[n.dataset.t];if(v)n.textContent=t(v[0],v[1]);});
    document.getElementById('demo-select').setAttribute('aria-label',t('시나리오','Scenario'));
    document.querySelector('.chan .pane-h h2').textContent=t('# 팀 협의','# Team negotiation');
    paintSugg();
    input.setAttribute('aria-label',t('업무 변경 이슈','Task change issue'));
  }
  input.setAttribute('aria-describedby','composer-help');
  function resizeInput(){input.style.height='auto';input.style.height=input.value?Math.min(240,Math.max(72,input.scrollHeight))+'px':'72px';}
  function setDraft(value){datedDraft=null;var replacement=input.cloneNode(false);replacement.value=value;input.replaceWith(replacement);input=replacement;resizeInput();}
  var help=document.createElement('div');help.id='composer-help';help.className='composer-help';document.getElementById('form').after(help);
  (function(){var form=document.getElementById('form'),quotes=document.getElementById('quotes'),box=document.createElement('div');box.className='cbox';form.before(box);box.append(quotes,form);
    var hint=document.createElement('span');hint.className='cbox-hint';hint.id='cbox-hint';form.insertBefore(hint,form.lastElementChild);})();
  function setLanguage(code){
    code=code==='en'?'en':'ko';V.language(code);
    document.querySelectorAll('.langs [data-lang]').forEach(function(x){x.setAttribute('aria-pressed',String(x.dataset.lang===code));});
    if(state)draw();else{chrome();input.placeholder=defaultPlaceholder();help.textContent=helpText();}
    document.dispatchEvent(new CustomEvent('pb-language'));
  }
  chrome();input.placeholder=defaultPlaceholder();help.textContent=helpText();
  try{var savedLang=localStorage.getItem('pb-lang');if(savedLang==='en'||savedLang==='ko')setLanguage(savedLang);}catch(err){}
  /* Language is chosen once when entering; it cannot change mid-session (keeps the conversation in one language). */
  (function(){
    var chosen=null;try{chosen=sessionStorage.getItem('pb-lang-chosen');}catch(err){}
    var q=new URLSearchParams(location.search).get('lang');if(q==='ko'||q==='en'){chosen=q;}
    function pick(code){setLanguage(code);try{localStorage.setItem('pb-lang',code);sessionStorage.setItem('pb-lang-chosen',code);}catch(err){}}
    if(chosen){pick(chosen);return;}
    var d=document.createElement('dialog');d.id='lang-gate';d.className='lang-gate';d.setAttribute('data-no-translate','');d.setAttribute('aria-labelledby','lg-t');
    d.innerHTML='<div class="lg-in"><img src="/front/planbee-logo.png" alt="" width="56" height="56"><h2 id="lg-t">Plan Bee</h2><p>사용할 언어를 고르세요 · Choose a language</p><div class="lg-opts"><button type="button" data-pick="ko"><b>한국어</b><span>대화와 보드를 한국어로</span></button><button type="button" data-pick="en"><b>English</b><span>Conversation and board in English</span></button></div><small>들어온 뒤에는 바꿀 수 없어요 · Fixed for this session</small></div>';
    document.body.append(d);d.addEventListener('cancel',function(e){e.preventDefault();});
    d.addEventListener('click',function(e){var b=e.target.closest('[data-pick]');if(!b)return;pick(b.dataset.pick);d.close();d.remove();});
    d.showModal();var cur=lang();var f=d.querySelector('[data-pick="'+cur+'"]');if(f)f.focus();
  })();
  document.getElementById('form').addEventListener('keydown',function(e){
    if(e.target!==input)return;
    if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)&&!e.isComposing){e.preventDefault();this.requestSubmit();return;}
    if(e.key==='Tab'&&!e.isComposing&&BLANK.test(input.value)){BLANK.lastIndex=0;e.preventDefault();selectBlank(e.shiftKey?input.selectionStart:input.selectionEnd,e.shiftKey);return;}
    var example=state&&state.demo&&state.demo.issue_example;
    if(e.key==='Tab'&&!e.shiftKey&&!e.isComposing&&!input.value.trim()&&example){
      e.preventDefault();
      if(lang()==='en'&&window.PlanBeeEnglish){var role=viewerRole,demo=state.demo.id;window.PlanBeeEnglish.resolve([example]).then(function(values){if(lang()!=='en'||viewerRole!==role||state.demo.id!==demo||input.value)return;setDraft(values[0]);datedDraft={text:values[0],source:example};input.focus();input.setSelectionRange(input.value.length,input.value.length);status();}).catch(function(){error(new Error('Example translation unavailable. Please enter your issue in English.'));});}
      else{setDraft(example);input.focus();input.setSelectionRange(example.length,example.length);status();}
    }
  });
  document.getElementById('form').addEventListener('input',function(e){if(e.target===input)resizeInput();});
  (document.querySelector('.sprint')||{}).textContent=t('서버 연결 중','Connecting to server');
  var tip=document.getElementById('tip');if(tip)tip.hidden=true;
  function label(pid){var p=state&&state.people.find(function(p){return p.id===pid;});return p?p.name:pid==='hive'?'Hive':pid==='pm'?'PM':pid||t('팀','Team');}
  function fmt(n){return Number(Number(n).toFixed(2));}
  function terminationLabel(value){var labels={reverted:['보고 전으로 되돌림','Reverted to before the report'],pm_stopped:['PM이 중단','Stopped by the PM'],not_a_change:['일정 변경 없음 · 답변만','No schedule change · answered'],search_budget_exhausted:['후보 탐색 한도 도달 · 불가능 판정 아님','Search budget reached · infeasibility not proven'],search_exhausted:['현재 허용 구조·시간 탐색에서 검증 후보 없음','No validated plan in the explored structures and slots'],no_consented_candidate:['검증 후보는 있으나 당사자 합의안 없음','Validated plans exist, but none has participant agreement']};var x=labels[value];return x?t(x[0],x[1]):value;}

  /* ---------- robust API ---------- */
  function sleep(ms){return new Promise(function(r){setTimeout(r,ms);});}
  async function api(path,body,opts){
    opts=opts||{};var tries=body===undefined?3:(opts.retry||1),last;
    for(var i=0;i<tries;i++){
      var ctl=new AbortController(),timer=setTimeout(function(){ctl.abort();},opts.timeout||(body===undefined?20000:180000));
      try{
        var res=await fetch(path,{method:body===undefined?'GET':'POST',signal:ctl.signal,cache:'no-store',headers:{'Content-Type':'application/json','X-Planbee-Role':opts.role||viewerRole},body:body===undefined?undefined:JSON.stringify(body)});
        var text=await res.text(),result=null;try{result=text?JSON.parse(text):{};}catch(err){result=null;}
        if(res.ok&&result)return result;
        var detail=result&&result.detail;
        last=new Error(typeof detail==='string'?detail:detail&&detail.message?detail.message:detail?JSON.stringify(detail):res.status>=500?t('서버가 준비 중이거나 일시 오류입니다 ('+res.status+'). 잠시 후 다시 시도합니다.','The server is starting or had a temporary error ('+res.status+'). Retrying shortly.'):t('요청 실패 ('+res.status+')','Request failed ('+res.status+')'));
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
  async function act(fn){if(busy)return;busy=true;clearError();status();try{await fn();}catch(err){automatic=false;if(pendingIssue){input.value=pendingIssue.text;pendingIssue=null;paint();}error(err);}finally{busy=false;status();document.querySelectorAll('.btn.loading').forEach(function(b){b.classList.remove('loading');});}}

  /* ---------- status line ---------- */
  var ACTIVE=['running','awaiting_pm_selection','waiting_confirm','waiting_pm'];
  function status(){
    var names={candidate_generate:t('후보 생성·검증','Generating and verifying plans'),candidate_assess:t('토론할 계획 고르기','Choosing plans to discuss'),candidate_discuss:t('공개 토론','Open discussion'),candidate_rank:t('토론 집계','Tallying the discussion'),candidate_pm:t('PM 결정','PM decision'),candidate_confirm:t('본인 확인','Personal confirmation'),candidate_failed:t('PM 검토','PM review'),done:t('완료','Done')};
    var budget=run&&run.llm_budget,active=!!(run&&ACTIVE.includes(run.status));
    var line=!booted?t('서버에 연결하는 중…','Connecting to the server…'):active?(names[run.step]||run.step)+(run.round?' · '+t('라운드 '+run.round,'round '+run.round):'')+(run.assessment_progress&&/assess|rank/.test(run.step)?' · '+run.assessment_progress.completed+'/'+run.assessment_progress.total:''):t('새 이슈를 기다리는 중','Waiting for a new issue');
    var next=!booted||!active?'':run.status==='awaiting_pm_selection'?t('추천 계획을 비교하고 PM이 결정하세요.','Compare the recommended plans; the PM decides.'):run.status==='waiting_pm'&&run.termination==='needs_rule_relaxation'?t('규칙 안에서 풀리지 않아요. 풀 규칙 하나를 고르세요.','Nothing works inside the rules. Pick one rule to relax.'):run.status==='waiting_pm'?t('PM이 상황을 확인하고 다음 조치를 정하세요.','The PM reviews the situation and decides the next step.'):run.status==='waiting_confirm'?t('본인 확인 대기 중입니다.','Waiting for personal confirmation.'):automatic?t('팀이 협의하고 있습니다…','The team is negotiating…'):t('일시정지 상태입니다. 계속 진행을 누르세요.','Paused. Press Continue.');
    stage.innerHTML='<strong>'+E(line)+'</strong>'+(busy?'<span class="stage-busy"> · '+E(t('처리 중','working'))+'</span>':'')+'<span class="stage-meta">'+E(((run&&active&&run.proxy_mode)||(state&&state.demo&&state.demo.llm_mode)||runtime.llm_mode||'')==='mock'?t('카드 규칙 재현','card-rule replay'):'live')+(budget&&active?' · '+E(t('호출 ','calls '))+budget.used+'/'+budget.max:'')+'</span>'+(next?'<div class="next-action">'+E(next)+(run&&['awaiting_pm_selection','waiting_pm'].includes(run.status)?' <button type="button" class="btn sm" id="jump-decision">'+E(t('바로 보기 ↓','Jump to it ↓'))+'</button>':'')+'</div>':'');
    var jump=document.getElementById('jump-decision');if(jump)jump.onclick=function(){var target=feed.querySelector('.decision-anchor');if(target)target.scrollIntoView({behavior:'smooth',block:'start'});};
    if(state&&state.demo.id==='m4_t4_composite')stage.querySelector('.stage-meta').insertAdjacentHTML('afterend','<span class="stage-tag" title="'+E(t('T4 데모 · 개인 동의 자동 수락 · PM만 최종 선택','T4 demo · algorithmic member consent · PM decides'))+'">'+E(t('시연 설정','Demo setting'))+'</span>');
    if(state&&state.demo.id==='m4_t6_game_demo'&&(runtime.auto_confirm||runtime.demo_force_agree))stage.querySelector('.stage-meta').insertAdjacentHTML('afterend','<span class="stage-tag" title="'+E(t('T6 시연 · 모든 역할 무조건 동의 · PM 최종 선택 필요','T6 demo · every role unconditionally agrees · PM makes the final choice'))+'">'+E(t('시연 · 모두 동의','Demo · all agree'))+'</span>');
    stage.setAttribute('aria-busy',busy?'true':'false');
    var demoRecovery=run&&runtime.demo_force_agree&&run.status==='waiting_pm'&&run.termination==='no_consented_candidate'&&run.candidates.length;
    document.getElementById('continue-run').disabled=busy||!run||(run.status!=='running'&&!demoRecovery)||automatic;
    document.getElementById('pause-run').disabled=!automatic;
    daily.querySelectorAll('[data-daily-issue]').forEach(function(button){var event=state&&state.demo.timeline&&state.demo.timeline.events.find(function(x){return x.id===button.dataset.dailyIssue;});button.disabled=busy||!event||!event.available;});
    var ds=document.getElementById('demo-select');ds.disabled=busy||!booted;if(state&&state.demo&&!busy)ds.value=state.demo.id;
    document.getElementById('current-board').disabled=!preview;
    document.getElementById('previous-day').disabled=busy||!booted||active||!state||!state.can_previous_day;
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
    var all=null;if(loadRun||(run&&!ACTIVE.includes(run.status)&&!(runHistory[0]&&runHistory[0].id===run.id&&runHistory[0].status===run.status)))all=await api('/candidate-runs');
    var s=await api('/state'),r=loadRun?((all||[])[0]||null):run;
    if(all)runHistory=all;
    if(my!==refreshSeq)return;   // a newer refresh already drew
    if(state&&state.demo&&s.demo&&state.demo.id!==s.demo.id)refs=[];
    if(state&&state.demo&&s.demo&&state.demo.id!==s.demo.id){setDraft('');refs=[];preview=null;}
    runtime.demo_force_agree=s.demo.id==='m4_t6_game_demo'&&runtime.t6_force_agree_enabled;
    state=s;if(loadRun)run=r;booted=true;seedGlossary(s);draw();
  }
  function draw(){
    chrome();
    state.viewer_role='pm';
    (document.querySelector('.sprint')||{}).textContent=scenarioTitle(state.demo.title)+' · '+(lang()==='en'?'day '+fmt(state.now):state.now_label);
    var dm=state&&state.demo&&state.demo.llm_mode,sm=runtime.llm_mode||'';var bd=document.querySelector('.badge');
    bd.textContent=dm==='mock'?'MOCK':dm==='live'&&sm!=='live'?t('LIVE 필요','LIVE NEEDED'):sm.toUpperCase();bd.classList.toggle('warn',dm==='live'&&sm!=='live');
    bd.title=dm==='mock'?t('이 시나리오는 저장된 카드 규칙으로 재현합니다 (LLM 호출 없음).','This scenario replays with stored card rules (no LLM calls).'):dm==='live'?t('이 시나리오는 실제 LLM으로 보고를 읽고 토론합니다.','This scenario reads the report and discusses with the live model.'):'';
    var demo=document.getElementById('demo-select');demo.innerHTML=state.demo.catalog.map(function(d){return '<option value="'+E(d.id)+'"'+(d.id===state.demo.id?' selected':'')+'>'+E(scenarioTitle(d.title))+'</option>';}).join('');
    paintDailyIssues();
    var src=state.tasks[state.demo.source_task];
    var example=state.demo.issue_example;input.placeholder=example?(example.length>110?example.slice(0,110)+'…':example):defaultPlaceholder();
    paintRefs();
    window.PlanBeeFocus=run&&run.task&&run.status!=='done'?[run.task]:[];
    V.render(state,preview&&preview.board,!!preview);paint();status();syncHeight();
  }

  function paintSugg(){
    var el=document.getElementById('sugg');if(!el)return;if(!state){el.innerHTML='';return;}
    var tps=state.demo.templates;el.classList.toggle('has-tpl',!!(tps&&tps.length));if(tps&&tps.length){var g=state.glossary_en||{};
      el.innerHTML='<span class="sl">'+E(t('문장 틀','Templates'))+'</span>'+tps.map(function(x){var tx=lang()==='en'&&g[x.text]?g[x.text]:x.text,tg=lang()==='en'&&g[x.tag]?g[x.tag]:x.tag;return '<button type="button" class="tpl" data-template="1" data-text="'+E(tx)+'" title="'+E(tx)+'">'+E(tg)+'</button>';}).join('')+
        '<span class="tpl-hint">'+E(t('[빈칸]을 고르면 선택지가 나와요 · Tab으로 다음 빈칸 · 보드에서 사람·업무를 끌어와도 돼요','Pick a [blank] to see its choices · Tab for the next one · or drag a person or task from the board'))+'</span>';return;}
    var tl=state.demo.timeline,items=tl?tl.events.filter(function(e){return e.available;}).map(function(e){return {id:e.id,tag:t('오늘','Today'),title:e.title,text:e.text};}):(state.demo.issue_example?(function(){var ex=String(state.demo.issue_example);if(lang()==='en'&&englishCache.has(ex))ex=englishCache.get(ex);return [{id:'',tag:t('예시','Example'),title:ex.slice(0,46)+(ex.length>46?'…':''),text:ex}];})():[]);
    el.innerHTML=items.length?'<span class="sl">'+E(t('예시','Try'))+'</span>'+items.map(function(x){return '<button type="button" data-sugg="'+E(x.id)+'" data-text="'+E(x.text)+'"><em>'+E(x.tag)+'</em>'+E(x.title.replace(/^[^·]*·\s*/,''))+'</button>';}).join(''):'';
  }
  /* ---------- fill-in templates: [blanks] in the composer ---------- */
  var BLANK=/\[[^\]\n]{1,24}\]/g;
  function selectBlank(from,back){var v=input.value,m,all=[];BLANK.lastIndex=0;while((m=BLANK.exec(v)))all.push([m.index,m.index+m[0].length]);if(!all.length)return false;
    var pick=back?all.filter(function(x){return x[1]<=from;}).pop()||all[all.length-1]:all.find(function(x){return x[0]>=from;})||all[0];
    input.focus();input.setSelectionRange(pick[0],pick[1]);setTimeout(paintPick,0);return true;}
  /* the selected [blank] offers its valid choices as one-click chips (people, tasks, half-days, amounts) */
  var pick=document.createElement('div');pick.id='blank-pick';pick.className='blank-pick';pick.hidden=true;document.getElementById('sugg').after(pick);
  var DAYS_KO=['월','화','수','목','금'],DAYS_EN=['Mon','Tue','Wed','Thu','Fri'],DAYS_FULL_EN=['Monday','Tuesday','Wednesday','Thursday','Friday'];
  function blankChoices(b){
    if(!state)return [];var now=state.now||0,end=state.week_end||5,out=[];
    if(/사람|person/i.test(b))return state.people.map(function(p){return {label:p.name,ref:['p',p.id]};});
    if(/업무|task/i.test(b)){   // the person already chosen in this sentence comes first
      var who=(refs.find(function(r){return r.type==='p';})||{}).id;
      return Object.values(state.tasks).filter(function(x){return !x.cut&&x.kind!=='done'&&x.kind!=='milestone'&&x.d>0;})
        .sort(function(a,c){return ((a.who===who)?0:1)-((c.who===who)?0:1)||a.s-c.s;}).map(function(x){return {label:x.title+(who&&x.who===who?'':''),ref:['t',x.id],mine:who&&x.who===who};});}
    if(/오전\/오후|AM\/PM/i.test(b)){for(var x=Math.ceil(now*2-1e-9)/2;x<end-1e-9;x+=.5){var d=Math.floor(x+1e-9)%5,pm=x-Math.floor(x+1e-9)>=.5;
        out.push({label:t(DAYS_KO[d]+(pm?' 오후':' 오전'),DAYS_EN[d]+(pm?' PM':' AM')),value:t(DAYS_KO[d]+'요일 '+(pm?'오후':'오전'),DAYS_FULL_EN[d]+(pm?' afternoon':' morning'))});}return out;}
    if(/^\[(요일|day)\]$/i.test(b)){for(var k=Math.ceil(now-1e-9);k<Math.ceil(end-1e-9);k++)out.push({label:t(DAYS_KO[k%5],DAYS_EN[k%5]),value:t(DAYS_KO[k%5]+'요일',DAYS_FULL_EN[k%5])});return out;}
    if(/반나절|half/i.test(b))return [{label:t('반나절','half a day'),value:t('반나절','half a day')},{label:t('하루','a day'),value:t('하루','a day')},{label:t('이틀','two days'),value:t('이틀','two days')}];
    return [];}
  function paintPick(){
    var on=blankSelected(),b=on?input.value.slice(input.selectionStart,input.selectionEnd):'',ch=on?blankChoices(b):[];
    pick.hidden=!ch.length;if(!ch.length){pick.innerHTML='';return;}
    pick.innerHTML='<span class="sl">'+E(b)+'</span>'+ch.map(function(c,i){return '<button type="button" data-choice="'+i+'"'+(c.mine?' class="mine"':'')+'>'+E(c.label)+'</button>';}).join('');
    pick._choices=ch;}
  pick.addEventListener('mousedown',function(e){e.preventDefault();});   // keep the blank selected
  pick.addEventListener('click',function(e){var b=e.target.closest('[data-choice]');if(!b||busy)return;var c=pick._choices[Number(b.dataset.choice)];if(!c)return;
    if(c.ref){window.PlanBeeApp.quote(c.ref[0],c.ref[1]);}
    else if(blankSelected()){var a=input.selectionStart;input.setRangeText(c.value,a,input.selectionEnd,'end');resizeInput();selectBlank(a+c.value.length);}
    paintPick();status();});
  ['click','keyup','focus','input'].forEach(function(ev){document.getElementById('form').addEventListener(ev,function(e){if(e.target===input)setTimeout(paintPick,0);},true);});
  function blankSelected(){var a=input.selectionStart,z=input.selectionEnd,v=input.value.slice(a,z);return z>a&&/^\[[^\]\n]{1,24}\]$/.test(v);}
  // a quoted person fills a [사람]/[person] blank, a task a [업무]/[task] blank: the selected one if it fits, else the first that fits
  var KIND={p:/^\[(사람|person)\]$/i,t:/^\[(업무|task)\]$/i};
  function fillBlank(type,text){var re=KIND[type];if(!re)return false;var v=input.value,a=input.selectionStart,z=input.selectionEnd,m;
    if(!(z>a&&re.test(v.slice(a,z)))){a=-1;BLANK.lastIndex=0;while((m=BLANK.exec(v))){if(re.test(m[0])){a=m.index;z=a+m[0].length;break;}}BLANK.lastIndex=0;if(a<0)return false;}
    input.setRangeText(text,a,z,'end');resizeInput();status();selectBlank(a+text.length);return true;}
  document.getElementById('sugg').addEventListener('click',function(e){var tp=e.target.closest('[data-template]');if(tp&&!busy){refs=[];paintRefs();setDraft(tp.dataset.text);resizeInput();selectBlank(0);status();return;}
    var b=e.target.closest('[data-text]');if(!b||busy)return;var text=b.dataset.text;
    if(lang()==='en'&&window.PlanBeeEnglish){window.PlanBeeEnglish.resolve([text]).then(function(v){setDraft(v[0]);datedDraft={text:v[0],source:text};input.focus();resizeInput();}).catch(function(){error(new Error('Example translation unavailable.'));});}
    else{setDraft(text);input.focus();resizeInput();}});
  function paintDailyIssues(){
    paintSugg();
    var timeline=state.demo.timeline;daily.hidden=true;if(!timeline)return;
    var available=timeline.events.filter(function(e){return e.available;}),history=timeline.runs||[];
    daily.innerHTML='<summary>'+E(t('오늘 입력 가능한 이슈 '+available.length+'개 · 누적 협상 '+history.length+'회','Issues available today: '+available.length+' · negotiations: '+history.length))+'</summary><div class="daily-content">'+timeline.events.map(function(e){return '<div class="daily-row"><button type="button" class="btn sm" data-daily-issue="'+E(e.id)+'"'+(!e.available||busy?' disabled':'')+'>'+E(e.title)+'</button><small>'+E(e.available?t('예시만 입력 · 보내기를 눌러 실행','Insert example only · press Send to start'):e.reason)+'</small></div>';}).join('')+(history.length?'<details><summary>'+E(t('이전 협상 기록','Previous negotiations'))+'</summary>'+history.map(function(r){return '<p class="daily-history">#'+r.id+' · D'+r.day+' · '+E(r.status)+'<br>'+E(r.issue)+'</p>';}).join('')+'</details>':'')+'</div>';
  }

  /* ---------- references (quotes) ---------- */
  // References are optional shared context, never a forced issue-task selection.
  function refLabel(r){
    if(r.type==='t'){var x=state&&state.tasks[r.id];return t('업무 ','Task ')+(x?x.title:r.id);}
    if(r.type==='p')return t('사람 ','Person ')+label(r.id);
    var h=state&&state.hand[r.id];return 'Handoff '+(h?((state.tasks[h.from]||{}).title||h.from)+' → '+((state.tasks[h.to]||{}).title||h.to):r.id);
  }
  var XSVG='<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';
  function chipKind(r){return r.type==='p'?t('사람','Person'):r.type==='t'?t('업무','Task'):'Handoff';}
  function chipLabel(r){
    if(r.type==='p')return '@'+label(r.id);
    if(r.type==='t'){var x=state&&state.tasks[r.id];return x?x.title:r.id;}
    var h=state&&state.hand[r.id];return 'Handoff: '+(h?((state.tasks[h.from]||{}).title||h.from)+' → '+((state.tasks[h.to]||{}).title||h.to):r.id);}
  function paintRefs(){
    var q=document.getElementById('quotes');if(!q)return;
    q.hidden=!refs.length;
    q.innerHTML=refs.map(function(r,i){return '<span class="qchip qk-'+r.type+'" title="'+E(t('보낼 때 이슈의 참고 정보로 함께 전달됩니다.','Sent as optional context with the issue.'))+'"><em>'+E(chipKind(r))+'</em>'+E(chipLabel(r).replace(/^@|^Handoff: /,''))+'<button type="button" data-ref="'+i+'" aria-label="'+E(t('인용 빼기','Remove quote'))+'">'+XSVG+'</button></span>';}).join('');
    var hint=document.getElementById('cbox-hint');if(hint)hint.textContent=refs.length?'':t('보드의 업무·사람·Handoff를 끌어와 인용','Drag a task, person or Handoff here to quote');
  }
  document.getElementById('quotes').addEventListener('click',function(e){if(e.target.closest('[data-clear-refs]')){refs=[];paintRefs();return;}var b=e.target.closest('[data-ref]');if(!b)return;refs.splice(Number(b.dataset.ref),1);paintRefs();});
  window.PlanBeeApp={quote:function(type,id){
    if(!state||!((type==='t'&&state.tasks[id])||(type==='p'&&state.people.some(function(p){return p.id===id;}))||(type==='h'&&state.hand[id])))return;
    if(!refs.some(function(r){return r.type===type&&r.id===id;}))refs.push({type:type,id:id});
    var name=type==='p'?label(id):type==='t'?(state.tasks[id].title||id):null;
    paintRefs();if(!(name&&fillBlank(type,name)))input.focus();status();
  }};
  function issueWithRefs(text){
    var extra=refs.map(function(r){return refLabel(r)+' ['+r.id+']';});
    return extra.length?text+'\n\n'+t('참조: ','References: ')+extra.join(', '):text;
  }

  /* ---------- feed: readable MAS discussion ---------- */
  var SPEECH={QUESTION:['질문','Question','t-cond'],ANSWER:['답변','Answer','t-ok'],PREFER:['선호','Prefers','t-ok'],REJECT:['반대','Objects','t-no'],CONDITION:['조건','Condition','t-cond'],PASS:['의견 없음','No comment','t-flat']};
  var CONSENT={ACCEPT:['동의','Accept','t-ok'],REJECT:['거절','Reject','t-no'],NEEDS_INPUT:['본인 확인 필요','Needs confirmation','t-cond'],AUTO_CONFIRM:['사전 응답(카드 규칙)','Pre-set reply (card rule)','t-ok']};
  var NOISE=['COPY_SKIPPED','REPEAT_SKIPPED','SPEECH_SKIPPED','SCHEMA_REPAIR','ASSESSMENT_REPAIR','SPEECH_REPAIR','TEMPLATE_DROPPED','REPAIR_REQUEST'];
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
      '<p class="agenda-task">'+E(task.title||run.task||t('업무 확인 필요','Task needs clarification'))+' <small>'+E(t('담당 ','owner ')+label(task.who))+'</small></p><p class="agenda-issue">'+E(conversationText(run.issue))+'</p>'+
      '<p class="agenda-who">'+E(t('참석: ','Participants: '))+E(participants())+' · '+E(t('결정: PM','Decision: PM'))+'</p></div>';
    var cur=null,noise=0,assessed=[],ranked=[],afterRank=false;
    function sys(text){return '<div class="sys-line">'+E(text)+'</div>';}
    function flush(){
      if(assessed.length){html+=sys(runtime.demo_force_agree?t(assessed.join(', ')+' — T6 시연 모드로 모든 검증 후보에 동의했어요.',assessed.join(', ')+' — unconditionally accepted verified plans in T6 demo mode.'):t(assessed.join(', ')+' — 각자 위임카드와 일정으로 후보를 평가했어요.',assessed.join(', ')+' — assessed the plans with their own cards and schedules.'));assessed=[];}
      if(ranked.length){html+=sys(t(ranked.join(', ')+' — 토론 내용을 반영해 최종 평가했어요.',ranked.join(', ')+' — updated their assessment with the discussion.'));ranked=[];}
      if(noise){html+=sys(t('응답 형식 보정 '+noise+'회 (자동)',noise+' automatic format repair(s)'));noise=0;}
    }
    function open(key,extra){if(cur===key+(extra||''))return;flush();cur=key+(extra||'');html+='<div class="stage-div"><span>'+E(key==='assess'&&runtime.demo_force_agree?t('3 · 시연용 무조건 동의','3 · Unconditional demo agreement'):t(STAGES[key][0],STAGES[key][1]))+(extra?E(' · '+t('라운드 '+extra,'round '+extra)):'')+'</span></div>';}
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
      if(who==='hive'){html+='<div class="msg in hive-line"><div class="av hive"></div><div><p>'+E(hiveText(m))+(m.candidate_id?' '+candChip(m.candidate_id):'')+'</p></div></div>';if(a==='CANDIDATES')html+=funnel(run.generation,run.shortlist);return;}
      if(key==='consent'||a==='AUTO_CONFIRM'){html+='<div class="consent-row"><b>'+E(label(who))+'</b>'+candChip(m.candidate_id)+badge(a==='NEEDS_INPUT'&&runtime.auto_confirm?['PM 선택 후 사전 응답','Pre-set reply after PM choice','t-cond']:a==='AUTO_CONFIRM'&&runtime.demo_force_agree&&/T6/.test(m.reason||'')?['시연용 동의 · 카드 판단 아님','Demo agreement · not a card decision','t-flat']:CONSENT[a])+'<span class="basis">'+E(t('근거: ','Basis: ')+conversationText(m.reason||'-'))+'</span></div>';return;}
      if(a==='PASS'){html+=sys(label(who)+' · '+t('추가 의견 없음','no further comment'));return;}
      var sp=SPEECH[a],pm=who==='pm';
      var tag=sp?badge(sp):a==='ESTIMATE'?badge(['견적 변경','Re-estimate','t-cond']):a==='CONSTRAINT_REVIEW'?badge(['제약 검토','Constraint review','t-cond']):pm?badge([{SELECT:'선택',REJECT:'모두 반려',REVISE:'수정 요청',CLOSE:'확인'}[a]||a,{SELECT:'Chose',REJECT:'Rejected all',REVISE:'Revision',CLOSE:'Acknowledged'}[a]||a,'t-flat']):'';
      var text=msgText(m);
      html+='<div class="msg in"><div class="av '+(pm?'pm':'proxy')+'">'+E(label(who).slice(0,1))+'</div><div><div class="meta"><b>'+E(label(who))+(pm?'':' · Proxy')+'</b>'+tag+(m.recipient?'<small>→ '+E(label(m.recipient))+'</small>':'')+candChip(m.candidate_id)+'</div><p>'+E(text)+'</p></div></div>';
    });
    flush();
    return html;
  }

  /* ---------- PM view: plan funnel, what each plan changes, earlier threads ---------- */
  function prio(ctx){var n=window.PlanBeePriority?window.PlanBeePriority(ctx):-1;return n>=0?'<span class="pb-pr p'+n+'">P'+n+'</span>':'';}
  function slot(x){x=Number(x)||0;var d=Math.floor(x+1e-9),wk=Math.floor(d/5),dn=d%5,pm=(x-d)>=.5-1e-9;
    return t(['월','화','수','목','금'][dn]+(wk?'(+'+wk+'주)':'')+(pm?' 오후':' 오전'),['Mon','Tue','Wed','Thu','Fri'][dn]+(wk?' (wk '+(wk+1)+')':'')+(pm?' PM':' AM'));}
  function baseTasks(src){var m={};if(!src)return m;
    if(Array.isArray(src.tasks))src.tasks.forEach(function(x){m[x.id]={id:x.id,who:x.who,title:x.title,start:x.start,days:x.days,kind:x.kind,context:x.context||{}};});
    else Object.values(src).forEach(function(x){if(!x.cut)m[x.id]={id:x.id,who:x.who,title:x.title,start:x.s,days:x.d,kind:x.kind,context:x.context||{}};});
    return m;}
  function planChanges(c,base){
    var out=[],after=baseTasks(c.board||{}),parts={};
    Object.values(after).forEach(function(x){var par=(x.context||{}).partition_of;if(par&&!base[x.id]&&base[par])(parts[par]=parts[par]||[]).push(x);});
    Object.values(after).forEach(function(x){var b=base[x.id];
      if(!b){var par=(x.context||{}).partition_of;if(par&&base[par])return;
        out.push({x:x,kind:'new',text:t('새 업무 → ','New → ')+label(x.who)+' · '+slot(x.start)+' · '+fmt(x.days)+t('일','d')});return;}
      if((x.days||0)<1e-6&&(b.days||0)>0)return;   // split into parts; the parts are listed
      var bits=[];
      if(b.who!==x.who)bits.push(label(b.who)+' → '+label(x.who));
      if(Math.abs((b.start||0)-(x.start||0))>1e-6)bits.push(slot(b.start)+' → '+slot(x.start));
      if(Math.abs((b.days||0)-(x.days||0))>1e-6)bits.push(fmt(b.days)+' → '+fmt(x.days)+t('일','d'));
      if(bits.length)out.push({x:x,kind:b.who!==x.who?'owner':'time',text:bits.join(' · ')});});
    Object.values(base).forEach(function(b){if(after[b.id]||b.kind==='done'||b.kind==='milestone')return;
      var ps=parts[b.id],board=c.board||{};
      if(ps){ps.sort(function(p,q){return p.start-q.start;});
        out.push({x:b,kind:ps.some(function(p){return p.who!==b.who;})?'owner':'time',text:t('나눔 · ','Split · ')+ps.map(function(p){return label(p.who)+' '+slot(p.start)+' '+fmt(p.days)+t('일','d');}).join(' + ')});return;}
      var d=(board.deferred||[]).find(function(z){return z.id===b.id;}),o=(board.omitted||[]).find(function(z){return z.id===b.id;});
      out.push({x:b,kind:'cut',text:d?t(d.to+'로 이관','deferred to '+d.to):o?t('생략 · 최종 검증에 포함','omitted · covered by the final check'):t('계획에서 제외','removed from the plan')});});
    out.sort(function(a,b){var o={owner:0,new:1,cut:2,time:3};return o[a.kind]-o[b.kind];});
    return out;}
  function loads(map){var l={};Object.values(map).forEach(function(x){if(x.kind==='milestone'||x.kind==='done')return;l[x.who]=(l[x.who]||0)+(Number(x.days)||0);});return l;}
  function changeBlock(c,base){
    var ch=planChanges(c,base);if(!ch.length)return '<p class="candidate-meta">'+E(t('보드 변경 없음 · 현재 배분 유지','No board change · keeps the current allocation'))+'</p>';
    var html='<ul class="pb-changes">'+ch.slice(0,6).map(function(r){return '<li class="pb-'+r.kind+'">'+prio(r.x.context)+'<b>'+E(r.x.title)+'</b> <span>'+E(r.text)+'</span></li>';}).join('')+(ch.length>6?'<li class="pb-more">'+E(t('외 '+(ch.length-6)+'건','+'+(ch.length-6)+' more'))+'</li>':'')+'</ul>';
    var l0=loads(base),l1=loads(baseTasks(c.board||{})),who=(c.affected||[]).filter(function(p){return Math.abs((l0[p]||0)-(l1[p]||0))>1e-6;});
    if(who.length)html+='<p class="pb-load">'+E(t('업무량 ','Load '))+who.map(function(p){return E(label(p))+' '+fmt(l0[p]||0)+'→'+fmt(l1[p]||0)+t('일','d');}).join(' · ')+'</p>';
    return html;}
  function reasonKey(r){r=String(r);return /데드라인|기한|deadline/i.test(r)?'deadline':/선후|의존|수렴|order/i.test(r)?'order':/역할|role|권한/i.test(r)?'role':/용량|가용|capacity|부재|unavail/i.test(r)?'capacity':'other';}
  function funnel(g,shortlist,finals){
    if(!g||!g.attempted)return '';
    var by={};Object.keys(g.reasons||{}).forEach(function(k){var key=reasonKey(k);by[key]=(by[key]||0)+g.reasons[k];});
    var name={deadline:t('마감 초과','Past deadline'),order:t('선후 순서','Order'),role:t('역할·권한','Role'),capacity:t('일정·가용','Capacity'),other:t('기타','Other')};
    var tot=g.attempted,segs=Object.keys(by).sort(function(a,b){return by[b]-by[a];}).map(function(k){return {cls:'f-'+k,n:by[k],lab:name[k]};});
    if(g.duplicates)segs.push({cls:'f-dup',n:g.duplicates,lab:t('중복','Duplicates')});
    segs.push({cls:'f-pass',n:g.feasible||0,lab:t('통과','Passed')});
    var bar='<div class="pf-bar" role="img" aria-label="'+E(t(tot+'개 중 '+(g.feasible||0)+'개 통과',(g.feasible||0)+' of '+tot+' passed'))+'">'+segs.map(function(x){return x.n?'<i class="'+x.cls+'" style="flex:'+x.n+'" title="'+E(x.lab+' '+x.n)+'"></i>':'';}).join('')+'</div>';
    var legend='<div class="pf-leg">'+segs.map(function(x){return x.n?'<span><i class="'+x.cls+'"></i>'+E(x.lab)+' <b>'+x.n+'</b></span>':'';}).join('')+'</div>';
    var steps=[[tot,t('만든 계획','Generated')],[g.feasible||0,t('검사 통과','Passed checks')]];
    if(shortlist&&shortlist.length)steps.push([shortlist.length,t('토론','Discussed')]);
    if(finals&&finals.length)steps.push([finals.length,t('PM에게','To the PM')]);
    return '<div class="pf"><div class="pf-steps">'+steps.map(function(x,i){return (i?'<span class="pf-arr" aria-hidden="true">→</span>':'')+'<span class="pf-step'+(i===steps.length-1?' last':'')+'"><b>'+x[0]+'</b><small>'+E(x[1])+'</small></span>';}).join('')+'</div>'+bar+legend+'</div>';}
  function outcome(r){
    if(r.termination==='applied'){var c=(r.candidates||[]).find(function(x){return r.pm_selection&&x.id===r.pm_selection.candidate_id;});return t('적용','Applied')+(c?' · '+planHeadline(r,c):'');}
    if(r.termination==='pm_rejected')return t('PM이 모두 반려','Rejected by the PM');
    if(r.termination==='issue_needs_clarification')return t('추가 설명 필요','Needs clarification');
    return r.termination?terminationLabel(r.termination):r.status;}
  function threadHTML(){
    var older=runHistory.filter(function(r){return !run||r.id!==run.id;});if(!older.length)return '';
    return '<details class="pb-threads" data-open="threads"><summary>'+E(t('이전 이슈 스레드 '+older.length+'개','Earlier issue threads ('+older.length+')'))+'</summary>'+older.map(function(r){
      var task=state.tasks[r.task]||{},c=(r.candidates||[]).find(function(x){return r.pm_selection&&x.id===r.pm_selection.candidate_id;});
      return '<details class="pb-thread" data-open="thread-'+r.id+'"><summary><b>#'+r.id+'</b> '+E((r.reporter&&r.reporter!=='pm'?label(r.reporter.slice(7)):'PM')+' · ')+E(conversationText(String(r.issue||'').split('\n')[0]).slice(0,80))+'<span class="pb-out">'+E(outcome(r))+'</span></summary>'+
        '<p class="candidate-meta">'+E(t('업무 ','Task '))+E(task.title||r.task||'-')+' · '+E(t('참여 ','Participants '))+E((r.participants||[]).map(label).join(', ')||'-')+' · '+E(t('라운드 ','Rounds '))+(r.round||0)+'</p>'+
        funnel(r.generation,r.shortlist)+(c?changeBlock(c,baseTasks(r.initial_board)):'')+'</details>';}).join('')+'</details>';}
  function candidateCard(c,isFinal){
    var number=candNo(c.id);
    var html='<article class="candidate-card candidate-compact" data-card="'+E(c.id)+'"><div class="candidate-row"><div><h3>'+E(t('후보 ','Plan '))+number+' · '+E(planHeadline(r,c))+'</h3><span class="candidate-meta">'+Object.keys(c.consents||{}).map(function(pid){var a=c.consents[pid];return E(label(pid))+' '+E({ACCEPT:a.source==='demo_algorithm'?t('시연용 동의','demo agreement'):a.auto_confirmed?t('사전 응답','pre-set reply'):t('동의','accept'),REJECT:t('거절','reject'),NEEDS_INPUT:runtime.auto_confirm?t('PM 선택 후 사전 응답','pre-set reply after PM choice'):t('본인 확인 필요','needs confirmation')}[a.action]||a.action);}).join(' · ')+'</span></div><div class="candidate-actions"><button class="btn sm" data-preview="'+E(c.id)+'">'+E(t('보드에서 보기','Show on board'))+'</button>';
    if(isFinal&&run.status==='awaiting_pm_selection')html+='<button class="btn go sm" data-select="'+E(c.id)+'">'+E(t('이 안으로 결정','Choose this plan'))+'</button>';
    html+='</div></div>'+changeBlock(c,baseTasks(state.tasks));
    if((c.plan_actions||[]).length)html+='<p class="candidate-meta">'+c.plan_actions.map(function(a){return E((state.tasks[a.task]||{}).title||a.task)+' · '+E(a.kind==='defer'?t(a.milestone+'로 이관','deferred to '+a.milestone):a.kind==='omit'?t('선택 검증 생략','optional check skipped'):t('임시 / 최종 단계로 분해','split into interim / final'));}).join(' · ')+'</p>';
    return html+'</article>';
  }
  /* ---------- channel threads (prototype design): one issue = one thread ---------- */
  var openThreads={},chosen={};
  var CHEV='<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var SPEECH_T={QUESTION:'t-flat',ANSWER:'t-ok',PREFER:'t-ok',REJECT:'t-no',CONDITION:'t-cond',PASS:'t-flat'};
  function pname(id){return id==='pm'?t('나 (PM)','Me (PM)'):label(id);}
  function av(id,kind){if(kind==='hive')return '<div class="av hive" aria-hidden="true"></div>';if(id==='pm')return '<div class="av pm">PM</div>';return '<div class="av'+(kind==='proxy'?' proxy':'')+'">'+E(label(id).slice(0,1))+'</div>';}
  function mention(id,kind){return id==='pm'?'<span class="mention me">'+E(t('@나','@me'))+'</span>':'<span class="mention'+(kind==='person'?'':' px')+'">@'+E(kind==='person'?label(id):t(label(id)+'의 프록시',label(id)+"'s proxy"))+'</span>';}
  function hiveMsg(text,extra){return '<div class="msg in">'+av('','hive')+'<div><div class="meta"><b>Hive</b></div>'+(text?'<p>'+E(text)+'</p>':'')+(extra||'')+'</div></div>';}
  function proxyMsg(id,tag,text,extra){return '<div class="msg in">'+av(id,'proxy')+'<div><div class="meta"><b>'+E(t(label(id)+'의 프록시',label(id)+"'s proxy"))+'</b>'+(tag||'')+'</div><p>'+E(text)+'</p>'+(extra||'')+'</div></div>';}
  function personRole(id){var p=state.people.find(function(x){return x.id===id;});return p?roleName(((state.profiles||{}).people||{})[id]&&state.profiles.people[id].role||p.role):'';}
  function runStatus(r){
    if(r.status==='running')return ['run',t('협의 중','Negotiating')];
    if(r.status==='awaiting_pm_selection')return ['need',t('PM 결정 필요','PM decision needed')];
    if(r.status==='waiting_confirm')return ['need',t('본인 확인 대기','Waiting for confirmation')];
    if(r.status==='waiting_pm'&&r.termination==='needs_rule_relaxation')return ['need',t('PM 규칙 선택 필요','PM rule choice needed')];
    if(r.status==='waiting_pm')return ['warn',t('합의 없음 · PM 검토','No agreement · PM review')];
    if(r.termination==='applied')return ['ok',t('해결됨 · 보드에 반영됨','Resolved · applied')];
    return ['run',outcome(r)];}
  function speeches(r){return (r.public_history||[]).filter(function(m){return SPEECH[m.response]&&m.requester!=='hive'&&m.requester!=='pm';});}
  function candOf(r,id){return (r.candidates||[]).find(function(c){return c.id===id;});}
  function candLabel(r,id){var c=candOf(r,id);if(c&&c.letter)return t('안 ','Plan ')+c.letter;var n=candNum(r,id);return t('검증안 #','Alt #')+n;}
  function candNum(r,id){var i=(r.candidates||[]).findIndex(function(c){return c.id===id;});return i<0?null:i+1;}
  function baseFor(r,cur){return cur&&r.status!=='done'?baseTasks(state.tasks):baseTasks(r.initial_board);}
  function evidence(r,m,cur){
    if(m.basis&&m.basis.length){
      var items=m.basis.map(function(ref){var k=ref.split(':')[0],v=ref.slice(k.length+1);
        if(k==='card')return '<li><button class="blink" type="button" data-pick="p" data-id="'+E(m.requester)+'" data-tab="profile" data-row="limit"><em>'+E(t(label(m.requester)+' 프로필',label(m.requester)+' · profile'))+'</em><span>'+E(t('받는 일 · 바람 · 한계','Takes · wishes · limits'))+'</span></button></li>';
        if(k==='task'&&state.tasks[v])return '<li>'+tlink(v)+'</li>';
        if(k==='handoff')return '<li>'+hlink(v)+'</li>';
        if(k==='plan'){var pc=candOf(r,v);return pc?'<li><button class="blink" type="button" data-preview="'+E(v)+'" data-run="'+r.id+'"><em>'+E(candLabel(r,v))+'</em><span>'+E(planHeadline(r,pc))+'</span></button></li>':'';}
        if(k==='history'){var q=(r.public_history||[])[+v];return q?'<li><span class="blink nolink"><em>'+E(label(q.requester))+'</em><span>'+E(msgText(q).slice(0,50))+'</span></span></li>':'';}
        return '';}).filter(Boolean);
      return '<details class="bas" data-open="b'+r.id+':'+(r.public_history||[]).indexOf(m)+'"><summary>'+E(t('근거 '+items.length,'Evidence '+items.length))+'</summary><ul>'+items.join('')+'</ul></details>';}
    var refs=[],c=m.candidate_id&&candOf(r,m.candidate_id),who=m.requester;
    if(c)refs.push('<li><button class="blink" type="button" data-preview="'+E(c.id)+'" data-run="'+r.id+'"><em>'+E(candLabel(r,c.id))+'</em><span>'+E(planHeadline(r,c))+'</span></button></li>');
    refs.push('<li><button class="blink" type="button" data-pick="p" data-id="'+E(who)+'" data-tab="profile" data-row="limit"><em>'+E(t(label(who)+' 프로필',label(who)+' · profile'))+'</em><span>'+E(t('받는 일 · 안 받는 일 · 본인 확인 한도','Takes · won\'t take · self-confirm limit'))+'</span></button></li>');
    if(c){var base=baseFor(r,cur),mine=planChanges(c,base).filter(function(x){return x.x.who===who||(c.affected||[]).indexOf(who)>=0&&x.kind!=='time';}).slice(0,2);
      mine.forEach(function(x){refs.push('<li><button class="blink" type="button" data-pick="t" data-id="'+E(x.x.id)+'" data-tab="profile" data-row="fixed"><em>'+E(t('업무','Task'))+'</em><span>'+E(x.x.title+' · '+x.text)+'</span></button></li>');});
      var ids=mine.map(function(x){return x.x.id;});
      Object.values(state.hand||{}).filter(function(h){return ids.indexOf(h.from)>=0||ids.indexOf(h.to)>=0;}).slice(0,2).forEach(function(h){refs.push('<li><button class="blink" type="button" data-pick="h" data-id="'+E(h.id)+'"><em>Handoff</em><span>'+E(((state.tasks[h.from]||{}).title||h.from)+' → '+((state.tasks[h.to]||{}).title||h.to))+'</span></button></li>');});}
    return '<details class="bas" data-open="b'+r.id+':'+(r.public_history||[]).indexOf(m)+'"><summary>'+E(t('근거 '+refs.length,'Evidence '+refs.length))+'</summary><ul>'+refs.join('')+'</ul></details>';}
  function discussionMode(r){return r&&r.consent_mode==='discussion';}
  function hlink(hid){var h=(state.hand||{})[hid];var title=h?((state.tasks[h.from]||{}).title||h.from)+' → '+((state.tasks[h.to]||{}).title||h.to):hid;
    return '<button class="blink" type="button" data-pick="h" data-id="'+E(hid)+'"><em>Handoff</em><span>'+E(title)+'</span></button>';}
  function tlink(tid){var x=state.tasks[tid]||{};return '<button class="blink" type="button" data-pick="t" data-id="'+E(tid)+'"><em>'+E(t('업무','Task'))+'</em><span>'+E(x.title||tid)+'</span></button>';}
  function impactCard(r){
    var im=r.impact;if(!im)return '';
    var row=function(c){return '<li>'+hlink(c.id)+'<span class="iw">'+E(slot(c.due))+' → <b>'+E(slot(c.expected))+'</b></span></li>';};
    var broken=(im.chain||[]).filter(function(c){return (im.broken||[]).indexOf(c.id)>=0;});
    var ppl=function(ids,cls){return (ids||[]).map(function(id){return '<span class="ip '+cls+'">'+E(label(id))+'</span>';}).join('');};
    return '<div class="pb-impact"><p class="ih">'+E(broken.length?t('깨지는 인계 '+broken.length+'개','Broken handoffs: '+broken.length):t('깨지는 인계 없음','No broken handoff'))+'</p>'+
      (broken.length?'<ul class="ilist">'+broken.map(row).join('')+'</ul>':'')+
      '<div class="ipeople">'+
        '<div><dt>'+E(t('보고','Reported'))+'</dt><dd>'+ppl([im.owner],'own')+'</dd></div>'+
        ((im.involved||[]).length?'<div><dt>'+E(t('영향','Affected'))+'</dt><dd>'+ppl(im.involved,'hit')+'</dd></div>':'')+
        ((im.may_help||[]).length?'<div><dt>'+E(t('대신 맡을 수 있음','Could take work'))+'</dt><dd>'+ppl(im.may_help,'help')+'</dd></div>':'')+
        ((im.not_involved||[]).length?'<div><dt>'+E(t('부르지 않음','Not called'))+'</dt><dd>'+ppl(im.not_involved,'off')+'</dd></div>':'')+
      '</div></div>';}
  function ruleCards(r){
    var opts=r.relaxation_options||(r.pm_handoff||{}).relaxation_options||[];if(!opts.length)return '';
    var g=state.glossary_en||{},L=function(x){return lang()==='en'&&g[x]?g[x]:x;};
    return '<div class="pb-rules decision-anchor">'+opts.map(function(o){var ok=o.feasible>0,who=o.authorizer==='pm'?t('PM이 허락','PM grants'):t(label(o.authorizer)+' 본인이 결정',label(o.authorizer)+' decides');
      return '<div class="rule'+(ok?'':' dead')+'"><div class="rtop"><b>'+E(o.id)+'</b><span class="rn2">'+E(ok?t('풀면 계획 '+o.feasible+'개',o.feasible+' plans if relaxed'):t('풀어도 계획 없음','Still no plan'))+'</span></div>'+
        '<p>'+E(L(o.label))+'</p><p class="src">'+E(L(o.rule||''))+' · '+E(who)+'</p>'+(o.tally&&o.tally.by&&Object.keys(o.tally.by).length?tallyLine({discussion_tally:o.tally}):'')+
        (ok?'<button class="btn '+(o.authorizer==='pm'?'go ':'')+'sm" type="button" data-rule="'+E(o.id)+'">'+E(o.authorizer==='pm'?t('이 규칙 허락','Allow this rule'):t(label(o.authorizer)+' 동의로 기록하고 진행','Record '+label(o.authorizer)+'\'s consent and continue'))+'</button>':(o.remaining&&o.remaining.length?'<p class="src">'+E(t('남는 문제: ','Still breaks: ')+o.remaining.slice(0,2).join(' · '))+'</p>':''))+'</div>';}).join('')+'</div>';}
  function tallyLine(c){
    var tl=c.discussion_tally;if(!tl)return '';
    var by=function(act){return (tl.by||[]).filter(function(x){return x.action===act;}).map(function(x){return label(x.who);});};
    var bit=function(ko,en,act,cls){var n=by(act);return '<span class="tl '+cls+(n.length?'':' zero')+'">'+E(t(ko,en))+' '+n.length+(n.length?' · '+E(n.join(', ')):'')+'</span>';};
    return '<span class="tally">'+bit('선호','Prefer','PREFER','pf')+bit('반대','Object','REJECT','ob')+bit('조건','Condition','CONDITION','cd')+bit('질문','Question','QUESTION','qs')+
      '</span>';}
  function replyLine(r,m,prev){
    if(m.reply_to===undefined||m.reply_to===null)return '';var q=(r.public_history||[])[m.reply_to];if(!q)return '';
    if(prev&&(prev===q||prev.reply_to===m.reply_to))return '<p class="rto">↩ <b>'+E(label(q.requester))+'</b>'+E(t('에게',''))+'</p>';
    return '<p class="rto" title="'+E(msgText(q))+'">↩ <b>'+E(label(q.requester))+'</b> '+E(msgText(q))+'</p>';}
  function agenda(r){
    var task=state.tasks[r.task]||{},parts=r.participants||[],finals=(r.final_candidates||[]).map(function(id){return candOf(r,id);}).filter(Boolean);
    var hasP0=Object.values(state.tasks).some(function(x){return /P0/.test((x.context||{}).priority||'');});
    var items=[[t('이 변경이 깨는 업무와 Handoff','Which tasks and Handoffs this breaks'),!!(r.impact||r.generation)],[t('누가 어떤 일을 언제 맡을지','Who takes which work, and when'),finals.length>0||r.status==='done'],[t('최종 계획 선택','Final plan choice'),!!r.pm_selection,'pm']];
    var who=parts.map(function(id){var why=id===task.who?t('이슈 업무 담당','Owns the issue task'):finals.some(function(c){return (c.affected||[]).indexOf(id)>=0;})?t('계획에서 업무가 바뀜','Work changes in a plan'):t('후속 Handoff로 연결','Linked by a Handoff');return '<li>'+mention(id,'proxy')+'<span>'+E(why)+'</span></li>';});
    var skip=state.people.filter(function(p){return parts.length&&parts.indexOf(p.id)<0;}).map(function(p){return p.name;});
    return '<div class="msg in">'+av('','hive')+'<div><div class="meta"><b>Hive</b></div><div class="agenda"><dl>'+
      '<div><dt>'+E(t('안건','Issue'))+'</dt><dd>'+E((task.title||r.task||t('업무 확인 필요','Task to identify'))+(task.who?' · '+t('담당 ','owner ')+label(task.who):''))+'</dd></div>'+
      '<div><dt>'+E(t('목표','Goal'))+'</dt><dd>'+E((state.deadline_label||'')+(hasP0?t(' 유지 · P0 업무는 줄이지 않음',' kept · P0 work is not cut'):t(' 유지',' kept')))+'</dd></div>'+
      '<div><dt>'+E(t('정해야 할 것','To decide'))+'</dt><dd><ul class="ag-items">'+items.map(function(x){return '<li class="'+(x[1]?'done':(x[2]||''))+'"><span class="ck" aria-hidden="true"></span><span>'+E(x[0])+'</span></li>';}).join('')+'</ul></dd></div>'+
      (who.length?'<div><dt>'+E(t('참석','Attending'))+'</dt><dd><ul class="roster">'+who.join('')+(skip.length?'<li><span>'+E(skip.join(', ')+t(' · 연결된 업무가 없어 부르지 않음',' · not called, no linked work'))+'</span></li>':'')+'</ul></dd></div>':'')+
      '</dl></div></div></div>';}
  function roundBlock(r,n,rows,cur,last){
    var ruleTalk=rows[0]&&rows[0].phase==='rule_discussion';
    var passed=rows.filter(function(m){return m.response==='PASS';}),said=rows.filter(function(m){return m.response!=='PASS';});
    var chips=said.filter(function(m){return SPEECH[m.response];}).map(function(m){var sp=SPEECH[m.response];return '<span class="rc '+SPEECH_T[m.response]+'">'+E(label(m.requester))+' '+E(t(sp[0],sp[1]))+(m.candidate_id&&candOf(r,m.candidate_id)?' <small>'+E(candLabel(r,m.candidate_id).replace(/^안 |^Plan /,''))+'</small>':'')+'</span>';}).join('');
    if(!said.length&&passed.length)chips='<span class="rc t-flat">'+E(t('새 의견 없음','No new points'))+'</span>';
    var body=said.map(function(m,i){var prev=i?said[i-1]:null;
      if(m.response==='INVITE')return '<div class="sys-line">'+E(t(label(m.recipient)+'에게 질문이 있어 토론에 초대','Invited '+label(m.recipient)+' for a direct question'))+'</div>';
      var sp=SPEECH[m.response];
      return '<div class="rrow"><div class="av proxy">'+E(label(m.requester).slice(0,1))+'</div><div><div class="meta"><b>'+E(t(label(m.requester)+'의 프록시',label(m.requester)+"'s proxy"))+'</b><span class="rt '+SPEECH_T[m.response]+'">'+E(t(sp[0],sp[1]))+'</span></div>'+
        replyLine(r,m,prev)+'<p>'+(m.recipient?mention(m.recipient,'proxy')+' ':'')+E(m.response==='PASS'&&/^x?$/.test(m.reason||'')?t('추가 의견 없음','No further comment'):msgText(m))+'</p>'+evidence(r,m,cur)+'</div></div>';}).join('')+(passed.length?'<div class="sys-line pass-line">'+E(t('추가 의견 없음 · ','No further comment · ')+passed.map(function(m){return label(m.requester);}).join(', '))+'</div>':'');
    var key=r.id+':'+(ruleTalk?'rule':'r')+n,open=openThreads[key]!==undefined?openThreads[key]:(cur&&last&&(r.status==='running'||ruleTalk&&r.status==='waiting_pm'));
    return '<details class="round in" data-open-key="'+key+'"'+(open?' open':'')+'><summary><span class="chev">'+CHEV+'</span><b>'+E(ruleTalk?t('규칙 의견','Views on the rules'):t(n+'라운드','Round '+n))+'</b><span class="rq">'+chips+'</span></summary><div class="rrows">'+body+'</div></details>';}
  function consentBlock(r,rows,cur){
    var body=rows.map(function(m){var a=m.response,lab=a==='NEEDS_INPUT'&&runtime.auto_confirm?['PM 선택 후 사전 응답','Pre-set reply after PM choice','t-cond']:a==='AUTO_CONFIRM'&&/T6/.test(m.reason||'')?['시연용 동의 · 카드 판단 아님','Demo agreement · not a card decision','t-flat']:CONSENT[a]||[a,a,'t-flat'];
      return '<div class="rrow"><div class="av proxy">'+E(label(m.requester).slice(0,1))+'</div><div><div class="meta"><b>'+E(t(label(m.requester)+'의 프록시',label(m.requester)+"'s proxy"))+'</b><span class="rt '+lab[2]+'">'+E(t(lab[0],lab[1]))+'</span>'+(m.candidate_id?' '+E(candLabel(r,m.candidate_id)):'')+'</div><p>'+E(conversationText(m.reason||''))+'</p></div></div>';}).join('');
    var key=r.id+':consent',open=openThreads[key]!==undefined?openThreads[key]:false;
    return '<details class="round in" data-open-key="'+key+'"'+(open?' open':'')+'><summary><span class="chev">'+CHEV+'</span><b>'+E(t('당사자 동의','Consent'))+'</b><span class="rq">'+E(t('바뀌는 사람이 정확한 계획에 답함','People whose work changes answer on the exact plan'))+'</span><span class="rn">'+E(t('답 '+rows.length,rows.length+' replies'))+'</span></summary><div class="rrows">'+body+'</div></details>';}
  function optionsBlock(r){
    var finals=(r.final_candidates||[]).map(function(id){return candOf(r,id);}).filter(Boolean),base=baseTasks(state.tasks),pickd=chosen[r.id];
    var opts='<fieldset class="opts"><legend class="sr">'+E(t('계획 선택','Choose a plan'))+'</legend>'+finals.map(function(c){
      var ch=planChanges(c,base),cons=Object.keys(c.consents||{}).map(function(pid){var a=c.consents[pid];return label(pid)+' '+({ACCEPT:a.source==='demo_algorithm'?t('시연용 동의','demo agreement'):a.auto_confirmed?t('사전 응답','pre-set reply'):t('동의','accept'),REJECT:t('거절','reject'),NEEDS_INPUT:runtime.auto_confirm?t('PM 선택 후 사전 응답','pre-set reply after PM choice'):t('본인 확인 필요','needs confirmation')}[a.action]||a.action);}).join(' · ');
      return '<label class="opt"><input type="radio" name="pm-'+r.id+'" value="'+E(c.id)+'"'+(pickd===c.id?' checked':'')+'><span><b>'+E(candLabel(r,c.id)+' · '+planHeadline(r,c))+'</b>'+
        '<span class="mets">'+(ch.length?ch.slice(0,4).map(function(x){var n=window.PlanBeePriority?window.PlanBeePriority(x.x.context):-1;return '<i>'+(n>=0?'P'+n+' ':'')+E(x.x.title+' · '+x.text)+'</i>';}).join(''):'<i>'+E(t('보드 변경 없음','No board change'))+'</i>')+'</span>'+
        (discussionMode(r)?tallyLine(c):'<span class="src">'+E(cons||t('동의 기록 없음','No consent record'))+'</span>')+'</span></label>';}).join('')+'</fieldset>';
    var others=(r.candidates||[]).filter(function(c){return (r.final_candidates||[]).indexOf(c.id)<0;});
    return hiveMsg(discussionMode(r)?t('토론까지 마친 계획 '+finals.length+'개예요. 하나를 고르면 보드에 반영돼요.',finals.length+' plans after discussion. Choosing one updates the board.'):t('계획 '+finals.length+'개 중에서 골라 주세요.','Choose one of '+finals.length+' plans.'),
      opts+'<div class="cacts decision-anchor"><button class="btn go sm" type="button" data-select="'+E(pickd||'')+'"'+(pickd?'':' disabled')+'>'+E(t('이 안으로 결정','Choose this plan'))+'</button><button class="btn sm" type="button" data-pm-action="reject">'+E(t('모두 반려','Reject all'))+'</button><button class="btn sm" type="button" data-pm-action="revise">'+E(t('수정 요청','Request revision'))+'</button></div>'+
      (others.length?'<details data-open="others"><summary class="src">'+E(t('토론에 오르지 않은 검증안 '+others.length+'개','Other valid plans ('+others.length+')'))+'</summary><ul class="pb-changes">'+others.map(function(c){var ch=planChanges(c,base);return '<li><button class="cand-chip" type="button" data-preview="'+E(c.id)+'" data-run="'+r.id+'">'+E(candLabel(r,c.id))+'</button> <span>'+E(ch.length?ch.slice(0,2).map(function(x){return x.x.title+' · '+x.text;}).join(' / '):t('보드 변경 없음','No board change'))+'</span></li>';}).join('')+'</ul></details>':''));}
  function resultCard(r){
    var c=r.pm_selection&&candOf(r,r.pm_selection.candidate_id),applied=r.termination==='applied';
    var ch=c?planChanges(c,baseTasks(r.initial_board)):[],sp=speeches(r).length,conf=(r.public_history||[]).filter(function(m){return m.response==='AUTO_CONFIRM'||m.response==='CONFIRM';}).length;
    return '<div class="msg in">'+av('','hive')+'<div><div class="meta"><b>Hive</b></div><div class="card '+(applied?'okc':'ask')+'"><div class="cstat">'+E(applied?t('해결됨 · 보드에 반영됨','Resolved · applied to the board'):t('적용하지 않음','Not applied'))+'</div>'+
      '<h3>'+E(applied&&c?planHeadline(r,c):outcome(r))+'</h3>'+(ch.length?'<ul>'+ch.slice(0,5).map(function(x){return '<li><b>'+E(x.x.title)+'</b> · '+E(x.text)+'</li>';}).join('')+'</ul>':'')+
      '<div class="stats"><span>'+E(t('프록시 답','Proxy replies'))+' <b>'+sp+'</b></span><span>'+E(t('라운드','Rounds'))+' <b>'+(r.round||0)+'</b></span><span>'+E(t('본인 확인','Confirmations'))+' <b>'+conf+'</b></span><span>'+E(t('PM 결정','PM decisions'))+' <b>'+(r.pm_selection?1:0)+'</b></span></div></div></div></div>';}
  function threadBody(r,cur){
    var out=[agenda(r)],block=null,consent=[],noise=0,assessed=[],afterRank=false;
    var lastN=null;(r.public_history||[]).forEach(function(m){if(SPEECH[m.response]&&m.requester!=='hive'&&m.requester!=='pm')lastN=(m.phase==='rule_discussion'?'rule':'')+(m.round||1);});
    function flushRound(){if(block){out.push(roundBlock(r,String(block.n).replace('rule',''),block.rows,cur,block.n===lastN));block=null;}}
    (r.public_history||[]).forEach(function(m){
      var a=m.response,who=m.requester;
      if(a==='RANK')afterRank=true;
      if(a==='ISSUE'||a==='TASK_IDENTIFIED')return;
      if(NOISE.includes(a)){noise++;return;}
      if(SPEECH[a]&&who!=='hive'&&who!=='pm'||a==='INVITE'){var n=(m.phase==='rule_discussion'?'rule':'')+(m.round||1);if(!block||block.n!==n){flushRound();block={n:n,rows:[]};}block.rows.push(m);return;}
      flushRound();
      if(a==='ASSESS'){assessed.push(label(who));return;}
      if(a==='RANK')return;
      if(assessed.length){out.push('<div class="sys-line">'+E(runtime.demo_force_agree&&state.demo.id==='m4_t6_game_demo'?t(assessed.join(', ')+' — 시연 설정으로 평가 없이 모두 동의 처리',assessed.join(', ')+' — demo setting: all agreed without assessment'):t(assessed.join(', ')+' — 각자 카드로 후보를 평가',assessed.join(', ')+' — assessed the plans with their own cards'))+'</div>');assessed=[];}
      if((afterRank&&['ACCEPT','REJECT','NEEDS_INPUT'].includes(a)&&who!=='hive'&&who!=='pm')||(a==='AUTO_CONFIRM'&&!r.pm_selection)){consent.push(m);return;}
      if(consent.length){out.push(consentBlock(r,consent,cur));consent=[];}
      if(a==='ESTIMATE'){out.push(proxyMsg(who,'<span class="rt t-cond">'+E(t('견적 변경','Re-estimate'))+'</span>',msgText(m)));return;}
      if(a==='IMPACT'){out.push(hiveMsg(t('이 변경의 영향이에요.','What this change affects.'),impactCard(r)));return;}
      if(a==='CONSTRAINT_REVIEW'){out.push(proxyMsg(who,'<span class="rt t-cond">'+E(t('제약 검토','Constraint review'))+'</span>'+(m.recipient?'<small>→ '+E(pname(m.recipient))+'</small>':''),msgText(m)));return;}
      if(a==='RULE_OPTIONS'){out.push(hiveMsg(t('지금 규칙으로는 마감을 지키는 계획이 없어요. 규칙을 하나씩 풀었을 때를 계산했어요.','No plan meets the deadline under the current rules. Hive worked out what each relaxed rule allows.')));return;}
      if(a==='SHORTLIST'||a==='DISCUSSION_TALLY'){if(!(a==='DISCUSSION_TALLY'&&cur&&r.status==='awaiting_pm_selection'))out.push('<div class="sys-line">'+E(msgText(m))+'</div>');return;}
      if(a==='CANDIDATES'&&discussionMode(r)){out.push(hiveMsg(t('마감을 지키는 계획 '+((r.generation||{}).feasible||'')+'개를 찾았어요.','Found '+((r.generation||{}).feasible||'')+' plans that meet the deadline.'),funnel(r.generation,r.shortlist,r.final_candidates)));return;}
      if(a==='CANDIDATES'){out.push(hiveMsg(t('검사를 통과한 계획 '+((r.generation||{}).feasible||'')+'개를 준비했어요. 이제 연결된 프록시가 각자 카드로 비교해요.','Prepared '+((r.generation||{}).feasible||'')+' plans that passed the checks. The linked proxies now compare them with their own cards.'),funnel(r.generation,r.shortlist,r.final_candidates)));return;}
      if(a==='APPLIED'||a==='DISCUSSION_STABLE'||a==='DEMO_AUTO_CONSENT')return;
      if(a==='AUTO_CONFIRM'){out.push(proxyMsg(who,'<span class="rt t-ok">'+E(t('사전 응답(카드 규칙)','Pre-set reply (card rule)'))+'</span>',msgText(m)));return;}
      if(who==='pm'){var tag={SELECT:['선택','Chose'],REJECT:['모두 반려','Rejected all'],REVISE:['수정 요청','Revision'],CLOSE:['확인','Acknowledged'],RULE_GRANTED:['규칙 허락','Rule granted'],REVERT:['되돌림','Reverted'],STOP:['중단','Stopped']}[a]||[a,a];
        out.push('<div class="msg in">'+av('pm')+'<div><div class="meta"><b>'+E(pname('pm'))+'</b><span class="rt t-flat">'+E(t(tag[0],tag[1]))+'</span></div><p>'+E(a==='SELECT'&&m.candidate_id?candLabel(r,m.candidate_id)+' · '+planHeadline(r,candOf(r,m.candidate_id)):msgText(m))+'</p></div></div>');return;}
      if(a==='PM_OPTIONS'&&cur&&r.status==='awaiting_pm_selection')return;
      out.push(hiveMsg(hiveText(m)));});
    flushRound();if(consent.length)out.push(consentBlock(r,consent,cur));
    if(noise)out.push('<div class="sys-line">'+E(t('응답 형식 보정 '+noise+'회 (자동)',noise+' automatic format repair(s)'))+'</div>');
    if(cur&&r.status==='awaiting_pm_selection')out.push(optionsBlock(r));
    if(cur&&r.status==='waiting_pm'&&r.termination==='needs_rule_relaxation')out.push(hiveMsg(t('풀 규칙 하나를 골라 주세요.','Pick one rule to relax.'),ruleCards(r)));
    if(cur)(state.pending_confirms||[]).forEach(function(c){out.push(hiveMsg(t(label(c.who)+'의 한도를 넘는 변경이라 본인 확인이 필요해요.','This change is beyond '+label(c.who)+'\'s limit; '+label(c.who)+' must confirm.'),'<div class="cacts decision-anchor"><button class="btn go sm" type="button" data-confirm="'+c.id+'" data-as="'+E(c.who)+'" data-ok="true">'+E(t(label(c.who)+' 응답: 동의',label(c.who)+' replies: accept'))+'</button><button class="btn sm" type="button" data-confirm="'+c.id+'" data-as="'+E(c.who)+'" data-ok="false">'+E(t(label(c.who)+' 응답: 거절',label(c.who)+' replies: reject'))+'</button><span class="src">'+E(t('시연에서는 팀원 응답을 대신 입력합니다','In the demo, enter the teammate\'s reply'))+'</span></div>'));});
    if(cur&&r.status==='waiting_pm'&&r.termination!=='needs_rule_relaxation')out.push(hiveMsg(t('합의된 계획이 없어 PM에게 넘어왔어요. 미합의 변경은 적용하지 않아요.','No agreed plan; handed to the PM. Unagreed changes are not applied.'),'<p class="src">'+E(t('종료 사유: ','Reason: ')+terminationLabel((r.pm_handoff&&r.pm_handoff.summary&&r.pm_handoff.summary.termination)||r.termination||''))+'</p><div class="cacts decision-anchor"><button class="btn sm" type="button" data-close-run>'+E(t('확인 · 현재 배분 유지','Acknowledge · keep current allocation'))+'</button></div>'));
    if(r.clarification&&r.termination!=='not_a_change')out.push(hiveMsg(conversationText(r.clarification)));
    if(r.status==='running')out.push(workingLine(r));
    if(r.status==='done'&&!r.clarification)out.push(resultCard(r));
    return out.join('');}
  /* ---------- loading: say what is happening and for how long ---------- */
  var stepClock={key:null,at:0};
  function stepText(r){
    var s=r&&r.step,n=r&&r.round||1,b=r&&r.llm_budget;
    var m={candidate_input:['보고를 읽고 업무와 영향을 찾는 중','Reading the report, finding the task and its impact'],
      candidate_generate:['계획을 만들고 규칙으로 검사하는 중','Building plans and checking them against the rules'],
      candidate_assess:['토론할 계획을 고르는 중','Choosing plans for discussion'],
      candidate_discuss:[n+'라운드 · 관련된 프록시들이 차례로 의견을 내는 중','Round '+n+' · the proxies involved take turns'],
      candidate_rank:['토론 결과를 집계하는 중','Tallying the discussion']}[s]||['처리 중','Working'];
    return t(m[0],m[1])+(b&&r.proxy_mode!=='mock'?t(' · LLM 호출 ',' · LLM calls ')+b.used:'');}
  function isLive(r){return (r&&r.proxy_mode||state&&state.demo&&state.demo.llm_mode||runtime&&runtime.llm_mode)==='live';}
  function workingLine(r){
    var key=r?r.id+':'+r.step+':'+(r.round||0):'pending';if(stepClock.key!==key){stepClock={key:key,at:Date.now()};}
    var sec=Math.floor((Date.now()-stepClock.at)/1000);
    return '<div class="msg in pb-working" aria-live="polite">'+av('','hive')+'<div><div class="meta"><b>Hive</b></div><div class="wk"><span class="spin" aria-hidden="true"></span><span class="wt">'+E(r?stepText(r):t('보고를 보내는 중','Sending the report'))+'</span><span class="wsec" data-since="'+stepClock.at+'">'+sec+t('초','s')+'</span>'+(r?'<button class="btn sm wstop" type="button" data-stop-run>'+E(t('중단','Stop'))+'</button>':'')+'</div>'+
      (isLive(r)?'<p class="src">'+E(t('실제 LLM 응답을 기다리고 있어요. 한 단계에 10–40초 걸릴 수 있어요.','Waiting for the live model. A step can take 10–40 seconds.'))+'</p>':'')+'</div></div>';}
  setInterval(function(){feed.querySelectorAll('.wsec[data-since]').forEach(function(x){x.textContent=Math.floor((Date.now()-Number(x.dataset.since))/1000)+t('초','s');});},1000);
  var pendingIssue=null;   // shown at once when the PM sends, before the server answers
  function pendingThread(){
    if(!pendingIssue)return '';
    return '<div class="msg in pb-root">'+av(pendingIssue.who)+'<div><div class="meta"><b>'+E(pname(pendingIssue.who))+'</b></div><p>'+E(pendingIssue.text)+'</p><div class="thread"><div class="tmsgs">'+workingLine(null)+'</div></div></div></div>';}
  function threadHTML2(r,cur){
    var reporter=r.reporter&&r.reporter!=='pm'?r.reporter.slice(7):'pm',st=runStatus(r),n=speeches(r).length;
    var open=openThreads[r.id]!==undefined?openThreads[r.id]:cur;
    var raw=String(r.issue||''),text=conversationText(raw.split('\n\n')[0]),rm=raw.match(/\n\n(?:참조|References): (.+)$/);
    var chips=rm?rm[1].split(', ').map(function(x){var v=x.replace(/\s*\[[^\]]+\]$/,''),k=/^사람 |^Person /.test(v)?t('사람','Person'):/^업무 |^Task /.test(v)?t('업무','Task'):'Handoff';return '<span class="qchip"><em>'+E(k)+'</em>'+E(v.replace(/^(사람|업무|Person|Task|Handoff) /,''))+'</span>';}).join(' '):'';
    return '<div class="msg in pb-root">'+av(reporter)+'<div><div class="meta"><b>'+E(pname(reporter))+'</b>'+(reporter!=='pm'?'<span class="role">'+E(personRole(reporter))+'</span>':'')+'</div><p>'+E(text)+'</p>'+(chips?'<p class="pb-quotes">'+chips+'</p>':'')+
      '<button class="tbar" type="button" data-tbar="'+r.id+'" aria-expanded="'+open+'"><span class="pill '+st[0]+'">'+E(st[1])+'</span><span class="tcount">'+E(t('답글 '+n+'개',n+' replies'))+'</span><span class="chev">'+CHEV+'</span></button>'+
      '<div class="fold'+(open?'':' closed')+'"><div class="thread"><div class="tmsgs">'+(open?threadBody(r,cur):'')+'</div>'+(open?'<div class="tfoot end"><span class="tend">'+(r.status==='done'?E(t('스레드 끝','End of thread')):'')+'</span>'+(cur&&r.status!=='running'&&r.termination!=='reverted'?'<button class="btn sm" type="button" data-revert-report title="'+E(t('이 보고를 보내기 전의 보드로 돌아가요','Go back to the board before this report'))+'">'+E(t('↺ 보고 전으로','↺ Before this report'))+'</button>':'')+'<button class="btn sm tclose" type="button" data-tbar="'+r.id+'"><span aria-hidden="true">⌃</span> '+E(t('스레드 접기','Collapse thread'))+'</button></div>':'')+'</div></div></div></div>';}
  function paint(){
    translationStatus();
    var open=new Set(Array.from(feed.querySelectorAll('details[open][data-open]')).map(function(n){return n.dataset.open;}));var atEnd=feed.scrollHeight-feed.scrollTop-feed.clientHeight<90,scroll=feed.scrollTop;
    if(!booted){feed.innerHTML='<div class="backend-empty">'+E(t('서버에 연결하는 중입니다… 처음 접속이면 서버가 깨어나는 데 1분 정도 걸릴 수 있어요.','Connecting… On a first visit the server may take about a minute to wake up.'))+'</div>';return;}
    var list=runHistory.filter(function(r){return !run||r.id!==run.id;}).slice().reverse();
    var html=list.map(function(r){return threadHTML2(r,false);}).join('');
    if(run)html+=threadHTML2(run,true);
    if(pendingIssue)html+=pendingThread();
    else if(!run)html+='<div class="pb-empty"><div class="pe-h"><span class="av hive" aria-hidden="true"></span><div><b>'+E(t('새 이슈를 기다리는 중','Waiting for a new issue'))+'</b><p>'+E(t('무엇이 바뀌었는지 자유롭게 적어 보내세요. 업무를 고르지 않아도 돼요.','Describe what changed in your own words. No need to pick a task.'))+'</p></div></div><ol class="pe-steps">'+[[t('이슈 보고','Report'),t('채팅에 변경 사항','What changed')],[t('Hive 검사','Hive check'),t('마감·순서·역할 규칙','Deadline, order, role rules')],[t('프록시 토론','Proxy discussion'),t('관련된 팀원 프록시가 의견을 냄','Proxies of the people involved weigh in')],[t('PM 선택','PM choice'),t('계획 1~3개 중 결정','Pick from 1–3 plans')]].map(function(x,i){return '<li><i>'+(i+1)+'</i><b>'+E(x[0])+'</b><span>'+E(x[1])+'</span></li>';}).join('')+'</ol></div>';
    feed.innerHTML=html;
    feed.querySelectorAll('details[data-open]').forEach(function(d){d.open=open.has(d.dataset.open);});
    feed.scrollTop=atEnd?feed.scrollHeight:scroll;
    translateConversation();
  }
  feed.addEventListener('toggle',function(e){var d=e.target;if(d&&d.dataset&&d.dataset.openKey)openThreads[d.dataset.openKey]=d.open;},true);
  feed.addEventListener('change',function(e){var x=e.target;if(!x||x.type!=='radio'||!run)return;chosen[run.id]=x.value;var c=run.candidates.find(function(c){return c.id===x.value;});if(c){preview=c;V.render(state,c.board,true);}var b=feed.querySelector('[data-select]');if(b){b.dataset.select=x.value;b.disabled=busy;}status();});
  feed.addEventListener('click',function(e){
    if(e.target.closest('[data-stop-run]')){stopRun();e.stopPropagation();return;}
    if(e.target.closest('[data-revert-report]')){revertReport();e.stopPropagation();return;}
    var tb=e.target.closest('[data-tbar]');if(tb){var id=Number(tb.dataset.tbar),cur=run&&run.id===id;openThreads[id]=!(openThreads[id]!==undefined?openThreads[id]:cur);paint();e.stopPropagation();return;}
    var pk=e.target.closest('[data-pick]');if(pk&&window.PlanBeePick){window.PlanBeePick(pk.dataset.pick,pk.dataset.id,pk.dataset.tab,pk.dataset.row);e.stopPropagation();return;}
    var pv=e.target.closest('[data-preview][data-run]');if(pv){var r=runHistory.concat(run?[run]:[]).find(function(x){return x.id===Number(pv.dataset.run);});var c=r&&(r.candidates||[]).find(function(x){return x.id===pv.dataset.preview;});if(c){preview=c;V.render(state,c.board,true);status();}e.stopPropagation();}
  },true);

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
    var q=queued;queued=null;if(q)await q();
    await afterRound();status();
  }
  var queued=null;   // an action asked for while a model call was in flight; runs when the call returns
  function whenIdle(fn,note){if(looping||busy){automatic=false;queued=fn;V.toast(note||t('지금 처리 중인 응답이 끝나면 실행할게요.','Will do this as soon as the current reply arrives.'));status();return;}fn();}
  function stopRun(){whenIdle(function(){return act(async function(){run=await api('/runs/'+run.id+'/stop',{});await refresh(false);});},t('지금 응답이 끝나면 멈출게요. 적용되는 계획은 없어요.','Stopping after the current reply. Nothing is applied.'));}
  function revertReport(){if(!run)return;if(!window.confirm(t('이 보고를 보내기 전의 보드로 되돌릴까요? 이 스레드의 계획은 적용되지 않아요.','Revert the board to before this report? No plan from this thread is applied.')))return;
    whenIdle(function(){return act(async function(){run=await api('/runs/'+run.id+'/revert-report',{});preview=null;await refresh(false);V.toast(t('보고 전 보드로 되돌렸어요.','Board reverted to before the report.'));});});}
  // Completing a run keeps the demonstration clock unchanged.
  // Time moves only through the explicit Next / Previous day controls.
  async function afterRound(){return;}

  /* ---------- events ---------- */
  document.getElementById('form').addEventListener('submit',function(e){e.preventDefault();var issue=input.value.trim();if(!issue)return;
    BLANK.lastIndex=0;if(BLANK.test(issue)){BLANK.lastIndex=0;selectBlank(0);error(new Error(t('[빈칸]을 채운 뒤 보내 주세요.','Fill in the [blanks] before sending.')));return;}act(async function(){
    var shownDemo=state&&state.demo&&state.demo.id;var latest=await api('/state');
    if((latest.demo&&latest.demo.id)!==shownDemo){refs=[];await refresh(true);throw new Error(t('시나리오가 변경되어 화면을 새로 고쳤습니다. 내용을 확인한 뒤 다시 보내 주세요.','The scenario changed. The screen was refreshed; review your issue and send again.'));}
    var original=datedDraft&&datedDraft.text===issue?datedDraft.source:issue;
    var rep0=reporterFor(issue);pendingIssue={who:rep0==='pm'?'pm':rep0.slice(7),text:issue};input.value='';paint();
    var dated=state.demo.timeline&&state.demo.timeline.events.find(function(e){return e.available&&e.text===original;});
    run=await api('/candidate-runs',{timeline_event_id:dated?dated.id:null,issue:issueWithRefs(dated?dated.text:issue),settings:{demo_auto_consent:state.demo.id==='m4_t4_composite'},language:lang()},{role:reporterFor(issue)});
    pendingIssue=null;
    if(run.termination!=='issue_needs_clarification'){setDraft('');refs=[];}else{setDraft(issue);}
    preview=null;await refresh(false);automatic=run.status==='running';}).then(loop);});
  document.getElementById('continue-run').onclick=function(){if(run&&run.status==='waiting_pm'&&runtime.demo_force_agree){act(async function(){run=await api('/runs/'+run.id+'/advance',{});await refresh(false);});return;}automatic=true;loop();};
  document.getElementById('pause-run').onclick=function(){automatic=false;status();};
  document.getElementById('current-board').onclick=function(){preview=null;if(state)V.render(state,null,false);status();};
  document.getElementById('next-day').onclick=function(){act(async function(){var r=await api('/day/next',{});setDraft('');refs=[];preview=null;await refresh(false);V.toast(t('하루가 지났어요 · 완료: ','A day passed · finished: ')+(r.finished.join(', ')||t('없음','none')));});};
  document.getElementById('previous-day').onclick=function(){act(async function(){await api('/day/previous',{});setDraft('');refs=[];preview=null;await refresh(false);V.toast(t('이전 날로 돌아왔어요','Returned to the previous day'));});};
  document.getElementById('demo-select').onchange=function(e){
    var sel=e.target,chosen=sel.value,current=state&&state.demo&&state.demo.id;if(chosen===current)return;
    var active=!!(run&&ACTIVE.includes(run.status));
    if(active&&!window.confirm(t('진행 중인 협상이 있어요. 시나리오를 바꾸면 이 협상은 끝나고 적용되지 않은 계획은 사라져요. 바꿀까요?','A negotiation is in progress. Switching ends it and drops plans not yet applied. Switch anyway?'))){sel.value=current;return;}
    automatic=false;++refreshSeq;
    act(async function(){
      try{await api('/demo/select',{demo:chosen,force:active});}
      catch(err){sel.value=current;await refresh(true);throw err;}
      run=null;preview=null;refs=[];setDraft('');await refresh(true);});};
  function syncHeight(){var app=document.querySelector('.app');app.style.height=window.innerWidth>900?'calc(100dvh - '+Math.ceil(app.getBoundingClientRect().top+window.scrollY)+'px)':'auto';}
  window.addEventListener('resize',syncHeight);
  /* One perspective: the PM. Relaying the scenario's report keeps its author; anything typed is the PM's. */
  function reporterFor(){return 'pm';}   // the user is always the PM; teammates' news is relayed in the PM's words
  function switchRole(role){reporterRole=role;try{localStorage.setItem('pb-reporter-role',role);}catch(err){}}
  document.getElementById('reset').onclick=function(){if(!window.confirm(t('현재 시나리오를 처음 상태로 되돌릴까요?','Reset the current scenario to its initial state?')))return;automatic=false;whenIdle(function(){return act(async function(){await api('/reset',{});run=null;preview=null;refs=[];setDraft('');await refresh(true);});});};
  feed.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||busy||!run)return;if(b.dataset.select||b.dataset.rule||b.dataset.pmAction||b.dataset.confirm)b.classList.add('loading');
    if(b.dataset.switchRole){act(function(){return switchRole(b.dataset.switchRole);});return;}
    if(b.dataset.preview){preview=run.candidates.find(function(c){return c.id===b.dataset.preview;});if(preview)V.render(state,preview.board,true);status();return;}
    act(async function(){
      if(b.dataset.select!==undefined){if(!b.dataset.select)return;var c=run.candidates.find(function(c){return c.id===b.dataset.select;});run=await api('/runs/'+run.id+'/pm-selection',{action:'select',candidate_id:c.id,plan_hash:c.plan_hash});preview=null;await refresh(false);}
      else if(b.dataset.pmAction){var reason=window.prompt(t('반려/수정 요청 이유를 적어 주세요','Give a reason for rejecting / requesting revision'));if(!reason)return;run=await api('/runs/'+run.id+'/pm-selection',{action:b.dataset.pmAction,reason:reason});await refresh(false);if(run.status==='running')automatic=true;}
      else if(b.dataset.confirm){await api('/confirmations/'+b.dataset.confirm,{ok:b.dataset.ok==='true'},{role:'person:'+b.dataset.as});run=await api('/runs/'+run.id);await refresh(false);}
      else if(b.hasAttribute('data-close-run')){run=await api('/runs/'+run.id+'/close',{});await refresh(false);}
      else if(b.dataset.rule){run=await api('/runs/'+run.id+'/rules',{rule_id:b.dataset.rule,reason:''});preview=null;await refresh(false);if(run.status==='running')automatic=true;}
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
