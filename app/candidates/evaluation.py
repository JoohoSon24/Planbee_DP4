"""Frozen shared-set human/agent rank distributions; no LLM judge substitutes labels."""
from copy import deepcopy
import hashlib
import itertools
import json
import math
import random
from .engine import public_candidate
from ..models import CandidateEvaluation
from .. import prompts


def ranking(scores):
    groups=[]
    for cid,score in sorted(scores.items(),key=lambda item:(-item[1],item[0])):
        if not groups or score!=groups[-1][0]:groups.append((score,[cid]))
        else:groups[-1][1].append(cid)
    return [g for _,g in groups]


def ranks(groups):
    out={};at=1
    for group in groups:
        for cid in group:out[cid]=at+(len(group)-1)/2
        at+=len(group)
    return out


def distribution(values,tau=1):
    if not values or tau<=0 or not math.isfinite(tau):raise ValueError('유효한 순위와 temperature가 필요함')
    base=min(values.values());weights={k:math.exp(-(v-base)/tau) for k,v in values.items()}
    total=sum(weights.values());return {k:v/total for k,v in weights.items()}


def compare(human_groups,agent_groups,tau=1):
    human=ranks(human_groups);agent=ranks(agent_groups)
    common=sorted(set(human)&set(agent))
    if len(common)<2:return dict(status='insufficient_candidates',K=len(common),ce=None)
    p=distribution({k:human[k] for k in common},tau);q=distribution({k:agent[k] for k in common},tau)
    ce=-sum(p[k]*math.log(max(q[k],1e-300)) for k in common);entropy=-sum(p[k]*math.log(p[k]) for k in common)
    concord=discord=tie_h=tie_a=0
    for a,b in itertools.combinations(common,2):
        h=(human[a]>human[b])-(human[a]<human[b]);v=(agent[a]>agent[b])-(agent[a]<agent[b])
        if h==v==0:continue
        if h==0:tie_h+=1
        elif v==0:tie_a+=1
        elif h==v:concord+=1
        else:discord+=1
    den=math.sqrt((concord+discord+tie_h)*(concord+discord+tie_a))
    return dict(status='compared',K=len(common),tau=tau,human_distribution=p,agent_distribution=q,
        ce=ce,human_entropy=entropy,kl=max(0,ce-entropy),uniform_ce=math.log(len(common)),
        kendall_tau_b=(concord-discord)/den if den else None,
        top1_agreement=bool(set(human_groups[0])&set(agent_groups[0])),
        coverage=len(common)/max(1,len(agent)),conditional=len(common)<len(agent))


def create(db,run,rubric,pid=None,seed=17):
    if rubric not in ('fairness','card_fit'):raise ValueError('rubric은 fairness/card_fit')
    ballots=run.ctx.get('final_assessments')
    if not ballots:raise ValueError('최종 LLM 순위가 아직 없음')
    if pid is None:pid=sorted(ballots)[0]
    if pid not in ballots:raise ValueError('평가 역할이 필요함')
    ids=list(run.ctx['shortlist']);random.Random(seed).shuffle(ids)
    mapping={f'안 {i+1}':cid for i,cid in enumerate(ids)}
    candidates=[next(c for c in run.ctx['candidates'] if c['id']==cid) for cid in ids]
    field='fairness_score' if rubric=='fairness' else 'card_fit_score'
    people=[pid]
    scores={cid:sum(next(o[field] for o in ballots[p] if o['candidate_id']==cid) for p in people)/len(people) for cid in ids}
    reference=ranking(scores)
    data=dict(rubric=rubric,pid=pid,seed=seed,tau=1,mapping=mapping,issue=run.ctx['issue'],
        pool_hash=run.ctx['pool_hash'],information_condition='own_card_and_public',
        candidates=deepcopy(candidates),reference=reference,
        agent_dispositions={o['candidate_id']:o['action'] for o in ballots[pid]},
        # Only the target role's card; never all cards.
        card=deepcopy(run.ctx['private_cards'][pid]) if pid else None,
        snapshot=run.ctx['board_snapshot'],history=deepcopy(run.ctx.get('evaluation_history',[])),human_groups=None,result=None,
        rubric_text=run.ctx['prompt_snapshot'].get(f'evaluation/{rubric}.md',''))
    data['evaluation_hash']=hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()
    row=CandidateEvaluation(run_id=run.id,data=data);db.add(row);db.flush();return row


def blind_view(row):
    d=row.data;inverse={v:k for k,v in d['mapping'].items()}
    return dict(id=row.id,run_id=row.run_id,rubric=d['rubric'],pid=d['pid'],rubric_text=d['rubric_text'],issue=d['issue'],
        evaluation_hash=d['evaluation_hash'],pool_hash=d['pool_hash'],information_condition=d['information_condition'],
        card=d['card'],public_context=d['snapshot'],discussion=[dict(who=e['requester'],to=e.get('recipient'),
            message=e['reason'],candidate=inverse.get(e.get('candidate_id'))) for e in d['history']
            if e['response'] in ('QUESTION','ANSWER','PREFER','CONDITION','PASS')],
        candidates=[dict(id=inverse[c['id']],allocations=c['allocations'],schedule_changes=c['schedule_changes'],
            tasks=c['board']['tasks'],deferred=c['board'].get('deferred',[]),omitted=c['board'].get('omitted',[]),
            plan_actions=c.get('plan_actions',[]),required_confirmations=c.get('required_confirmations',[])) for c in d['candidates']],submitted=bool(d['human_groups']))


def submit(row,groups,evaluation_hash,eligibility=None):
    d=deepcopy(row.data)
    if evaluation_hash!=d['evaluation_hash']:raise ValueError('평가 버전 불일치')
    if d['human_groups'] is not None:raise ValueError('이미 제출한 라벨은 변경할 수 없음 · 새 evaluation을 생성하세요')
    flat=[x for g in groups for x in g]
    if not groups or any(not g for g in groups) or len(flat)!=len(set(flat)):raise ValueError('빈 그룹/중복 후보')
    if set(flat)!=set(d['mapping']):raise ValueError('같은 후보 전체를 순위에 포함하세요. 동률은 같은 그룹으로 제출')
    eligibility=eligibility or {}
    if eligibility and set(eligibility)!=set(d['mapping']):raise ValueError('수락 가능 여부는 모든 후보에 대해 제출하세요')
    if any(value not in ('ACCEPT','REJECT','NEEDS_INPUT') for value in eligibility.values()):raise ValueError('유효하지 않은 수락 가능 여부')
    mapped=[[d['mapping'][x] for x in g] for g in groups]
    result=compare(mapped,d['reference'],d['tau'])
    inverse={v:k for k,v in d['mapping'].items()}
    for field in ('human_distribution','agent_distribution'):
        if field in result:result[field]={inverse[k]:v for k,v in result[field].items()}
    decisions=[(value,d['agent_dispositions'][d['mapping'][key]]) for key,value in eligibility.items()]
    result['disposition_agreement']=sum(h==a for h,a in decisions)/len(decisions) if decisions else None
    rejected=[a for h,a in decisions if h=='REJECT']
    result['human_rejected_agent_accepted_rate']=sum(a=='ACCEPT' for a in rejected)/len(rejected) if rejected else None
    d.update(human_groups=groups,human_eligibility=eligibility,result=result);row.data=d
    return result
