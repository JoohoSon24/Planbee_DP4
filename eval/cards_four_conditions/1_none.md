# 위임 카드 없음

객관 정보=False / 자동 권한=False

- 수 09:10 mia → 기록: 기능 구현 · 3일 → 4일 / 기능 구현 하루 추가 필요
- 수 09:11 mia → ara: 기능 코드 · 수 저녁 → 목 저녁
- 수 09:12 hive: 마감 판정 · 기능 코드 수 저녁 위험 · 담당 Proxy에게 실행 가능한 분담안을 요청
- 수 09:13 hive: 도움 요청 · 기능 코드 · 수 저녁까지 · 개발
- 수 09:14 mia → 기록: 독립 기능 코드 · 1일 · 따로 할 수 있음
- 수 09:15 hive: 위임카드 확인 단계 · 2명의 '개발' Proxy에게 각자 자기 카드와 일정으로 요청
- 수 09:16 hive: 1라운드 · 위임 요청 · Jun의 프록시, Sol의 프록시
- 수 09:17 mia → jun: 독립 기능 코드 · 1일 · 수 저녁까지 돼요?
- 수 09:18 hive: 반려 · Jun의 프록시 답 NEEDS_INPUT · OVERLOAD: Jun 4½ + 1 = 5½/5일로 넘침 · 라운드는 쓰지 않음
- 수 09:19 jun → mia: 독립 기능 코드 · 거절 / 엔진의 일정 검사에서 불가능하다고 확인됨
- 수 09:20 mia → sol: 독립 기능 코드 · 1일 · 수 저녁까지 돼요?
- 수 09:21 sol → mia: 독립 기능 코드 · 1일 · 본인 확인 필요 / 개발 3건 · 개인 작업량은 보지 않은 잠정 답 · 실제 일정은 엔진 검사
- 수 09:22 hive: 권한 확인 · Sol의 한도 또는 바쁨·미확인 메모 → 본인 확인
- 수 09:23 person: 독립 기능 코드 1일 맡을게요 · 확인
- 수 09:24 sol → ara: 독립 기능 코드 · 수 저녁 · 가약속
- 수 09:25 hive: 규칙 확인 · 넘침 없음 · 제출일 · 범위 그대로 · Sol: 본인이 확인함 → 담당 확인만
- 수 09:26 person: 독립 기능 코드는 Sol에게 · 확인
- 수 09:27 mia → ara: 기능 코드 · 수 저녁

## 결과
{
  "pm_decisions": 0,
  "pm_talks": 0,
  "confirms": 2,
  "proxy_msgs": 9,
  "rounds": 1,
  "hive_rejects": 1,
  "late_end": 0,
  "promises_moved": 0,
  "past_deadline": 0,
  "scope_cut": 0,
  "overload": 0,
  "overrides": 0,
  "cost": {
    "Sol": {
      "늘어남": 1.0,
      "밀림": 0
    }
  },
  "cost_people": 1,
  "top_share": 1.0,
  "top_who": "Sol",
  "fairness": {
    "totals": {
      "mia": 5.0,
      "jun": 4.5,
      "sol": 3.0,
      "ara": 1.0
    },
    "variance": 2.421875,
    "range": 4.0,
    "definition": "past_effort + current-week allocated days (done included once)"
  }
}
