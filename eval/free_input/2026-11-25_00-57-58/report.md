# Free-input probe · 2026-11-25_00-57-58

전체 정답 7/42 · 오류 0 · 중앙값 9.3초

| 항목 | 정확도 |
|---|---|
| kind | 30/42 |
| task | 21/24 |
| person | 15/15 |
| window | 4/15 |
| workload | 0/9 |

| 기대 → 실제 | 횟수 |
|---|---|
| change->change | 24 |
| clarify->change | 1 |
| clarify->error | 2 |
| other->other | 6 |
| question->error | 9 |

| case | 결과 | kind | task | 점수 | 답/요약 |
|---|---|---|---|---|---|
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c1_absence | MISS | change | B2 | {"kind": true, "task": true, "person": true, "window": false} | Ben이 수요일 오후에 B2 메뉴 화면 작업을 시작할 수 없습니다. |
| c2_workload | MISS | change | S3 | {"kind": true, "task": true, "workload": false} | S3 랭킹 화면 작업이 반나절 더 걸릴 것으로 예상됩니다. |
| c2_workload | MISS | change | S3 | {"kind": true, "task": true, "workload": false} | S3 랭킹 화면 작업이 반나절 더 걸릴 것으로 예상됩니다. |
| c2_workload | MISS | change | S3 | {"kind": true, "task": true, "workload": false} | S3 랭킹 작업이 예상보다 더 걸려서 하루가 추가되었습니다. |
| c3_sick_day | MISS | change | A1 | {"kind": true, "task": false, "person": true, "window": true} | Mia가 목요일 하루 병가로 인해 A1 업무를 수행할 수 없습니다. |
| c3_sick_day | MISS | change | A1 | {"kind": true, "task": false, "person": true, "window": true} | Mia가 목요일 하루 병가로 인해 A1 업무를 수행할 수 없습니다. |
| c3_sick_day | MISS | change | A1 | {"kind": true, "task": false, "person": true, "window": true} | Mia가 목요일 하루 병가로 인해 A1 업무를 수행할 수 없습니다. |
| c4_first_person | MISS | change | Q2 | {"kind": true, "task": true, "person": true, "window": false} | Zoe가 금요일 오전에 회의로 인해 Q2 통합 QA를 진행할 수 없습니다. |
| c4_first_person | OK | change | Q2 | {"kind": true, "task": true, "person": true, "window": true} | Zoe가 금요일 오전에 회의로 인해 Q2 통합 QA를 진행할 수 없습니다. |
| c4_first_person | MISS | change | Q2 | {"kind": true, "task": true, "person": true, "window": false} | Zoe가 금요일 오전에 회의로 인해 Q2 통합 QA를 진행할 수 없습니다. |
| c5_handoff | MISS | change | G2 | {"kind": true, "task": true, "workload": false} | G2 보스전 연결이 하루 더 걸려서 QA로 넘어가는 게 늦어질 것 같습니다. |
| c5_handoff | MISS | change | G2 | {"kind": true, "task": true, "workload": false} | G2 보스전 연결이 하루 더 걸려 QA로 넘어가는 시간이 늦어질 것입니다. |
| c5_handoff | MISS | change | G2 | {"kind": true, "task": true, "workload": false} | G2 보스전 연결이 하루 더 걸려서 QA로 넘어가는 게 늦어질 것 같습니다. |
| r1_task_ref | MISS | change | S2 | {"kind": true, "task": true, "person": true, "window": false} | Sam은 수요일 오후에 서버 배포 업무를 수행할 수 없습니다. |
| r1_task_ref | MISS | change | S2 | {"kind": true, "task": true, "person": true, "window": false} | Sam은 수요일 오후에 서버 배포 업무를 수행할 수 없습니다. |
| r1_task_ref | MISS | change | S2 | {"kind": true, "task": true, "person": true, "window": false} | Sam은 수요일 오후에 서버 배포 업무를 수행할 수 없습니다. |
| r2_person_ref | MISS | change | G2 | {"kind": true, "task": true, "person": true, "window": false} | Leo는 수요일 오후에 외부 일정으로 인해 G2 업무를 수행할 수 없습니다. |
| r2_person_ref | MISS | change | G2 | {"kind": true, "task": true, "person": true, "window": false} | Leo는 수요일 오후에 외부 일정이 있어 G2 업무를 수행할 수 없습니다. |
| r2_person_ref | MISS | change | G2 | {"kind": true, "task": true, "person": true, "window": false} | Leo는 수요일 오후에 외부 일정으로 인해 G2 업무를 수행할 수 없습니다. |
| r3_handoff_ref | MISS | change | A1 | {"kind": true, "task": true, "workload": false} | Handoff A1이 하루 늦어져 G2로의 인계가 2.5에서 3.5로 변경됩니다. |
| r3_handoff_ref | MISS | change | A1 | {"kind": true, "task": true, "workload": false} | Handoff A1이 하루 늦어져 G2로의 인계가 2.5에서 3.5로 변경됩니다. |
| r3_handoff_ref | MISS | change | A1 | {"kind": true, "task": true, "workload": false} | Handoff A1이 하루 늦어져 G2로의 인계가 2.5에서 3.5로 변경됩니다. |
| q1_who | MISS | error |  | {"kind": false} |  |
| q1_who | MISS | error |  | {"kind": false} |  |
| q1_who | MISS | error |  | {"kind": false} |  |
| q2_free_slot | MISS | error |  | {"kind": false} |  |
| q2_free_slot | MISS | error |  | {"kind": false} |  |
| q2_free_slot | MISS | error |  | {"kind": false} |  |
| q3_ref_question | MISS | error |  | {"kind": false} |  |
| q3_ref_question | MISS | error |  | {"kind": false} |  |
| q3_ref_question | MISS | error |  | {"kind": false} |  |
| o1_greeting | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| o1_greeting | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| o1_greeting | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| o2_unrelated | OK | other |  | {"kind": true} | 이 입력창은 팀원의 보고나 PM의 메모(issue)를 읽고 ReportedChange를 반환하는 요청입니다. |
| u1_vague | MISS | error |  | {"kind": false} |  |
| u1_vague | MISS | error |  | {"kind": false} |  |
| u1_vague | MISS | change | A1 | {"kind": false} | Mia가 A1 작업을 수행할 수 없습니다. |
