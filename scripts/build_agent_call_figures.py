"""Reproducible SVG + PNG call maps. Run with python3 (Pillow required)."""
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
import math

OUT = Path(__file__).resolve().parents[1] / 'assets' / 'docs'
OUT.mkdir(exist_ok=True)
FONT = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
C = {'ink':'#182c43','muted':'#52667c','line':'#a3b2c4','bg':'#f5f7fb',
     'code':'#e8efff','code_accent':'#345bc4','llm':'#e3f4ed','llm_accent':'#187956',
     'human':'#fff1d9','human_accent':'#94600d','neutral':'#ffffff','neutral_accent':'#52667c'}

class Figure:
    def __init__(self, h, number, title, subtitle):
        self.w, self.h = 1600, h
        self.im=Image.new('RGB',(self.w*2,h*2),C['bg']); self.d=ImageDraw.Draw(self.im)
        self.svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{h}" viewBox="0 0 1600 {h}" role="img"><title>{escape(title)}</title><desc>{escape(subtitle)}</desc><rect width="1600" height="{h}" fill="{C["bg"]}"/>']
        self.text(60,38,f'PLANBEE / ENGINEERING FIGURE {number}',20,C['code_accent'],True)
        self.text(60,79,title,44,bold=True)
        self.text(60,140,subtitle,23,C['muted'])
        for x,typ,label in [(60,'code','Hive · 코드 / 일정·진행 제어'),(560,'llm','Proxy · 개인 LLM / 위임 판단'),(1090,'human','사람 · 당사자 / PM')]:
            self.rect(x,190,24,24,C[typ],C[typ+'_accent'],5)
            self.text(x+36,187,label,22,C['ink'])
    def rect(self,x,y,w,h,fill,stroke=None,r=16):
        self.d.rounded_rectangle((x*2,y*2,(x+w)*2,(y+h)*2),radius=r*2,fill=fill,outline=stroke,width=2 if stroke else 1)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke or "none"}"/>')
    def text(self,x,y,t,size=24,color=None,bold=False):
        color=color or C['ink']; font=ImageFont.truetype(FONT,size*2,index=0)
        self.d.text((x*2,y*2),t,font=font,fill=color,stroke_width=1 if bold else 0)
        self.svg.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="Apple SD Gothic Neo,Noto Sans CJK KR,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(t)}</text>')
    def line(self,points,color=None,width=2,arrow=True):
        color=color or C['line']; self.d.line([(x*2,y*2) for x,y in points],fill=color,width=width*2)
        self.svg.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{color}" stroke-width="{width}"/>')
        if arrow:
            x,y=points[-1]; px,py=points[-2]; a=math.atan2(y-py,x-px)
            tri=[(x,y),(x-11*math.cos(a-.45),y-11*math.sin(a-.45)),(x-11*math.cos(a+.45),y-11*math.sin(a+.45))]
            self.d.polygon([(int(x*2),int(y*2)) for x,y in tri],fill=color)
            self.svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in tri)+f'" fill="{color}"/>')
    def band(self,y,k,title,note):
        self.text(60,y,k,19,C['code_accent'],True); self.text(145,y-4,title,29,bold=True)
        self.text(145,y+36,note,21,C['muted'])
    def card(self,x,y,title,lines,typ='code',w=460,h=170):
        self.rect(x,y,w,h,C[typ],r=18); self.rect(x,y,5,h,C[typ+'_accent'],r=2)
        self.text(x+23,y+19,title,27,bold=True)
        for i,s in enumerate(lines): self.text(x+23,y+65+i*31,s,22,C['muted'])
    def row(self,y,cards,arrows=True):
        for i,(title,lines,typ) in enumerate(cards): self.card(60+i*510,y,title,lines,typ)
        if arrows:
            for x in (520,1030): self.line([(x+5,y+85),(x+44,y+85)])
    def save(self,name):
        self.svg.append('</svg>'); (OUT/f'{name}.svg').write_text('\n'.join(self.svg))
        self.im.save(OUT/f'{name}.png',optimize=True)

