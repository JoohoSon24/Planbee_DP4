"""Import the five-person T6 source without changing existing scenarios.

Rebuild: .venv/bin/python scripts/import_t6_scenario.py --source /path/to/export
"""
from pathlib import Path
import argparse,hashlib,shutil,yaml
ROOT=Path(__file__).resolve().parents[1]
SID='m4_t6_game_demo'
ISSUE='제가 목요일 오후 Q2 통합 QA 스모크를 진행할 수 없습니다. 금요일 오전 최종 회귀와 서명은 제가 담당하겠습니다. Ben·Leo와 스모크 분담과 데모 빌드 일정을 조정해 주세요.'
SUPPORT='5명·12개 원 업무와 데모 milestone을 연결합니다. 기본 예시는 Zoe 목요일 오후 부재를 반영한 Q2 스모크/최종 회귀 분담입니다. 스모크 0.5일과 Zoe 최종 회귀 0.5일, 전체 1일 QA와 빌드 선행조건을 코드로 보존합니다. Ben 또는 Sam에게 P0 스모크를 넘기면 본인 확인을 요청합니다. T4의 알고리즘 자동 동의는 T6에 적용하지 않습니다. 현재 V2는 PM 최종 선택을 요구하므로 원문의 H04 PM 0회 경로와 다릅니다. 신규 상점 Task 생성·교체와 작성자 진행률 동기화 전용 경로는 아직 구현되지 않았으며 원문 기대 사례로 구분합니다.'
NORMALIZATION='시간축은 2026-11-23 월요일=0, 화요일 13:00=1.5, 금요일 17:00=5입니다. Task d는 기준 시각 이후 남은 시간이며 진행률은 원문의 작성자 추정값을 별도 보존합니다. 공통 초기 보드에 기본 H04의 Zoe 목요일 오후 부재를 가용 시간 제약으로 반영했으므로 기존 Q2 배정은 기한 위험 상태입니다. 원문 G3의 금요일 오후 0.5일은 13:00~17:00이지만 16:00 유효 빌드 조건과 충돌합니다. 현재 실행은 공통 데모 마감 17:00을 적용하고 16:00 조건은 미확정 원문 조건으로 보존하며, 이를 충족했다고 주장하지 않습니다. 숙련도는 원문 문자열로 보존하고 과거 실적 건수를 만들어 넣지 않습니다.'

