Hive가 반려한 원인(validation_feedback.reasons)과 원 Task의 범위를 읽고 실제로 다른 구조로 복구하라. 같은 오류·같은 구조를 반복하지 않는다. 마감 연장이나 완료 기준 축소로 통과시키지 않는다.

반려 원인별로 다음을 시도한다.
- 데드라인 위반·기한 초과: 한 사람이 전부 맡아 늦어지면, 이슈나 Task가 말한 경계로 parts를 나눠 병렬로 진행하는 구조를 낸다. 또는 allowed_change_tasks 안의 다른 미착수 업무를 schedule_changes로 옮겨 시간을 확보한다.
- 범위 이관·재구조화 금지, 권한 미명시: plan_actions를 모두 비우고([]), parts 분해나 schedule_changes로 다시 설계한다.
- 분량 보존 위반: parts effort 합을 original_task.days와 정확히 맞춘다(일 단위, 1일=8h).
- 요청한 일정 이동 미반영: schedule_changes에 original_task.id와 board의 현재 시작(s)에 이동량을 더한 start를 넣는다.

모든 template과 plan_actions 항목에 basis(8자 이상)를 쓴다. 복구가 정말 불가능하면 빈 templates와 구체 이유를 답한다.

수신자의 슬롯 충돌이면 해당 수신자의 허용된 미착수 업무를 다른 날로 이동하는 결합안을 먼저 확인한다. QA 서명 담당 부재나 필수 QA 뒤 빌드 시간이 없는 경우에는 서명 대행·QA 생략·겹쳐 실행을 만들어내지 않는다. 지금 탐색에서 못 찾은 것과 하드 제약으로 차단된 것을 명확히 구분한다.