f=Figure(2240,'01','전체 에이전트 호출 흐름','먼저 기한을 회복하고, 그 배분에서 당사자 협상으로 공정성을 조정한다. 화살표는 실행 순서·분기를 나타낸다.')
f.band(255,'01','입력 → 담당자 재견적 → 전체 일정 검사','LLM은 새 정보의 의미를 해석하고, Hive가 의존성과 마감을 계산한다.')
f.row(340,[('업무 기록 입력',['사용자 → API → Run 생성','초기 보드·마일스톤 스냅샷','POST /records'], 'human'),('담당자 A · reestimate()',['기록 + 자신의 업무를 읽음','근거가 있는 소요 변경만 반환','ingest → 견적 갱신'],'llm'),('Hive · deadline_gate',['dependency_check → 일정 재계산','마감·용량·승인 가용 시간 검사','위험 → 02 / 안전 → 03 / 위반 보류'],'code')])
f.line([(1310,510),(1310,546),(800,546),(800,593)])
f.band(595,'02','기한 회복 · 위험이 있을 때만 실행','거절은 불가능성 증명이 아니다. 공개 사유를 가지고 다자간 대안을 찾는다.')
f.row(680,[('분할·전체 양도·일정 재배치',['A: split()으로 첫 분할안 제안','분리안 없음 → 전체 업무 토론','각 참여자: 양도·순서 변경 재제안'],'llm'),('당사자 A·B·C… · 토론',['reply() / help_reply(): 최초 응답','discuss(): 거절·재제안·제3자 합류','변경된 제안 → 영향 당사자 재동의'],'llm'),('Hive · 합의 후 최종 제약 검증',['최신 보드의 마감·용량·가용 검사','통과 → 원자적 반영 / 실패 → 재협상','미합의 종료 → PM 검토·재시도'],'code')])
f.text(65,865,'초기 요청·조건 응답은 bids/tally 경로. 다자간 토론은 같은 bids에서 discussion.turn()으로 전환한다.',21,C['muted'])
f.line([(1310,850),(1535,850),(1535,940),(1490,940)])
f.card(60,920,'Hive · 검증·합의된 기한 충족 배분 저장',[
    'finish 또는 discussion_commit → 전체 일정 재검증 → record_feasible_baseline()',
    '기한 회복 완료 경로도 반드시 fairness_gate로 이어진다. 아직 기한·용량이 불안전하면 공정성 협상을 보류한다.'
],w=1430,h=140)
f.line([(800,1060),(800,1094)])
f.band(1100,'03','공정성 검토 → 실제 분담 협상','공정성 지표는 시작할 업무·후보를 제안한다. 지표 자체가 최종 합의를 선택하지 않는다.')
f.row(1185,[('Hive · fairness_gate',['과거 부담 + 이번 주 업무량 계산','부담 차이·연결 업무·역할 확인','기준 미달 / 후보 없음 → 유지'],'code'),('담당자 A · split()',['기한 충족 기준 배분에서 출발','어떤 업무를 나눌지 먼저 제안','Hive card_check → 최초 수신자 B'],'llm'),('A·B·C… · discuss()',['B 응답 → 거절 사유 공개','모든 참여자가 수정·재제안 가능','새 수신자 C도 직접 판단 [Fig.02]'],'llm')])
f.line([(1310,1355),(1310,1395),(290,1395),(290,1435)])
f.row(1440,[('각 당사자 · 동일 버전 동의',['주는 사람·받는 사람·영향받는 사람','변경안 v+1 → 기존 수락 전부 초기화','한도·민감 조건은 사람 확인'],'human'),('Hive · discussion_commit',['최신 보드에서 마감·용량 재검증','일정 변경 → 재동의 요청','검증·동의 충족 시 원자적 반영'],'code'),('최종 배분 또는 기준 배분 유지',['합의: 배분 확정 + 전후 지표 기록','대안 소진 / 한도: 미합의안 폐기','공정성 실패 → 기한 충족 배분 유지'],'code')])
f.band(1655,'04','주 흐름을 보조하는 호출과 사람의 결정','일반 기한 회복에서 수신 마감 연장으로 위험을 숨기지 않는다.')
f.row(1740,[('위임카드 작성 · 별도 API',['interpret_card(): 자연어 → 정책 초안','당사자가 확인·저장한 뒤 사용','분리 분석 API도 split() 별도 호출'],'llm'),('PM · 예외와 재개',['ask: 범위 축소·유예안 검토','grant/reject → 필요한 당사자 확인','라운드 확대 후 retry → 이력 유지'],'human'),('명시적 조작 · 별도 경로',['수신 시점 변경: 확인 후 재계산','wait_reply(): 수신 조건 응답용','묶음 이동: 사람 합의 + 코드 반영'],'human')],arrows=False)
f.rect(60,1950,1480,210,'#182c43')
f.text(85,1973,'모든 단계의 공통 계약',27,'#ffffff',True)
for i,t in enumerate(['정보 경계  |  각 LLM에는 자기 위임카드만 전달. 다른 사람의 카드 원문은 전달하지 않는다.',
                        '판단 분리  |  LLM은 수락·거절·재제안 / Hive 코드는 일정·역할·용량 검증과 상태 전이를 담당한다.',
                        '관측·재개  |  Run에 턴·요청자·수신자·사유·버전·Hive 활동·초기/이후 마일스톤을 순서대로 기록한다.']): f.text(85,2020+i*36,t,23,'#e0e9f8')
