# coding: utf-8
"""Append 'T1-T5 expected vs actual' pages to docs/Report.pdf from saved Live experiment summaries.

Reads past_versions/agent_prompts/<version>/experiments/<stamp>_live/summary.json for the
versions listed in VERSIONS, so every number on the page comes from a saved run.
Keeps all existing pages; re-running replaces only the pages this script added
(/PlanBeeM4ResultsBase). Run after append_agent_md_report.py.
"""
from pathlib import Path
from io import BytesIO
import json
import sys
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
INK = '#203249'; MUTED = '#56677b'; BLUE = '#e9f0fc'; GREEN = '#e4f3ec'; GOLD = '#fcf0d8'; RED = '#fbe4e4'
DATE = '2026-11-23'
VERSIONS = ['v006', 'v007', 'v008', 'v009']
SCEN = ['m4_t1_rescheduling', 'm4_t2_reallocation', 'm4_t3_scope_reduction', 'm4_t4_composite', 'm4_t5_infeasible']
LABEL = {'m4_t1_rescheduling': 'T1 일정 이동', 'm4_t2_reallocation': 'T2 업무 재분배', 'm4_t3_scope_reduction': 'T3 범위 이관',
         'm4_t4_composite': 'T4 복합 조정', 'm4_t5_infeasible': 'T5 해결 불가'}
EXPECT = {
    'm4_t1_rescheduling': ('PM 선택 대기', 'Polish만 다음 월요일로 이동, 소요 0.75일 유지, Bug Fix 일정 불변. 참가자는 Dev 한 명.'),
    'm4_t2_reallocation': ('PM 선택 대기', 'UI Integration을 로직 1일(Dev) / 에셋 연결 1일(Art)로 분담. Bug Fix, Integration Test 일정 유지. Art 본인 확인 필요.'),
    'm4_t3_scope_reduction': ('PM 선택 대기', 'Advanced Effects 4일과 잔여 Art FX 0.5일을 Beta로 이관. Core Integration 1일, Final QA 2일 유지. GD가 영향 당사자.'),
    'm4_t4_composite': ('PM 선택 대기', 'Anim Integration을 임시 반영 / 최종 교체 2단계(합 1일)로 분해, 최종 교체는 FX 이후. Retest 생략안은 QA 본인 확인 필요.'),
    'm4_t5_infeasible': ('PM 검토 (search_exhausted)', '유효 후보 0개. Dev, QA의 제약 검토 의견과 함께 PM에 보류 검토 전달. 마감 자동 연장 없음.'),
}


ANALYSIS = [
    ('버전별로 막힌 지점과 보완',
     'v006: T4가 평가 단계에서 존재하지 않는 후보 ID를 참조해 종료 -> v007에서 정확한 ID 목록으로 1회 재요청 추가.\n'
     'v007: T3가 생성 단계에서 종료. 프롬프트의 "이관은 parts=[]"를 모델이 template 최상위 parts로 오해 -> v008에서 빈 parts를 원 업무 전체로 정규화하고, 형식이 틀린 template 하나만 제외하도록 변경.\n'
     'v008: T3가 생성은 통과(기대 후보 3개)했으나 공개 발언이 목록에 없는 후보·수신자를 가리켜 종료 -> v009에서 수신자 이름을 id로 정규화하고 후보 ID를 1회 재요청.', 'llm'),
    ('기대와 실제가 일치한 부분',
     '일정·제약 판단(Hive)은 모든 버전에서 기대와 같았다. T5는 매번 후보 0개로 PM 검토에 전달됐고 마감을 연장하지 않았다. '
     'T4는 Retest 유지안과 QA 확인이 필요한 Retest 생략안이 함께 나와, 생략을 정답으로 강제하지 않는다는 시나리오 의도와 맞았다. '
     'T1은 Dev 한 명만 참여해 불필요한 호출이 없었다(5회).', 'code'),
    ('해석의 한계',
     '시나리오당 Live 1회 결과라 성공률이 아니다. 같은 버전도 LLM 응답에 따라 다른 지점에서 형식 오류가 날 수 있다(v009에서도 T2 평가 재요청, T3 template 제외가 발생). '
     '"기대 도달"은 PM 선택 대기 또는 PM 검토 상태와 기대 후보의 존재를 뜻하며, 실제 PM 선택·본인 확인·적용 성공과는 별도로 평가해야 한다.', 'human'),
]


def latest_live(version):
    found = sorted((ROOT / 'past_versions/agent_prompts').glob(f'*_{version}_*/experiments/*_live/summary.json'))
    if not found:
        sys.exit(f'{version} Live 실험 결과가 없습니다')
    return found[-1], {r['scenario']: r for r in json.loads(found[-1].read_text(encoding='utf-8'))}


RUNS = {v: latest_live(v) for v in VERSIONS}

reader = PdfReader(TARGET)
meta = reader.metadata or {}
base = int(meta.get('/PlanBeeM4ResultsBase', len(reader.pages)))
buf = BytesIO(); c = canvas.Canvas(buf, pagesize=A4)


def wrap(value, size, width):
    # 이 CID 글꼴에는 가운뎃점(·) 글리프가 없어 쉼표로 바꾼다.
    value = value.replace(' · ', ', ').replace('·', ', ')
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
    text(38, H - 40, f'PLAN BEE  /  M4 SCENARIO RESULTS  /  {DATE}', 8, '#45618a')
    text(38, H - 77, title, 21)
    text(38, H - 105, sub, 10, MUTED, W - 76)
    c.setStrokeColor(HexColor('#d8e1eb')); c.line(38, 38, W - 38, 38)
    text(38, 23, '근거: past_versions/agent_prompts/<버전>/experiments/*_live · 판정: scripts/check_m4_results.py', 8, MUTED)
    text(W - 62, 23, str(base + n), 9, MUTED)


