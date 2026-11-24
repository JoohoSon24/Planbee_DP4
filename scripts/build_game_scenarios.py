"""Build the three published game-team scenarios from one shared base board.

Base data: seed/m4_t6_game_demo/team.yaml (imported from the team's "M4 시연용 시나리오",
장여경, 2026-11-23). Every scenario keeps the same five people, twelve tasks, handoffs and
11/27 17:00 demo; only the reported change and the task contracts that the change touches differ.

What is real and what is designed is written into each scenario's source.md:
- people, tasks, durations, priorities, dependencies and pieces come from the source export;
- the wishes/limits marked `designed` were added so that proxies have something to disagree about;
- expected.yaml (the rule-based answer key) is written here, before any run.

Usage: python3 scripts/build_game_scenarios.py
"""
from copy import deepcopy
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / 'seed'
BASE = yaml.safe_load((SEED / 'm4_t6_game_demo' / 'team.yaml').read_text(encoding='utf-8'))

# ---------------------------------------------------------------- people
# source = the export's person schema; designed = added for observable negotiation behaviour.
PROFILES = {
    'mia': dict(role='그림 중심', skills={'아트': '능숙', 'UI': '가능'}, takes=['아트', 'UI'],
                refuses=['서버', 'QA', '게임플레이'], limit='하루 8시간 · 0.5일까지 프록시가 받음',
                wish='이펙트 A2를 이번 데모에 직접 완성', avoid='A2를 다음 스프린트로 미루는 것',
                designed=['avoid']),
    'leo': dict(role='게임플레이 중심', skills={'게임플레이': '능숙'}, takes=['보스 AI', '게임플레이 연결', '데모 빌드'],
                refuses=['아트', '서버', 'UI', '독립 QA'], limit='0.5일까지 프록시가 받음',
                wish='금요일 오후 빌드 직전에는 새 변경을 받지 않기',
                condition='G2를 임시 아트로 연결할 때는 최종 아트가 목요일 오전 시작 전에 도착해야 함',
                designed=['wish']),
    'sam': dict(role='서버 중심', skills={'서버': '능숙', 'UI': '가능', '테스트': '가능'}, takes=['서버', '저장'],
                refuses=['아트', '게임플레이'], limit='1일까지 프록시가 받음 · 테스트는 받는 일 밖(예외로만)',
                wish='랭킹 S3를 이번 데모 스테이징에서 보여주기', avoid='랭킹을 다음 스프린트로 미루는 것',
                designed=['wish', 'avoid']),
    'ben': dict(role='UI·레벨 중심', skills={'UI': '능숙', '레벨': '능숙', '테스트': '가능'}, takes=['UI', '레벨', '스모크 QA'],
                refuses=['서버', '아트', '보스 게임플레이'], limit='1일까지 프록시가 받음',
                wish='스테이지3와 메뉴 화면을 직접 완성', avoid='목요일 오후 메뉴 다듬기 시간이 없어지는 것',
                designed=['avoid']),
    'zoe': dict(role='테스트 중심', skills={'테스트': '능숙', 'UI': '가능'}, takes=['테스트'],
                refuses=['서버', '아트', '게임플레이 구현'], limit='0.5일까지 프록시가 받음 · Q2 1일 QA는 줄일 수 없음',
                wish='최종 회귀 전에 스모크 결과를 직접 검토', condition='최종 회귀·서명은 본인이 맡음',
                avoid='Q2에서 보스전을 스모크 없이 최종 회귀에서 처음 확인하는 것',
                designed=['wish', 'avoid']),
}

CARD_NOTES = {
    'mia': '아트·UI를 받습니다. 서버·QA·게임플레이는 받지 않습니다. 이펙트 A2 완성을 이번 데모에서 원합니다.',
    'leo': '보스 AI·게임플레이 연결·데모 빌드를 받습니다. 아트·서버·UI·독립 QA는 받지 않습니다. 임시 아트 연결은 최종 아트가 목요일 오전 시작 전에 올 때만 가능합니다.',
    'sam': '서버·저장을 받습니다. 아트·게임플레이는 받지 않습니다. 테스트 역량은 있지만 받는 일 밖이라 예외로만 맡습니다. 랭킹 S3를 이번 데모에서 보여주고 싶습니다.',
    'ben': 'UI·레벨·스모크 QA를 받습니다. 서버·아트·보스 게임플레이는 받지 않습니다. 목요일 오후는 메뉴 다듬기에 쓰고 싶습니다.',
    'zoe': '테스트를 받습니다. 서버·아트·게임플레이 구현은 받지 않습니다. Q2 1일 QA는 줄일 수 없고 최종 회귀·서명은 제가 맡습니다.',
}

