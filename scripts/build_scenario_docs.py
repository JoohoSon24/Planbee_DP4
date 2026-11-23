"""Generate initial boards, complete cards and task descriptions from the actual seeds.
Run with: PLANBEE_LLM=mock .venv/bin/python scripts/build_scenario_docs.py
"""
from pathlib import Path
import sys
import re
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import store, hive

MARKER='<!-- GENERATED_INITIAL_BOARD -->'
INTRO={
 'demo5_release':'''# 데모 5 · 8인 릴리스와 반복 분담 협상

## 시나리오 유형과 관찰 목표

계약 동결, 보안 승인, QA, 릴리스가 연결된 8인 팀의 20개 작업입니다.
첫 요청의 보라가 위임 설정 때문에 거절하고, 보라가 찬을 초대하는 분담안을 냅니다.
찬도 자신의 설정에 맞춰 거절·재제안하며, 새 버전에서 모두 다시 동의합니다.
기본 Mock에서는 5라운드에 두 수신자의 분담이 합의됩니다. 공정성 지표는 요청의
참고 자료이며 최솟값을 고르는 자동 선발로 협상을 대신하지 않습니다.

## 브라우저 실행과 기대 흐름

1. `demo5_release`를 고르고 ‘1/3 · 계약 검증 분담 5라운드’를 실행합니다.
   보라의 거절 → 보라의 분담 재제안 → 찬의 거절 → 찬의 수정안 → v3 전체 동의를 확인합니다.
2. ‘2/3 · QA 지연과 의존 일정 복구’를 실행합니다. 은의 회귀 작업이 반일 늘어납니다.
   페이가 독립 실패 경로를 맡고, 코드가 후속 배포 기한을 다시 검증합니다.
3. 마지막 릴리스 재검사로 종료합니다. Handoff 위험·용량 위반 없이 종료해야 합니다.

‘직접 누르기’로 바꾸면 카드 한도 밖의 요청에 사람 확인이 표시됩니다.
`runs/`에는 실제 대화 순서, Hive의 작업과 초기/턴별/최종 milestone이 남습니다.

''',
 'demo6_cross_region':'''# 데모 6 · 10인 교차 리전과 미합의·원자적 복구

## 시나리오 유형과 관찰 목표

10명이 24개 작업과 4개 milestone을 다룹니다. 백엔드·QA·운영의 서로 다른
업무 줄과 원장→QA→릴리스의 의존관계, 두 리전의 배포·롤백 준비가 연결됩니다.
첫 협상은 기한을 넘는 대안을 차단하고 최대 라운드에서 멈추는 실패 경로입니다.
이후 원장 2조각 분할과 운영 작업 맞교환을 하나의 묶음으로 재배치합니다.

## 브라우저 실행과 기대 흐름

1. `demo6_cross_region`을 고르고 첫 단계를 실행합니다. 준의 거절 후 카이에게
   6일짜리 검증을 요청하는 대안은 Hive가 데드라인 위반으로 차단합니다.
   안전한 수정안을 냈더라도 최대 3라운드 안에 전원 동의를 받지 못하면
   `max_rounds`로 끝나며 원래 작업 배정을 유지합니다.
2. 두 번째 단계는 원장 1일씩을 준·카이에게 분리하고 노엘·올린의 운영 작업을
   맞교환하는 **4건의 원자적 묶음**입니다. 전원 동의 전에는 어느 작업도 적용하지 않습니다.
   ‘직접 누르기’ 상태에서 한 명을 거절시키면 전체 취소도 확인할 수 있습니다.
3. 마지막 정합성 검사 입력 기록을 처리하고 금요일까지의 전체 기한을 재검증합니다.

묶음은 LLM이 자동 생성하는 협상안이 아니라, 데모에서 명시한 대안에 당사자 동의를
받는 기존 묶음 API입니다. 첫 단계의 다자간 협상과 구분해서 관찰하세요.

'''}