f.text(60,2190,'SOURCE  app/workflow.py · app/discussion.py · app/llm.py · app/task_partition.py · app/runlogs.py',19,C['muted'])
f.save('agent_call_flow')

f=Figure(2450,'02','다자간 discussion · 한 번의 평가에서 합의까지','같은 요청의 반복 호출이 아니라, 버전·거절 사유·참여자·동의가 바뀌는 상태 기반 협상이다.')
steps=[
('01','Hive · 세션 시작','code','기한 회복 또는 공정성 단계의 맥락·원래 업무·현 제안·공개 이력을 준비한다.',
 '공정성: A→B 최초 요청 / 기한: 초기 거절·조건을 승계하거나 whole_task 토론 시작'),
('02','Hive · 매 라운드 사전 검증','code','preview(): 복제한 보드에서 전체 의존성·모든 Handoff 마감·역할·용량을 검사한다.',
 '위반 → BLOCKED 사유와 수정 요청. 사전 계산은 토론 피드백이며 최종 검증은 합의 뒤 08에서 수행.'),
('03','수신자 B → 영향 당사자 A…','llm','각자 discuss(자신, 자기 카드, 공개 맥락)를 호출한다. 수신자가 먼저 답한다.',
 '입력: 자기 부하·일정, 공개 제안·마감·이전 거절 사유·조건 / 타인의 카드 원문 제외'),
('04','각 LLM · 응답·이유 공개','llm','ACCEPT: 현 버전 수락 / REJECT: 사유를 남기고 수정 요청 / NEEDS_INPUT: 사람 확인',
 '거절 → 05 / COUNTER 대안 → 06 / 해당 버전 전원 수락 → 07. 응답·이유는 이력에 누적'),
('05','거절 후 · 모든 참여자 수정 기회','llm','A만 고치는 구조가 아니다. B·C 등 각 참여자에게 REVISE_REQUEST를 보낸다.',
 '앞선 거절 이유·조건 + 자기 카드로 재제안 → 06. 같은 안 차단 / 새 대안 없으면 종료'),
('06','새 대안 · v+1 / 새 참여자 C 합류','code','COUNTER 채택 → 분담·일정 변경 전체를 v+1에 결합, 기존 수락 초기화, 새 수신자·영향 당사자 참여.',
 '다음 라운드 02로 돌아가 재검증 → C 포함 해당 안의 모든 영향 당사자에게 새 동의 요청'),
('07','당사자 전원 · 정확한 버전 확인','human','업무 제공자·수신자와 일정/부담 영향 당사자의 동의를 모은다.',
 'NEEDS_INPUT·자동위임 한도 초과·검토 조건 → 사람에게 같은 버전의 전체 안 확인'),
('08','Hive · 커밋 직전 다시 검증','code','discussion_commit: 현재 보드에서 다시 검증. 일정 서명이 달라졌으면 동의 초기화.',
 '재검증·해당 버전 동의가 모두 맞아야 원자적 반영. 실패하면 미합의 변경을 적용하지 않음')]
