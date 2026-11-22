"""Run the current deterministic demo set, save receipts, and rebuild the report.

  PLANBEE_LLM=mock .venv/bin/python run_all_demos.py
"""
from pathlib import Path
import json, os, subprocess, sys

ROOT=Path(__file__).resolve().parent
os.environ['PLANBEE_LLM']='mock'
from app import sim, store

out={}
for demo in store.demos():
    state,metrics=sim.simulate(demo)
    out[demo]={'metrics':metrics,'resolved':state.get('resolved',[]),'granted':state.get('granted',[]),
               'stats':state.get('stats',{}),'warnings':state.get('gate',{}).get('warnings',[]),
               'phase':state.get('meta',{}).get('phase')}
    print(demo, 'OK', 'messages=',metrics['proxy_msgs'],'confirms=',metrics['confirms'],flush=True)
(fair_state,fair_metrics)=sim.simulate('demo4_planbee',handoff_updates={'evidence':{'t':4.5}})
out['demo4_no_deadline_risk']={'metrics':fair_metrics,'resolved':fair_state.get('resolved',[]),
    'stats':fair_state.get('stats',{}),'warnings':fair_state.get('gate',{}).get('warnings',[]),
    'phase':fair_state.get('meta',{}).get('phase'),
    'scenario':'same Demo 4 input, evidence handoff relaxed to Friday evening so the initial dependency check has no deadline risk'}
print('demo4 no-deadline-risk fairness route OK','messages=',fair_metrics['proxy_msgs'],
      'confirms=',fair_metrics['confirms'],flush=True)
(ROOT/'eval/current_version_runs.json').write_text(json.dumps(
    {'date':'2026-11-18','provider':'Mock','mode':'planbee',
     'default_metrics':{k:v['metrics'] for k,v in out.items()},'default_runs':out},
    ensure_ascii=False,indent=2)+'\n')

from evaluate_cards import run as run_card_conditions
run_card_conditions()

from app.sim import simulate
comparison=[]
for pref in ['fast','fair']:
    state,metrics=simulate('demo4_planbee',pref=pref)
    comparison.append({'pref':pref,'metrics':metrics,'state':state})
folder=ROOT/'eval/demo4_planbee';folder.mkdir(parents=True,exist_ok=True)
(folder/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+'\n')
lines=['# 데모 4 · 업무 맥락·휴가·공정성','','Mock 비교는 사건·카드·경력·업무량을 고정하고 후보 선택 기준만 바꿨다.','',
       '|기준|담당자|사람 확인|부담 분산|부담 최대-최소|제출일 초과|','|---|---|---:|---:|---:|---:|']
for r in comparison:
    m=r['metrics'];who=r['state']['resolved'][0]['body'].split('가 ')[0].split('이 ')[0]
    lines.append(f"|{r['pref']}|{who}|{m['confirms']}|{m['fairness']['variance']}|{m['fairness']['range']}|{m['past_deadline']}|")
(folder/'RESULTS.md').write_text('\n'.join(lines)+'\n')

from run_bundle_demo import run_case
bundle_dir=ROOT/'eval/bundles';bundle_dir.mkdir(parents=True,exist_ok=True)
bundle_results=[]
for case in ['swap','split','chain','reject']:
    r=run_case(case);bundle_results.append(r)
    (bundle_dir/f'{case}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
(bundle_dir/'results.json').write_text(json.dumps(bundle_results,ensure_ascii=False,indent=2)+'\n')
rows=['# 묶음 이동 실행 결과','','메모리 DB에서 실제 구현을 실행한 결과. 자동 제안 생성이나 Live LLM 비교가 아니다.','',
      '|사례|결과|사람 확인|규칙 통과|','|---|---|---:|---|']
for r in bundle_results:
    rows.append(f"|{r['case']}|{r['result']['outcome']}|{len(r['result'].get('waiting_for',[]))}|{r['after']['gate']['ok']}|")
(bundle_dir/'RESULTS.md').write_text('\n'.join(rows)+'\n')
print('bundles OK', [r['result']['outcome'] for r in bundle_results],flush=True)

subprocess.run([sys.executable,str(ROOT/'docs/build_backend_report.py')],check=True,cwd=ROOT)
