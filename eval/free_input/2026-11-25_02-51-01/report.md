# Free-input probe · 2026-11-25_02-51-01

전체 정답 17/18 · 오류 1 · 중앙값 11.2초

| 항목 | 정확도 |
|---|---|
| kind | 17/18 |
| task | 10/10 |
| person | 7/7 |
| window | 7/7 |
| workload | 3/3 |
| answer | 4/4 |

| 기대 → 실제 | 횟수 |
|---|---|
| change->change | 10 |
| change->error | 1 |
| clarify->clarify | 1 |
| other->other | 2 |
| question->question | 4 |

| case | 결과 | kind | task | 점수 | 답/요약 |
|---|---|---|---|---|---|
| c1_absence | OK | change | B2 | {"kind": true, "task": true, "person": true, "window": true} | Ben이 수요일 오후에는 B2 메뉴 화면을 시작할 수 없고, 목요일 오후부터 가능하다. |
| c2_workload | OK | change | S3 | {"kind": true, "task": true, "workload": true} | S3 랭킹 화면이 반나절 더 걸립니다. |
| c3_sick_day | OK | change | A2 | {"kind": true, "task": true, "person": true, "window": true} | Mia가 목요일 하루 병가입니다. |
| c4_first_person | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe가 금요일 오전에 회의가 생겨서 Q2 통합 QA를 못 봅니다. |
| c5_handoff | OK | change | G2 | {"kind": true, "task": true, "workload": true} | G2 보스전 연결이 하루 더 걸려 QA로 넘어가는 게 늦어질 것 같습니다. |
| r1_task_ref | OK | change | S2 | {"kind": true, "task": true, "person": true, "window": true} | Sam이 수요일 오후에 S2 · 서버 배포를 못 하고 목요일 오전부터 가능하다. |
| r2_person_ref | OK | change | G2 | {"kind": true, "task": true, "person": true, "window": true} | Leo는 수요일 오후에 외부 일정이 있어 G2 업무를 수행할 수 없습니다. |
| r3_handoff_ref | MISS | error |  | {"kind": false} | model_output_invalid: {"type": "ValidationError", "status": null, "fields": [{"p |
| t1_tpl_absence | OK | change | S2 | {"kind": true, "task": true, "person": true, "window": true} | Sam 님이 수요일 오후에 S2 · 서버 배포 작업을 못 합니다. |
| t2_tpl_workload | OK | change | G2 | {"kind": true, "task": true, "workload": true} | G2 · 보스전 연결 작업이 반나절 더 걸립니다. |
| t3_tpl_dayoff | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe 님이 금요일 하루 쉬어요. |
| t4_tpl_question | OK | question |  | {"kind": true, "answer": true} | 업무 A2 · 이펙트 다듬기는 목요일 오전부터 오후까지 진행됩니다. 현재로서는 목요일 오후에 완료될 것으로 예상됩니다. |
| q1_who | OK | question |  | {"kind": true, "answer": true} | Q2는 Zoe가 맡고 있으며, 목요일 오후부터 금요일 오전까지 진행됩니다. 현재 Zoe는 금요일 오전에 Q2를 진행할 수 있습니다. |
| q2_free_slot | OK | question |  | {"kind": true, "answer": true} | 목요일 오후에는 Leo와 Ben이 비어 있습니다. 따라서 이 시간에 작업을 맡길 수 있는 사람이 있습니다. |
| q3_ref_question | OK | question |  | {"kind": true, "answer": true} | 업무 B2 · 메뉴 화면은 수요일 오후부터 목요일 오전까지 진행됩니다. 현재 진행 중인 업무는 화요일 오후에 시작하여 수요일 오전까지 이어지는  |
| o1_greeting | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| u1_vague | OK | clarify |  | {"kind": true} | 어떤 일정이 꼬였는지 구체적으로 말씀해 주실 수 있나요? |