for i,(n,title,typ,a,b) in enumerate(steps):
    y=270+i*181
    f.rect(60,y,1480,151,C[typ]); f.rect(60,y,8,151,C[typ+'_accent'],r=3)
    f.text(85,y+18,n,31,C[typ+'_accent'],True); f.text(155,y+17,title,29,bold=True)
    f.text(155,y+64,a,23,C['ink']); f.text(155,y+103,b,22,C['muted'])
    if i<7 and i!=5: f.line([(800,y+152),(800,y+177)])
# New version loops back to validation; all-accepted responses bypass revision.
f.line([(60,1250),(28,1250),(28,526),(60,526)],C['code_accent'])
f.line([(1540,888),(1570,888),(1570,1431),(1540,1431)],C['llm_accent'])
f.rect(60,1730,1480,225,'#e8efff')
f.text(85,1752,'업무 자체도 분해할 수 있다 · whole_task',29,bold=True)
f.text(85,1800,'예: 원래 4일 → A 핵심 2일 → B 정상 계약 검증 1일 + C 실패/격리 검증 1일 (B·C 병렬)',25)
f.text(85,1842,'전체 노력 4일을 보존하고 depends_on으로 병렬 DAG를 명시. 원 업무는 모든 조각 완료를 기다리는 장벽이 된다.',23,C['muted'])
f.text(85,1881,'원래 후속 업무·마감은 유지한다. Hive가 효과를 검증하고 A·B·C 및 영향 당사자가 새 배분에 동의해야 한다.',23,C['muted'])
f.band(1990,'END','종료는 세 가지 · 무조건 합의로 표시하지 않는다','라운드 한도는 기본 15, 설정 범위 1–50. 한 라운드에 여러 참여자의 LLM 호출이 발생할 수 있다.')
f.row(2070,[('합의 완료',['검증 + 해당 버전 전원 동의','기한 회복이면 기준 배분 저장','→ 공정성 단계로 계속 진행'],'code'),('대안 소진 / 최대 라운드',['no_valid_alternative / max_rounds','기한 단계 → PM 검토','공정성 단계 → 기준 배분 유지'],'human'),('사람 거절 / 일정 변화',['거절 → 수정 협상으로 복귀','일정 변경 → 재동의 라운드','커밋 검증 실패 → 롤백·종료'],'code')],arrows=False)
f.text(60,2280,'TRACE  각 REQUEST / 응답 / BLOCKED / AGREED / END와 라운드·제안 버전·사유를 Run에 기록',23,C['code_accent'],True)
f.text(60,2324,'공정성 지표의 변화는 전후 평가·제안 참고다. 분산 최소안을 자동으로 골라 당사자 협상을 대신하지 않는다.',23,C['muted'])
f.text(60,2395,'SOURCE  app/discussion.py: turn / preview / commit / _end · app/task_partition.py',19,C['muted'])
f.save('negotiation_round_detail')
print('Created two SVG + 2× PNG figures in',OUT)
