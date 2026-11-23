"""Build the proposed evaluation protocol; figures are design targets, not results."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph,Table,TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/PlanBee_Benchmark_Design.pdf'
pdfmetrics.registerFont(TTFont('Korean','/System/Library/Fonts/Supplemental/AppleGothic.ttf'))
W,H=595.28,841.89;M=44;CW=W-2*M
INK=colors.HexColor('#192D34');MUTED=colors.HexColor('#52676F');GOLD=colors.HexColor('#BA861C');PALE=colors.HexColor('#EDF3F2')
style=ParagraphStyle('body',fontName='Korean',fontSize=10,leading=16,textColor=INK,wordWrap='CJK',spaceAfter=8)
small=ParagraphStyle('small',parent=style,fontSize=8.6,leading=13)
c=canvas.Canvas(str(OUT),pagesize=(W,H));c.setTitle('Plan Bee 성능 평가 설계 - Quantitative & Qualitative');c.setAuthor('Plan Bee')
y=0;page=0

def begin(kicker,title,sub):
 global y,page
 page+=1;c.setFillColor(INK);c.rect(0,H-18,W,18,fill=1,stroke=0)
 c.setFont('Korean',9);c.setFillColor(GOLD);c.drawString(M,H-51,kicker)
 c.setFont('Korean',23);c.setFillColor(INK);c.drawString(M,H-85,title)
 y=H-112;p(sub,small);y-=8

def p(text,s=style):
 global y
 obj=Paragraph(text,s);_,h=obj.wrap(CW,700)
 assert y-h>48,(page,text,y,h)
 obj.drawOn(c,M,y-h);y-=h+8

def head(text):
 global y
 y-=6;c.setFont('Korean',12);c.setFillColor(INK);c.drawString(M,y-14,text);y-=28

def table(headers,rows,widths):
 global y
 data=[[Paragraph(x,small) for x in row] for row in [headers]+rows]
 t=Table(data,colWidths=[CW*x for x in widths],hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#CFDAD9')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
 _,h=t.wrap(CW,700);assert y-h>48,(page,y,h);t.drawOn(c,M,y-h);y-=h+14

def finish():
 c.setStrokeColor(colors.HexColor('#CFDAD9'));c.line(M,40,W-M,40);c.setFillColor(MUTED);c.setFont('Korean',8);c.drawString(M,26,'PLAN BEE  /  EVALUATION PROTOCOL  /  2026-11-24');c.drawRightString(W-M,26,f'{page:02d}');c.showPage()

begin('BENCHMARK DESIGN / PROPOSED','무엇을 성능이라고 볼 것인가','정량(Quan)과 정성(Qual)을 분리한 평가 설계안. 아래 표본 수와 기준은 제안값이며, 측정 완료 결과가 아니다.')
head('핵심 질문')
p('시간 안에 가능한 계획을 충분히 찾는가? 에이전트가 자기 카드와 상대 피드백으로 판단하는가? 사람이 납득할 후보를 고르고, 날짜가 바뀐 뒤에도 합의와 제약을 유지하는가?')
# Native vector flow: clear labels, no stretched character spacing.
labels=[('01 탐색','의미 구조 + 조합 확장'),('02 검증','Hive 하드 제약'),('03 협상','카드 + 공개 피드백'),('04 결정','PM 선택 + 적용')]
bw=(CW-27)/4;top=y
for i,(a,b) in enumerate(labels):
 x=M+i*(bw+9);c.setFillColor(PALE);c.roundRect(x,top-67,bw,64,7,fill=1,stroke=0);c.setFillColor(INK);c.setFont('Korean',11);c.drawString(x+10,top-25,a);c.setFont('Korean',8);c.drawString(x+10,top-46,b)
y-=89
head('모드를 섞으면 성능 결론이 무너진다')
table(['모드','평가할 수 있는 것','평가하면 안 되는 것'],[
['카드 기반 협상','수락·거절 적합성, 피드백 반영, 합의 품질','사람 확인이 남은 후보를 최종 합의로 집계'],
['T6 무조건 동의 시연','후보·일정 검증, UI 완주, PM 선택 경로','높은 합의율을 협상 지능의 증거로 사용'],
['Mock / 실제 Live','Mock은 회귀·제약 검사, Live는 행동·비용','Mock 성공을 Live 성능으로 합산']],[.22,.39,.39])
head('평가 단위와 기본 원칙')
p('단일 이슈 run, 동일 보드를 잇는 다회차 episode, 고정 후보 집합 평가를 별도 단위로 둔다. 마감 위반이나 동의 버전 오류가 있으면 빠르고 공정해 보여도 유효한 성공으로 세지 않는다.')
p('가능한 사례는 사전에 검증한 witness plan을 보유한다. 불가능·조건부 사례도 포함한다. 후보를 못 찾았다는 이유만으로 수학적 불가능이라고 판정하지 않는다.',small)
finish()

begin('01 / QUANTITATIVE','정량 지표와 분모','하나의 종합점수부터 만들지 않는다. 안전성 → 탐색 → 협상 → 사람 정렬 → 운영 비용 순서로 보고한다.')
table(['축','정의 / 반드시 함께 기록할 정보'],[
['제약 안전성','잘못 적용한 계획 수 / 전체 적용 수. 마감·용량·가용시간·역할·의존성·범위·서명을 별도 검사. 목표 0건.'],
['탐색 성공률','witness가 있는 실행 가능 사례 중 검증 후보를 1개 이상 찾은 비율. 생성 실패·예산 종료·후보 고갈을 분리.'],
['대안 커버리지','정답에 명시된 연산자/담당자 가족 중 발견한 가족 수. Ben 이관과 Sam+S3 이동을 다른 가족으로 집계. 제목만 다른 후보는 제외.'],
['거짓 성공 / 거짓 포기','불가능 사례를 성공 처리한 비율 / witness가 있는데 후보 없음으로 끝낸 비율. 조건부 승인을 미확정 성공으로 세지 않음.'],
['동의 적합성','영향 당사자의 정확한 plan hash 동의 비율, 명시적 금지 위반률, 변경 후 재동의 누락률. 무조건 동의 모드는 제외.'],
['다회차 완주','episode 전체 이슈를 유효하게 처리한 비율. 이전 합의의 비의도적 변경, 완료 작업 재배정, 잘못된 예시 노출, 자동 날짜 이동을 별도 집계.'],
['사람 선호 정렬','동일 후보 집합에서 공정성·본인 카드 적합성 순위를 각각 비교. CE/KL, top-1 일치, Kendall tau-b와 관측 커버리지.'],
['효율과 공정성 참고','run별 p50/p95 지연, 실제 요청·재시도·토큰·번역 비용. 부담 분산·최대 부담·정규화 사용률의 전후 변화는 참고 지표.']],[.23,.77])
head('모호한 “후보 없음”을 쪼개기')
p('종료 코드를 search_budget_exhausted / explored_no_candidate / model_error / no_consented_candidate / awaiting_pm_selection로 나눈다. PM 선택 대기는 정상 중간 상태이며 실패가 아니다. 분모에 포함된 모델 장애 수와 재시도 수를 숨기지 않는다.')
p('동일 실행 배치·범위·의존성을 plan hash로 중복 제거한다. 탐색 개수가 늘었어도 유효 가족 커버리지가 같으면 다양성 향상이라고 주장하지 않는다.',small)
finish()

begin('02 / DATASET','무엇을 어떤 정답으로 검증할까','원문 사례를 입력 문장만 모은 데이터가 아니라, 보드·카드·변경 사실·허용 결과가 고정된 fixture로 만든다.')
table(['사례 그룹','정답 라벨과 확인할 핵심'],[
['S01 QA 부재','가능. Ben 인수 / Sam 인수+S3 이동 witness를 각각 보존. Zoe 최종 회귀·서명 유지.'],
['S03·05·06·07·08','가능. 업무 이동·선택 범위 이관, P0 독립성. S06의 서로 다른 합법 시각도 수용.'],
['S02·04·12·13·16','조건부. 단계 분해, 중단·재개, 신규 범위, 추가 테스트, 다중 보고 등 구현 지원 여부를 별도 라벨. 미지원은 성공률 분모에서 몰래 제거하지 않음.'],
['S09·10·11·15·17','문서의 현재 하드 제약상 불가능. 분할 정책·서명 권한·QA 순서·마감을 우회한 허위 성공을 차단.'],
['S14 / 정책 변형','P1 제외는 숨은 P0 의존성이 없는지 확인. 허용 범위·승인 권한을 명시한 witness로 판정.']],[.3,.7])
head('다회차 episode - T6')
p('화요일 QA 부재 보고 → PM 적용 → 수요일 A2 이동(또는 슬롯이 허용하는 B2 이동) → 목요일 빌드 인계 재점검 → 금요일 실제 QA 완료 후 빌드 확인. 매 단계의 before/after 보드, 완료 사실, 신규 이슈 창, 합의 버전을 저장한다. 날짜는 Next/Previous 조작으로만 바뀐다.')
head('구성·분할 제안')
p('원형 17개에 슬롯·담당자·문장 변형을 각 3개 추가해 68개 fixture를 제안한다. 단순 수치 변형도 독립 fixture라 부르되 동일 원형 가족끼리는 개발/테스트 세트를 분리한다. 2명의 검토자가 라벨과 witness를 확인하고 불일치를 해결한다.')
p('각 fixture는 expected feasible / conditional / infeasible / unsupported를 구별한다. 조건부 사례는 필요한 확인·정책을 갖춘 변형과 갖추지 않은 변형을 짝으로 만든다. 현재 구현 지원 상태는 평가 실행 시 다시 감사한다.',small)
finish()

begin('03 / EXPERIMENT','비교 실험과 사람 순위 평가','후보 생성의 효과와 discussion의 효과를 분리한다. 동일 run 결과를 여러 독립 표본인 것처럼 세지 않는다.')
table(['실험','통제와 비교'],[
['생성 엔진 비교','근접 슬롯 탐색 vs 주간 전체 슬롯·결합 이동. 같은 보드·허용 연산자·raw budget·seed. 발견률과 비용 곡선을 함께 비교.'],
['협상 ablation','같은 동결 후보 풀에서 토론 없음 / 공개 정보 토론 / 본인 카드 기반 토론. 참가자 순서·후보 표시 순서는 seed로 통제.'],
['시연 대조군','T6 무조건 동의를 별도 행으로 둔다. UI·스케줄링 성공은 보고하되 협상 품질 우승으로 해석하지 않는다.'],
['반복 규모','pilot: 원형 17개×1 seed×2 설정=34회. 본 실험 제안: 68개×5 seed×4 설정=1,360회. 비용·표본 설계 확정 후 실행.']],[.25,.75])
head('사람 순위와 Cross-entropy')
p('사람과 LLM에 동일한 K개 검증 후보를 보여준다. 공정성은 동일 공개 정보, 카드 적합성은 해당 본인 카드만 제공한다. 사람은 LLM 순위·PM 결정에 노출되지 않은 상태에서 전체 순위와 동률, 별도 수락 여부를 기록한다.')
p('낮은 rank가 선호. 동률은 평균 rank. p(i)=softmax(-(human_rank(i)-1)/tau), q(i)=softmax(-(agent_rank(i)-1)/tau). 제안 tau=1을 사전 고정한다. CE=-sum p(i)log q(i), KL=CE-H(p), 균등 baseline=log K. K&lt;2는 순위 비교 불가로 표시한다.',small)
p('미평가 후보는 최하위로 만들지 않는다. 공통 관측 집합에서 조건부 정규화하고 coverage를 보고한다. 서로 다른 후보 풀의 CE를 무조건 평균하지 않는다. PM의 운영 선택은 독립 사람 평가 정답과 분리한다.',small)
head('불확실성 보고')
p('시나리오 가족 단위 paired bootstrap 95% 구간과 seed별 분산을 보고한다. 성공률의 분모·실패 수를 원자료와 함께 제시한다. 모델·프롬프트를 고르는 개발 세트와 최종 테스트를 분리하고, 테스트 결과를 본 뒤 기준을 바꾸지 않는다.')
finish()

begin('04 / QUALITATIVE','정성 평가 - 말의 수보다 논리','공개 대화와 실제 보드 변화를 함께 읽는다. 자기평가나 LLM judge 한 명을 정답으로 삼지 않는다.')
table(['차원','0점','1점','2점','3점'],[
['업무 이해','범위·순서 왜곡','추상 언급','구체 Task·산출물 확인','중간/최종 산출물과 연쇄 영향 정확'],
['피드백 반영','거절 무시·복사','상대 말 반복','조건에 맞는 답변','수정안과 타협 근거까지 연결'],
['카드·권한','비공개 누출·대리 수락','권한 혼동','자기 한도·확인 구분','예외 수락과 버전 동의까지 추적'],
['협력과 공정성','숫자 최소화로 대체','공정함만 주장','부담·역량 trade-off 설명','상대 조건을 반영해 대안 비교'],
['실패·인계 설명','허위 성공','후보 없음만 통보','원인과 미적용 상태 설명','탐색 한계·불가능·PM 선택지를 구분']],[.18,.17,.19,.22,.24])
head('검토 절차')
p('설정 이름을 가린 두 명의 평가자가 독립 코딩한다. 각 점수에 event ID·후보 hash·짧은 발췌와 근거를 붙인다. ordinal weighted kappa와 불일치율을 보고하고 합의 조정 전 원점수를 보존한다. LLM judge는 후보 구간 찾기 보조로만 쓰고 사람 판정을 대체하지 않는다.')
head('좋은 분석 예와 반례')
p('S01에서 Sam이 원래 S3 충돌만 반복하면 낮은 점수다. S3가 금요일로 옮겨진 후보의 실제 일정과 QA 예외 확인을 연결하면 높은 점수다. Zoe가 “Ben 확인 필요”를 자기 NEEDS_INPUT 근거로 재사용하면 권한 혼동으로 코딩한다.')
p('T6에서 모두 강제 ACCEPT한 기록은 이 rubric의 카드·협력 품질에서 N/A로 처리한다. 대신 시연 모드가 화면과 로그에 명시되는지, 실제 사람 승인으로 위장하지 않는지를 평가한다.',small)
finish()

begin('05 / EXECUTION PLAN','실행 순서와 결과물','이 문서는 평가 프로토콜 제안이다. 새로운 실험 결과를 만들어 넣지 않으며, 기존 데모 1회 성공을 일반 성능으로 확대하지 않는다.')
table(['단계','산출물 / 통과 조건'],[
['A. Fixture 감사','cases.yaml: 보드·카드 hash, 변경 사실, 허용 연산자, 기대 라벨, witness와 거절 근거. 날짜별 episode 및 미지원 기능 라벨 확정.'],
['B. 결정적 회귀','후보 preview/commit의 독립 제약 oracle. 분량·서명·QA→빌드·동의 revision·원자 적용·날짜 유지 테스트. 하드 제약 오류 0건이 우선 gate.'],
['C. Pilot Live','격리 DB, 고정 모델·프롬프트·후보 표시 seed. 호출/시간 예산과 중단 조건 고정. Mock·카드 토론·강제 동의를 별도 디렉토리와 mode로 저장.'],
['D. 사람 평가','고정 풀의 독립 링크, 동일 정보 조건, 무작위 표시 순서와 역매핑. 순위·동률·허용 여부 수집 후 CE/KL과 정성 코딩.'],
['E. 본 실험·공개','설정별 수치 표·95% 구간, 실패 유형, 정성 사례 대조, 전체/성공 run의 비용을 함께 공개. 원시 대화와 개인정보는 접근 분리.']],[.25,.75])
head('최소 기록 schema')
p('case_id, episode_id, turn_id, mode, feasibility_label, fixture_hash, commit, model, prompt_hash, seed, raw/retained counts, operator families, plan_hash, affected parties, consent source, PM choice, final gate, termination, token/latency/retry/translation usage, public event references.',small)
head('권장 결과 표')
p('설정별로 N / 지원·미지원 수 / 탐색 성공률 / 거짓 성공 / 거짓 포기 / 가족 커버리지 / 실제 합의율 / episode 완주 / CE 공정성·카드 / 정성 점수 / p95 지연 / 토큰을 나란히 표시한다. 강제 동의 행의 실제 합의율·카드 적합성은 N/A로 둔다.')
head('우선 결정할 사항')
p('사람 평가자와 카드 접근 권한, 최종 test 세트 크기·예산, 조건부 사례의 승인 정책, 정확한 타임슬롯 단위, 정성 rubric의 가중치. 우선은 축별 보고를 권장하며 종합 가중 점수는 이 결정 후 고정한다.')
p('기준 자료: 저장소 app/candidates, app/hive.py, app/timeline.py, prompts/, tests/ 및 제공된 M4 사례 S01-S17. 구현 상태와 평가 모드는 실행한 commit을 기준으로 추적한다.',small)
finish();c.save();print(OUT)
