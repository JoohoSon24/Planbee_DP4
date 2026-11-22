# coding: utf-8
"""Append the current discussion design to Report.pdf, preserving its original pages.
Requires reportlab, pypdf, pymupdf. Run with .venv/bin/python.
"""
from pathlib import Path
from io import BytesIO
from html import escape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader,PdfWriter
import pymupdf
ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'docs/Report.pdf'
FONT='HYSMyeongJo-Medium'
pdfmetrics.registerFont(UnicodeCIDFont(FONT))
W,H=A4
INK='#203249';MUTED='#56677b';BLUE='#e9f0fc';GREEN='#e4f3ec';GOLD='#fcf0d8'
buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
reader=PdfReader(TARGET)
base=int((reader.metadata or {}).get('/PlanBeeBasePages',len(reader.pages)))
backup=Path('/tmp/planbee-report-before-discussion.pdf')
if not backup.exists():backup.write_bytes(TARGET.read_bytes())

def text(x,y,value,size=10,color=INK,width=None,leading=None):
    c.setFillColor(HexColor(color));c.setFont(FONT,size)
    leading=leading or size*1.55
    lines=[];line=''
    for ch in value:
        if ch=='\n' or (width and pdfmetrics.stringWidth(line+ch,FONT,size)>width):
            lines.append(line);line='' if ch=='\n' else ch
        else:line+=ch
    lines.append(line)
    for i,line in enumerate(lines):c.drawString(x,y-i*leading,line)
    return y-len(lines)*leading

def page(n,title,sub):
    c.setFillColor(HexColor('#f7f9fc'));c.rect(0,0,W,H,fill=1,stroke=0)
    text(38,H-40,'PLAN BEE  /  DISCUSSION ENGINEERING NOTE  /  2026-11-19',8,'#45618a')
    text(38,H-77,title,21)
    text(38,H-105,sub,10,MUTED,W-76)
    c.setStrokeColor(HexColor('#d8e1eb'));c.line(38,38,W-38,38)
    text(38,23,'기존 본문 이후의 현행 코드 보충 · app/discussion.py / app/llm.py',8,MUTED)
    text(W-62,23,str(base+n),9,MUTED)

def box(x,y,w,h,title,body,kind='code'):
    color={'code':BLUE,'llm':GREEN,'human':GOLD}[kind]
    c.setFillColor(HexColor(color));c.roundRect(x,y-h,w,h,10,fill=1,stroke=0)
    text(x+13,y-21,title,11)
    text(x+13,y-40,body,9,MUTED,w-26,13)

def arrow(x,y,end):
    c.setStrokeColor(HexColor('#7890aa'));c.line(x,y,x,end)
    c.line(x,end,x-4,end+6);c.line(x,end,x+4,end+6)

page(1,'11. discussion / bids round 확대도','초록 = 개인 LLM 호출 · 파랑 = Hive 코드 · 노랑 = 사람 확인. 수치 평가가 협상 동의를 대신하지 않는다.')
text(38,H-125,'A = 원 담당자 · B = 최초 수신자 · C = 추가 참여자. 수락/대안 설계는 각 개인 프록시의 호출 종류다.',8,MUTED,W-76)
rows=[
 ('Hive · A → B 요청과 현재 버전 v 준비','원 Task 전체 context, 현재 배분·일정, 공개 조건·이력, 당사자 목록을 준비한다.','code'),
 ('Hive · preview() / 일정 사전 검증','마감·용량·부재·역할·의존관계 검사. 위반이면 구체적 사유를 공개하고 revise로 이동한다.','code'),
 ('각 당사자 A/B/C · 수락 판단 LLM / respond','ConsentDecision: 자기 카드와 현재 자기 업무로 판단. 카드 적합성·실제 한도·동의 여부를 출력한다.','llm'),
 ('각 당사자 A/B/C · 대안 설계 LLM / revise','RevisionProposal / PartitionDraft: 분할·양도·업무 이동·협업 대안 또는 PASS.','llm'),
 ('Hive · 제안 검증과 버전 전이','분량 보존·범위 중복·공개 한도·일정 검사. 새 안이면 v+1, 모든 수락 초기화, 새 당사자 초대.','code'),
 ('당사자 전체 동의 / 필요하면 사람 확인','받는 사람뿐 아니라 주는 사람, 이동되는 다른 업무 담당, 지원자와 일정 영향 당사자의 동의가 필요하다.','human'),
 ('Hive · discussion_commit() 재검증','최신 보드 재계산, 버전·동의·일정 서명 확인. 달라진 일정에는 다시 동의. 통과한 변경만 반영.','code'),
 ('합의 또는 종료 · PM summary','미합의 변경 미적용. 기한 회복 실패는 PM 검토, 공정성 실패는 검증된 마감 기준 배분 유지.','code')]
