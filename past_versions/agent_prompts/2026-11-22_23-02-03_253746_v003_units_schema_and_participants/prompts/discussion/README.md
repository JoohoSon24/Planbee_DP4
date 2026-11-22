# Discussion agent 프롬프트

이 폴더의 Markdown 본문이 실제 Live LLM 호출에 사용됩니다. 공통 agent 역할을 개인별로 재사용하고, 호출 시 해당 참여자의 위임카드만 주입합니다. 다른 참여자의 비공개 카드는 넣지 않습니다.

| 파일 | 사용 시점 / 역할 |
| --- | --- |
| `system.md` | 모든 Live 호출의 공통 역할과 도구 응답 규칙 |
| `actor.md` | 발화자와 본인 위임 설정 주입. `${name}`, `${id}`, `${delegation}` 자리표시자 유지 |
| `consent.md` | 현재 배분의 수락·거절·본인 확인 필요 여부 판단 (`ConsentDecision`) |
| `design.md` | 재제안 설계의 공통 목표. 공개 피드백과 검증 사유와 함께 전달 |
| `partition.md` | 독립 분할: LLM이 분량 참고안을 선택하고 실제 업무 경계·산출물·선후 관계 설계 (`PartitionDraft`) |
| `revision.md` | 전체 양도·다른 업무 이동·협업 등 수정안 설계 (`RevisionProposal`) |
| `strategy_independent_split.md` | 독립 산출물 분할 전략의 요구사항 |
| `strategy_whole_transfer.md` | 원 업무 전체 재배분 전략의 요구사항 |
| `strategy_move_other_work.md` | 다른 Task의 실제 담당/시작 변경 요구사항 |
| `strategy_collaborate.md` | 실제 지원 업무와 협업 근거 요구사항 |
| `strategy_feedback.md` | 전략이 제안에 반영되지 않았을 때 복구 지시 |
| `format_repair.md` | 모델 출력 스키마 오류의 복구 지시 |

## 편집과 적용

각 파일의 본문 전체가 프롬프트입니다. 편집자 설명은 이 README에 적으세요. 내용은 UTF-8로 저장하고 빈 파일은 허용하지 않습니다. 실행 경로와 무관하게 `app/prompts.py`가 저장소 기준으로 읽으며, 캐시 없이 호출할 때마다 읽으므로 서버가 새 코드를 로드한 이후에는 MD 수정이 다음 호출에 반영됩니다. 진행 중 run에서 바꾸면 이후 호출부터 달라지므로 버전 비교는 새 run으로 수행하는 것을 권장합니다.

## 코드와의 경계

`app/llm.py`는 위 프롬프트에 본인의 카드, 현재 업무/일정, 공개 대화 이력과 제안을 붙입니다. `app/discussion.py`는 전략·검증 피드백·라운드·호출 한도·버전별 동의를 관리합니다. JSON 출력 스키마와 일정/마감 검증은 Python에 남아 있습니다. MD만 바꿔 검증을 우회할 수는 없습니다. 최초 견적·help 등 discussion 밖의 개별 프롬프트는 이번 분리 범위에 포함하지 않았습니다.
