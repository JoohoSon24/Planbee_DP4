"""Rebuild the two reproducible, synthetic multilateral discussion scenarios."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def person(pid, name, role, past=0):
    return dict(id=pid, name=name, role=role, rec={'계약':6,'테스트':6,'운영':6}, wants=[], notes={'past_effort':past})


def card(pid, days=1, note='', refuse=None, unavailable=None):
    return dict(who=pid, auto_days=days, refuse_tags=refuse or [], note=note,
        policy=dict(source_note=note, busy=False, unavailable=unavailable or [], weekly_limit=None, questions=[], approved=True))


def task(tid, who, title, start, days, tag, deliverable, kind='', split=False):
    return dict(id=tid, who=who, title=title, s0=start, d=days, tag=tag, kind=kind,
        context=dict(description=f'{title} 작업을 수행하고 {deliverable}을 전달한다.', purpose=title,
            deliverable=deliverable, splittable_hint=split,
            split_boundary='계약·픽스처를 공유한 독립 검증 조각만 분리한다.' if split else '동일 담당자가 전체를 검증한다.',
            acceptance=['재현 가능한 정상·실패 사례 포함','기존 데이터·권한 경계를 유지','후속 담당자가 산출물을 검증']))


def hand(hid, source, target, title, due):
    return dict(id=hid, **{'from':source,'to':target}, title=title, what=title+' 검증 산출물', t=due)


def rules(rounds=15, spread=10):
    return [dict(key=k,label=label,value=value) for k,label,value in [
        ('deadline','금요일 11/20 제출',{'week_end':5}),('weekly_cap','주 5일',{'days':5}),
        ('pm_only','범위·미루기는 PM',{'actions':['cut','defer']}),('rounds',f'최대 {rounds}라운드',{'max':rounds}),
        ('pref','최초 요청 참고: 부담 균형',{'choice':'fair'}),('fairness','부담 차이 검토',{'min_range':spread,'min_gap':2})]]


def allocation(who,title,days,effort):
    return dict(who=who,title=title,days=days,effort=effort,what=title+' 독립 검증')


def dialogue(who, mode, version, action, reason, allocations=None):
    answer=dict(action=action,reason=reason)
    if allocations:answer['allocations']=allocations
    return dict(match=dict(who=who,mode=mode,version=version,tag='계약'),answer=answer)


def write(name, team, feed, mock):
    root=ROOT/'seed'/name;root.mkdir(exist_ok=True)
    for filename, data in [('team.yaml',team),('feed.yaml',feed),('mock_llm.yaml',mock)]:
        (root/filename).write_text(yaml.safe_dump(data,allow_unicode=True,sort_keys=False),encoding='utf-8')


def demo5():
    people=[person('hana','하나','백엔드',8),person('bora','보라','백엔드'),person('chan','찬','백엔드'),person('duri','두리','백엔드',2),
            person('eun','은','QA',2),person('faye','페이','QA',2),person('geo','지오','운영',2),person('haru','하루','운영',2)]
    cards=[card('hana',1,'상태 전이 코어는 유지하고 독립 계약 테스트만 나눕니다.'),card('bora',.75,'계약 검증은 0.75일 분량만 맡고 나머지는 동료에게 제안합니다.'),
           card('chan',.5,'기존 약속 때문에 새 계약 검증은 0.5일만 약속합니다.'),card('duri',1,'보안 담당이라 새 계약 작업은 맡지 않습니다.',['계약']),
           card('eun',1,'릴리스 QA의 판단과 승인 책임은 유지합니다.'),card('faye',1,'독립된 회귀 픽스처를 검증합니다.'),
           card('geo',1,'QA 산출물을 받은 뒤 배포합니다.'),card('haru',1,'금요일 오후는 가용 시간이 없습니다.',unavailable=[dict(start=4.5,end=5,reason='교육')])]
    tasks=[task('contract','hana','다중 테넌트 상태 전이·계약 검증',0,3,'계약','상태 전이 코어와 계약 테스트',split=True),
           task('audit','hana','감사 로그 승인',3,1,'운영','승인된 감사 이벤트 목록'),
           task('bora_base','bora','기존 파서 호환성',3.5,.5,'계약','호환성 결과'),task('chan_base','chan','멱등키 조사',3.5,.5,'계약','멱등성 샘플'),
           task('security','duri','접근 제어 감사',0,1,'운영','접근 제어 판정'),task('rotate','duri','서명 키 회전',2,.5,'운영','키 전환 체크리스트'),
           task('qa_setup','eun','릴리스 QA 환경',0,.5,'테스트','재현 가능한 환경'),task('qa_pack','eun','승인·실패 경로 회귀',3,1,'테스트','회귀 검사 결과',split=True),
           task('faye_base','faye','테스트 데이터 비식별화',0,.5,'테스트','비식별 픽스처'),task('faye_docs','faye','QA 인수 문서',4,.5,'테스트','인수 체크리스트'),
           task('infra','geo','스테이징 네트워크',0,.5,'운영','스테이징 주소'),task('release','geo','통합 릴리스 점검',4,.5,'운영','배포 가능 빌드'),
           task('observe','haru','관측 대시보드',0,1,'운영','오류율·지연 대시보드'),task('rollback','haru','롤백 모의훈련',3,.5,'운영','복구 시간 기록'),
           task('contract_gate','duri','M1 계약 동결',3,0,'계약','계약 동결',kind='milestone'),
           task('security_gate','duri','M2 보안 승인',3,0,'운영','보안 승인',kind='milestone'),
           task('qa_gate','faye','M3 QA 통과',4,0,'테스트','QA 판정',kind='milestone'),
           task('release_gate','geo','M4 릴리스 승인',4.5,0,'운영','릴리스 승인',kind='milestone'),
           task('monitor','geo','배포 후 관측',4.5,.5,'운영','30분 관측 요약'),task('final','hana','최종 체크리스트 확인',4.5,.5,'운영','릴리스 체크리스트')]
    hands=[hand('contract_ready','contract','contract_gate','계약 동결본',3),hand('qa_input','contract','qa_pack','테스트 가능한 계약 코어',3),
           hand('security_ready','security','security_gate','접근 제어 결과',2),hand('qa_ready','qa_pack','release','릴리스 QA 판정',4),
           hand('qa_checkpoint','qa_pack','qa_gate','회귀 결과',4),hand('audit_ready','audit','release_gate','감사 로그 승인',4),
           hand('release_ready','release','release_gate','릴리스 빌드',4.5),hand('monitor_ready','release','monitor','관측 시작 승인',4.5),
           hand('final_ready','release_gate','final','배포 체크리스트',4.5)]
    feed={'start':dict(label='1/3 · 계약 검증 분담 5라운드',now=0,next_phase='qa',narr='보라의 거절과 찬의 재제안을 거쳐 세 사람의 분담 동의를 받습니다.',records=[dict(who='hana',src='작업',text='계약 검증 분담을 논의합니다.')]),
          'qa':dict(label='2/3 · QA 지연과 의존 일정 복구',now=1,next_phase='review',narr='회귀 범위 증가를 읽고 독립 픽스처를 분리합니다.',records=[dict(who='eun',src='저장소',text='실패 경로 회귀 추가로 반일 증가')]),
          'review':dict(label='3/3 · 릴리스 전체 일정 재검사',now=2,next_phase='end',narr='마지막 관측 기록을 읽고 약속과 부담을 검사합니다.',records=[dict(who='geo',src='작업',text='스테이징과 릴리스 인수 조건 확인 완료')])}
    mock=dict(reestimate=[dict(match=dict(who='eun',contains='반일 증가'),answer=dict(task='qa_pack',days=1.5,basis='독립 실패 경로 픽스처 반일 추가'))],
        split={'contract':dict(piece=dict(title='독립 계약 검증',days=2,tag='계약',what='정상·실패 계약 검증',handover='계약 스키마와 재현 픽스처'),keep=dict(title='상태 전이 코어',days=1)),
               'qa_pack':dict(piece=dict(title='추가 실패 경로 픽스처',days=.5,tag='테스트',what='실패 경로 검증'),to='downstream',keep=dict(title='릴리스 회귀 코어',days=1))},
        bid={'추가 실패 경로 픽스처':{'faye':dict(days=.5)}}, discussion=[
            dialogue('bora','respond',1,'REJECT','내 설정은 계약 검증 0.75일까지만 허용합니다. 나눠 주세요.'),
            dialogue('bora','revise',1,'COUNTER','나는 0.75일, 찬에게 나머지 범위를 요청합니다.',[allocation('bora','정상 경로 계약',.75,1),allocation('chan','실패 경로 계약',1.25,1)]),
            dialogue('chan','respond',2,'REJECT','현재 일정과 내 설정상 0.5일까지만 약속할 수 있습니다.'),
            dialogue('chan','revise',2,'COUNTER','픽스처를 재사용하면 내 범위를 0.5일에 검증합니다. 새 버전으로 재동의해 주세요.',[allocation('bora','정상 경로 계약',.75,1),allocation('chan','실패 경로 계약',.5,1)])])
    team=dict(meta=dict(title='데모 5 · 8인 릴리스와 5라운드 분담',phase='start',now=0,week_start='2026-11-16',deadline_label='릴리스 · 11/20 금',narr='계약 동결 → QA → 릴리스의 세 단계를 실행해 보세요.',summary='8명·20개 작업·4개 milestone. 거절, 제3자, 재동의와 QA 지연 복구.',scenario_doc='demo5_release_discussion.md'),people=people,cards=cards,tasks=tasks,handoffs=hands,records=[],rules=rules())
    write('demo5_release',team,feed,mock)


def demo6():
    ids=[('ira','이라','백엔드',12),('june','준','백엔드',0),('kai','카이','백엔드',0),('lena','레나','백엔드',2),
         ('mina','미나','QA',2),('pia','피아','QA',2),('quinn','퀸','QA',2),('noel','노엘','운영',2),('olin','올린','운영',2),('rhea','레아','운영',2)]
    people=[person(*x) for x in ids]
    cards=[card(pid,1, '전체 묶음과 선후 약속을 확인한 뒤 동의합니다.') for pid,_,_,_ in ids]
    cards[1]=card('june',1,'한 명이 계약 검증 전체를 맡지 않습니다. 작업 범위를 분리해 주세요.')
    cards[2]=card('kai',1,'검증 캐시를 활용할 수 있지만 확정안의 일정과 범위에 다시 동의해야 합니다.')
    tasks=[task('ledger','ira','교차 리전 원장과 계약 검증',0,4,'계약','원장 코어와 리전별 독립 검증',split=True),
           task('ira_final','ira','원장 최종 승인',4,.5,'운영','원장 승인 기록'),
           task('june_base','june','기존 중복 처리 분석',3,.5,'계약','중복 처리 샘플'),task('june_docs','june','계약 인수 문서',3.5,.5,'계약','API 계약 설명'),
           task('kai_base','kai','재시도 캐시 준비',3,.5,'계약','공유 테스트 캐시'),task('kai_docs','kai','운영 오류 사례',3.5,.5,'계약','오류 사례 문서'),
           task('schema','lena','결제 스키마 마이그레이션',0,1,'계약','변환 스키마'),task('backfill','lena','이력 데이터 점검',2,1,'계약','백필 검증 기록'),
           task('qa_setup','mina','QA 환경 점검',0,.5,'테스트','QA 실행 환경'),task('qa_batch','mina','리전별 정합성 QA',4,.5,'테스트','정합성 결과',split=True),
           task('pia_base','pia','회귀 픽스처 정리',0,.5,'테스트','정리된 픽스처'),task('pia_check','pia','실패 복구 사례 검토',2,.5,'테스트','복구 사례 목록'),
           task('quinn_base','quinn','부하 샘플 수집',0,.5,'테스트','부하 샘플'),task('quinn_check','quinn','최종 QA 확인',4.5,.5,'테스트','QA 서명'),
           task('ops_a','noel','동부 리전 배포 자동화',0,1,'운영','동부 배포 스크립트'),task('noel_check','noel','오류 알림 검증',3,.5,'운영','알림 증거'),
           task('ops_b','olin','서부 리전 롤백 자동화',0,1,'운영','서부 롤백 스크립트'),task('olin_check','olin','복구 문서 정리',3,.5,'운영','운영 런북'),
           task('rhea_base','rhea','운영 관측 환경',0,.5,'운영','관측 대시보드'),task('deploy','rhea','양 리전 릴리스 승인',4.5,.5,'운영','승인된 릴리스'),
           task('schema_gate','lena','M1 스키마 준비',1,0,'계약','스키마 동결',kind='milestone'),task('ledger_gate','lena','M2 원장 계약 동결',4,0,'계약','원장 계약 동결',kind='milestone'),
           task('qa_gate','quinn','M3 정합성 QA 완료',4.5,0,'테스트','QA 완료',kind='milestone'),task('release_gate','rhea','M4 양 리전 릴리스',5,0,'운영','릴리스 완료',kind='milestone')]
    hands=[hand('schema_ready','schema','schema_gate','스키마 동결',1),hand('ledger_ready','ledger','ledger_gate','원장 계약',4),
           hand('ledger_qa','ledger','qa_batch','정합성 QA 입력',4),hand('qa_ready','qa_batch','deploy','QA 판정',4.5),
           hand('qa_checkpoint','qa_batch','qa_gate','정합성 결과',4.5),hand('ops_ready','ops_a','deploy','동부 배포 스크립트',2),
           hand('rollback_ready','ops_b','deploy','서부 롤백 스크립트',2),hand('release_ready','deploy','release_gate','릴리스 결과',5)]
    feed={'start':dict(label='1/3 · 일정 위반 차단과 최대 라운드',now=0,next_phase='bundle',narr='합의하지 않은 변경은 적용하지 않는지 확인합니다.',records=[dict(who='ira',src='메신저',text='원장 검증의 공정한 분담을 논의합니다.')]),
          'bundle':dict(label='2/3 · 4건 묶음 분할·맞교환',action='bundle',now=0,next_phase='qa',narr='원장 두 조각과 운영 맞교환을 전체 동의로 적용합니다.',transfers=[dict(task='ledger',to='june',amount=1),dict(task='ledger',to='kai',amount=1),dict(task='ops_a',to='olin'),dict(task='ops_b',to='noel')]),
          'qa':dict(label='3/3 · 두 리전 QA 일정 재검사',now=1,next_phase='end',narr='독립 회귀 기록과 전체 릴리스 기한을 검증합니다.',records=[dict(who='mina',src='작업',text='리전별 정합성 검사 입력과 경로 확인 완료')])}
    mock=dict(reestimate=[],split={'ledger':dict(piece=dict(title='리전별 독립 계약 검증',days=2,tag='계약',what='두 리전 계약 검증'),keep=dict(title='원장 트랜잭션 코어',days=2))},discussion=[
        dialogue('june','respond',1,'REJECT','전체 검증을 한 사람에게 넘길 수 없습니다. 분담이 필요합니다.'),
        dialogue('june','revise',1,'COUNTER','카이에게 긴 검증 실행을 요청합니다. 실제 기한 충족은 Hive가 확인해 주세요.',[allocation('kai','느린 전체 검증',6,2)]),
        dialogue('kai','revise',2,'COUNTER','느린 제안은 기한을 넘었습니다. 준과 캐시를 공유하는 안전한 수정안을 냅니다.',[allocation('june','동부 계약',1,1),allocation('kai','서부 계약',1,1)])])
    team=dict(meta=dict(title='데모 6 · 10인 교차 리전·미합의와 원자적 복구',phase='start',now=0,week_start='2026-11-16',deadline_label='양 리전 릴리스 · 11/20 금',narr='첫 협상 실패 뒤 묶음 재배치로 전체 동의를 받습니다.',summary='10명·24개 작업·4개 milestone. 일정 위반 차단, 최대 라운드, 분할·맞교환.',scenario_doc='demo6_cross_region.md'),people=people,cards=cards,tasks=tasks,handoffs=hands,records=[],rules=rules(3,14))
    write('demo6_cross_region',team,feed,mock)


if __name__=='__main__':
    demo5();demo6()
