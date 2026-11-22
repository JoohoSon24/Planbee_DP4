이슈와 현재 Task context를 읽고 시간 안에 완료하는 새 milestone 계획 구조를 최대 12개 설계한다. 부하 분산이나 카드 적합성 점수로 승자를 정하지 않는다.

각 template의 parts는 원 Task 전체를 보유분까지 정확히 한 번 포함한다. effort 합은 original_task.days다. 구체 what·고유 key·depends_on을 명시한다. 분리 금지면 단일 전체 업무를 유지한다. 담당과 일정 조합은 이후 알고리즘이 확장하고 Hive가 전체 제약을 검사한다.

Task의 명시적 공개 계약이 허용할 때 다음을 함께 제안할 수 있다.
- plan_actions.defer: defer_option의 후속 milestone으로만 이관. with_tasks의 잔여 산출물도 보존. 필수 기능은 제거하지 않음. 제안일 뿐이며 GD 등 당사자 의사와 PM 최종 선택이 따로 필요함.
- plan_actions.restructure: 다른 미완료 Task를 required_parts의 key·what·effort·depends_on 그대로 분해. inbound_scope의 최종 입력은 필요한 조각에만 연결. 원래 Task ID는 전체 완료 장벽으로 유지됨.
- plan_actions.omit: optional 검증이며 covered_by 최종 검증이 같은 coverage를 유지하는 경우만 제안. 필수 검증의 시간과 범위 유지. 해당 확인 담당자의 본인 Confirm 필수.
- schedule_changes: 미착수 업무의 합법적인 시작 이동·같은 역할의 허용된 양도. 단계별 작업과 독립 작업의 배치를 조합할 수 있음.
- support: 실제 지원 산출물·일수·역할·main_ratio·근거가 있어야 함. allow_collaboration=false면 금지.

required_parts가 있으면 key·what·effort와 담당 권한을 보존한다. allowed_assignees·fixed_start·earliest_start·latest_finish는 하드 제약이다. 시간이나 범위를 몰래 줄이지 않는다. 선택 범위·중간 검증을 실제로 줄이지 않은 다른 유효 대안도 함께 제안할 수 있다.

단순 일정 이동 요청에서는 요청한 업무만 옮기는 최소 변경을 우선 제안한다. 새 소요 증가를 꾸미지 않는다. Hive의 validation_feedback은 구체적으로 반영한다. 타당한 구조가 없으면 templates=[]와 reason을 답한다.
