/* Presentation only. Persisted messages and negotiation decisions stay intact. */
(function (root) {
  'use strict';
  var actions={REQUEST:'요청',REVISE_REQUEST:'다시 제안 요청',REPAIR_REQUEST:'수정 요청',INVITE:'대화에 초대',
    ACCEPT:'동의',REJECT:'거절',COUNTER:'다른 제안',PASS:'대안 없음',NEEDS_INPUT:'본인 확인',CONDITION:'조건',
    BLOCKED:'조정 필요',AGREED:'합의 완료',END:'논의 종료',FINAL_CONSTRAINT_CHECK:'최종 확인',
    SCHEDULE_CHANGED:'일정 변경',STRATEGY_CHANGE:'다른 방법 검토',MODEL_UNAVAILABLE:'응답 대기',MODEL_OUTPUT_INVALID:'응답 재확인'};
  var strategies={independent_split:'독립 업무 분담',whole_transfer:'업무 전체 양도',move_other_work:'다른 업무 이동',collaborate:'협업'};
  function short(s,n){s=String(s||'').replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,n-1)+'…':s;}
  function parse(s){try{return JSON.parse(s);}catch(_){return null;}}
  function issue(x){
    if(typeof x==='string')return x;
    if(!x)return '';
    var names={EFFORT_SUM:'전체 업무 분량이 맞지 않아요',OWNER_IN_PIECE:'원 담당자의 보유분을 함께 조정해야 해요',
      DUPLICATE_SCOPE:'같은 업무 범위가 겹쳐 있어요',DUPLICATE_PROPOSAL:'이미 검토한 안과 같아요',
      ROLE:'담당자의 역할이 맞지 않아요',UNSPLITTABLE:'이 업무는 독립적으로 나눌 수 없어요',
      SCHEDULE_OR_DEPENDENCY:'마감이나 선후 일정을 다시 조정해야 해요',PUBLIC_LIMIT:'공개한 업무량 한도를 넘어요',
      EMPTY_COUNTER:'구체적인 변경 내용이 필요해요',REVISION_ACTION:'수정안이나 대안이 없는 이유를 알려주세요',
      MODEL_OUTPUT_FORMAT:'응답 내용을 다시 확인해야 해요'};
    var result=names[x.code]||x.text||x.message||'제약을 다시 확인해야 해요';
    if(x.code==='EFFORT_SUM')result+=' (필요 '+x.expected+'일 / 제안 '+x.actual+'일)';
    if(x.code==='PUBLIC_LIMIT')result+=' (한도 '+x.limit+'일 / 제안 '+x.proposed+'일)';
    return result;
  }
  function present(m){
    var raw=m.k==='proxy'?(m.f||[]).map(function(f){return f.t;}).join(' · '):String(m.text||'');
    var action=m.a||'',reason='',plan=null,meta='',round=m.round,version=null;
    if(m.k==='proxy' && /^\d+라운드 · v\d+ · /.test((m.f||[])[0]?.t||'')){
      meta=m.f[0].t;reason=(m.f[1]||{}).t||'';plan=parse((m.f[2]||{}).t||'');
    }else if(m.k==='hive'){
      var match=raw.match(/^(\d+)라운드 · v(\d+) · ([^·]+) · ([^·]+) · ([A-Z_]+) · ([\s\S]*)$/);
      if(match){round=+match[1];version=+match[2];meta=match.slice(1,5).join(' · ');action=match[5];reason=match[6];
        var at=reason.lastIndexOf(' · {"allocations"');
        if(at>=0){plan=parse(reason.slice(at+3));reason=reason.slice(0,at);}
      }
    }
    if(meta&&!version){var v=meta.match(/v(\d+)/);if(v)version=+v[1];}
    if(!meta){
      var ordinary=m.k==='proxy'?(m.f||[]).filter(function(f){var obj=parse(f.t);if(obj&&obj.allocations){plan=obj;return false;}return true;}).map(function(f){return f.t;}).join(' · '):raw;
      return {text:short(m.say||ordinary,190),reason:ordinary,raw:raw,action:actions[action]||action,
        round:round,version:version,plan:plan,notes:[m.basis,m.pref].filter(Boolean),structured:false};
    }
    var problems=parse(reason),explanation=Array.isArray(problems)?problems.map(issue).join(' / '):reason;
    // Repair requests can contain an embedded validation array after their lead-in.
    var begin=reason.indexOf('[{"code"');
    if(begin>=0){var items=parse(reason.slice(begin));if(Array.isArray(items))explanation=items.map(issue).join(' / ');}
    var parts=(plan||{}).allocations||[],mine=parts.filter(function(a){return a.who===m.to;}),speech;
    switch(action){
      case 'REQUEST':speech=mine.length===1?'‘'+short(mine[0].title,42)+'’ '+mine[0].days+'일을 담당하는 안은 어때요?':'이 배분안으로 진행해도 괜찮을까요?';break;
      case 'REVISE_REQUEST':speech='앞서 나온 조건을 반영해서 다른 방법을 제안해 줄래요?';break;
      case 'REPAIR_REQUEST':speech='방금 안에서 조정이 필요한 부분이 있어요. '+short(explanation,120);break;
      case 'INVITE':speech='아직 합의하지 못했어요. 함께 맡을 부분이나 다른 방법을 제안해 줄래요?';break;
      case 'ACCEPT':speech='좋아요. 이 배분안에 동의해요.';break;
      case 'REJECT':speech='지금 안에는 동의하기 어려워요. '+short(explanation,150);break;
      case 'COUNTER':speech='이렇게 바꿔보면 어떨까요? '+short(explanation,130);break;
      case 'PASS':speech='지금 조건에서는 제가 제안할 다른 방법을 찾지 못했어요.';break;
      case 'NEEDS_INPUT':speech='제가 바로 확정하기는 어려워요. 본인 확인을 받고 답할게요.';break;
      case 'CONDITION':speech=reason.replace('본인이 공개한 새 업무량 상한 ','제가 새로 맡을 수 있는 양은 최대 ')+'이에요.';break;
      case 'BLOCKED':speech='이 안은 조정이 필요해요. '+short(explanation,150);break;
      case 'FINAL_CONSTRAINT_CHECK':speech='마감과 업무량, 가용 시간, 당사자 동의를 다시 확인했어요. 적용 가능한 안이에요.';break;
      case 'AGREED':speech='모두 동의했고 최종 검증도 통과했어요. 이 배분안으로 확정했어요.';break;
      case 'END':speech=reason==='agreement'?'배분 합의를 마쳤어요.':reason==='max_llm_calls'?'전체 모델 호출 한도에 도달했어요. 미합의 변경은 적용하지 않고 PM에게 전달할게요.':reason==='max_rounds'?'정해진 라운드 안에 합의하지 못했어요. 미합의 변경은 적용하지 않을게요.':/model_/.test(reason)?'모델 응답 문제로 논의를 마치지 못했어요. 미합의 변경은 적용하지 않을게요.':'더 진행할 수 있는 대안을 찾지 못했어요. 미합의 변경은 적용하지 않을게요.';break;
      case 'SCHEDULE_CHANGED':speech='확인을 기다리는 동안 일정이 바뀌었어요. 새 일정으로 다시 동의를 받을게요.';break;
      case 'STRATEGY_CHANGE':var strategy=Object.keys(strategies).find(function(s){return reason.includes(s);});speech='이번에는 '+(strategies[strategy]||'다른 방법')+'도 검토해 볼게요.';break;
      case 'MODEL_UNAVAILABLE':speech='모델 응답을 받지 못했어요. 당사자가 거절한 것으로 처리하지는 않을게요.';break;
      case 'MODEL_OUTPUT_INVALID':speech='모델 응답 형식에 문제가 있어 내용을 다시 확인하고 있어요.';break;
      default:speech=short(explanation,180);
    }
    return {text:speech,reason:explanation,raw:raw,action:actions[action]||action,round:round,version:version,
      plan:plan,notes:[m.basis,m.pref].filter(Boolean),structured:true};
  }
  root.PlanBeeConversation={present:present,short:short};
})(globalThis);