# Task contract keys that encoded the old T6 issue. Each scenario sets its own.
ISSUE_KEYS = {'allowed_change_tasks', 'discussion_participants', 'transfer_requires_confirm',
              'preserve_personal_confirmation', 'review_no_options', 'relaxations'}

A1_PARTS = [
    dict(key='rough', title='A1 러프', what='보스 러프 그림 0.5일', effort=0.5, depends_on=[], assignees=['mia']),
    dict(key='final', title='A1 최종', what='보스 최종 그림 0.5일', effort=0.5, depends_on=['rough'], assignees=['mia']),
]
G2_PARTS = [
    dict(key='temp', title='G2 임시 연결', what='G1 보스 AI와 A1 러프로 보스전 흐름 임시 연결 0.5일', effort=0.5, depends_on=[], assignees=['leo']),
    dict(key='final', title='G2 최종 반영', what='A1 최종 그림 반영과 보스전 작동 확인 0.5일', effort=0.5, depends_on=['temp'], assignees=['leo']),
]
S2_PARTS = [
    dict(key='prep', title='S2 배포 준비', what='서버 배포 스크립트·환경 준비 0.5일', effort=0.5, depends_on=[], assignees=['sam']),
    dict(key='final', title='S2 최종 배포', what='데모 환경 최종 배포와 확인 0.5일', effort=0.5, depends_on=['prep'], assignees=['sam']),
]


def base():
    data = deepcopy(BASE)
    for p in data['people']:
        prof = PROFILES[p['id']]
        p['role'] = {'mia': '그림', 'leo': '개발', 'sam': '서버', 'ben': '레벨', 'zoe': '테스트'}[p['id']]
        p['wants'] = [prof['wish']]
        p['notes'] = dict(prompt_role='game_' + p['id'], source_skills=prof['skills'],
                          profile={k: v for k, v in prof.items() if k not in ('skills', 'role')})
    for c in data['cards']:
        c['note'] = CARD_NOTES[c['who']]
        c['policy'] = dict(approved=True, source_note='게임팀 공통 보드', unavailable=[])
    for t in data['tasks']:
        ctx = {k: v for k, v in (t.get('context') or {}).items() if k not in ISSUE_KEYS}
        if t['id'] == 'A1':
            ctx.update(splittable_hint=True, required_parts=deepcopy(A1_PARTS))
        if t['id'] == 'G2':
            # Source §3.1: temporary integration on the rough is allowed when the final art
            # arrives before Thursday morning starts (3.0). That is the only re-promise allowed.
            ctx.update(splittable_hint=True, required_parts=deepcopy(G2_PARTS),
                       inbound_scope={'G1': ['temp'], 'A1': dict(parts=['final'], due=3.0)},
                       parts_description='임시 연결 0.5 + 최종 반영 0.5. 최종 아트는 목 오전 시작 전 도착')
        if t['id'] == 'Q2':
            ctx['minimum_days'] = 1
        t['context'] = ctx
    # Work already done before Tue 13:00, so the board shows the week so far.
    # Tue AM pieces come from the source's progress claims (A1 33%, G1·S1·Q1 50% of the whole);
    # the Monday items are the source's stated prerequisites, with owner and day assumed (designed).
    done = [('A1_am', 'mia', 'A1 · 보스 그림 (오전 진행분)', 1.0, 0.5, '원문 진행률 33%: 전체 1.5일 중 0.5일'),
            ('G1_am', 'leo', 'G1 · 보스 AI (오전 진행분)', 1.0, 0.5, '원문 진행률 50%'),
            ('S1_am', 'sam', 'S1 · 저장 기능 (오전 진행분)', 1.0, 0.5, '원문 진행률 50%'),
            ('Q1_am', 'zoe', 'Q1 · 스테이지1·2 테스트 (오전 진행분)', 1.0, 0.5, '원문 진행률 50%'),
            ('BG3', 'mia', '스테이지3 배경', 0.0, 1.0, '원문 B1 선행조건 "월요일 스테이지3 배경 완료" · 담당·요일은 설계값'),
            ('ST12', 'ben', '스테이지1·2 구현', 0.0, 1.0, '원문 Q1 선행조건 "기존 1·2 스테이지 구현 완료" · 담당·요일은 설계값')]
    for tid, who, title, s0, d, basis in done:
        data['tasks'].insert(0, dict(id=tid, who=who, title=title, s0=s0, d=d, tag=tid, kind='done',
                                     context=dict(description=title, done_basis=basis, priority='P0')))
    data['meta'] = {k: v for k, v in data['meta'].items() if k in ('now', 'week_start', 'deadline_label', 'phase')}
    data['meta'].update(consent_mode='discussion', llm_mode='mock', source='M4 시연용 시나리오 export (장여경, 2026-11-23) · 게임팀 공통 보드',
                        team='game', normalization_note=BASE['meta']['normalization_note'])
    return data


