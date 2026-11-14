# Plan Bee 백엔드 (Handoffs 세 화면)

프로토타입 "Handoffs 세 화면"의 상태와 시연 흐름을 서버로 옮긴 것입니다.
화면에 박혀 있던 대본(`runWed`, `runThu`, `runGrant`) 대신, 기록이 들어오면 프록시와 Hive가 실제로 계산해서 같은 결과를 냅니다.

## 실행

한 줄씩 복사해 실행합니다.

```bash
pip install -r requirements.txt
```
```bash
python seed.py
```
```bash
uvicorn app.api:app --reload
```

서버가 켜지면 `http://localhost:8000` 이 화면, `http://localhost:8000/docs` 가 API 문서입니다.
`python seed.py` 는 DB를 비우고 더미 데이터로 다시 채웁니다. 표 구조가 바뀐 버전으로 올렸을 때는 서버가 처음 켜질 때 자동으로 다시 채웁니다.

서버 없이 시연 흐름을 터미널에 찍어 보려면 (첫 인자 `defer` 또는 `cut`, 둘째 인자 `fast` 또는 `learn`):

```bash
python run_demo.py defer fast
```

테스트:

```bash
pytest -q
```

환경 변수

| 이름 | 기본 | 뜻 |
|---|---|---|
| `PLANBEE_DB` | `sqlite:///planbee.db` | DB 주소 |
| `PLANBEE_LLM` | `mock` | `mock` = 대본(`seed/mock_llm.yaml`), `live` = OpenRouter |
| `OPENROUTER_API_KEY`, `PLANBEE_MODEL` | | `live` 일 때만. `.env` 파일에 적어도 됨 (`.env.example` 참고) |

## 화면 고치기

`web/index.html` 이 프로토타입 화면입니다. 서버가 같은 주소에서 내보내므로 파일을 저장하고 브라우저를 새로 고치면 바로 보입니다.
화면은 `GET /state` 로 받은 값을 `adopt()` 로 `S` 에 얹어 그리고, 버튼은 `act()` 로 서버를 부릅니다.
모양(CSS, `paint…` 함수)은 프로토타입 그대로라 디자인을 바꿀 때 서버 쪽은 건드릴 필요가 없습니다.
입력 화면의 "직접 누르기"를 켜면 팀원 확인을 서버가 대신 누르지 않고 기다립니다.

## 구조

```
app/
  models.py     DB 표 14개
  hive.py       ⚙ Hive. 일정 계산 · Handoff 상태 · 견적 기본값 · 규칙 확인(gate). LLM 없음
  llm.py        ⬢ 프록시가 쓰는 부분. Mock / Live. 답은 pydantic 으로 모양 강제
  workflow.py   LangGraph 협상 그래프 + PM 조작(허락 · 약속 다시 정하기 · 옮기기)
  store.py      시드 · 판 읽기 · 기록 도우미 · 되돌리기 · 화면용 JSON
  api.py        FastAPI
web/
  index.html    화면 (프로토타입 + 서버 연결)
seed/
  team.yaml     사람 6 · 일 14 · Handoff 4 · 기록 3 · 규칙 4  (프로토타입 초기 상태)
  feed.yaml     시연 버튼이 넣는 수요일 · 목요일 기록
  mock_llm.yaml Mock LLM 대본 (견적 변경 · 떼어 낼 조각 · 조각별 일수)
tests/
```

누가 무엇을 정하는가

| 주체 | 하는 일 | 코드 |
|---|---|---|
| ⬢ 프록시 (사람마다 하나) | 기록을 읽고 견적 고치기, 떼어 낼 조각 정하기, 요청에 **수락 / 거절 / 조건부 / 본인 확인 필요** 중 하나로 답하기 | `llm.py` |
| ⚙ Hive (코드) | 일정 다시 계산, 늦어질 Handoff 찾기, 프록시 답이 규칙 안인지 검사, 라운드 진행, 받을 사람 고르기 | `hive.py`, `workflow.py` |
| ○ 사람 | 위임 카드로 한도를 정함. 한도를 넘는 일과 자기 일을 넘기는 것만 확인 또는 거절 | `PUT /people/{id}/card`, `POST /confirmations/{id}` |
| PM | 규칙 하나 허락, 약속 다시 정하기, 일 옮기기 | `POST /asks/{id}/grant` 등 |

협상 한 건이 지나가는 단계 (`run.step`)

```
기본 경로            ingest -> help -> bids <-> tally -> propose -> confirm -> commit -> finish
한도를 넘으면        tally -> person (본인 확인) -> propose
받을 사람이 없으면   tally -> ask (PM 대기) -> granted -> bids (라운드 새로) 또는 cutconfirm -> finish
```

**위임 카드.** 사람마다 `auto_days`(이 일수까지는 프록시가 알아서 수락), `refuse_tags`(받지 않는 일), `gives_help`(30분 도움 요청을 받는가), `note` 가 있습니다. 한도를 넘는지는 코드가 검사해서, 프록시가 뭐라고 답했든 넘으면 본인에게 묻습니다.

