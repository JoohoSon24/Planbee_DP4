규칙 안에서는 마감을 지키는 계획이 없어 Hive가 풀 수 있는 규칙 후보(rules)를 계산했다. 각 규칙에는 풀면 생기는 계획 수(feasible), 누가 결정하는지(authorizer), 무엇이 바뀌는지(patch_summary)가 있다.
self의 입장에서 이번 턴에 규칙 하나에 대한 의견을 말하라. candidate_id에는 규칙 id(예: R1)를 쓴다.
- 내 일정·바람·한계(my_profile, my_delegation)와 부딪히는 규칙이 있으면 REJECT로 이유를 구체적으로 말한다.
- 풀어도 계획이 0개인 규칙은 고르지 않는다.
- 둘 이상이 가능하면 PREFER로 하나를 고르고 다른 규칙과 비교한 이유를 한 문장으로 말한다.
- 다른 사람의 일정을 바꾸는 규칙을 그 사람 대신 승인하지 않는다. 필요하면 QUESTION으로 그 사람에게 묻는다(recipient 지정).
- 내게 온 질문이 있으면 먼저 ANSWER한다. 앞사람의 문장을 반복하지 않는다. 새 쟁점이 없으면 PASS.
basis에는 card, task:<ID>, handoff:<ID> 중 실제로 기댄 것을 적고, 답장이면 reply_to에 public_history index를 적는다.

rules[].my_cost는 그 규칙을 풀었을 때 나에게 생기는 손해를 코드가 내 프로필로 계산한 값이다. 규칙마다 score가 다르면 가장 큰 규칙에 REJECT하고 reasons를 말하고, 아니면 score가 가장 작은 규칙을 PREFER한다. 모두 0이면 PASS한다. 다른 사람의 바람을 내 것처럼 말하지 않고, 앞 사람의 문장을 옮겨 쓰지 않는다.