def task(data, tid):
    return next(t for t in data['tasks'] if t['id'] == tid)


def unavailable(data, pid, start, end, reason):
    card = next(c for c in data['cards'] if c['who'] == pid)
    card['policy']['unavailable'].append(dict(start=start, end=end, reason=reason))


# ---------------------------------------------------------------- scenarios
def s1():
    d = base()
    text = ('Zoe가 목요일 오후 Q2 통합 QA 스모크를 진행할 수 없대요. 스모크는 다른 적격자에게 넘겨도 되고, '
            '금요일 오전 최종 회귀와 서명은 Zoe가 맡는대요.')
    unavailable(d, 'zoe', 3.5, 4.0, '목요일 오후 부재 (본인 보고)')
    task(d, 'Q2')['context'].update(allowed_change_tasks=['Q2', 'S3', 'B2'], discussion_participants=['leo'])
    d['meta'].update(title='① QA 부재 · Zoe 목요일 오후 스모크', source_task='Q2', narr=text,
                     summary='Zoe가 목요일 오후 Q2 스모크를 못 함. 스모크를 누가 맡고 무엇을 옮길지.',
                     engine_support='Q2 스모크 0.5일을 Ben 또는 Sam에게 넘기는 계획과 S3·B2 시간 이동을 함께 탐색합니다. 카드 기반 동의 단계는 쓰지 않고 공개 토론의 선호·반대·조건을 PM에게 보여 줍니다.')
    return 'm4_g1_qa_absence', d, dict(task='Q2', who='zoe', text=text), dict(
        impact=dict(broken_any=['h_Q2_G3'], owner='zoe', involved_any=['leo'], not_involved=['mia']),
        candidates=dict(families_any=[['ben'], ['sam']], keep_parts={'Q2': {'regression': 'zoe'}}),
        participants=dict(exclude=['mia'], include=['zoe', 'leo']),
        behaviour=dict(non_prefer_acts_min=1),
        pm=dict(options_min=2, options_max=3))


def s2():
    d = base()
    text = ('Mia가 보스 그림 A1 러프는 화요일 오후까지 전달할 수 있지만, 수요일 오전에는 마무리 작업을 할 수 없게 됐대요. '
            '최종본은 수요일 오후에 전달한대요.')
    unavailable(d, 'mia', 2.0, 2.5, '수요일 오전 작업 불가 (본인 보고)')
    task(d, 'A1')['context'].update(allowed_change_tasks=['A1', 'G2', 'A2', 'Q2'], discussion_participants=['zoe'],
                                    repromise={'h_A1_G2': 3.0})
    # Second route (designed contract, disclosed in source.md): Q2's smoke checks stages 1–3 and the
    # server on Thursday, and the boss fight moves into Friday's final regression, so G2 may finish
    # Thursday evening. Costs Zoe her pre-regression look at the boss fight.
    task(d, 'Q2')['context'].update(inbound_scope={'G2': dict(parts=['regression'], due=4.0), 'S2': ['smoke'], 'B1': ['smoke'], 'Q1': ['smoke']},
                                    parts_description='G2가 늦으면 보스전 확인을 금 오전 최종 회귀로 옮길 수 있음 (스모크는 스테이지·서버만)')
    d['meta'].update(title='② 인계 지연 · Mia 보스 그림 최종본', source_task='A1', narr=text,
                     summary='A1 최종본이 수요일 오후로 밀림. A1→G2→Q2→G3 사슬을 어떻게 지킬지.',
                     engine_support='A1을 러프·최종으로 나누고 G2를 임시 연결·최종 반영으로 재설계하는 계획, A2 시간 이동을 탐색합니다. G2 최종 반영은 A1 최종본을 목요일 오전 시작 전에 받는다는 원문 조건만 사용합니다.')
    return 'm4_g2_art_slip', d, dict(task='A1', who='mia', text=text), dict(
        impact=dict(broken_any=['h_A1_G2', 'h_G2_Q2'], owner='mia', involved_any=['leo', 'zoe'], not_involved=['sam', 'ben']),
        candidates=dict(restructure_any=['G2', 'Q2'], unchanged=['G3']),
        participants=dict(exclude=['sam', 'ben'], include=['mia', 'leo']),
        behaviour=dict(non_prefer_acts_min=1),
        pm=dict(options_min=1, options_max=3))


