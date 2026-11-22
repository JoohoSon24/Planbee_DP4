"""External outcome oracle. This module is never injected into model prompts."""

def checks(sid,result):
    candidates=result.get('candidates',[])
    final=set(result.get('final_candidates') or [])
    matches=[];compromise=[]
    for c in candidates:
        board=c['board'];tasks={t['id']:t for t in board['tasks']};actions=c.get('plan_actions',[])
        def at(tid,start=None,days=None):
            t=tasks.get(tid)
            return bool(t and (start is None or abs(t['start']-start)<1e-8) and (days is None or abs(t['days']-days)<1e-8))
        valid=bool(board['gate']['ok'])
        if sid=='m4_t1_rescheduling':
            valid=valid and at('polish',5,.75) and at('bug_fix',6,1.5) and result.get('participants')==['dev']
        elif sid=='m4_t2_reallocation':
            valid=valid and {(a['key'],a['who'],a['effort']) for a in c['allocations']}=={('logic','dev',1),('assets','art',1)} and at('bug_fix',6,1) and at('integration_test',7,2)
        elif sid=='m4_t3_scope_reduction':
            deferred={t['id']:t for t in board.get('deferred',[])}
            valid=valid and set(deferred)=={'advanced_effects','advanced_fx'} and abs(deferred['advanced_effects']['days']-4)<1e-8 and abs(deferred['advanced_fx']['days']-.5)<1e-8 and all(t['to']=='Beta' for t in deferred.values()) and at('core_integration',days=1) and at('final_qa',7,2) and 'gd' in c['affected']
        elif sid=='m4_t4_composite':
            stage=[t for t in tasks.values() if (t['context'] or {}).get('partition_of')=='anim_integration']
            final_part=next((t for t in stage if abs(t['days']-.25)<1e-8),None)
            fx=tasks.get('fx_assets')
            valid=valid and len(stage)==2 and abs(sum(t['days'] for t in stage)-1)<1e-8 and at('critical_fix',days=1) and at('final_qa',7,2) and bool(final_part and fx and final_part['start']>=fx['start']+fx['days']-1e-8)
            if valid and any(a['kind']=='omit' for a in actions):
                if 'qa' in c.get('required_confirmations',[]):compromise.append(c['id'])
                else:valid=False
        else:valid=False
        if valid:matches.append(c['id'])
    if sid=='m4_t5_infeasible':
        actors={e['requester'] for e in result.get('public_history',[]) if e['response']=='CONSTRAINT_REVIEW'}
        ready=result['status']=='waiting_pm' and result.get('termination')=='search_exhausted' and not candidates and {'dev','qa'}<=actors
    else:ready=result['status']=='awaiting_pm_selection' and bool(final&set(matches))
    return dict(expected_outcome_ready=ready,matching_candidates=matches,matching_pm_options=sorted(final&set(matches)),
        qa_confirm_compromise_candidates=compromise,applied=result.get('termination')=='applied',
        note='실제 사람 승인·선택은 별도. 유효 대안/PM 대기와 실제 적용 성공은 구분한다.')
