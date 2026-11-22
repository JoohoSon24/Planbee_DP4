# 에이전트 MD 개선과 실험 기록

각 버전의 `prompts/`에 당시 MD 원본, `manifest.json`에 프롬프트·코드·시드 hash, `NOTES.md`에 가설과 실패 원인을 보존합니다. `experiments/`에는 실제 실행 결과를 둡니다. Live와 Mock을 분리하며, 오류·중단·부분 기록을 삭제하거나 성공으로 바꾸지 않습니다.

**기준 충족**은 T1~T4의 검증된 후보가 당사자 검토를 거쳐 PM 선택 대기에 도달하거나 T5가 Dev·QA의 제약 확인 후 PM 검토로 끝났다는 뜻입니다. 실제 PM 선택·사람 동의·적용 완료율이나 사람 순위 평가 점수가 아닙니다.

| 버전 | 가설 | 기록된 실행 |
|---|---|---|
| [000_baseline](agent_prompts/2026-11-22_19-48-38_272587_v000_baseline/NOTES.md) | 기존 프롬프트와 코드의 한계를 기준선으로 보존. T1 불필요한 전원 호출, T3 범위 이관과 T4 조건부 의존성/검증 생략 미지원. | 실행 결과 없음 / 원본 보존 |
| [001_role_and_plan_operators](agent_prompts/2026-11-22_22-51-34_273869_v001_role_and_plan_operators/NOTES.md) | 개인별 MD와 실제 범위/검증/단계별 연산, 단독 이동의 참여자 축소로 T1~T4 유효 후보를 만들고 T5는 Dev·QA 설명 뒤 PM 보류 검토로 종료한다. | [mock · 3/4 · seed 17 · 부분/스크립트 오류](agent_prompts/2026-11-22_22-51-34_273869_v001_role_and_plan_operators/experiments/2026-11-22_22-51-45_065726_mock/summary.json)<br>[mock · 4/5 · seed 17 · 완료](agent_prompts/2026-11-22_22-51-34_273869_v001_role_and_plan_operators/experiments/2026-11-22_22-52-32_946536_mock/summary.json)<br>[live · 0/1 · seed 17 · 완료](agent_prompts/2026-11-22_22-51-34_273869_v001_role_and_plan_operators/experiments/2026-11-22_22-53-16_890680_live/summary.json) |
| [002_preserve_own_effort](agent_prompts/2026-11-22_22-54-26_410872_v002_preserve_own_effort/NOTES.md) | T1의 6h→8h 반올림을 코드에서 제거하고 Dev MD에 동일 업무의 소요량 보존 검사를 추가하면 Live에서도 요청한 이동만 제안된다. | [live · 2/5 · seed 17 · 완료](agent_prompts/2026-11-22_22-54-26_410872_v002_preserve_own_effort/experiments/2026-11-22_22-57-56_346042_live/summary.json) |
| [003_units_schema_and_participants](agent_prompts/2026-11-22_23-02-03_253746_v003_units_schema_and_participants/NOTES.md) | Live v002의 일/시간 혼동과 잘못된 plan_actions.kind를 MD로 명확히 하고 한 번의 필드 오류 피드백 복구만 허용한다. 무관한 업무 이동을 제한해 실제 당사자만 토론한다. | [live · 4/5 · seed 17 · 완료](agent_prompts/2026-11-22_23-02-03_253746_v003_units_schema_and_participants/experiments/2026-11-22_23-06-01_772379_live/summary.json) |
| [004_quarter_day_and_exact_budget](agent_prompts/2026-11-22_23-11-11_636255_v004_quarter_day_and_exact_budget/NOTES.md) | 재견적의 6h 반올림과 형식 복구 호출 집계 누락을 재현 테스트로 수정. M4 2h 단위와 실제 호출 예산을 보존하면 T1~T5가 모두 기대한 PM 검토 또는 선택 대기까지 도달한다. | [mock · 5/5 · seed 17 · 완료](agent_prompts/2026-11-22_23-11-11_636255_v004_quarter_day_and_exact_budget/experiments/2026-11-22_23-11-38_278115_mock/summary.json)<br>[live · 4/5 · seed 17 · 완료](agent_prompts/2026-11-22_23-11-11_636255_v004_quarter_day_and_exact_budget/experiments/2026-11-22_23-11-51_924606_live/summary.json) |
| [005_classify_duration_change_first](agent_prompts/2026-11-22_23-17-43_447707_v005_classify_duration_change_first/NOTES.md) | 재견적 응답에서 실제 소요량 변경 여부를 먼저 분리하면 단순 일정 이동에서 모순된 숫자를 적용하지 않는다. 나머지 시나리오의 실제 소요 증가는 유지하고 모든 결과를 Live로 검증한다. | [live · 4/5 · seed 17 · 완료](agent_prompts/2026-11-22_23-17-43_447707_v005_classify_duration_change_first/experiments/2026-11-22_23-17-55_099652_live/summary.json) |
| [006_keep_verified_options](agent_prompts/2026-11-22_23-27-57_605805_v006_keep_verified_options/NOTES.md) | PM 승인 대기를 새 설계로 오인하지 않고 보충 생성 실패 시 검증 후보를 보존·재평가한다. 이관된 업무의 이중 합산과 실제 실행이 같은 중복 후보를 제거한다. | [live · 2/2 · seed 17 · 완료](agent_prompts/2026-11-22_23-27-57_605805_v006_keep_verified_options/experiments/2026-11-22_23-31-00_887456_live/summary.json)<br>[mock · 5/5 · seed 17 · 완료](agent_prompts/2026-11-22_23-27-57_605805_v006_keep_verified_options/experiments/2026-11-22_23-31-02_007963_mock/summary.json) |

## 해석과 재실행

- v003은 형식 복구 중 budget ctx가 복사되어 호출 수 일부가 누락되는 결함이 있었습니다. v003 호출 수를 비용 통계로 사용하지 않습니다. v004에서 재현 테스트와 함께 수정했습니다.
- v001과 v004에서도 T1의 결과를 실패로 남겼으며, 같은 6h를 8h로 바꾸는 문제가 남았는지 실제 Live로 계속 검증합니다. 재견적과 후보 배치를 별개로 검사합니다.
- T4 원문의 예시는 Retest 생략이지만, 월요일에 임시 Integration과 최종 교체를 끝내 Retest를 유지하는 유효 대안도 있습니다. 생략을 강제로 고르도록 프롬프트를 조작하지 않습니다. 생략 후보는 QA 본인 Confirm이 필요합니다.
- 버전별 과거 MD는 런타임 `prompts/` 밖에 두므로 새 run에 옛 지시가 섞이지 않습니다. 실행 중 편집은 이미 시작한 run의 고정된 프롬프트를 바꾸지 않습니다.
- 실제 사람 평가 라벨이나 CE 점수를 대신 만들지 않습니다. Live 실험에서 PM 선택과 당사자 본인 확인은 자동 승인하지 않습니다.

```bash
.venv/bin/python scripts/prompt_versions.py 다음버전이름 --hypothesis "검증할 변경 가설"
.venv/bin/python scripts/iterate_m4_prompts.py --version past_versions/agent_prompts/버전폴더 --llm live --max-calls 36
.venv/bin/python scripts/summarize_prompt_iterations.py
```

실험은 버전 manifest와 현재 코드·MD가 같은지 먼저 검사합니다. 이전 코드 hash가 다르면 새 버전을 만들어 실험해야 합니다. 현재 실행·역할 체험은 [Live 가이드](../docs/LIVE_GUIDE.md)를 따르세요.
