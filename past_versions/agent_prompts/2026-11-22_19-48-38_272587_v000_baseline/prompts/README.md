# Plan Bee 프롬프트 원본

| 폴더 | 역할 | 데이터 접근 |
| --- | --- | --- |
| `candidate_generation/` | 이슈를 읽고 실행 가능한 Task 구조 설계·복구 | 공개 Task/일정/역할만. 개인 카드/정답 순위 없음 |
| `discussion/assess.md` | 후보별 개인 초기 평가 | 본인 카드 + 공개 후보 |
| `discussion/speak.md` | 순서대로 질문·응답·공개 조건 | 본인 카드 + 공개 대화 |
| `discussion/rank.md` | 토론 후 최종 개인 선호 | 본인 카드 + 공개 대화 |
| `discussion/candidate_consent.md` | 후보별 영향 당사자 의사 | 본인 카드 + 정확한 후보 hash |
| `evaluation/` | 사람 평가 안내 | 평가 역할의 본인 카드 + 같은 공개 정보 |

새 후보 경로는 `app/candidates/engine.py`가 사용합니다. run 시작 시 모든 원본의 내용/hash를 고정해 도중 편집이 같은 실험에 섞이지 않게 합니다. 기존 `partition.md`, `revision.md`, `consent.md` 등은 legacy 경로에서 계속 사용합니다. JSON schema·시간 검증·동의·PM 권한·CE 계산은 Python이 수행합니다. Markdown 본문 전체가 실제 지시이며 편집자 설명은 README에 적으세요.
