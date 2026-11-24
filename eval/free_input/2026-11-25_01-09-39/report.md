# Free-input probe · 2026-11-25_01-09-39

전체 정답 33/42 · 오류 0 · 중앙값 9.5초

| 항목 | 정확도 |
|---|---|
| kind | 39/42 |
| task | 21/24 |
| person | 15/15 |
| window | 12/15 |
| workload | 9/9 |
| answer | 6/6 |

| 기대 → 실제 | 횟수 |
|---|---|
| change->change | 24 |
| clarify->question | 3 |
| other->other | 6 |
| question->question | 9 |

| case | 결과 | kind | task | 점수 | 답/요약 |
|---|---|---|---|---|---|
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에는 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에는 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에는 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c2_workload | OK | change | S3 | {"kind": true, "task": true, "workload": true} | S3 랭킹 화면이 반나절 더 걸린다. |
| c2_workload | OK | change | S3 | {"kind": true, "task": true, "workload": true} | S3 랭킹 화면이 반나절 더 걸린다. |
| c2_workload | OK | change | S3 | {"kind": true, "task": true, "workload": true} | S3 랭킹 화면이 반나절 더 걸린다. |
| c3_sick_day | OK | change | A2 | {"kind": true, "task": true, "person": true, "window": true} | Mia가 목요일 하루 병가로 A2 · 이펙트 다듬기를 진행할 수 없습니다. |
| c3_sick_day | OK | change | A2 | {"kind": true, "task": true, "person": true, "window": true} | Mia가 목요일 하루 병가로 A2 · 이펙트 다듬기를 진행할 수 없습니다. |
| c3_sick_day | OK | change | A2 | {"kind": true, "task": true, "person": true, "window": true} | Mia가 목요일 하루 병가로 인해 A2 · 이펙트 다듬기를 진행할 수 없습니다. |
| c4_first_person | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe가 금요일 오전에 회의가 생겨서 Q2 통합 QA를 못 봅니다. |
| c4_first_person | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe가 금요일 오전에 회의가 생겨서 Q2 통합 QA를 못 봅니다. |
| c4_first_person | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe가 금요일 오전에 회의가 생겨서 Q2 통합 QA를 못 봅니다. |
| c5_handoff | OK | change | G2 | {"kind": true, "task": true, "workload": true} | G2 보스전 연결이 하루 더 걸려 QA로 넘어가는 게 늦어질 것 같습니다. |
| c5_handoff | OK | change | G2 | {"kind": true, "task": true, "workload": true} | G2 보스전 연결이 하루 더 걸려 QA로 넘어가는 게 늦어질 것 같습니다. |
| c5_handoff | OK | change | G2 | {"kind": true, "task": true, "workload": true} | G2 보스전 연결이 하루 더 걸려 QA로 넘어가는 게 늦어질 것 같습니다. |
| r1_task_ref | OK | change | S2 | {"kind": true, "task": true, "person": true, "window": true} | Sam이 수요일 오후에 서버 배포 업무를 못 합니다. |
| r1_task_ref | OK | change | S2 | {"kind": true, "task": true, "person": true, "window": true} | Sam이 수요일 오후에 S2 · 서버 배포를 못 합니다. |
| r1_task_ref | OK | change | S2 | {"kind": true, "task": true, "person": true, "window": true} | Sam이 수요일 오후에 서버 배포 업무를 못 합니다. |
| r2_person_ref | OK | change | G2 | {"kind": true, "task": true, "person": true, "window": true} | Leo가 수요일 오후에 외부 일정이 있어 G2 업무를 수행할 수 없습니다. |
| r2_person_ref | OK | change | G2 | {"kind": true, "task": true, "person": true, "window": true} | Leo가 수요일 오후에 외부 일정이 있어 G2 업무를 수행할 수 없습니다. |
| r2_person_ref | OK | change | G2 | {"kind": true, "task": true, "person": true, "window": true} | Leo가 수요일 오후에 외부 일정이 있어 G2 업무를 수행할 수 없습니다. |
| r3_handoff_ref | MISS | change | A2 | {"kind": true, "task": false, "workload": true} | A1 인계가 하루 늦어져 G2 작업이 하루 더 걸립니다. |
| r3_handoff_ref | MISS | change | A2 | {"kind": true, "task": false, "workload": true} | A1 인계가 하루 늦어져 G2 작업이 하루 더 걸립니다. |
| r3_handoff_ref | MISS | change | A2 | {"kind": true, "task": false, "workload": true} | A1 인계가 하루 늦어져 G2 작업이 하루 더 걸립니다. |
| q1_who | OK | question |  | {"kind": true, "answer": true} | Q2는 Zoe가 맡고 있습니다. Q2의 일정은 목요일 오후부터 금요일 오후까지입니다. |
| q1_who | OK | question |  | {"kind": true, "answer": true} | Q2는 Zoe가 맡고 있습니다. Q2의 일정은 목요일 오후부터 금요일 오후까지입니다. |
| q1_who | OK | question |  | {"kind": true, "answer": true} | Q2는 Zoe가 맡고 있습니다. Q2의 일정은 목요일 오후부터 금요일 오후까지입니다. |
| q2_free_slot | OK | question |  | {"kind": true} | 목요일 오후에는 Mia가 이펙트 다듬기(A2) 작업을 하고 있습니다. Leo는 보스전 연결(G2) 작업을 진행 중입니다. Sam과 Ben, Zo |
| q2_free_slot | OK | question |  | {"kind": true} | 목요일 오후에는 Mia가 이펙트 다듬기(A2) 작업을 하고 있습니다. Leo는 보스전 연결(G2) 작업을 진행 중이며, Sam은 서버 배포(S2 |
| q2_free_slot | OK | question |  | {"kind": true} | 목요일 오후에는 Mia가 이펙트 다듬기(A2) 작업을 하고 있습니다. Leo는 보스전 연결(G2) 작업을 진행 중입니다. Sam과 Ben, Zo |
| q3_ref_question | OK | question |  | {"kind": true, "answer": true} | 업무 B2 · 메뉴 화면은 수요일 오후부터 목요일 오후까지 진행됩니다. 현재 진행 상황에 따라 마감일은 금요일 오후로 예상됩니다. |
| q3_ref_question | OK | question |  | {"kind": true, "answer": true} | 업무 B2 · 메뉴 화면은 수요일 오후부터 목요일 오후까지 진행됩니다. 현재 예상 완료일은 금요일 오후입니다. |
| q3_ref_question | OK | question |  | {"kind": true, "answer": true} | 업무 B2 · 메뉴 화면은 수요일 오후부터 목요일 오후까지 진행됩니다. 현재 예상 완료일은 금요일 오후입니다. |
| o1_greeting | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o1_greeting | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o1_greeting | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 창에는 이번 주 일정에 생긴 변경을 적어 주세요. 보드에 대한 질문에도 답할 수 있어요. |
| u1_vague | MISS | question |  | {"kind": false} | 일정이 꼬였다는 구체적인 내용이 없어서 어떤 부분이 영향을 받는지 알 수 없습니다. 추가적인 정보가 필요합니다. |
| u1_vague | MISS | question |  | {"kind": false} | 일정에 대한 구체적인 내용이 없어서 확인이 필요합니다. 어떤 일정이 꼬였는지, 또는 어떤 변경 사항이 있는지 알려주시면 좋겠습니다. |
| u1_vague | MISS | question |  | {"kind": false} | 일정에 대한 구체적인 내용이 없어서 확인이 필요합니다. 어떤 일정이 꼬였는지, 또는 어떤 변경 사항이 있는지 알려주시면 좋겠습니다. |