**답 유형.** 프록시는 자기 사람의 카드 · 일정 · 기록만 보고 `ACCEPT` / `REJECT` / `COUNTER` / `NEEDS_INPUT` 중 하나를 고릅니다. `COUNTER` 의 조건은 두 가지입니다: `help`(누가 30분 봐 주면 가능), `defer`(내 일 하나를 2주차로 미루면 가능). Hive 는 `hive.check_reply()` 로 답이 규칙 안인지만 보고, 어긋나면 이유(`OVERLOAD`, `BAD_CONDITION`)를 붙여 한 번 돌려보냅니다. 반려는 라운드를 쓰지 않습니다.

**라운드.** `bids` 한 번이 한 라운드입니다. 1라운드는 조각을 맡아 달라고 묻고, 다음 라운드는 조건부 답의 `help` 조건을 상대 프록시에게 확인합니다. `defer` 조건은 미루기가 PM 전용이라 프록시끼리 풀 수 없고, PM 확인의 선택지가 됩니다. 규칙 `rounds`(기본 3) 안에 못 풀면 남은 항목과 함께 PM에게 갑니다.

사람이나 PM을 기다릴 때는 `run.status` 가 `waiting_confirm` / `waiting_pm` 이 되고 그래프가 멈춥니다.
답이 오면 같은 run 이 멈춘 단계부터 다시 돕니다. 진행 상태가 DB에 있어서 서버를 껐다 켜도 이어집니다.

## 화면 ↔ API

`GET /state` 하나가 프로토타입의 `S` 와 같은 모양을 돌려줍니다. 화면은 이것으로 다시 그리면 됩니다.
상태를 바꾸는 모든 POST 도 바뀐 `/state` 를 돌려줍니다.

| 화면 | 프로토타입 동작 | API |
|---|---|---|
| 공통 | 처음 그리기, 다시 그리기 | `GET /state` |
| 공통 | 시연 · 수요일/목요일 기록 받기 | `POST /demo/advance` `{auto_confirm}` |
| 공통 | 되돌리기 / 처음부터 | `POST /undo` / `POST /reset` |
| 입력 | 들어온 기록 | `GET /records`, `POST /records` |
| 입력 | 내 규칙, 받을 사람 고르는 기준 | `GET /rules`, `PUT /rules/pref` |
| 입력 | 위임 카드 | `GET /cards`, `PUT /people/{id}/card` |
| 입력 | 라운드 수 | `PUT /rules/rounds` `{max}` |
| 입력 | 팀원 확인 | `GET /confirmations`, `POST /confirmations/{id}` `{ok}` |
| 판 | 막대 · 화살표 · 남은 여유 | `GET /board` |
| 판 | 오간 말 | `GET /log?hid=` |
| 판 | 막대 자세히 | `GET /tasks/{id}` |
| 판(배정판) | 집었을 때 프록시 답 / 놓기 | `GET /tasks/{id}/bids`, `POST /tasks/{id}/move` `{dest}` |
| Handoffs | 목록 · 걸러 보기 · 아래 집계 | `GET /handoffs?filter=all|watch|live|done` |
| Handoffs | 자세히 (약속 · 예상 · 앞 단계 · 바뀐 기록 · 오간 말) | `GET /handoffs/{id}` |
| Handoffs | PM 확인에서 규칙 허락 | `POST /asks/{id}/grant` `{key}` 또는 `{index}` |
| Handoffs | 약속 다시 정하기 | `POST /handoffs/{id}/reagree` |

`auto_confirm: true` 는 시연용으로 사람 확인을 서버가 대신 누릅니다(프로토타입과 같은 동작).
`false` 면 가약속에서 멈추고 `pending_confirms` 에 쌓이며, 그동안 새 기록과 PM 조작은 409 로 막힙니다.

## 프로토타입과 다른 점

- 프록시가 답 유형을 직접 고르고, 사람마다 위임 카드가 있습니다. 그래서 확인하는 사람이 프로토타입과 다릅니다: Ivy 는 한도(½일)를 넘어 본인이 확인하고, Sam 은 한도(1일) 안이라 프록시가 알아서 수락합니다.
- 목요일에 Sam 의 프록시는 "넘침" 대신 "버그 고치기를 미루면 가능"이라는 조건을 내고, 이것이 PM 확인의 선택지가 됩니다.
- 사람 확인을 실제로 기다릴 수 있고, 거절도 받습니다. 맡을 사람이 거절하면 다른 답을 다시 보고, 없으면 PM에게 갑니다.
- 남는 일 나누기(`캐릭터 몸`, `상태 머신 연결`)는 가약속 때가 아니라 당사자 확인 뒤에 판에 반영됩니다.
- 버그 고치기를 미루는 허락의 효과 문구가 `Sam 하루 비워짐` 이 아니라 계산값인 `Sam 2일 비워짐` 입니다.
- 시각 표기(`수 09:10` …)는 메시지 하나에 1분씩 가는 시연용 시계입니다.
- `/state` 의 `gate.warnings` 가 제출일을 넘기는 일을 알려 줍니다(프로토타입에는 없음).
# Planbee_DP4