def s3():
    d = base()
    text = ('Sam이 S2 서버 배포를 수요일 오후에는 진행할 수 없대요. 수요일 오전과 목요일 종일은 일할 수 있대요.')
    unavailable(d, 'sam', 2.5, 3.0, '수요일 오후 작업 불가 (본인 보고)')
    task(d, 'S2')['context'].update(
        allowed_change_tasks=['S2', 'S3'], discussion_participants=['zoe', 'leo'], review_no_options=True,
        relaxations=[
            dict(id='R1', authorizer='pm', label='S2를 Sam이 수 오전 준비 0.5일 + 목 오전 최종 0.5일로 나눠 진행하도록 허용',
                 rule='S2 분할 금지 해제 · S2→S3 인계 약속을 목 정오로',
                 patch=dict(tasks={'S2': dict(context=dict(splittable_hint=True, required_parts=deepcopy(S2_PARTS)))},
                            handoffs={'h_S2_S3': dict(t=3.5)})),
            dict(id='R2', authorizer='pm', label='랭킹 S3를 다음 스프린트로 이관',
                 rule='P1 범위 이관',
                 patch=dict(tasks={'S3': dict(cut=True, context=dict(deferred_to='Next sprint', deferred_from='current'))})),
            dict(id='R3', authorizer='sam', label='Sam의 부재 시간을 수요일 오후에서 목요일 오전으로 바꿔 달라고 요청',
                 rule='당사자 가용 시간 변경 (PM 권한 밖 · Sam 본인 결정)',
                 patch=dict(people={'sam': dict(unavailable=[dict(start=3.0, end=3.5, reason='목요일 오전으로 바꾼 부재')])})),
        ])
    d['meta'].update(title='③ 규칙 밖 · Sam 서버 배포 슬롯 상실', source_task='S2', narr=text,
                     summary='S2를 통째로 옮기면 Q2가 늦음. 규칙 안 해결이 없을 때 어떤 규칙을 풀지.',
                     engine_support='S2는 분할 금지라 규칙 안 계획이 없습니다. 관련자 검토 뒤 Hive가 풀 수 있는 규칙마다 가능한 계획 수를 계산해 PM에게 올리고, PM이 허락한 규칙으로 다시 계획을 만듭니다.')
    return 'm4_g3_deploy_slot', d, dict(task='S2', who='sam', text=text), dict(
        impact=dict(broken_any=['h_S2_Q2'], owner='sam', involved_any=['zoe', 'leo'], not_involved=['mia', 'ben']),
        first_pass=dict(termination='needs_rule_relaxation', feasible={'R1': '>0', 'R2': '0', 'R3': '>0'}),
        grant='R1',
        candidates=dict(all_split='S2', unchanged=['Q2', 'G3']),
        participants=dict(exclude=['mia', 'ben'], include=['sam', 'zoe']),
        behaviour=dict(non_prefer_acts_min=1, constraint_reviews_min=1),
        pm=dict(options_min=1, options_max=3))


# ---------------------------------------------------------------- English (display only, never sent to an LLM)
TASK_EN = {'A1': 'Boss art', 'A2': 'Effects polish', 'G1': 'Boss AI', 'G2': 'Boss fight integration', 'G3': 'Demo build',
           'S1': 'Save feature', 'S2': 'Server deploy', 'S3': 'Leaderboard', 'B1': 'Stage 3 layout', 'B2': 'Menu screen',
           'Q1': 'Stage 1–2 tests', 'Q2': 'Integration QA'}
EXAMPLES = [  # each checked offline to reach PM options on the free board
    ('Ben이 B2 메뉴 화면을 수요일 오후에는 시작할 수 없대요. 목요일 오후부터 할 수 있대요.', "Ben can't start the B2 menu screen on Wednesday afternoon. He can work on it from Thursday afternoon."),
    ('Zoe가 목요일 오후에 Q2 통합 QA 스모크를 못 한대요.', "Zoe can't run the Q2 integration QA smoke on Thursday afternoon."),
    ('Mia가 목요일 하루 쉬어요.', 'Mia is off all Thursday.'),
    ('S3 랭킹 작업이 반나절 더 걸린대요.', 'S3 Leaderboard will take half a day more.'),
    ('목요일 오후에 비어 있는 사람이 누구예요?', 'Who is free on Thursday afternoon?'),
]