def box(x, y, w, title, body, kind):
    color = {'code': BLUE, 'llm': GREEN, 'human': GOLD, 'bad': RED}[kind]
    n = len(wrap(body, 9, w - 26))
    h = 34 + n * 13 + 4
    c.setFillColor(HexColor(color)); c.roundRect(x, y - h, w, h, 10, fill=1, stroke=0)
    text(x + 13, y - 19, title, 11)
    text(x + 13, y - 36, body, 9, MUTED, w - 26, 13)
    return y - h


def outcome(r):
    if r['checks']['expected_outcome_ready']:
        return '기대 도달', GREEN
    return {'model_output_invalid': '형식 오류 종료', 'search_exhausted': '후보 없음'}.get(r['termination'], r['termination'] or r['status']), RED


# ── 17. 기대 결과와 버전별 실제 결과 ────────────────────────────────────
page(1, '17. T1~T5 기대 결과와 실제 Live 실행',
     '같은 판정기로 각 프롬프트·코드 버전의 Live 실행(gpt-4o-mini, 시나리오당 1회)을 채점했다. 사람의 PM 선택·본인 확인은 시뮬레이션하지 않으므로 "기대 도달"은 적용 성공이 아니라 기대한 상태와 후보에 도달했다는 뜻이다.')
y = H - 150
for sid in SCEN:
    state, body = EXPECT[sid]
    y = box(44, y, W - 88, f'{LABEL[sid]}  |  기대 상태: {state}', body, 'code') - 6
y -= 8
# version table
cols = [44, 150] + [150 + i * 98 for i in range(1, len(VERSIONS) + 1)]
c.setFillColor(HexColor('#e2e8f0')); c.rect(44, y - 20, W - 88, 20, fill=1, stroke=0)
text(52, y - 14, '시나리오', 9)
for i, v in enumerate(VERSIONS):
    text(cols[i + 1] + 8, y - 14, v, 9)
y -= 20
for sid in SCEN:
    c.setStrokeColor(HexColor('#d8e1eb')); c.line(44, y - 30, W - 44, y - 30)
    text(52, y - 13, LABEL[sid], 9)
    for i, v in enumerate(VERSIONS):
        r = RUNS[v][1].get(sid)
        if not r:
            text(cols[i + 1] + 8, y - 13, '-', 9, MUTED); continue
        label, color = outcome(r)
        c.setFillColor(HexColor(color)); c.roundRect(cols[i + 1] + 4, y - 27, 92, 24, 5, fill=1, stroke=0)
        text(cols[i + 1] + 9, y - 13, label, 8)
        text(cols[i + 1] + 9, y - 23, f"호출 {r['llm_budget']['used']}회, {r['duration_seconds']:.0f}초", 7, MUTED)
    y -= 30
text(44, y - 16, '초록 = 판정기 기준 기대 결과 도달, 빨강 = 미도달, - = 미실행(v007 실험은 T4 토론 중 사용자 요청으로 중단, T5 미실행). 각 칸은 해당 버전의 마지막 Live 실험 1회다.', 8, MUTED, W - 88)
c.showPage()

# ── 18. 비교 분석 ───────────────────────────────────────────────────────
last = VERSIONS[-1]; R = RUNS[last][1]
ok = sum(R[s]['checks']['expected_outcome_ready'] for s in SCEN)
page(2, '18. 기대와 실제의 차이 분석',
     f'최신 {last}에서 5개 중 {ok}개가 기대 상태에 도달했다. 실패는 모두 일정·제약 판단이 아니라 LLM 응답 형식에서 발생했고, 버전마다 그 지점을 하나씩 보완했다.')
y = H - 140
detail = []
for sid in SCEN:
    r = R[sid]; ch = r['checks']
    extra = f"기대에 맞는 후보 {len(ch['matching_candidates'])}개, 그중 PM 추천안 {len(ch['matching_pm_options'])}개"
    if ch['qa_confirm_compromise_candidates']:
        extra += f", QA 확인이 필요한 Retest 생략안 {len(ch['qa_confirm_compromise_candidates'])}개"
    if sid == 'm4_t5_infeasible':
        extra = '후보 0개로 search_exhausted, PM 검토로 전달'
    detail.append(f"{LABEL[sid]}: {outcome(r)[0]} ({extra})")
y = box(44, y, W - 88, f'{last} 시나리오별 결과', '\n'.join(detail), 'code') - 10
for title, body, kind in ANALYSIS:
    y = box(44, y, W - 88, title, body, kind) - 10
c.showPage()

c.save(); buf.seek(0)
appendix = PdfReader(buf); writer = PdfWriter()
for p in reader.pages[:base]:
    writer.add_page(p)
for p in appendix.pages:
    writer.add_page(p)
writer.add_metadata({**dict(meta), '/PlanBeeM4ResultsBase': str(base), '/PlanBeeM4ResultsVersion': DATE})
temp = TARGET.with_suffix('.pending.pdf')
with open(temp, 'wb') as f:
    writer.write(f)
temp.replace(TARGET)
print(f'{TARGET}: {base} existing pages + {len(appendix.pages)} result pages')
for v, (path, _) in RUNS.items():
    print(v, path.parent.relative_to(ROOT))
qa = Path('/tmp/pdfs'); qa.mkdir(parents=True, exist_ok=True)
pdf = pymupdf.open(TARGET)
for i in range(base, len(pdf)):
    pdf[i].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(qa / f'm4-results-{i + 1}.png')
