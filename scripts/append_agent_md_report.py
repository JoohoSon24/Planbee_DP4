# coding: utf-8
"""Append a short guide to each agent prompt MD (prompts/*.md) to docs/Report.pdf.

Keeps every existing page. Re-running replaces only the pages this script added
(tracked by the /PlanBeeAgentMdBase metadata). Style matches append_discussion_report.py.
Requires reportlab, pypdf, pymupdf. Run with .venv/bin/python.
Note: append_discussion_report.py rebuilds pages 11+ from its own base, so run this
script again after it.
"""
from pathlib import Path
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'docs/Report.pdf'
FONT = 'HYSMyeongJo-Medium'
pdfmetrics.registerFont(UnicodeCIDFont(FONT))
W, H = A4
INK = '#203249'; MUTED = '#56677b'; BLUE = '#e9f0fc'; GREEN = '#e4f3ec'; GOLD = '#fcf0d8'
DATE = '2026-11-23'

reader = PdfReader(TARGET)
meta = reader.metadata or {}
base = int(meta.get('/PlanBeeAgentMdBase', len(reader.pages)))
buf = BytesIO(); c = canvas.Canvas(buf, pagesize=A4)


def wrap(value, size, width):
    lines = []; line = ''
    for ch in value:
        if ch == '\n' or (width and pdfmetrics.stringWidth(line + ch, FONT, size) > width):
            lines.append(line); line = '' if ch == '\n' else ch
        else:
            line += ch
    lines.append(line)
    return lines


def text(x, y, value, size=10, color=INK, width=None, leading=None):
    c.setFillColor(HexColor(color)); c.setFont(FONT, size)
    leading = leading or size * 1.55
    lines = wrap(value, size, width)
    for i, line in enumerate(lines):
        c.drawString(x, y - i * leading, line)
    return y - len(lines) * leading


def page(n, title, sub):
    c.setFillColor(HexColor('#f7f9fc')); c.rect(0, 0, W, H, fill=1, stroke=0)
    text(38, H - 40, f'PLAN BEE  /  AGENT PROMPT NOTE  /  {DATE}', 8, '#45618a')
    text(38, H - 77, title, 21)
    text(38, H - 105, sub, 10, MUTED, W - 76)
    c.setStrokeColor(HexColor('#d8e1eb')); c.line(38, 38, W - 38, 38)
    text(38, 23, '현행 V2 candidate_discussion 기준 · prompts/ · app/llm.py _ask()', 8, MUTED)
    text(W - 62, 23, str(base + n), 9, MUTED)


def box(x, y, w, title, body, kind):
    """Draw a box whose height fits its body; return the y just below it."""
    color = {'code': BLUE, 'llm': GREEN, 'human': GOLD}[kind]
    n = len(wrap(body, 9, w - 26))
    h = 34 + n * 13 + 4
    c.setFillColor(HexColor(color)); c.roundRect(x, y - h, w, h, 10, fill=1, stroke=0)
    text(x + 13, y - 19, title, 11)
    text(x + 13, y - 36, body, 9, MUTED, w - 26, 13)
    return y - h


# ── 15. 역할 MD ─────────────────────────────────────────────────────────
page(1, '15. 에이전트별 MD 프롬프트의 역할',
     'prompts/ 아래 MD는 각 LLM 호출의 지시문이다. 코드를 바꾸지 않고 에이전트의 판단 기준을 조정하는 곳이며, run 시작 시 hash로 고정된다.')
y = H - 132
y = box(44, y, W - 88, '한 번의 개인 Proxy 호출에 들어가는 MD',
        'system 메시지 = discussion/system.md (공통 규칙) + discussion/actor.md (본인 이름, 위임카드) + agents/<역할>.md (본인 역할 지침)\n'
        'user 메시지 = 호출별 MD (assess | speak | rank | candidate_consent 등) + 입력 데이터(JSON)\n'
        '다른 사람의 역할 MD와 위임카드는 들어가지 않는다. 생성 AI 호출에는 역할 MD, 카드가 없다.', 'code') - 14
roles = [
    ('agents/dev.md | Dev Proxy (구현 담당)',
     '원래 소요량이 보존되는지 확인한다(단순 이동에 소요 증가 금지). Task에 적힌 분리 경계(로직 전담 / 에셋 연결)를 지킨다. '
     '기능 우선순위는 추측하지 않고 GD에게 공개 질문한다. 임시 반영과 최종 교체를 구분하며, QA 시간 단축으로 일정 충돌을 덮지 않는다.'),
    ('agents/art.md | Art Proxy (에셋 담당)',
     '수행 가능한 에셋 연결은 검토한다. 본인 확인이 필요한 신규 인수는 NEEDS_INPUT이며 금지(REJECT)와 혼동하지 않는다. '
     '지연을 알릴 때 기존, 새 총 소요량, 최종 전달 시각, 미리 줄 수 있는 중간 산출물을 구분한다. 공개 발언에 카드 원문을 인용하지 않는다.'),
    ('agents/gd.md | GD Proxy (기획, 범위 담당)',
     '카드의 기능 우선순위와 범위 변경 권한을 따른다. 필수 Core를 보호하고, 선택 기능 이관이 현재 milestone 완료 기준을 유지하는지 검토한다. '
     '판단 근거만 공개하고, 자기 동의가 PM 최종 선택을 대신하지 않는다. 타인의 단독 이동에 불필요한 veto를 걸지 않는다.'),
    ('agents/qa.md | QA Proxy (검증 담당)',
     '선행 산출물 완료 전 검증이나 필수 Final QA 단축에는 동의하지 않는다. 선택 중간 Retest와 필수 최종 검증을 구분하고, '
     '카드가 허용하는 Retest 생략도 본인 확인이 필요하면 NEEDS_INPUT으로 답한다. 실제 가능한 검증 시작, 종료를 PM이 판단할 수 있게 설명한다.'),
    ('agents/reestimate.md | 담당자 재견적 (그림 1의 02단계)',
     '이슈가 일정 이동인지 소요량 변화인지(duration_changed) 먼저 정한다. "하루 뒤로 이동"은 소요 변화가 아니다. '
     '소요가 바뀌면 새 총 견적(days), 근거, 이슈 원문의 정확한 인용을 답한다. 근거 없이 견적을 올리지 않는다.'),
]
for title, body in roles:
    y = box(44, y, W - 88, title, body, 'llm') - 10