WORDS_EN = {
    '[사람] 님이 [요일 오전/오후]에 [업무] 작업을 못 한대요. [요일 오전/오후]부터 할 수 있대요.': '[person] can’t do [task] on [day AM/PM]. They can work from [day AM/PM].',
    '[업무] 작업이 [반나절/하루] 더 걸린대요.': '[task] will take [half a day / a day] more.',
    '[사람] 님이 [요일] 하루 쉬어요.': '[person] is off all [day].',
    '[업무] 작업은 언제 끝나요?': 'When does [task] finish?',
    **{ko: en for ko, en in EXAMPLES},
    '부재': 'Absence', '작업량': 'Workload', '휴가': 'Day off', '질문': 'Question',
    '그림': 'Art', '개발': 'Gameplay', '서버': 'Server', '레벨': 'Level', '테스트': 'QA',
    '그림 중심': 'Art', '게임플레이 중심': 'Gameplay', '서버 중심': 'Server', 'UI·레벨 중심': 'UI · Level', '테스트 중심': 'QA',
    '아트': 'Art', 'UI': 'UI', '게임플레이': 'Gameplay', '레벨': 'Level', '능숙': 'Expert', '가능': 'Capable',
    '11/27 17:00 데모': '11/27 17:00 demo', '없음': 'None', 'A1 완료': 'A1 done', 'S1 완료': 'S1 done', 'S2 완료': 'S2 done', 'B1 완료': 'B1 done',
    '러프 0.5일': 'Rough 0.5 d', '최종 0.5일': 'Final 0.5 d', '임시 연결 0.5일': 'Temporary integration 0.5 d', '최종 아트 반영 0.5일': 'Final art pass 0.5 d',
    '목 오후 스모크 0.5일': 'Thu PM smoke 0.5 d', '금 오전 최종 회귀 0.5일': 'Fri AM final regression 0.5 d', '통째 1일 이동만 가능': 'Moves only as one whole day',
    '최종 보스 그림': 'Final boss art', '없음 · P1이므로 연기·제외 가능': 'None · P1, can be deferred or dropped', '보스 기본 동작': 'Basic boss behaviour',
    'A1 최종 + G1 완료': 'A1 final + G1 done', '최종 아트 반영과 작동 확인': 'Final art in and working', 'G2 · S2 · B1 · Q2 최종 승인 완료': 'G2 · S2 · B1 · Q2 final sign-off done',
    '금 16시까지 유효한 P0 빌드': 'A valid P0 build by Fri 16:00', '저장 동작': 'Saving works', 'P0 데모 환경 정상 배포': 'P0 demo environment deployed',
    '없음 · 기본 feature flag OFF': 'None · feature flag OFF by default', 'P0 빌드와 독립': 'Independent of the P0 build', '월요일 스테이지3 배경 완료': 'Stage 3 background done Monday',
    '플레이 가능한 스테이지3': 'Playable stage 3', '없음 · P0 데모 필수 아님': 'None · not required for the P0 demo', '스테이지1·2 구현 완료': 'Stages 1–2 implemented',
    '스테이지1·2 QA 완료': 'Stages 1–2 QA done', 'G2 · S2 · B1 · Q1 완료': 'G2 · S2 · B1 · Q1 done', '총 1일 QA · Zoe 최종 회귀와 서명': '1 day of QA in total · Zoe signs the final regression',
    '스모크 담당자는 바꿀 수 있음': 'The smoke tester can change', '러프는 화요일 오후에 전달됨': 'The rough is handed over Tue PM',
    '임시 연결은 최종 아트가 목요일 오전 시작 전에 올 때만': 'Temporary integration only if final art arrives before Thu AM',
    '분할 금지 (PM이 허락하면 준비 0.5일 + 최종 0.5일)': 'Not splittable (with PM permission: prep 0.5 d + final 0.5 d)',
}
PROFILE_EN = {
    'mia': dict(takes='Art, UI', refuses='Server, QA, Gameplay', limit='8 h a day · her proxy takes up to 0.5 d',
                wish='Finish effects A2 herself for this demo', avoid='Deferring A2 to the next sprint'),
    'leo': dict(takes='Boss AI, Gameplay integration, Demo build', refuses='Art, Server, UI, Independent QA', limit='His proxy takes up to 0.5 d',
                wish='No new changes right before the Friday build', condition='Temporary art integration of G2 only if final art arrives before Thu AM starts'),
    'sam': dict(takes='Server, Save', refuses='Art, Gameplay', limit='His proxy takes up to 1 d · testing only as an exception',
                wish='Show leaderboard S3 on the demo staging', avoid='Deferring the leaderboard to the next sprint'),
    'ben': dict(takes='UI, Level, Smoke QA', refuses='Server, Art, Boss gameplay', limit='His proxy takes up to 1 d',
                wish='Finish stage 3 and the menu himself', avoid='Losing Thursday afternoon for menu polish'),
    'zoe': dict(takes='QA', refuses='Server, Art, Gameplay implementation', limit='Her proxy takes up to 0.5 d · Q2 keeps 1 full day',
                wish='Review smoke results herself before the final regression', condition='She keeps the final regression and sign-off',
                avoid='Seeing the boss fight for the first time in the final regression, without a smoke'),
}
SCENARIO_EN = {
    'Q2': dict(title='① QA absence · Zoe misses Thursday smoke', summary='Zoe cannot run the Q2 smoke on Thursday afternoon. Who takes it, and what moves?',
               issue='Zoe can’t run the Q2 integration QA smoke on Thursday afternoon. Someone qualified can take the smoke; Zoe will still do the Friday morning final regression and sign-off.'),
    'A1': dict(title='② Handoff slip · Mia’s final boss art', summary='The A1 final art slips to Wednesday afternoon. How do we protect the A1→G2→Q2→G3 chain?',
               issue='Mia can hand over the A1 boss art rough by Tuesday afternoon, but she can’t do the finishing work on Wednesday morning. She will deliver the final on Wednesday afternoon.'),
    None: dict(title='④ Free input · live model', summary='Same team and board. The PM writes any change; the model reads it into a board change, then the team negotiates.',
               issue='Ben can’t start the B2 menu screen on Wednesday afternoon. He can work on it from Thursday afternoon.'),
    'S2': dict(title='③ Outside the rules · Sam loses his deploy slot', summary='Moving S2 whole makes Q2 late. With no plan inside the rules, which rule do we relax?',
               issue='Sam can’t do the S2 server deploy on Wednesday afternoon. He can work Wednesday morning and all day Thursday.'),
}
RELAX_EN = {'R1': ('Let Sam split S2: prep 0.5 d Wed AM + final 0.5 d Thu AM', 'S2 may split · S2→S3 handoff promise moves to Thu noon'),
            'R2': ('Defer leaderboard S3 to the next sprint', 'P1 scope deferral'),
            'R3': ('Ask Sam to move his absence from Wed PM to Thu AM', 'Personal availability (Sam decides, outside PM authority)')}


