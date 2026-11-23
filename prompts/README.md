# Plan Bee 프롬프트 원본

| 폴더 | 역할 | 데이터 접근 |
| --- | --- | --- |
| `input/resolve_task.md` | 줄글 이슈에서 원인 Task 식별·모호하면 질문 | 공개 업무·역할·이슈만, 개인 카드 없음 |
| `candidate_generation/` | 이슈를 읽고 실행 가능한 Task 구조 설계·복구 | 공개 Task/일정/역할만. 개인 카드/정답 순위 없음 |
| `discussion/assess.md` | 후보별 개인 초기 평가 | 본인 카드 + 공개 후보 |
| `discussion/speak.md` | 순서대로 질문·응답·공개 조건 | 본인 카드 + 공개 대화 |
| `discussion/rank.md` | 토론 후 최종 개인 선호 | 본인 카드 + 공개 대화 |
| `discussion/candidate_consent.md` | 후보별 영향 당사자 의사 | 본인 카드 + 정확한 후보 hash |
| `translation/english.md` | 공개 대화의 표시용 영어 번역 | 공개 이슈·발언만. 비공개 카드·평가 없음 |
| `evaluation/` | 사람 평가 안내 | 평가 역할의 본인 카드 + 같은 공개 정보 |

새 후보 경로는 `app/candidates/engine.py`가 사용합니다. run 시작 시 모든 원본의 내용/hash를 고정해 도중 편집이 같은 실험에 섞이지 않게 합니다. 기존 `partition.md`, `revision.md`, `consent.md` 등은 legacy 경로에서 계속 사용합니다. JSON schema·시간 검증·동의·PM 권한·CE 계산은 Python이 수행합니다. Markdown 본문 전체가 실제 지시이며 편집자 설명은 README에 적으세요.

## 개인별 MD와 과거 버전

`agents/dev.md`, `art.md`, `gd.md`, `qa.md`는 해당 역할에만 주입되는 개인 역할 지침입니다. 실제 권한은 본인 위임카드가 우선합니다. `agents/reestimate.md`는 새 기록의 전체 견적·잔여 견적 해석, `discussion/no_options.md`는 후보 고갈 시 실제 당사자의 확인과 PM 전달을 담당합니다.

과거 원본과 가설·실험 결과는 저장소 루트의 `past_versions/agent_prompts/`에 보존합니다. 런타임 프롬프트 폴더 안에 과거 파일을 넣지 않아 run snapshot에 옛 버전이 섞이지 않습니다. 버전별 manifest에 프롬프트·코드·시드 hash를 저장하고, 실제 Live와 Mock 결과를 구분합니다.

업무 식별도 run 공유 호출·시간 예산을 사용합니다. `POST /candidate-runs`에서 `task_id`를 생략하면 실행하며, 기존 명시적 Task API도 유지합니다. 잘못된 ID와 완료 업무는 코드로 차단합니다.
