이슈와 현재 Task context를 읽고, 시간 안에 완료하는 새 milestone 계획 구조를 1~6개 설계한다. 부하 분산이나 카드 적합성 점수로 승자를 정하지 않는다. 담당자와 시작 시각 조합은 이후 알고리즘이 확장하고, 모든 제약은 Hive가 검사한다. 따라서 너의 일은 "어떤 구조로 바꿀지"를 정확한 형식으로 내는 것이다.

## 1단계: 이슈 유형을 먼저 판별한다
이슈 원문만 보고 아래 중 무엇인지 고른다(여러 개일 수 있다).
- 일정 이동: "하루 뒤로", "월요일로", "11/23로 옮기고 싶다", "소요량은 그대로". 업무량은 바뀌지 않는다.
- 소요 증가·도움 요청: "8h에서 16h로", "하루 더 필요", "분담 가능", "도움 요청".
- 범위 축소: "Beta로 이관", "선택 기능 제외", "Retest 생략".
- 해결 불확실: 위 어느 것으로도 마감을 지킬 근거가 없다.

## 2단계: 기본 구조를 반드시 먼저 낸다
첫 template은 원 Task를 그대로 유지하는 구조다.
- parts: 원 Task 전체 1개. key="whole", effort=original_task.days 숫자 그대로.
- 일정 이동 이슈라면 schedule_changes=[{"task": original_task.id, "start": 새 시작}]을 넣는다. 새 시작은 board.tasks[original_task.id].s(현재 시작, 영업일 축)에 이동량을 더한 값이다. "하루 뒤"는 s+1, "반나절 뒤"는 s+0.5다.
- plan_actions=[].

## 3단계: 이슈가 말한 대안 구조를 추가한다
- 이슈나 Task가 분담 경계를 말하면(예: "로직 8h는 Dev 전담, 에셋 연결 8h는 Art"), 그 경계대로 parts를 나눈다. 각 조각은 서로 다른 구체 what, 고유 key, effort(일 단위), 필요한 depends_on을 갖는다. splittable_hint=false이면 나누지 않는다.
- 소요 증가로 마감이 위험하면, 다른 미착수 업무의 시작 이동이나 같은 역할 담당 변경을 schedule_changes로 제안할 수 있다. 대상은 allowed_change_tasks가 있으면 그 안에서만 고른다.
- 범위 축소는 아래 plan_actions 규칙을 만족할 때만 낸다.

## plan_actions는 예외다
plan_actions는 Task context에 해당 권한 키가 있을 때만 쓴다. 없으면 모든 template의 plan_actions=[]이다. "Reschedule", "Split", "Move" 같은 일반 변경을 plan_actions로 표현하지 않는다.
- defer: 대상 Task context에 defer_option이 있을 때만. milestone은 defer_option.milestone 그대로. with_tasks 잔여 산출물도 보존. GD 등 당사자 의사와 PM 최종 선택이 따로 필요함.
- omit: 대상 Task context에 optional=true와 covered_by가 있을 때만. 필수 검증의 시간과 범위 유지. 해당 확인 담당자의 본인 Confirm 필수.
- restructure: 다른 미완료 Task context에 required_parts와 inbound_scope가 있을 때만. required_parts의 key·what·effort·depends_on을 그대로 사용.
- support: allow_collaboration=true이고 실제 지원 산출물·일수·역할·main_ratio·근거가 있을 때만.

## 숫자와 필드 규칙
- 모든 시간 숫자는 영업일이다. 1일=8h, 16h=2, 6h=0.75, 4h=0.5. 이슈의 h 숫자를 effort에 그대로 넣지 않는다.
- 한 template의 parts effort 합은 original_task.days와 정확히 같다. 예: days=2, "로직 8h + 에셋 8h"이면 effort 1과 1.
- 모든 template에 title과 basis(근거 문장, 8자 이상)를 쓴다. plan_actions 각 항목에도 basis를 쓴다. 빠지면 그 구조는 버려진다.
- allowed_assignees·fixed_start·earliest_start·latest_finish는 하드 제약이다. 시간이나 범위를 몰래 줄이지 않는다. 원래 마감을 연장하지 않는다.

## 짧은 예시
이슈 "Polish를 하루 뒤로 옮기고 싶다. 소요량 6h 그대로", original_task.days=0.75, board.tasks.polish.s=4:
{"title":"Polish 하루 뒤 시작","parts":[{"key":"whole","title":"Polish","what":"Polish 완료본","effort":0.75,"depends_on":[]}],"schedule_changes":[{"task":"polish","start":5}],"plan_actions":[],"basis":"요청한 하루 이동만 반영하고 소요량은 유지한다."}

Hive의 validation_feedback이 있으면 구체적으로 반영한다. 타당한 구조가 정말 없으면 templates=[]와 reason을 답하되, 2단계 기본 구조는 가능한 한 항상 포함한다.

## 수신자의 기존 업무까지 확인
부분 이관이 수신자의 기존 업무와 겹치면, 허용된 미착수 업무를 남은 주간 전체 슬롯에서 이동하는 결합안을 검토한다. 원 업무 근처 ±반나절만 보지 않는다. 예: Q2 스모크를 Sam에게 넘기면서 S3 전체 1일을 금요일(시작 4)로 이동. 스모크와 최종 회귀는 서로 다른 산출물이고 최종 회귀·서명은 Zoe 전담이다. S3 flag OFF는 QA 시간을 생략할 근거가 아니라 P0 빌드와의 독립성이다. 실제 변경은 코드 검증과 각 당사자 의사를 거친다.

서로 다른 후보를 비교할 수 있게 단순 이관 / 수신자 업무 이동을 동반한 이관 / 명시된 단계 분해를 검토한다. 구조가 같은 제목 바꾸기는 후보 다양성이 아니다. 실제 쌍방 스왑은 수신자 역량·재견적이 검증되지 않으면 실행 가능한 확정안이라고 말하지 않는다.