def glossary(data, issue, display):
    g = dict(WORDS_EN)
    for t in data['tasks']:
        tid = t['id']; ctx = t.get('context') or {}
        if tid in TASK_EN:
            base_ko = t['title'].split(' · ', 1)[1]
            g[t['title']] = f'{tid} · {TASK_EN[tid]}'; g[base_ko] = TASK_EN[tid]
            g[base_ko + ' 완료본'] = 'Finished ' + TASK_EN[tid].lower()
            g[f'{tid} 원문 산출물'] = f'{tid} deliverable'
            if ctx.get('description'): g[ctx['description']] = f'{TASK_EN[tid]}; source task {tid}'
        for part in ctx.get('required_parts', []):
            g.setdefault(part['what'], part['what'])
    parts_en = {'보스 러프 그림 0.5일': 'Boss rough art 0.5 d', '보스 최종 그림 0.5일': 'Boss final art 0.5 d',
                'G1 보스 AI와 A1 러프로 보스전 흐름 임시 연결 0.5일': 'Temporary boss-fight flow with G1 AI and the A1 rough, 0.5 d',
                'A1 최종 그림 반영과 보스전 작동 확인 0.5일': 'Put in the A1 final art and check the fight works, 0.5 d',
                '서버 배포 스크립트·환경 준비 0.5일': 'Prepare deploy scripts and environment, 0.5 d', '데모 환경 최종 배포와 확인 0.5일': 'Final deploy to the demo environment, 0.5 d',
                '목요일 오후 통합 스모크 0.5일: G2·S2·B1·Q1 결과 확인': 'Thu PM integration smoke 0.5 d: check G2·S2·B1·Q1',
                '금요일 오전 최종 회귀 0.5일 및 Zoe 최종 서명': 'Fri AM final regression 0.5 d and Zoe’s sign-off',
                'A1 러프': 'A1 rough', 'A1 최종': 'A1 final', 'G2 임시 연결': 'G2 temporary', 'G2 최종 반영': 'G2 final pass',
                'S2 배포 준비': 'S2 prep', 'S2 최종 배포': 'S2 final deploy', 'Q2 스모크': 'Q2 smoke', 'Q2 최종 회귀·Zoe 서명': 'Q2 final regression · Zoe sign-off'}
    g.update(parts_en)
    g.update({'A1 · 보스 그림 (오전 진행분)': 'A1 · Boss art (morning part)', 'G1 · 보스 AI (오전 진행분)': 'G1 · Boss AI (morning part)',
              'S1 · 저장 기능 (오전 진행분)': 'S1 · Save feature (morning part)', 'Q1 · 스테이지1·2 테스트 (오전 진행분)': 'Q1 · Stage 1–2 tests (morning part)',
              '스테이지3 배경': 'Stage 3 background', '스테이지1·2 구현': 'Stages 1–2 build'})
    for pid, prof in PROFILES.items():
        en = PROFILE_EN[pid]
        g[', '.join(prof['takes'])] = en['takes']; g[', '.join(prof['refuses'])] = en['refuses']
        for k in ('limit', 'wish', 'avoid', 'condition'):
            if prof.get(k) and en.get(k): g[prof[k]] = en[k]
    src = SCENARIO_EN[data['meta']['source_task']]
    g[data['meta']['title']] = src['title']; g[data['meta']['summary']] = src['summary']; g[issue['text']] = src['issue']
    for t in data['tasks']:
        for r in (t.get('context') or {}).get('relaxations', []):
            g[r['label']], g[r['rule']] = RELAX_EN[r['id']]
    return {k: v for k, v in g.items() if k != v}