PRESERVED_INTROS = {'demo1': '# 데모 1 · 게임 개발팀\n'
          '\n'
          '## 질문과 설정\n'
          '\n'
          '게임 프로토타입을 금요일에 제출하는 6인 팀입니다. 먼저 캐릭터 그림이 늦고, 다른 날에는 캐릭터 코드를 구현하는 일이 늦습니다. 두 경우 모두 독립 조각을 '
          '나눌 수 있는지 확인합니다. 그림→코드→테스트 Handoff가 있어 앞 작업의 지연은 뒤 일정에 전파됩니다.\n'
          '\n'
          '모든 인물·작업량·경력·메신저 기록은 시연용 합성 자료입니다. 사람 확인은 시뮬레이터에서 자동 승인됩니다.\n'
          '\n'
          '## 팀과 위임카드\n'
          '\n'
          '| 사람 | 역할 | 카드 권한/메모 | 시나리오상 특징 |\n'
          '|---|---|---|---|\n'
          '| Mia | 그림 | 1일까지 자동 수락 | 원 담당자. 그림 경험 6건 |\n'
          '| Ivy | 그림 | 0.5일까지 자동 수락 | 배경 경험은 많지만 캐릭터 그림 경험은 1건 |\n'
          '| Leo | 개발 | 1일까지 자동 수락 | 캐릭터 코드 경험 4건 |\n'
          '| Sam | 개발 | 1일까지 자동 수락 · “오전엔 리뷰 안 받음” | 버그 경험 9건, 이번 주 일정이 꽉 참 |\n'
          '| Ben | 개발 | 1일까지 자동 수락 | 요청 코드 경험은 없고, Sam의 도움을 조건으로 제안 |\n'
          '| Zoe | 테스트 | 0.5일까지 자동 수락 | 테스트 경험 12건, 후속 테스트 담당 |\n'
          '\n'
          '카드 한도를 넘는 수락은 프록시가 확정하지 않고 당사자 확인으로 보냅니다. PM만 업무를 다음 주로 미루거나 제출 범위를 줄일 수 있습니다.\n'
          '\n'
          '## 사건과 Mock 제안\n'
          '\n'
          '1. 수요일 기록: Mia가 `무기_v3.psd`를 세 번째 다시 올리고 그림이 3일째 진행 중입니다. Mock은 캐릭터 그림 견적을 3일에서 4일로 '
          '올립니다. 담당 Proxy는 무기 그림 1일을 독립 조각으로 제안합니다. Ivy의 자동 한도(0.5일)를 넘으므로 Ivy와 Mia가 각각 확인합니다.\n'
          '2. 목요일 기록: Leo가 상태 머신을 새로 만드는 커밋을 올렸습니다. 캐릭터 코드 견적을 1.5일에서 2.5일로 조정합니다. 움직임 코드 1일을 분리해 '
          'Sam·Ben에게 묻습니다. Sam은 버그 작업을 2주차로 미루면 가능, Ben은 Sam이 30분 도와주면 가능하다고 답합니다. 이 조건은 PM 권한이므로 '
          'PM 검토가 필요합니다.\n'
          '\n'
          '최신 실행은 README의 Mock 시작 명령과 아래 초기 보드를 기준으로 재현합니다.\n'
          '\n',
 'demo2': '# 데모 2 · Plan Bee M4 주간\n'
          '\n'
          '## 질문과 설정\n'
          '\n'
          '2026-11-16~20 통합 리허설 주간입니다. 에이전트 쪽은 협상 엔진과 단일 에이전트 베이스라인을, 화면 쪽은 API와 UI·사용자 조사를 만듭니다. '
          '역할이 다른 사람에게도 산출물이 독립적이면 넘길 수 있는지, 연쇄 지연에 PM만 할 수 있는 일정 이동·범위 축소가 어떤 역할을 하는지 살핍니다.\n'
          '\n'
          '사람·작업량·기록은 데모용 합성 값입니다. 사람 확인은 자동 승인됩니다.\n'
          '\n'
          '## 팀과 위임카드\n'
          '\n'
          '| 사람 | 역할 | 카드 권한/메모 | 관련 역량·업무 |\n'
          '|---|---|---|---|\n'
          '| 여경 (yk) | 에이전트 | 1일까지 자동 수락 | 협상 엔진 경험 6, 프롬프트 4, 베이스라인 2 |\n'
          '| 정민 (jm) | 에이전트 | 1일까지 자동 수락 · “저녁에만 리뷰 가능” | 베이스라인 경험 3, 협상 엔진 2, 평가 2 |\n'
          '| 주호 (jh) | 화면 | 1일까지 자동 수락 | API 5, 화면 4, 배포 1 |\n'
          '| 나정 (nj) | 화면 | 0.5일까지 자동 수락 | 화면 6, 사용자 조사 5, API 1 |\n'
          '\n'
          '## 사건과 Mock 제안\n'
          '\n'
          '- 화요일: 재개 커밋을 세 번째 되돌린 기록과 체크포인트 재개 실패를 받아 협상 엔진을 2.5일에서 3.5일로 올립니다. `재개 로직 (DB 저장)` '
          '1일을 화면 역할의 주호에게 제안합니다. 독립적인 산출물은 run 표에 재개 상태를 저장하는 코드입니다.\n'
          '- 목요일: 베이스라인이 엔진 시드를 읽지 못하는 문제가 있습니다. 싱글 에이전트 베이스라인을 2일에서 3일로 올리고 `시드 어댑터` 1일을 분리합니다. '
          '정민이 엣지 케이스·교착 처리를 다음 주로 미루는 조건을 내므로 PM 검토를 거칩니다.\n'
          '\n'
          '최신 실행은 README의 Mock 시작 명령과 아래 초기 보드를 기준으로 재현합니다.\n'
          '\n',
 'demo3_cards': '# 데모 3 · 위임카드 네 조건\n'
                '\n'
                '## 고정 시나리오\n'
                '\n'
                '개발자 Mia의 기능 구현이 3일에서 4일로 늘었습니다. 테스트를 맡은 Ara가 금요일 전에 기능 코드를 받아야 하므로, `독립 기능 코드` '
                '1일을 같은 역할의 Jun 또는 Sol에게 요청합니다. Jun은 이미 4.5일, Sol은 2일의 개발 작업이 있어 Jun은 추가 수락이 불가능하고 '
                'Sol은 가능합니다. 원 요청자인 Mia도 넘기는 조각을 확인합니다.\n'
                '\n'
                '모든 조건에서 팀, 작업, 사건, 역할, 시드, 사람 확인 자동 승인, 실제 Hive 일정 검사는 동일합니다. 실험에서만 후보 Proxy에게 주는 '
                '정보와 자동 수락 권한을 바꿉니다.\n'
                '\n'
                '## 2×2 조건\n'
                '\n'
                '| 조건 | 개인 여건 정보 | 자동 수락 권한 | 카드 설정 의미 |\n'
                '|---|---|---|---|\n'
                '| 1 · 카드 없음 | 없음 | 0일 | 제안은 공통 기준값, 실제 일정은 Hive가 걸러냄 |\n'
                '| 2 · 여건만 | 있음 | 0일 | 자기 작업량·경험·미룰 업무를 보지만 사람 확인 필요 |\n'
                '| 3 · 권한만 | 없음 | 1일 | 일정 정보가 제한된 상태에서 1일까지 제안 가능 |\n'
                '| 4 · 둘 다 | 있음 | 1일 | 개인 여건을 보고 한도 안에서 자동 수락 가능 |\n'
                '\n'
                '“객관적 여건 정보”는 Proxy가 자기 작업량·역량·미룰 수 있는 업무를 아는 것을 뜻합니다. “권한”은 자동으로 맡겠다고 확정할 수 있는 최대 '
                '일수입니다. 타인의 카드 원문은 각 Proxy에게 공개되지 않습니다.\n'
                '\n'
                '## 실행 결과\n'
                '\n'
                '| 조건 | 배정된 사람 | 확인 | Hive 반려 | PM 결정 | 제출일 초과 |\n'
                '|---|---|---:|---:|---:|---:|\n'
                '| 카드 없음 | Sol | 2 | 1 | 0 | 0 |\n'
                '| 여건만 | Sol | 2 | 0 | 0 | 0 |\n'
                '| 권한만 | Sol | 1 | 1 | 0 | 0 |\n'
                '| 둘 다 | Sol | 1 | 0 | 0 | 0 |\n'
                '\n'
                '이 작은 사례에서는 정보가 실제 일정에 맞는 후보 답을 만들어 엔진 반려가 줄었고, 자동 권한은 사람 확인을 한 번 줄였습니다. 네 조건 모두 '
                '같은 1일 요청을 Sol이 맡았으므로, 이 결과만으로 장기 성능이나 공정성 향상을 주장하지 않습니다.\n'
                '\n'
                '원자료: `eval/cards_four_conditions/RESULTS.md` 및 각 조건별 JSON/대화 Markdown.\n'
                '\n',
 'demo4_bundles': '# 데모 4 추가 기능 · 원자적 묶음 이동\n'
                  '\n'
                  '## 목적\n'
                  '\n'
                  '서로 연결된 여러 작업의 교환·재배치를 한꺼번에 검증하고 확정하는 API 예제입니다. 일반 협상 LangGraph 흐름에 포함된 LLM 데모는 '
                  '아닙니다. `app/bundles.py`가 작업 목록을 받아 전체 일정·선후 관계·용량을 미리 계산하고, 관련 당사자 전원의 확인 후 한 번에 '
                  '반영합니다. 한 사람이 거절하면 부분 적용을 남기지 않고 전체를 취소합니다.\n'
                  '\n'
                  '## 시나리오 공통 설정\n'
                  '\n'
                  'Mia와 Jun은 개발 역할, Sol도 개발 역할이며 Ara는 테스트입니다. 세 개발자는 개발 경험 3으로 설정되고, 묶음 예제의 카드 자동 '
                  '한도는 각 2일입니다. 모든 작업·사람·일정은 메모리 DB에서 만든 합성 자료입니다.\n'
                  '\n'
                  '## 네 실행 사례\n'
                  '\n'
                  '| 사례 | 제안 | 예상 확인자 | 결과 |\n'
                  '|---|---|---:|---|\n'
                  '| swap | Mia의 `x`와 Jun의 `y`를 서로 교환 | 2 | committed |\n'
                  '| split | Mia의 `x`를 Jun·Sol에게 각 0.5일 분배 | 1 | committed |\n'
                  '| chain | `x`, `y`, `z`를 Mia→Jun→Sol→Mia로 순환 이동 | 3 | committed |\n'
                  '| reject | 맞교환 중 둘째 당사자가 거절 | 2 | cancelled; 일부 이동 없음 |\n'
                  '\n'
                  '네 사례 모두 이후 실제 일정·규칙 검사가 통과했습니다. `reject`는 실패한 제안이 규칙에 맞게 취소된 경우라 실행 자체의 실패가 '
                  '아닙니다.\n'
                  '\n'
                  '## 재현과 결과 파일\n'
                  '\n'
                  '```bash\n'
                  'PLANBEE_LLM=mock .venv/bin/python run_bundle_demo.py --case all\n'
                  '```\n'
                  '\n'
                  '각 실행 전후 상태는 `eval/bundles/{swap,split,chain,reject}.json`, 요약은 '
                  '`eval/bundles/RESULTS.md`에 저장됩니다.\n'
                  '\n',
 'demo4_planbee': '# 데모 4 · 업무 맥락, 모호한 위임카드, 부하 균형\n'
                  '\n'
                  '## 업무 맥락\n'
                  '\n'
                  'Plan Bee 프로젝트의 재개 로직이 지연되어, 담당 Proxy가 전체 일을 무작정 쪼개는 대신 목적·파일·산출물·분리 경계·완료 조건을 '
                  '보고 판단합니다.\n'
                  '\n'
                  '| Task | 목적/산출물 | 분리 경계 | 제안/기대 처리 |\n'
                  '|---|---|---|---|\n'
                  '| 협상 재개와 증거 로그 | 재개 코어와 읽기 전용 증거 조회 | 읽기 전용 조회는 독립 가능. 상태 전이·동의 트랜잭션은 나누지 않음 | '
                  '`읽기 전용 증거 로그 API` 1일 분리 |\n'
                  '| 일회성 승인과 서명 키 교체 | 키 교체와 이중 확정 방지 | 공유 키·감사 기록이 한 트랜잭션에 있어야 함 | 분리 불가로 표시 |\n'
                  '| 사용자 인터뷰 동의서 | 확인된 동의서 | 개인정보 원문은 나누지 않음 | 분리 불가 |\n'
                  '| 리허설 배포 점검 | 정상 URL | 체크리스트 기반 검사는 독립 가능 | 후보 작업으로는 가능하나 현재 이슈 조각은 아님 |\n'
                  '\n'
                  '## 위임카드와 개인 누적 부담\n'
                  '\n'
                  '| 사람 | 과거 작업량(시드값) | 카드 원문 | 구조화된 해석/권한 |\n'
                  '|---|---:|---|---|\n'
                  '| 여경 (담당) | 3 | “재개 로직은 내가 마무리할게요. 읽기 전용 조회처럼 독립된 부분만 다른 사람에게 맡겨주세요.” | auto '
                  '1일, 승인됨; 재개 코어 유지와 조회 분리 허용 |\n'
                  '| 정민 | 1 | “11월 19일부터 20일까지 휴가라 그때는 일을 못 해요. 그 전의 독립 API는 1.5일까지 맡겨도 괜찮아요.” | '
                  'auto 1.5일; 수~금 휴가 구간(끝 시각 미포함) |\n'
                  '| 주호 | 8 | “최근 배포와 긴급 수정이 계속돼서 나 너무 바쁨. 작은 API라도 새로 맡기기 전에 나에게 확인해 주세요.” | '
                  'busy=true, auto 1일; 바쁨을 임의의 숫자 한도로 바꾸지 않고 본인 확인 |\n'
                  '| 나정 | 3 | “테스트와 문서에서 모호한 요구사항은 먼저 물어봐 주세요. 실제 사용자의 동의서는 함부로 쪼개지 말아주세요.” | auto '
                  '1일; 불명확 요구는 확인, 동의서 분리 금지 |\n'
                  '\n'
                  '## 결과: 후보 선택 기준만 변경\n'
                  '\n'
                  '사건·카드·역량·업무량은 고정하고 선택 기준만 `fast`와 `fair`로 바꿨습니다.\n'
                  '\n'
                  '| 기준 | 최종 후보 | 본인 확인 | 과거+현재 업무량 분산(분산값) | 범위 | 기한 초과 |\n'
                  '|---|---|---:|---:|---:|---:|\n'
                  '| 빠른 종료 (fast) | 주호 | 2 | 10.796875 | 9.0 | 0 |\n'
                  '| 누적 부담 균형 (fair) | 정민 | 1 | 6.125 | 6.5 | 0 |\n'
                  '\n'
                  '정민은 휴가 시작 전 독립 API를 맡을 수 있으므로 두 후보 모두 마감은 지켰습니다. 공정성 휴리스틱이 이 시나리오에서 더 낮은 분산 후보를 '
                  '골랐다는 관찰이며, 전역 최적성이나 실제 팀 효과를 뜻하지 않습니다.\n'
                  '\n'
                  '## 마감 위험이 없을 때의 공정성 경로\n'
                  '\n'
                  '별도 실행에서는 같은 issue를 유지하고 증거 API Handoff의 약속만 금요일 저녁(4.5일)으로 늦춰, 견적 수정 뒤에도 전달 일정이 '
                  '위험하지 않게 했습니다. 과거 부담+현재 작업량의 범위는 기본 기준(3일)을 넘고, 부담이 큰 담당자와 같은 역할의 낮은 부담 후보 사이도 '
                  '2일 이상이어서 `fairness_gate`가 분담 검토를 시작합니다. LLM은 `읽기 전용 증거 로그 API` 1일을 분리하고, 후보 '
                  'Proxy가 답한 뒤 Hive는 마감 위험을 만들지 않는 안 가운데 부담 분산을 가장 낮추는 수락안을 고릅니다.\n'
                  '\n'
                  '이 실행에서는 정민이 1.5일을 맡았고, 업무 소유자 여경이 확인했습니다. 마감 위험은 0건이며, 분산은 8.80에서 6.12로 낮아졌습니다. '
                  '**기한이 지켜진다고 바로 종료하지 않고, 불균형이 기준을 넘으면 위임·카드·동의 단계를 거치는 경로**를 확인한 Mock 결과입니다.\n'
                  '\n'
                  '## 별도 Live 확인\n'
                  '\n'
                  '`run_demo4.py --live-check`는 실제 LLM으로 분리 판단·카드 해석을 질의하지만, 이 API는 변경안을 적용하지 않는 '
                  '검사 전용입니다. 기록된 Live 응답은 `eval/demo4_planbee/live_checks.json`; Mock fast/fair '
                  '비교는 `comparison.json`에 분리해 저장했습니다.\n'
                  '\n'}