for i,(title,body,kind) in enumerate(rows):
    y=H-152-i*76;box(44,y,W-88,63,title,body,kind)
    if i<7 and i!=4:arrow(W/2,y-64,y-74)
    if i==2:text(W/2+9,y-70,'거절 / 수정 필요',7,MUTED)
# Consent bypasses revision; an adopted counter returns to the next preview.
def branch(x,from_row,to_row,label):
    y1=H-152-from_row*76-31;y2=H-152-to_row*76-31
    edge=44 if x<W/2 else W-44
    c.setStrokeColor(HexColor('#7890aa'));c.lines([(edge,y1,x,y1),(x,y1,x,y2),(x,y2,edge,y2)])
    direction=1 if edge>x else -1
    c.lines([(edge,y2,edge-5*direction,y2+3),(edge,y2,edge-5*direction,y2-3)])
    c.saveState();c.translate(x-5,min(y1,y2)+15);c.rotate(90);text(0,0,label,7,'#345b92');c.restoreState()
branch(24,2,5,'ACCEPT / NEEDS_INPUT')
branch(W-22,4,1,'COUNTER v+1 : next round')
text(44,64,'반복 경로: REJECT → revise → COUNTER v+1 → preview → 영향 당사자 전원 respond',9,'#345b92',W-88)
c.showPage()

page(2,'12. 각 LLM 호출의 입력과 의미','각 호출의 모델은 해당 개인의 설정을 사용한다. 다른 사람의 비공개 위임카드 원문은 입력에 포함하지 않는다.')
calls=[
 ('A · reestimate() / EstimateDecision','입력: 담당자 기록, 자기 Task context와 현 견적\n출력: task / days / basis / evidence 또는 변경 없음. 정확한 기록 인용 없이 견적을 올리지 않는다.'),
 ('B · split() / Split','입력: 원 Task 목적·산출물·분리 경계·완료 기준·이전 피드백\n출력: 독립 조각 + 보유분 + 인수인계 방향 또는 splittable=false와 이유. false는 일정 불가능의 판정이 아니다.'),
 ('C · discuss(respond) / ConsentDecision','입력: 자기 카드, 현재 v의 자기 신규 업무, 공개 업무·마감·대화\n출력: settings_check / settings_reason / max_incoming_days / action / reason. 실제 업무 금지와 자동 수락 권한을 구분한다.'),
 ('D · discuss(revise) / RevisionProposal · PartitionDraft','입력: 자기 카드, 공개 거절·한도·검증 피드백, 전체 Task context, 일정 참고 패턴\n출력: 전체 대안 또는 PASS. 독립 분할은 LLM이 숫자 패턴을 선택하고 실제 산출물·의존관계를 작성한다. 코드가 선택이나 동의를 대신하지 않는다.'),
 ('E · reply() / help_reply() / wait_reply()','초기 위임 경로의 조각 응답, 지원 요청 응답, 수신 시각 변경 응답에 사용한다. 개인 카드로 수락·거절·조건을 판단하며 이후 discussion에 공개 피드백을 승계한다.'),
 ('F · interpret_card() / CardPolicy','별도 카드 작성 API. 자기 자연어 메모를 정책 초안으로 해석한다. 사람이 확인한 정책만 가용 시간·용량 검증에 반영한다.')]
for i,(title,body) in enumerate(calls):box(44,H-150-i*95,W-88,82,title,body,'llm')
text(44,71,'호출 장애는 거절이 아니다: 일시적 HTTP 오류는 제한 재시도. 호출 불가와 출력 형식 오류도 구분하여 기록한다.',9,MUTED,W-88)
c.showPage()

page(3,'13. help는 분할만 하는가?','독립 분리 판단과 전체 일정의 회복 전략을 구분한다. 분리 불가 이후에도 아래 대안을 협상한다.')
strategies=[
 ('1 · 독립 분할 / whole_task 재분해','각 조각의 범위·effort 합을 보존한다. 독립이면 병렬, 선행 작업이 있으면 key/depends_on으로 명시한다. 원 Task 전체 분해에는 보유분도 포함한다.'),
 ('2 · 전체 양도','분리 금지 업무도 한 사람에게 온전히 양도할 수 있다. 기존 Task/Handoff와 마감을 유지하고 원 담당자·수신자·영향 당사자 동의를 받는다.'),
 ('3 · 다른 업무의 담당·위치 변경','schedule_changes={task,start,who}로 미착수 업무를 옮긴다. 원 업무를 그대로 유지해도 다른 업무를 이동하여 시간을 확보할 수 있다. 과거·완료 업무 이동은 금지한다.'),
 ('4 · 명시적 협업','support={who,days,what}와 basis를 제시한다. 지원 작업도 실제 일정·용량에 포함한다. 주 작업 단축은 근거가 있어야 하며 지원이 본 업무보다 늦으면 차단한다.')]