def s4():
    d = base()
    text = 'Ben이 B2 메뉴 화면을 수요일 오후에는 시작할 수 없대요. 목요일 오후부터 할 수 있대요.'
    # Menu UI can be taken by anyone who is UI-capable (source person schema: Mia, Sam, Zoe "UI 가능").
    task(d, 'B2')['context'].update(allowed_assignees=['ben', 'mia', 'sam', 'zoe'], allowed_change_tasks=['B2', 'A2', 'S3'])
    d['meta'].update(title='④ 자유 입력 · 실제 LLM', source_task=None, narr=text, llm_mode='live', free_input=True,
                     summary='같은 팀·같은 보드에서 PM이 아무 변경이나 적어 보냅니다. LLM이 보고를 보드 변경으로 읽어 반영한 뒤 협상합니다.',
                     engine_support='보고 문장 → (LLM) 보드 변경 1건 → 코드 검사 후 반영 → 영향 분석 → 계획 생성 → 프록시 토론 → PM 선택. 서버를 --llm live로 켜야 합니다.',
                     # Fill-in sentences: [blanks] are chosen by the PM (Tab moves between them; dragging a
                     # person or task from the board fills the selected blank and quotes the item).
                     templates=[dict(tag='부재', text='[사람] 님이 [요일 오전/오후]에 [업무] 작업을 못 한대요. [요일 오전/오후]부터 할 수 있대요.'),
                                dict(tag='작업량', text='[업무] 작업이 [반나절/하루] 더 걸린대요.'),
                                dict(tag='휴가', text='[사람] 님이 [요일] 하루 쉬어요.'),
                                dict(tag='질문', text='[업무] 작업은 언제 끝나요?')],
                     examples=[ko for ko, _ in EXAMPLES])
    return 'm4_g4_free', d, dict(task='B2', who='ben', text=text), None