def cell(value):
    if isinstance(value,(dict,list)):
        value=yaml.safe_dump(value,allow_unicode=True,default_flow_style=True).strip()
    return str(value).replace('|','\\|').replace('\n','<br>')


def table(headers,rows):
    return ['|'+'|'.join(headers)+'|','|'+'|'.join('---' for _ in headers)+'|']+['|'+'|'.join(cell(v) for v in row)+'|' for row in rows]+['']


def build():
    target=ROOT/'docs/DEMOS.md'
    manual_marker='<!-- MANUAL_APPENDIX -->'
    appendix=target.read_text().split(manual_marker,1)[1].strip() if target.exists() and manual_marker in target.read_text() else ''
    catalog=store.demo_catalog(include_archived=True)
    documents=['# 데모 시나리오와 실행 안내', '',
        '모든 인물·업무량·위임 설정은 합성 시연 데이터입니다. 초기 보드·카드·Task 상세는 현재 시드에서 계산합니다.', '',
        '## 시작과 브라우저 사용', '',
        '```bash\n.venv/bin/python start.py --llm live\n# 재현 가능한 Mock 실행\n.venv/bin/python start.py --llm mock\n```', '',
        'Live 실행은 `.env`에 `OPENROUTER_API_KEY`가 필요합니다. 브라우저 상단에서 데모를 고르고 시연 버튼을 순서대로 누릅니다. 데모 전환 시 초기 상태로 시작합니다. 실행 세부 설정은 [README](../README.md), 협상·제약 검증은 [에이전트 호출 흐름](AGENT_CALL_FLOW.md)을 참고하세요.', '',
        '화면 상단의 01 입력·재견적 / 02 기한 회복 / 03 공정성 협상은 처리 단계입니다. 협상 라운드 수와 데모 시연 순서는 별도로 표시합니다. Run 파일도 처리 단계별 섹션으로 대화·Hive 검증·마일스톤을 기록합니다.', '',
        '## 데모 목록', '']
    documents+=table(['데모 ID','시나리오'],[[e['id'],f"[{e['title']}](#{e['id']})"] for e in catalog])
    old=store.DEMO
    try:
        for entry in store.demo_catalog(include_archived=True):
            demo=entry['id'];store.use_demo(demo)
            raw=store.load_yaml('team.yaml');feed=store.load_yaml('feed.yaml')
            eng=store.make_engine('sqlite://')
            with store.make_session_factory(eng)() as db:
                store.reset(db);b=store.board(db);hive.schedule(b)
                names={p.id:p.name for p in b.people.values()}
                source=store.SEED/demo/'source.md'
                prefix=(source.read_text(encoding='utf-8') if source.exists() else None) or INTRO.get(demo) or PRESERVED_INTROS.get(demo) or '# '+entry['title']+'\n\n'
                if source.exists():
                    prefix=re.sub(r'!\[[^\]]*\]\([^\n]+\)',f'[원본 일정 보드](/demos/{demo}/board)',prefix)
                    prefix+='\n\n### 실행 엔진 지원 범위\n\n'+raw['meta']['engine_support']+'\n\n'+raw['meta']['normalization_note']+'\n\n'
                cases=store.SEED/demo/'cases.md'
                if cases.exists():prefix+='\n\n## 추가 시연 사례 원문 및 기대 판정\n\n'+cases.read_text(encoding='utf-8')+'\n\n위 표는 원문의 기대 동작입니다. 현재 구현은 실행 엔진 지원 범위를 따르며, 표의 모든 자연어 변경을 자동 반영한다는 뜻은 아닙니다.\n'
                # Historic receipt counts are stale once the negotiation protocol changes.
                if '## 기본 실행 결과' in prefix:
                    prefix=prefix.split('## 기본 실행 결과')[0]+'최신 실행은 README의 Mock 시작 명령과 아래 초기 보드를 기준으로 재현합니다.\n\n'
                lines=prefix.rstrip().splitlines()+['',MARKER,'','## 초기 milestone 보드','',
                    f"시드: `seed/{demo}/` · {len(b.people)}명 · {len(b.tasks)}개 Task · {len(b.hands)}개 Handoff.",
                    '시간 단위는 월요일 오전=0, 금요일 저녁=5입니다. 시작·완료 시각은 실제 일정 계산 결과이며 아래 날짜 표현도 같은 주간을 뜻합니다.', '']
                checkpoints=[]
                for t in b.tasks.values():
                    if t.kind=='milestone':checkpoints.append([t.id,t.title,names[t.who],hive.num(t.s+t.d),hive.when(t.s+t.d),'milestone'])
                for h in b.hands.values():
                    checkpoints.append([h.id,h.title,names[b.tasks[h.from_task].who]+' → '+names[b.tasks[h.to_task].who],hive.num(hive.pred(b,h)),hive.when(h.t),hive.STATE_NAME[hive.h_state(b,h)]])
                lines+=table(['ID','milestone / 전달 약속','담당 / 전달 방향','예상 완료(일)','약속 시각 / checkpoint','초기 상태'],checkpoints)
                lines+=['### 초기 전체 Task 보드','']+table(['Task','담당','업무','시작(일)','완료(일)','소요(일)','상태'],
                    [[t.id,names[t.who],t.title,hive.num(t.s),hive.num(t.s+t.d),hive.num(t.d),t.kind or '예정'] for t in b.tasks.values()])
                lines+=['## 각자의 위임카드','', '이 표는 사람이 검토하는 시나리오 설명입니다. 실행 중 각 LLM에는 자기 카드만 전달됩니다.','']
                for p in b.people.values():
                    c=store.card(db,p.id)
                    lines += [f'### {p.name} (`{p.id}`) · {p.role}','',
                        f'- 자동 수락 한도: {c.auto_days:g}일 / 늦춰 받기 한도: {c.wait_days:g}일',
                        '- 받지 않는 태그: '+(', '.join(c.refuse_tags or []) or '없음'),
                        '- 도움 요청 수락: '+('허용' if c.gives_help else '거절'),
                        '- 메모: '+(c.note or '추가 메모 없음'),
                        '- 승인된 일정 조건: '+cell(c.policy or {}),
                        '- 태그별 경험: '+cell(p.rec or {}),
                        '- 희망 업무: '+(', '.join(p.wants or []) or '별도 지정 없음'),
                        '- 최근 누적 부담: '+str((p.notes or {}).get('past_effort',0))+'일','']
                lines+=['## 각 Task 세부 description','']
                for t in b.tasks.values():
                    ctx=t.context or {};incoming=[h for h in b.hands.values() if h.to_task==t.id];outgoing=[h for h in b.hands.values() if h.from_task==t.id]
                    deliverable=ctx.get('deliverable') or ', '.join(h.what for h in outgoing) or t.title+' 완료본과 검증 기록'
                    description=ctx.get('description') or ctx.get('purpose') or f'{t.title} 작업을 수행하고 {deliverable}을 준비합니다.'
                    lines += [f'### `{t.id}` · {t.title}','',f'- 담당: {names[t.who]} / 태그: {t.tag}',
                        f'- 초기 일정: {t.s:g}~{t.s+t.d:g}일, 소요 {t.d:g}일',
                        '- Description: '+description,'- 산출물: '+cell(deliverable),
                        '- 입력 의존성: '+(', '.join(f'{h.from_task} → {t.id}: {h.what}' for h in incoming) or '별도 선행 Handoff 없음'),
                        '- 후속 전달: '+(', '.join(f'{t.id} → {h.to_task}: {h.what}, {hive.when(h.t)}까지' for h in outgoing) or '별도 후속 Handoff 없음'),
                        '- 분리 경계: '+str(ctx.get('split_boundary','Mock 분리안과 후속 의존 일정 검사로 독립성을 판단합니다.')),
                        '- 완료 기준: '+cell(ctx.get('acceptance') or ['산출물 전달','후속 담당자가 검증 가능','약속 시각과 역할 유지']),'']
                lines+=['## 브라우저 시연 단계 목록','']+table(['순서','단계 키','버튼','행동','다음 단계'],
                    [[i,key,f.get('label','시연 · 다음 단계'),f.get('action','records'),f['next_phase']] for i,(key,f) in enumerate(feed.items(),1)])
                lines+=['## 실행','',f'```bash\n.venv/bin/python start.py --demo {demo} --llm mock\n```','',
                        '브라우저 상단에서 다른 데모로 전환하면 초기 상태로 시작합니다. 시연 버튼을 순서대로 누르고, 사람 확인은 ‘기록과 규칙’에서 처리합니다. PM 대기라면 ‘PM 확인 보기’에서 제시된 규칙 허락 또는 약속 변경을 선택합니다.','']
                # Stable boundaries let the API return only the selected demo.
                documents += [f'<!-- DEMO_START:{demo} -->',f'<a id="{demo}"></a>','']
                documents += [('#'+line if line.startswith('#') else line) for line in lines]
                documents += [f'<!-- DEMO_END:{demo} -->','']
            eng.dispose()
    finally:store.use_demo(old)
    documents += [manual_marker,appendix]
    target.write_text('\n'.join(line.rstrip() for line in documents),encoding='utf-8')


if __name__=='__main__':build()
