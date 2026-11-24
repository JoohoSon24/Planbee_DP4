# ① QA 부재 · Zoe 목요일 오후 스모크

Zoe가 목요일 오후 Q2 스모크를 못 함. 스모크를 누가 맡고 무엇을 옮길지.

## 보고 (실제 발화자: zoe)

> Zoe가 목요일 오후 Q2 통합 QA 스모크를 진행할 수 없대요. 스모크는 다른 적격자에게 넘겨도 되고, 금요일 오전 최종 회귀와 서명은 Zoe가 맡는대요.

## 데이터 출처
- 사람·업무·소요·우선순위·선후관계·조각: M4 시연용 시나리오 export (장여경, 2026-11-23). 원문은 `seed/m4_t6_game_demo/source.md`.
- 사람 프로필의 바람·피하고 싶은 것 중 아래 항목은 **협상 행동을 관찰하려고 추가한 설계값**입니다: mia avoid, leo wish, sam wish, sam avoid, ben avoid, zoe wish, zoe avoid.
- 보고된 변경은 보드의 가용 시간 제약으로 반영했습니다 (`cards[].policy.unavailable`).
- 화요일 13:00 이전에 끝난 일: 화요일 오전 진행분(A1·G1·S1·Q1)은 원문 진행률에서, 월요일의 스테이지3 배경·스테이지1·2 구현은 원문 선행조건에서 가져왔고 담당·요일은 설계값입니다.
- 동의 단계: 카드 기반 평가·본인 확인을 쓰지 않습니다 (`consent_mode: discussion`). 프록시는 공개 토론에서 선호·반대·조건·질문만 남기고 PM이 고릅니다.

## 정답지 (실행 전에 작성, `expected.yaml`)
```yaml
impact:
  broken_any:
  - h_Q2_G3
  owner: zoe
  involved_any:
  - leo
  not_involved:
  - mia
candidates:
  families_any:
  - - ben
  - - sam
  keep_parts:
    Q2:
      regression: zoe
participants:
  exclude:
  - mia
  include:
  - zoe
  - leo
behaviour:
  non_prefer_acts_min: 1
pm:
  options_min: 2
  options_max: 3
```