def build(source):
    md=next(source.glob('*.md'));raw=md.read_text();image=next(source.rglob('image.png'))
    dest=ROOT/'seed'/SID;dest.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(md,dest/'source.md');shutil.copyfile(image,dest/'board.png')
    cases=next((source.parent/'Senario').glob('M4 시연용 사례 정리*.md'),None) if (source.parent/'Senario').exists() else None
    if cases:shutil.copyfile(cases,dest/'cases.md')
    names={'mia':('Mia','그림'),'leo':('Leo','개발'),'sam':('Sam','서버'),'ben':('Ben','레벨'),'zoe':('Zoe','테스트')}
    skills={'mia':{'아트':'능숙','UI':'가능'},'leo':{'게임플레이':'능숙'},'sam':{'서버':'능숙','UI':'가능','테스트':'가능'},'ben':{'UI':'능숙','레벨':'능숙','테스트':'가능'},'zoe':{'테스트':'능숙','UI':'가능'}}
    notes={
      'mia':'아트·UI를 받으며 서버·QA·게임플레이는 받지 않습니다. 신규 인수 0.5일까지 프록시 수락. P0 기한 변경은 본인 확인. 이펙트 완성을 희망합니다.',
      'leo':'보스 AI·게임플레이 연결·데모 빌드를 받으며 아트·서버·UI·독립 QA는 받지 않습니다. 0.5일까지 프록시 수락. 러프 기반 임시 연결은 Leo 본인 확인. G3는 Zoe의 최종 회귀·서명 후 수행합니다.',
      'sam':'서버·저장 작업만 1일까지 프록시 수락합니다. 아트·게임플레이는 받지 않습니다. UI·테스트 수행 역량은 있으나 테스트는 받는 일 밖이며 QA 대행에는 Sam 본인 동의가 필요합니다.',
      'ben':'UI·레벨·스모크 QA를 받으며 서버·아트·보스 게임플레이는 받지 않습니다. 1일까지 프록시 수락하지만 P0 소유권 변경에는 Ben 본인 확인이 필요합니다. Q2 스모크 0.5일을 목요일 오후에 수행할 수 있습니다. 레벨 완성을 희망합니다.',
      'zoe':'테스트만 받으며 서버·아트·게임플레이 구현은 받지 않습니다. 0.5일까지 프록시 수락합니다. Q2 총 1일 QA는 줄일 수 없습니다. 금요일 오전 최종 회귀 0.5일과 서명은 Zoe 전담이며 직접 확인합니다. 기본 H04에서 목요일 오후에는 부재입니다.'}
    people=[dict(id=k,name=n,role=r,rec={},wants=['이펙트 완성'] if k=='mia' else ['레벨 완성'] if k=='ben' else ['QA 품질 유지'] if k=='zoe' else [],notes=dict(prompt_role='t6_'+k,source_skills=skills[k])) for k,(n,r) in names.items()]
    cards=[dict(who=k,auto_days=1 if k in ('sam','ben') else .5,wait_days=0,gives_help=True,note=notes[k],policy=dict(approved=True,source_note='T6 원문 및 기본 H04 보고',unavailable=[dict(start=3.5,end=4)] if k=='zoe' else [])) for k in names]
    def task(tid,who,title,start,days,priority='P0',**extra):
        context=dict(description=title+'; 원문 Task ID '+tid,deliverable=title+' 완료본',acceptance=['원문 필수 산출물과 선행조건 유지'],priority=priority,time_quantum=.25,allowed_assignees=[who],allow_collaboration=False,splittable_hint=False,active_participants_only=True,latest_finish=5)
        context.update(extra)
        return dict(id=tid,who=who,title=tid+' · '+title,s0=start,d=days,tag=tid,context=context)
    tasks=[task('A1','mia','보스 그림',1.5,1,progress_claim=.33,progress_basis='원문 작성자의 전체 33% 진행 주장',parts_description='러프 0.5일 + 최종 0.5일'),task('A2','mia','이펙트 다듬기',3,1,'P1',optional=True,defer_option=dict(milestone='Next sprint',authorizers=['mia'])),
      task('G1','leo','보스 AI',1.5,.5,progress_claim=.5),task('G2','leo','보스전 연결',2.5,1,parts_description='Leo 본인 승인 시 임시 연결 0.5 + 최종 반영 0.5. 현재 기본 H04에서는 전체 유지'),
      task('G3','leo','데모 빌드',4.5,.5,fixed_start=4.5,source_build_cutoff='16:00 (원문 미확정 충돌 조건)',acceptance=['유효한 P0 빌드','Q2 최종 회귀·서명 완료 후 착수','현재 실행 마감 17:00, 원문 16:00 충돌은 별도 명시']),
      task('S1','sam','저장 기능',1.5,.5,progress_claim=.5),task('S2','sam','서버 배포',2,1,parts_description='동일 Sam의 0.5+0.5 중단·재개는 원문의 시연 가정; 현재 기본 경로는 연속 1일'),
      task('S3','sam','랭킹',3,1,'P1',optional=True,feature_flag='OFF',defer_option=dict(milestone='Next sprint',authorizers=['sam'])),
      task('B1','ben','스테이지3 배치',1.5,1,external_prerequisite='월요일 완료된 스테이지3 배경'),task('B2','ben','메뉴 화면',2.5,1,'P1',optional=True,defer_option=dict(milestone='Next sprint',authorizers=['ben'])),
      task('Q1','zoe','스테이지1·2 테스트',1.5,.5,progress_claim=.5,external_prerequisite='기존 스테이지1·2 구현 완료'),
      task('Q2','zoe','통합 QA',3.5,1,splittable_hint=True,minimum_days=1,latest_finish=4.5,allowed_change_tasks=['Q2','S3'],discussion_participants=['leo'],transfer_requires_confirm=['ben','sam'],preserve_personal_confirmation=True,
        required_parts=[dict(key='smoke',title='Q2 스모크',what='목요일 오후 통합 스모크 0.5일: G2·S2·B1·Q1 결과 확인',effort=.5,depends_on=[],assignees=['zoe','ben','sam']),dict(key='regression',title='Q2 최종 회귀·Zoe 서명',what='금요일 오전 최종 회귀 0.5일 및 Zoe 최종 서명',effort=.5,depends_on=['smoke'],assignees=['zoe'])])]
    tasks.append(dict(id='milestone',who='leo',title='Demo · 11/27 17:00',s0=5,d=0,kind='milestone',tag='milestone',context=dict(completion_barrier=True)))
    edges=[('A1','A2',3),('A1','G2',2.5),('G1','G2',2.5),('S1','S2',2),('S2','S3',3),('B1','B2',2.5)]+[(s,'Q2',3.5) for s in ('G2','S2','B1','Q1')]+[(s,'G3',4.5) for s in ('G2','S2','B1','Q2')]+[('G3','milestone',5)]
    hands=[dict(id='h_'+a+'_'+b,**{'from':a,'to':b},title=a+' → '+b,what=a+' 원문 산출물',t=t) for a,b,t in edges]
    meta=dict(title='T6 · Game Demo · 5인 게임 데모 협상',summary='5명·12개 Task, 11/27 17:00 데모. 기본: Zoe 목요일 오후 부재와 Q2 분담.',phase='issue',now=1.5,week_start='2026-11-23',deadline_label='11/27 17:00 데모',source_task='Q2',source='제공된 M4 시연용 시나리오 export',source_sha256=hashlib.sha256(md.read_bytes()).hexdigest(),engine_support=SUPPORT,normalization_note=NORMALIZATION,narr=ISSUE)
    team=dict(meta=meta,people=people,cards=cards,tasks=tasks,handoffs=hands,records=[],rules=[dict(key='deadline',label=meta['deadline_label'],value=dict(week_end=5)),dict(key='weekly_cap',label='1일 8시간·개인 주간 용량 5일',value=dict(days=5)),dict(key='rounds',label='토론 한도',value=dict(max=15)),dict(key='pref',label='공정성 참고',value=dict(choice='fair'),locked=False)])
    feed=dict(issue=dict(task='Q2',label='T6 · Zoe Q2 스모크 부재',now=1.5,next_phase='end',narr=ISSUE,records=[dict(who='zoe',src='본인 인계 변경 보고',text=ISSUE)]))
    for name,data in [('team.yaml',team),('feed.yaml',feed),('mock_llm.yaml',dict(reestimate=[],split={}))]:(dest/name).write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False))
    catalog_path=ROOT/'seed/catalog.yaml';catalog=yaml.safe_load(catalog_path.read_text())
    if SID not in catalog['scenarios']:catalog['scenarios'].append(SID)
    catalog_path.write_text(yaml.safe_dump(catalog,allow_unicode=True,sort_keys=False))
    print(dest)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    build(parser.parse_args().source)
