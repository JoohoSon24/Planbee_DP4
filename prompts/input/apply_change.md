PM이 보낸 메시지(issue)를 읽고 ReportedChange 하나를 반환하라. PM은 팀원에게 들은 일을 전하기도 한다("Ben이 …래요"). 1인칭("제가 …")이면 그 업무 담당자의 말을 옮긴 것으로 본다.

먼저 kind를 정한다.
- change: 이번 주 일정에 영향을 주는 사실이 있다(누가 언제 일을 못 함, 업무가 더/덜 걸림).
- question: 보드·팀·일정에 대한 질문이다. answer에 1–3문장으로 답한다. week(반나절마다 누가 어떤 업무를 하는지)와 free(반나절마다 비어 있는 사람), tasks의 when을 그대로 읽어 답하고 계산하지 않는다. 누가 비어 있는지는 free만 보고 답한다. facts에 있는 내용만 쓰고, 시간은 "수요일 오후"처럼 요일과 오전/오후로 말한다. 모르면 모른다고 쓴다.
- other: 인사, 잡담, 팀과 무관한 요청. answer는 비워 둔다.
question/other이면 task_id, person, unavailable_slots, extra_days를 비워 둔다.

kind가 change일 때:
- 두 종류를 구분한다.
  · "못 한다/부재/병가/회의/외부 일정" → 사람이 그 시간에 일할 수 없음 → person + unavailable_slots
  · "더 걸린다/늦어진다/커졌다/줄었다" → 업무량이 바뀜 → extra_days (반나절=0.5, 하루=1, 줄면 음수). 이 경우 unavailable_slots는 비운다.
- unavailable_slots: 일할 수 없는 반나절 목록. 각 항목은 day(월·화·수·목·금)와 part(오전·오후·종일). 숫자로 시간을 계산하지 않는다.
  "수요일 오후에는 못 하고 목요일 오후부터 가능" → unavailable_slots [수 오후], available_again 목 오후. "목요일 하루 병가" → [목 종일].
- available_again: "~부터 할 수 있다/가능하다"가 있으면 다시 일할 수 있는 첫 반나절(day, part). 없으면 null. 코드가 그 직전까지를 부재로 채운다.
- person: 일할 수 없는 사람 id(people 목록). 업무량 변경이면 null.
- task_id: 변경의 원인이 되는 업무 id. 사람이 부재하면 그 시간에 그 사람이 맡고 있는 업무(tasks의 start~end가 겹치는 것)를 고른다. 영향을 받는 후속 업무가 아니라 원인 업무다.
- summary: 반영 내용을 한 문장으로.
누가, 무엇이 바뀌었는지 메시지에 없으면(예: "일정이 좀 꼬였어요") 지어내지 말고 task_id=null로 두고 clarification에 질문 하나를 쓴다.

references는 PM이 보드에서 직접 끌어와 인용한 항목이다. "이 업무", "이 사람", "이 인계"는 references를 뜻한다. task_id·person을 고를 때 references를 먼저 쓰고, 질문에 답할 때도 그 항목을 기준으로 답한다. 인계(handoff)가 인용되면 원인 업무는 from_task다.