for i,(title,body) in enumerate(strategies):box(44,H-151-i*112,W-88,96,title,body,'code' if i!=3 else 'llm')
box(44,220,W-88,120,'종료 전 대안 탐색과 동의','처음 두 사람의 대안 소진은 팀 전체 소진이 아니다. 아직 묻지 않은 후보를 초대한다. 한 전략이 소진되면 전체 양도·다른 업무 이동·협업으로 중점 전략을 바꿔 새 요청을 보낸다. 같은 버전·전략의 PASS를 이유 없이 재호출하지 않는다.\n새 버전은 모든 수락을 초기화한다. 최대 라운드 / 후보·전략 소진 / 호출 장애를 구분하고 미합의 변경은 적용하지 않는다.','human')
text(44,73,'범위: 임의의 미래 업무를 무제한 재분해하는 전역 최적화기가 아니다. 합의된 대안과 실제 제약 검증이 적용의 조건이다.',9,MUTED,W-88)
c.showPage()

page(4,'14. Task 근거와 관측·검증 계약','다이어그램은 설계와 호출 경로를 설명한다. Mock 대본이나 자동 사람 확인을 실제 Live 자발적 합의 성능과 혼동하지 않는다.')
box(44,H-151,W-88,118,'LLM이 실제로 읽는 Task 근거','seed/*/team.yaml → DB Task.context → discussion의 original_task.context와 전체 tasks[].context\ndescription / purpose / deliverable / split_boundary / acceptance 등을 판단 입력으로 전달한다.\n사람용 Markdown: docs/DEMOS.md의 각 Task 세부 description. LLM이 Markdown 파일을 직접 읽는 방식은 아니다.','code')
box(44,H-290,W-88,134,'한 라운드의 기록과 재동의','Run에는 처리 단계(01/02/03), 라운드, 발화자→수신자, 현재 버전, 제안 내용, 응답·거절 사유·조건, Hive 반려·최종 검증과 초기/턴별/최종 milestone을 기록한다.\nCOUNTER v+1은 기존 수락을 재사용하지 않는다. 다른 업무의 양도나 협업 지원이 추가되면 그 당사자도 참여한다.','code')
box(44,H-446,W-88,112,'공개 참고 패턴은 자동 선택이 아니다','공개 일정과 공개된 당사자 한도만으로 독립 분량의 가능한 숫자 조합을 참고 제공한다. 실제로 나눌 수 있는 산출물·의존관계는 LLM이 설계한다. 실제 제안은 다시 검증하며 공정성 분산 최소안을 자동 확정하지 않는다.','llm')
box(44,H-580,W-88,112,'Live 검증 해석과 남은 제한','gpt-4.1 전체 3단계: 40회 호출·오류 0회, 분할/재분해 합의 2회, 마지막 공정성 대안 소진 1회. 최종 Hive gate 통과. gpt-4o-mini의 미합의 실행도 보존했다.\n소수 실행과 자동 사람 확인은 일반 성공률·자동 위임 준수의 증명이 아니다. 원본은 runs/live 및 eval/live_debug, 비교 표는 AGENT_CALL_FLOW.md에 있다.','human')
text(44,70,'근거: app/llm.py · discussion.py · negotiation_contract.py · plan_adjustments.py · task_partition.py · tests/',8,MUTED,W-88)
c.save();buf.seek(0)
appendix=PdfReader(buf);writer=PdfWriter()
for p in reader.pages[:base]:writer.add_page(p)
for p in appendix.pages:writer.add_page(p)
writer.add_metadata({'/Title':'Plan Bee - Report and Discussion Architecture','/PlanBeeBasePages':str(base),'/PlanBeeDiscussionVersion':'2026-11-19'})
temp=TARGET.with_suffix('.pending.pdf')
with temp.open('wb') as f:writer.write(f)
temp.replace(TARGET)
# Render the appendix for mandatory visual QA and the docs' standalone zoom image.
qa=ROOT/'tmp/pdfs';qa.mkdir(parents=True,exist_ok=True)
pdf=pymupdf.open(TARGET)
for i in range(base,len(pdf)):
    pix=pdf[i].get_pixmap(matrix=pymupdf.Matrix(1.6,1.6));pix.save(qa/f'discussion-report-{i+1}.png')
    if i==base:pix.save(ROOT/'assets/docs/discussion_llm_zoom.png')
print(f'{TARGET}: {base} original + {len(appendix.pages)} appendix = {len(pdf)} pages')
