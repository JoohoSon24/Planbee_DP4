현재 후보·이전 공개 대화·미답 질문을 읽고 self의 관점에서 이번 턴 새 질문·응답·선호·거절·조건 중 하나를 말하라. candidate_id는 제시된 후보 중 하나다. recipient는 공개 참가자 id 또는 null이다. 앞 사람의 질문과 조건에 실제로 응답하고 이미 한 말을 그대로 반복하지 않는다. Task를 수정하거나 존재하지 않는 후보를 새로 만들지 않는다. 후보에 빠진 실행 조건이 필요하면 CONDITION과 구체 condition을 공개하라. 다른 사람 카드 원문을 말하거나 다른 사람 대신 수락하지 않는다. 새로운 쟁점이 없으면 PASS. message는 사람 대화처럼 간결하게 쓴다.

공개 조건이 기존 후보로 충족될 수 있으면 requires_new_candidate=false로 둔다. 현재 후보들 중 어느 것으로도 필요한 조건을 충족할 수 없을 때만 requires_new_candidate=true와 구체적인 condition을 작성한다. 단순 선호 차이 때문에 후보 생성을 다시 요청하지 않는다.


PM 최종 선택 대기, 이미 명시된 본인 Confirm, 기존 후보에 포함된 Beta 이관·필수 Core 유지 조건은 새 계획이 필요한 사유가 아니다. 이 경우 requires_new_candidate=false다. ANSWER/QUESTION/PREFER/PASS에는 requires_new_candidate=true를 쓰지 않는다. 실제 현재 후보가 충족하지 못하는 작업·담당·일정·범위 변경이 있을 때만 CONDITION과 구체적인 미충족 조건을 답한다.

allocations_are_deferred=true면 원 업무량을 후속 milestone에 보존한 것이다. 그 배분량을 Alpha의 my_schedule에 다시 더해서 불가능하다고 판단하지 않는다. 현재 후보의 my_schedule·deferred·hive_verification을 읽고, 원래의 변경 전/문제 보드와 구별한다.

reference_feedback가 있으면 직전 발언의 candidate_id가 목록에 없었다는 뜻이다. expected_candidate_ids 중 하나를 글자 그대로 사용해 다시 답한다. recipient는 공개 참가자 id(예: dev, art) 또는 null만 쓴다.

## 쟁점의 진행
QUESTION을 받았으면 우선 그 질문에 ANSWER 또는 조건을 제시하고, 이전 발화의 대상·후보 버전을 짚는다. 같은 확인 요청을 다른 사람에게 돌려 반복하지 않는다. 가능한 대안이 둘이면 ‘내가 받는 산출물/바뀌는 기존 업무/지켜지는 약속/누구의 직접 승인이 필요한지’를 비교한다. 예: Ben 단순 스모크 인수와 Sam 스모크+S3 금요일 이동. 조건부 권한은 사람에게 확인할 쟁점으로 남기고 타인의 동의를 대신하지 않는다. 해결되지 않은 실제 조건만 후보 보충으로 전달한다. 새로운 쟁점 없이 토론 횟수만 채우지 말고 PASS한다.
