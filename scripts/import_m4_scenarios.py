"""Import the five M4 design scenarios without modifying the external source.

Rebuild: .venv/bin/python scripts/import_m4_scenarios.py --source /path/to/Senario
The imported source.md and board.png preserve the original design and provenance.
"""
from pathlib import Path
import argparse
import hashlib
import re
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
IDS = ['m4_t1_rescheduling','m4_t2_reallocation','m4_t3_scope_reduction','m4_t4_composite','m4_t5_infeasible']
NAMES = ['T1 · Simple Rescheduling · 일정 이동','T2 · Task Reallocation · 업무 재분배','T3 · Scope Reduction · 범위 축소','T4 · Composite Negotiation · 복합 협상','T5 · Infeasible Conflict · 해결 불가능 충돌']
ISSUES = [
 'Polish 작업을 하루 뒤인 11/23으로 이동하고 싶습니다. Bug Fix와 Core X 일정은 그대로 유지하고 싶습니다. Polish 소요량은 6h 그대로입니다.',
 'UI Integration 작업에 예상보다 하루가 더 필요합니다. 기존 8h에서 총 16h(2일)로 증가했습니다. 로직 연결 8h는 Dev 전담, 에셋 연결 8h는 Art에게 분담 가능합니다. Bug Fix는 예정대로 끝내야 합니다. 작업의 재분배를 요청합니다.',
 'Advanced Effects 구현은 기존 16h에서 32h(4일)가 필요합니다. Core Integration도 다음 주에 마쳐야 해서 Alpha 마감을 맞추기 어렵습니다. GD와 선택 기능의 Beta 이관을 논의하고 PM에게 범위 축소 승인을 요청하고 싶습니다.',
 'Character Animation은 기존 24h에서 32h(4일)로 증가해 11/20 가용 8h를 추가 사용합니다. FX Assets 잔여 4h는 11/23 오전에 수행해 12:00 전달 가능합니다. 임시 에셋은 11/20 제공 가능합니다. Dev·QA와 조정하고 싶습니다.',
 'Critical Fix의 기존 작업은 완료했지만 추가 결함으로 잔여 수정 16h(2일)가 더 필요합니다. 이 잔여 작업은 11/26·27 각 8h에만 가능합니다. QA는 완료 후 연속 2영업일 16h가 필요합니다. 11/27 릴리스 일정을 지킬 수 있는지 확인해 주세요.'
]
SUPPORT = [
 'Dev 단독으로 일정 이동 후보를 평가하며 GD·Art·QA LLM을 불필요하게 호출하지 않습니다. Hive가 제약을 검증합니다. 공통 V2 정책상 최종 적용에는 PM 선택이 필요합니다. 원안의 단독 자동 처리와는 다릅니다.',
 'Task에 명시된 로직/에셋 범위와 담당 권한을 검증하여 Dev·Art 분담을 지원합니다. Art 본인 Confirm과 PM 선택 후 적용합니다.',
 '선택 범위의 Beta 이관과 잔여 Art FX 동반 이관을 후보로 검증합니다. GD의 범위 판단과 PM의 명시적 최종 선택 전에는 이관하지 않습니다. 필수 Core와 Final QA는 유지합니다.',
 '임시 Integration과 최종 교체의 단계별 분해, 선행 FX의 최종 교체 연결, 선택 Retest의 동일 항목 Final QA 포함을 검증합니다. Retest 생략 후보에는 QA 본인 Confirm이 필요합니다. 월요일에 두 Integration 단계를 모두 끝내면 Retest 유지도 가능하므로 생략을 정답으로 강제하지 않습니다. V2 공통 정책상 적용에는 PM 최종 선택이 필요합니다.',
 'Dev 전담·분리 금지·협업 단축 금지·수정 완료 후 QA 2일·11/27 마감을 하드 제약으로 보존합니다. 미해결 시 PM에게 보류 검토를 전달하며 릴리스/마일스톤을 자동 연장하지 않습니다.'
]


