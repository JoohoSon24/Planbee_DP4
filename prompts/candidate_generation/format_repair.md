직전 생성 응답은 answer schema에 맞지 않았다. format_errors의 실제 필드 오류를 고쳐 한 번만 새 구조를 제출한다. JSON 문자열이 아니라 answer 도구로 답한다. 개인 카드나 정답은 제공되지 않는다.

- 1일=8h. effort는 시간(h)이 아닌 일(day). 32h는 4, 6h는 0.75다. original_task.days 숫자와 parts effort 합을 맞춘다.
- plan_actions.kind는 defer / omit / restructure만. 일정 이동은 schedule_changes=[{task:실제TaskID,start:영업일시각}], 단순 이동의 plan_actions는 빈 배열이다.
- 원 Task 전체 유지·양도는 parts 하나, 분해는 parts 여러 개. 각 parts 항목의 key,title,what,effort,depends_on 필드를 채운다. effort는 반드시 양수다.
- 이관/생략은 plan_actions의 defer/omit이고 그 plan_actions[].parts=[]다. template 최상위 parts는 비우지 않고 대상 Task 전체를 최소 1개 담는다. 역할이나 새 범위를 멋대로 만들지 말고 Task의 공개 계약을 지킨다.
- 첫 응답의 많은 구조를 모두 복제하지 않는다. 가장 명확한 구조 1~3개만 정확하게 반환한다. 허용되는 의미 설계가 없으면 templates=[]와 이유를 반환한다.

원 이슈와 Task, 공개 보드, validation_feedback이 있으면 함께 적용한다. 형식만 고치면서 Task의 내용·권한·마감을 바꾸지 않는다.