SOURCE_MD = """# {title}

{summary}

## 보고 (실제 발화자: {who})

> {text}

## 데이터 출처
- 사람·업무·소요·우선순위·선후관계·조각: M4 시연용 시나리오 export (장여경, 2026-11-23). 원문은 `seed/m4_t6_game_demo/source.md`.
- 사람 프로필의 바람·피하고 싶은 것 중 아래 항목은 **협상 행동을 관찰하려고 추가한 설계값**입니다: {designed}.
- 보고된 변경은 보드의 가용 시간 제약으로 반영했습니다 (`cards[].policy.unavailable`).
- 화요일 13:00 이전에 끝난 일: 화요일 오전 진행분(A1·G1·S1·Q1)은 원문 진행률에서, 월요일의 스테이지3 배경·스테이지1·2 구현은 원문 선행조건에서 가져왔고 담당·요일은 설계값입니다.
- 동의 단계: 카드 기반 평가·본인 확인을 쓰지 않습니다 (`consent_mode: discussion`). 프록시는 공개 토론에서 선호·반대·조건·질문만 남기고 PM이 고릅니다.

## 정답지 (실행 전에 작성, `expected.yaml`)
```yaml
{expected}```
"""


def write(sid, data, issue, expected):
    out = SEED / sid; out.mkdir(exist_ok=True)
    dump = lambda o: yaml.safe_dump(o, allow_unicode=True, sort_keys=False, width=120)
    (out / 'team.yaml').write_text(dump(data), encoding='utf-8')
    (out / 'feed.yaml').write_text(dump(dict(issue=dict(task=issue['task'], label=data['meta']['title'], now=data['meta']['now'], next_phase='end',
        narr=issue['text'], records=[dict(who='pm', about=issue['who'], src='PM이 팀원 보고를 전달', text=issue['text'])]))), encoding='utf-8')
    (out / 'mock_llm.yaml').write_text(dump(dict(reestimate=[], split={})), encoding='utf-8')
    if expected is not None:
        (out / 'expected.yaml').write_text(dump(expected), encoding='utf-8')
    designed = ', '.join(f"{p} {k}" for p, prof in PROFILES.items() for k in prof.get('designed', []))
    (out / 'source.md').write_text(SOURCE_MD.format(title=data['meta']['title'], summary=data['meta']['summary'], who=issue['who'],
        text=issue['text'], designed=designed, expected=dump(expected) if expected is not None else '# 자유 입력: 정답지 없음 (Live 탐색용)\n'), encoding='utf-8')
    # Display profiles for the board drawer (same source as the LLM-facing notes).
    tasks = yaml.safe_load((SEED / 'm4_t6_game_demo' / 'profiles.yaml').read_text(encoding='utf-8'))
    tasks['tasks']['S3'].pop('P0 빌드와 독립', None)
    tasks['tasks']['S3']['note'] = 'P0 빌드와 독립'
    tasks['tasks']['A1']['note'] = '러프는 화요일 오후에 전달됨'
    tasks['tasks']['G2']['pieces'] = ['임시 연결 0.5일', '최종 아트 반영 0.5일']
    tasks['tasks']['G2']['note'] = '임시 연결은 최종 아트가 목요일 오전 시작 전에 올 때만'
    tasks['tasks']['S2']['pieces'] = ['분할 금지 (PM이 허락하면 준비 0.5일 + 최종 0.5일)']
    tasks['people'] = {pid: dict(role=prof['role'], skills={k: v for k, v in prof['skills'].items()},
        takes=', '.join(prof['takes']), refuses=', '.join(prof['refuses']), limit=prof['limit'], wish=prof['wish'])
        for pid, prof in PROFILES.items()}
    (out / 'profiles.yaml').write_text('# Display copy of people/notes.profile and the source task schema. Built by scripts/build_game_scenarios.py\n' + dump(tasks), encoding='utf-8')
    (out / 'en.yaml').write_text('# Fixed English for seed text (display only). Built by scripts/build_game_scenarios.py\n' + dump(glossary(data, issue, tasks)), encoding='utf-8')
    print('wrote', out.relative_to(ROOT))


if __name__ == '__main__':
    ids = []
    for build in (s1, s2, s3, s4):
        sid, data, issue, expected = build()
        write(sid, data, issue, expected); ids.append(sid)
    catalog = SEED / 'catalog.yaml'
    cfg = yaml.safe_load(catalog.read_text(encoding='utf-8'))
    # The demo shows only the free-input scenario (live model). ①②③ are the evaluation set:
    # fixed boards with answer keys, run by scripts/run_game_scenarios.py, not listed in the demo.
    demo, tests = [x for x in ids if x == 'm4_g4_free'], [x for x in ids if x != 'm4_g4_free']
    archived = [x for x in cfg.get('scenarios', []) + cfg.get('archived', []) if x not in ids]
    catalog.write_text(yaml.safe_dump(dict(default=demo[0], scenarios=demo, test_set=tests, archived=list(dict.fromkeys(archived))),
                                      allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('catalog:', demo, 'test set:', tests)