def task(tid,who,title,start,hours,done=False,**ctx):
    return dict(id=tid,who=who,title=title,s0=start,d=hours/8,tag=tid,kind='done' if done else '',context=dict(
        description=title+' 작업. 1일=8h, 주말은 제외한 영업일 기준입니다.',deliverable=title+' 완료본',
        acceptance=['원 시나리오의 필수 산출물 유지','담당 권한과 선행 조건 준수'],
        splittable_hint=False,allowed_assignees=[who],allow_collaboration=False,**ctx))


def edge(src,dst,due):
    return dict(id='h_'+src+'_'+dst,**{'from':src,'to':dst},title=src+' → '+dst,what=src+' 검증 완료본',t=due)


def build(source):
    md=next(source.glob('*.md'));text=md.read_text(encoding='utf-8')
    sections=re.split(r'(?m)^# T[1-5]\. ',text)[1:]
    if len(sections)!=5:raise ValueError('T1~T5 원문이 필요합니다')
    image_dir=next(p for p in source.iterdir() if p.is_dir())
    all_tasks=[
      [task('x_spec','gd','X Spec',0,8,True),task('ux_review','gd','UX Review',2,8,True),task('icons','art','Icons',0,12,True),task('charge_anim','art','Charge Anim',2,16,True),task('core_x','dev','Core X',1,24,True),task('polish','dev','Polish',4,6,requested_start=5,latest_finish=8,max_shift_days=1,original_start=4),task('bug_fix','dev','Bug Fix',6,12,fixed_start=6,latest_finish=8),task('smoke','qa','Smoke Test',3,8,True),task('final_test','qa','Final Test',8,16,fixed_start=8,latest_finish=10)],
      [task('x_spec','gd','X Spec',0,8,True),task('ui_copy','gd','UI Copy',2,8,True),task('ui_assets','art','UI Assets',1,16,True),task('fx_assets','art','FX Assets',4,8,True),task('core_x','dev','Core X',1,24,True),task('ui_integration','dev','UI Integration',5,8,latest_finish=6),task('bug_fix','dev','Bug Fix',6,8,fixed_start=6,latest_finish=7),task('smoke','qa','Smoke Test',4,8,True),task('integration_test','qa','Integration Test',7,16,fixed_start=7,latest_finish=9)],
      [task('feature_spec','gd','Feature Spec',0,8,True),task('x_lite','gd','X Lite Review',4,4,True),task('core_assets','art','Core Assets',1,16,True),task('advanced_fx_done','art','Advanced FX 완료분',4,8,True),task('advanced_fx','art','Advanced FX 잔여',5,4,latest_finish=7,optional=True,beta_requires_pm=True),task('core_x','dev','Core X',1,24,True),task('advanced_effects','dev','Advanced Effects',5,16,optional=True,beta_requires_pm=True,latest_finish=7),task('core_integration','dev','Core Integration',6,8,latest_finish=7),task('smoke','qa','Core Smoke',4,8,True),task('final_qa','qa','Final QA',7,16,fixed_start=7,latest_finish=9)],
      [task('feature_spec','gd','Feature Spec',0,8,True),task('ux_review','gd','UX Review',3,8,True),task('scope_review','gd','Scope Review',5,8,latest_finish=7),task('character_animation','art','Character Animation',1,24,latest_finish=5),task('fx_assets','art','FX Assets 잔여',4,4,latest_finish=5.5),task('beta_handoff','art','Beta Handoff',6,8,latest_finish=8),task('core_x','dev','Core X',1,24,True),task('anim_integration','dev','Anim Integration',5,8,latest_finish=7,split_boundary='임시 에셋 Integration 6h + 최종 교체 2h; 최종 교체는 FX Assets 수신 후. 선행관계 변경은 조건부로 검증해야 함.'),task('critical_fix','dev','Critical Fix',6,8,latest_finish=7),task('smoke','qa','Smoke Test',4,8),task('retest','qa','Integration Retest',6,8,fixed_start=6,latest_finish=7,optional=True,omit_requires_confirm='qa',split_boundary='Retest 시작 전 영업일까지 최종 Integration 완료 필요. 생략은 QA 본인 Confirm 필요.'),task('final_qa','qa','Final QA',7,16,fixed_start=7,latest_finish=9)],
      [task('feature_spec','gd','Feature Spec',0,8,True),task('release_notes','gd','Release Notes',7,8),task('core_assets','art','Core Assets',1,16,True),task('final_assets','art','Final Assets',5,8,True),task('core_x','dev','Core X',1,24,True),task('critical_fix_done','dev','Critical Fix 완료분',5,24,True),task('critical_fix','dev','Critical Fix 추가 수정',8,16,earliest_start=8,latest_finish=10),task('smoke','qa','Smoke Test',4,8,True),task('final_qa','qa','Final QA',8,16,earliest_start=8,latest_finish=10)]
    ]
    all_edges=[
      [edge('core_x','final_test',8),edge('bug_fix','final_test',8)],
      [edge('ui_integration','integration_test',7),edge('bug_fix','integration_test',7)],
      [edge('core_x','core_integration',6),edge('core_integration','final_qa',7),edge('advanced_effects','final_qa',7)],
      [edge('character_animation','fx_assets',5),edge('fx_assets','anim_integration',6),edge('anim_integration','retest',6),edge('anim_integration','final_qa',7),edge('critical_fix','final_qa',7)],
      [edge('critical_fix','final_qa',8)]
    ]
    for i,sid in enumerate(IDS):
        root=ROOT/'seed'/sid;root.mkdir(exist_ok=True)
        tasks=all_tasks[i];now=8 if i==4 else 4 if i in (0,3) else 5
        source_name=['polish','ui_integration','advanced_effects','character_animation','critical_fix'][i]
        if i==1:
            target=next(t for t in tasks if t['id']==source_name)
            target['context']['splittable_hint']=True
            target['context']['required_parts']=[dict(key='logic',title='UI 로직 연결',what='UI 로직 연결 8h',effort=1,assignees=['dev']),dict(key='assets',title='UI 에셋 연결',what='UI 에셋 연결 8h',effort=1,assignees=['art'])]
            target['context']['split_boundary']='총 16h일 때 로직 연결 8h(Dev 전담) + 에셋 연결 8h(Art 가능). 다른 임의 조각은 허용하지 않음.'
        for t in tasks:
            t['context']['source_scenario']=sid
            t['context']['time_quantum']=.25
        source_task=next(t for t in tasks if t['id']==source_name)
        source_task['context']['active_participants_only']=True
        source_task['context']['allowed_change_tasks']=[['polish'],['ui_integration','bug_fix'],['advanced_effects','advanced_fx','core_integration'],['character_animation','fx_assets','anim_integration','critical_fix','retest'],['critical_fix']][i]
        if i==0:source_task['context']['single_actor']=True
        if i==2:
            source_task['context']['defer_option']=dict(milestone='Beta',with_tasks=['advanced_fx'],authorizers=['gd'],alpha_dependencies=[{'from':'advanced_effects','to':'final_qa'}])
            next(t for t in tasks if t['id']=='advanced_fx')['context']['deferred_with']='advanced_effects'
        if i==3:
            integration=next(t for t in tasks if t['id']=='anim_integration')
            integration['context'].update(splittable_hint=True,
                required_parts=[dict(key='temporary',title='임시 에셋 Integration',what='임시 에셋 기반 Integration 6h',effort=.75,assignees=['dev']),dict(key='final',title='최종 에셋 교체',what='전달받은 최종 에셋 교체 2h',effort=.25,assignees=['dev'],depends_on=['temporary'])],
                inbound_scope={'fx_assets':['final']})
            next(t for t in tasks if t['id']=='retest')['context'].update(covered_by='final_qa',coverage=['animation_integration'])
            next(t for t in tasks if t['id']=='final_qa')['context'].update(coverage=['animation_integration','critical_fix'],minimum_days=2)
        if i==4:source_task['context']['review_no_options']=True
        owners={p:[t['id'] for t in tasks if t['who']==p] for p in ('gd','art','dev','qa')}
        people=[dict(id=p,name=p.upper() if p in ('gd','qa') else p.title(),role={'gd':'기획','art':'아트','dev':'개발','qa':'QA'}[p],notes=dict(prompt_role=p),rec={tag:6 for tag in owners[p]},wants=[]) for p in owners]
        # In T2 Art explicitly has the asset integration skill; speed is unchanged.
        people[1]['rec']['ui_integration']=6
        notes={
          'gd':'Core X·Core Integration은 P0 필수. Advanced Effects는 P2 선택으로 제외해도 Alpha 필수 요구사항 충족. Beta 이관 제안 가능, 확정 권한은 PM.',
          'art':'신규 작업 인수는 본인 Confirm 필요. UI Integration 에셋 연결 8h 수행 가능. Advanced Effects Beta 이관 PM 승인 시 관련 잔여 FX도 이관 가능.',
          'dev':'필수 Core·Bug Fix·Critical Fix는 타인 이관 불가. Polish는 11/25까지, 1영업일 이내 이동 가능. UI 로직 8h는 전담. 가용일 하루 8h를 초과할 수 없음.',
          'qa':'선행 구현 완료 후 검증. Final QA 16h는 연속 2영업일이며 단축·사전 테스트 불가. T4의 선택 Retest만 본인 Confirm 후 생략 가능; Final QA에 동일 항목 포함.'}
        notes=[
          dict(gd='다른 사람 일정에 영향 없는 Polish 이동에는 협의가 필요하지 않음.',art='Polish 변경은 내 업무에 영향 없음.',dev='Polish는 P3, 11/25까지 완료. 본인 작업은 1영업일 이내 이동 가능. 11/23 가용 8h. Bug Fix와 Core X 일정 유지.',qa='Final Test는 Core X와 Bug Fix 완료 후 수행. Polish는 필수 테스트 선행 작업이 아님.'),
          dict(gd='필수 UI 요구사항을 유지.',art='11/23 가용 8h, 기존 배정 없음. UI Integration 에셋 연결 8h 수행 역량 있음. 신규 인수는 Art 본인 Confirm 필요.',dev='11/23·24 각 8h 가용. UI 로직 연결 8h와 Bug Fix 8h는 Dev 전담. UI는 로직/에셋 연결 각 8h로 분리 가능.',qa='UI Integration 및 Bug Fix 완료 후 11/25~26 Integration Test 16h. 담당 변경으로 테스트 범위 축소 불가.'),
          dict(gd='Core X·Core Integration은 P0 필수. Advanced Effects는 P2 선택이며 제외해도 Alpha 필수 요구사항 충족. 범위 축소 제안 가능, 확정 권한 없음.',art='Advanced FX 12h 중 8h 완료. 잔여 4h는 11/23 예정. PM이 Advanced Effects Beta 이관을 승인하면 잔여 FX도 자동 이관되며 별도 Confirm 불필요.',dev='11/23·24 각 8h 가용. Core Integration 8h 필수. Advanced Effects 32h이며 두 작업은 독립적. 기능 우선순위는 GD에게 확인해야 함.',qa='11/25~26 Final QA 16h 고정. Advanced Effects 제외 시 Core X와 Core Integration만 검증 가능. 기존 일정 변경 없음.'),
          dict(gd='기존 범위 내 재배치와 선택 중간 검증 생략에 PM 승인 불필요.',art='Character Animation 추가 8h는 11/20에 수행. FX Assets 잔여 4h는 11/23 오전, 12:00 전달. 임시 에셋은 11/20 제공 가능.',dev='11/23·24 각 8h 가용. Anim Integration 8h와 Critical Fix 8h 필수. 임시 에셋 Integration 6h와 최종 교체 2h로 분해 가능. 교체는 최종 FX 수신 후. Critical Fix는 독립적.',qa='11/24 Retest 8h는 최종 Integration이 전 영업일까지 끝나야 함. Retest 선택 검증이며 본인 Confirm 후 생략 가능. 동일 항목을 11/25~26 Final QA 16h에 포함. Final QA는 Anim Integration과 Critical Fix 모두 완료 후.'),
          dict(gd='11/27 릴리스 목표. 공식 마일스톤 변경은 상위 승인 필요.',art='추가 수정은 Dev 전담이라 이관 받을 수 없음.',dev='추가 수정 16h는 11/26·27 각 8h에만 수행. 병렬 처리·타인 이관·수정 범위 축소·협업 단축 모두 불가.',qa='추가 수정 완료 후 Final QA 16h를 연속 2영업일 수행. 사전 테스트·부분 검증·시간 단축 불가.')
        ][i]
        cards=[dict(who=p,auto_days=0 if p=='art' else 1,wait_days=0,gives_help=True,note=notes[p],policy=dict(approved=True,source_note='M4 시나리오 원문에 명시된 가용 시간',unavailable=[])) for p in owners]
        # Preserve availability in business-day coordinates (Mon 11/16 = 0).
        if i in (1,2,3):
            next(c for c in cards if c['who']=='dev')['policy']['unavailable']=[dict(start=4,end=5),dict(start=7,end=10)]
        if i==1:
            next(c for c in cards if c['who']=='art')['policy']['unavailable']=[dict(start=6,end=10)]
        if i==4:
            for c in cards:
                if c['who']=='dev':c['note']+=' T5 추가 수정 16h는 11/26·27에만 수행. 분해·양도·범위 축소·협업 시간 단축 모두 금지.'
        marker='final_test' if i==0 else 'integration_test' if i==1 else 'final_qa'
        tasks.append(task('milestone','gd','Release' if i==4 else 'Alpha',10 if i in (0,4) else 9,0,completion_barrier=True))
        tasks[-1]['kind']='milestone'
        hands=all_edges[i]+[edge(marker,'milestone',10 if i in (0,4) else 9)]
        meta=dict(title=NAMES[i],summary=ISSUES[i],phase='issue',now=now,week_start='2026-11-16',deadline_label='11/27 릴리스' if i==4 else '11/27 Alpha' if i==0 else '11/26 Alpha',narr='다음 시나리오 이슈를 눌러 원문의 변경 요청을 처리하세요.',source_task=source_name,source='Senario/M4 시나리오 설계',source_sha256=hashlib.sha256(text.encode()).hexdigest(),engine_support=SUPPORT[i],normalization_note=('원문 이미지의 막대 위치와 시간 길이가 맞지 않는 곳은 본문 시간(h)을 우선했습니다. T1은 11/23 가용 8h 조건에 따라 Bug Fix를 11/24 시작으로 고정하고 Final Test는 11/26~27로 정규화했습니다. T5 초기 보드에는 새로 발견된 잔여 수정 16h를 표시합니다.'))
        data=dict(meta=meta,people=people,cards=cards,tasks=tasks,handoffs=hands,records=[],rules=[dict(key='deadline',label=meta['deadline_label'],value=dict(week_end=10 if i in (0,4) else 9)),dict(key='weekly_cap',label='2주 계획·1일 8h·동시 작업 금지',value=dict(days=10)),dict(key='pm_only',label='범위 축소·마일스톤 변경은 PM 권한',value=dict(actions=['cut','defer'])),dict(key='rounds',label='최대 15라운드',value=dict(max=15)),dict(key='pref',label='후보 선택 참고',value=dict(choice='fair'),locked=False)])
        feed=dict(issue=dict(task=source_name,label=NAMES[i]+' · 변경 요청',now=now,next_phase='end',narr=ISSUES[i],records=[dict(who='art' if i==3 else 'dev',src='시나리오 변경 요청',text=ISSUES[i])]))
        estimate={1:2,2:4,3:4,4:2}.get(i)
        mock=dict(reestimate=[dict(match=dict(who='art' if i==3 else 'dev',contains=ISSUES[i][:18]),answer=dict(task=source_name,days=estimate,basis='명시된 원 시나리오의 소요량'))] if estimate else [],split={})
        for name,obj in [('team.yaml',data),('feed.yaml',feed),('mock_llm.yaml',mock)]:
            (root/name).write_text(yaml.safe_dump(obj,allow_unicode=True,sort_keys=False),encoding='utf-8')
        section='# T'+str(i+1)+'. '+sections[i]
        section=re.sub(r'!\[image[^\]]*\]\([^\n]+\)',f'[원본 일정 보드](/demos/{sid}/board)',section)
        (root/'source.md').write_text(section,encoding='utf-8')
        shutil.copyfile(image_dir/('image.png' if i==0 else f'image {i}.png'),root/'board.png')
    (ROOT/'seed/catalog.yaml').write_text(yaml.safe_dump(dict(default=IDS[0],scenarios=IDS),sort_keys=False),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    build(parser.parse_args().source)