text(44, 62, '공통 원칙: 동의는 해당 후보 버전(plan hash)에만 유효하다. 역할 MD는 판단 기준을 주지만 숫자, 일정의 유효성은 Hive 코드가 검사한다.',
     9, '#345b92', W - 88)
c.showPage()

# ── 16. 호출별 MD ───────────────────────────────────────────────────────
page(2, '16. 호출별 MD: 무엇을 언제 지시하는가',
     '역할 MD가 "누구로서" 판단할지를 정한다면, 호출별 MD는 "이번 호출에서 무엇을 답할지"를 정한다. 괄호는 그림 1의 단계 번호다.')
y = H - 132
calls = [
    ('candidate_generation/system.md + transform.md | 생성 AI (03)',
     '실행 가능성만 설계하는 후보 생성 담당. 카드, 정답 없이 이슈와 Task 계약을 읽고 서로 다른 계획 구조를 최대 12개 제안한다. '
     '공정성 승자를 고르지 않고, 목적, 완료 기준, 원래 마감을 바꾸지 않는다.', 'llm'),
    ('candidate_generation/repair.md | format_repair.md | 생성 AI 복구 (03)',
     'repair: Hive가 모든 후보를 반려했을 때 탈락 사유를 근거로 다른 구조를 1회 제안한다. '
     'format_repair: 응답 형식 오류 시 필드별 오류를 받아 1회만 다시 제출한다.', 'llm'),
    ('discussion/system.md | actor.md | 모든 개인 Proxy 공통',
     'system: 본인 기록만 근거로, answer 함수 한 번으로 답한다. 근거 없는 내용은 지어내지 않는다. actor: 이번 호출의 본인 이름, ID, 위임카드를 채워 넣는 틀이다.', 'code'),
    ('discussion/assess.md | rank.md | 초기 / 최종 평가 (05)',
     '제시된 모든 후보에 ACCEPT / REJECT / NEEDS_INPUT과 종합, 공정성, 카드 적합성 점수(0~100)를 빠짐없이 답한다. '
     'rank는 토론에서 나온 질문, 조건을 반영하고, 판단이 바뀌면 공개 가능한 이유를 남긴다.', 'llm'),
    ('discussion/speak.md | 공개 발언 (05)',
     '이번 턴에 QUESTION | ANSWER | PREFER | REJECT | CONDITION | PASS 중 하나를 말한다. 앞사람의 질문과 조건에 실제로 답하고 같은 말을 반복하지 않는다.', 'llm'),
    ('discussion/candidate_consent.md | 후보별 동의 (06)',
     '정확한 후보 ID, plan hash의 전체 변경을 보고 답한다. 카드의 실제 금지는 REJECT, 자동 권한 밖이지만 본인 확인으로 가능한 것은 NEEDS_INPUT, 권한 안은 ACCEPT.', 'llm'),
    ('discussion/assessment_repair.md | format_repair.md | 응답 복구',
     '평가의 후보 ID 누락, 중복, 오타나 스키마 오류를 구체적 피드백과 함께 1회 다시 요청한다. 재실패하면 run을 중단하고 사유를 기록한다.', 'code'),
]
for title, body, kind in calls:
    y = box(44, y, W - 88, title, body, kind) - 9
text(44, 62, '초록 = LLM 판단 지시 | 파랑 = 공통 틀, 복구 규칙. legacy 경로용 MD(strategy_*, design, partition, revision 등)는 V2 주 흐름에서 쓰지 않는다.',
     8, MUTED, W - 88)
c.showPage()

c.save(); buf.seek(0)
appendix = PdfReader(buf); writer = PdfWriter()
for p in reader.pages[:base]:
    writer.add_page(p)
for p in appendix.pages:
    writer.add_page(p)
writer.add_metadata({**{k: v for k, v in meta.items()}, '/PlanBeeAgentMdBase': str(base), '/PlanBeeAgentMdVersion': DATE})
temp = TARGET.with_suffix('.pending.pdf')
with open(temp, 'wb') as f:
    writer.write(f)
temp.replace(TARGET)
print(f'{TARGET}: {base} existing pages + {len(appendix.pages)} agent MD pages')

qa = Path('/tmp/pdfs'); qa.mkdir(parents=True, exist_ok=True)
pdf = pymupdf.open(TARGET)
for i in range(base, len(pdf)):
    pdf[i].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(qa / f'agent-md-report-{i + 1}.png')
