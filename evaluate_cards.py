"""Four information/authority conditions on the same four-person scenario.
Mock only; in-memory DB. The engine always keeps the actual schedule for safety.
python evaluate_cards.py [--condition 1|2|3|4]
"""
import argparse
import json
from pathlib import Path
from app import sim, store, workflow
from app.llm import MockLLM, Reply
OUT=Path(__file__).resolve().parent/'eval'/'cards_four_conditions'
CONDITIONS=[('1_none','위임 카드 없음',False,False),('2_objective','객관적 여건만',True,False),('3_authority','권한만',False,True),('4_both','두 정보 모두',True,True)]
class ViewMock(MockLLM):
    def __init__(self,objective):
        super().__init__();self.objective=objective
    def reply(self,person,card,piece,c):
        if self.objective:
            return super().reply(person,card,piece,c)
        # No private workload/deferrable-task/experience inference in this condition.
        # The common one-day task quote is public and identical for both candidates.
        # A positive proposal is provisional until the engine checks the actual plan.
        if c.get('violation'):
            return Reply(type='REJECT',reason='엔진의 일정 검사에서 불가능하다고 확인됨')
        if piece.tag in (card.refuse_tags or []):
            return Reply(type='REJECT',reason='카드의 업무 거부')
        return Reply(type='ACCEPT' if piece.days<=card.auto_days else 'NEEDS_INPUT',days=piece.days,reason='개인 작업량은 보지 않은 잠정 답 · 실제 일정은 엔진 검사')
def run(selected=None):
    OUT.mkdir(parents=True,exist_ok=True); results=[]
    for key,label,objective,authority in CONDITIONS:
        if selected and not key.startswith(str(selected)+'_'):continue
        old=store.DEMO;old_get=workflow.get_llm
        store.use_demo('demo3_cards'); policy=ViewMock(objective)
        workflow.get_llm=lambda:policy
        changes={pid:{'auto_days':1 if authority else 0,'wait_days':0,'gives_help':False,'refuse_tags':[]} for pid in ['mia','jun','sol','ara']}
        try:s,m=sim.simulate('demo3_cards',cards=changes)
        finally:workflow.get_llm=old_get;store.use_demo(old)
        item=dict(id=key,label=label,objective=objective,authority=authority,metrics=m,state=s)
        results.append(item);(OUT/(key+'.json')).write_text(json.dumps(item,ensure_ascii=False,indent=2))
        lines=[f'# {label}', '',f'客観情報={objective} / 自動権限={authority}'.replace('客観情報','객관 정보').replace('自動権限','자동 권한'),'']
        for msg in s['log']:
            if msg['k']=='proxy':
                text=' · '.join(f['t'] for f in msg['f']);text+=' / '+msg['basis'] if msg['basis'] else ''
                lines.append(f"- {msg['t']} {msg['from']} → {msg['to'] or '기록'}: {text}")
            else:lines.append(f"- {msg['t']} {msg['k']}: {msg.get('text','')}")
        lines+=['','## 결과',json.dumps(m,ensure_ascii=False,indent=2)]
        (OUT/(key+'.md')).write_text('\n'.join(lines)+'\n')
        print(label, {k:m[k] for k in ['pm_decisions','confirms','hive_rejects','past_deadline']})
    if not selected:
        (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        md=['# 동일 시나리오의 네 조건','', '객관 정보=프록시에게 제공하는 본인 작업량·숙련도·미룰 수 있는 일. 권한=새 업무 1일까지 자동 수락. 엔진은 모든 조건에서 실제 일정을 검사한다. 모든 사람 확인은 수락으로 자동 처리한 Mock 실행이다.','', '|조건|객관 정보|자동 권한|본인 확인|엔진 반려|PM 결정|제출일 초과 작업|','|---|---|---|---:|---:|---:|---:|']
        for r in results:
            m=r['metrics'];md.append(f"|{r['label']}|{r['objective']}|{r['authority']}|{m['confirms']}|{m['hive_rejects']}|{m['pm_decisions']}|{m['past_deadline']}|")
        (OUT/'RESULTS.md').write_text('\n'.join(md)+'\n')
    return results
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--condition',type=int,choices=[1,2,3,4]);run(ap.parse_args().condition)
