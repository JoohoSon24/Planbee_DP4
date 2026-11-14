# Plan Bee 백엔드 구조

CS473 Team Plan Bee · DP3 Lo-fi · 2026-11-14 기준 · 대상 화면: "Handoffs 세 화면" 프로토타입

이 문서는 `planbee-backend` 코드가 무엇으로 만들어졌고, 데이터가 어디에 저장되며, AI가 어느 단계에서 무슨 일을 하는지 정리한 것입니다.

## 1. 한눈에 보기

| 층 | 하는 일 | 쓰는 것 | 파일 |
|---|---|---|---|
| 화면 | 세 화면(입력 · 판 · Handoffs)을 그리고 버튼을 서버로 보냄 | HTML + JavaScript (프레임워크 없음) | `web/index.html` |
| API | 화면의 요청을 받아 아래 층을 부르고 결과를 JSON으로 돌려줌 | FastAPI, uvicorn | `app/api.py` |
| 협상 워크플로 | 기록 하나가 들어온 뒤 해결될 때까지의 단계를 순서대로 돌림 | LangGraph | `app/workflow.py` |
| 프록시 (AI) | 견적 고치기, 떼어 낼 조각 정하기, 요청에 수락 · 거절 · 조건부 · 본인 확인 필요로 답하기 | Mock 대본 또는 OpenRouter | `app/llm.py` |
| Hive (규칙 코드) | 일정 계산, 늦어질 Handoff 찾기, 프록시 답 검사, 라운드 진행 | 순수 Python | `app/hive.py` |
| 저장 | 사람 · 일 · Handoff · 오간 말 · 확인을 표에 보관 | SQLite, SQLAlchemy | `app/models.py`, `app/store.py` |

요청 한 번이 지나가는 길은 아래와 같습니다.

```
1. 브라우저 (web/index.html)      버튼을 누르면 POST /demo/advance 같은 요청을 보냄
2. uvicorn -> FastAPI (api.py)    요청을 받아 해당 함수를 실행
3. LangGraph 그래프 (workflow.py) 협상 단계를 순서대로 돌림
     - 프록시가 쓴다   -> llm.py   (Mock 대본 또는 실제 LLM)
     - Hive가 판단한다 -> hive.py  (LLM 없음)
     - 읽고 쓴다       -> SQLite   (planbee.db)
4. 바뀐 전체 상태를 JSON으로 응답 -> 화면이 다시 그림
```

## 2. uvicorn이 뭔가요

uvicorn은 **파이썬 웹 서버 프로그램**입니다. FastAPI로 쓴 코드는 "이 주소로 요청이 오면 이 함수를 실행하라"는 설명서일 뿐이라, 혼자서는 인터넷 요청을 받지 못합니다. uvicorn이 컴퓨터의 포트(기본 8000번)를 열고 기다리다가, 브라우저가 보낸 요청을 받아 FastAPI에 넘기고 결과를 되돌려 줍니다.

식당에 비유하면 FastAPI는 주방(주문별 조리법), uvicorn은 문을 열고 주문을 받아 주방에 전달하는 홀 직원입니다.

```bash
uvicorn app.api:app --reload
```

| 부분 | 뜻 |
|---|---|
| `app.api` | `app/api.py` 파일 |
| `:app` | 그 파일 안의 `app` 이라는 FastAPI 객체 |
| `--reload` | 코드를 저장하면 서버가 자동으로 다시 시작됨 (개발할 때만 사용) |

실행한 터미널을 닫거나 Ctrl+C를 누르면 서버가 꺼집니다. 켜져 있는 동안 `http://localhost:8000` 은 화면, `http://localhost:8000/docs` 는 API 문서입니다.

## 3. 기술 스택

| 분류 | 기술 | 버전 (개발 환경) | 고른 이유 |
|---|---|---|---|
| 언어 | Python | 3.13 | LangGraph 등 AI 도구가 파이썬 중심 |
| 웹 프레임워크 | FastAPI | 0.162 | 코드만 쓰면 API 문서(`/docs`)가 자동으로 생김 |
| 웹 서버 | uvicorn | | FastAPI의 표준 실행 방법 |
| DB | SQLite | | 파일 하나(`planbee.db`)라 설치가 필요 없음 |
| DB 접근 | SQLAlchemy | 2.1 | 주소만 바꾸면 Postgres로 옮길 수 있음 |
| 워크플로 | LangGraph | 1.2 | DP2 리포트에서 정한 구조 (LLM이 쓰고, Python이 판단하고, LangGraph가 돌림) |
| 모양 검사 | pydantic | 2.13 | LLM 답과 API 요청의 형식을 강제 |
| LLM | OpenRouter (선택) | | `PLANBEE_LLM=live` 일 때만 사용. 기본은 Mock. 모델은 `PLANBEE_MODEL` 로 고름 |
| 시드 | YAML | | 사람이 읽고 고치기 쉬움 |
| 테스트 | pytest | | 시나리오 17개 + Hive 단위 6개 + Live 형식 3개 |
| 화면 | HTML, CSS, JavaScript | | 프로토타입 파일을 그대로 사용 |

환경 변수로 바꾸는 것: `PLANBEE_DB` (DB 주소), `PLANBEE_LLM` (`mock` 또는 `live`), `PLANBEE_MODEL`, `OPENROUTER_API_KEY`. 폴더에 `.env` 파일을 두면 자동으로 읽습니다.

실제 LLM 모드(`live`)는 요청·응답 형식만 가짜 서버로 테스트했고, OpenRouter에 실제로 연결해 본 적은 아직 없습니다.

## 4. DB 구조

표는 14개이고, 프로토타입 화면이 들고 있던 상태 `S` 를 그대로 나눠 담았습니다.

### 4-1. 판 (계획)

| 표 | 한 행이 뜻하는 것 | 주요 칸 |
|---|---|---|
| `person` | 팀원 한 명 (프록시는 사람과 1:1이라 이 행을 근거로 씀) | `role` 역할, `rec` 태그별 과거 작업 건수, `wants` 해 보고 싶은 일 |
| `card` | 위임 카드. 사람이 자기 프록시에게 맡긴 한도 | `auto_days` 이 일수까지는 알아서 수락, `refuse_tags` 받지 않는 일, `gives_help` 도움 요청을 받는가, `note` |
| `task` | 일 하나 (판의 막대) | `who` 담당, `s0` 계획 시작, `s` 실제 시작, `d` 현재 견적, `plan` 처음 계획, `tag`, `kind`, `cut`, `cut_options` |
| `handoff` | 넘겨주기 하나 (판의 화살표) | `from_task` → `to_task`, `t` 약속 시각, `done`, `prop` 가약속, `agreed` 다시 정함, `basis` |
| `handoff_event` | Handoff의 바뀐 기록 한 줄 | `t`, `kind` (hive · proxy · pm · person), `text` |

시간은 '일' 단위 숫자입니다. 0 = 월 아침, 3 = 수 저녁, 4.5 = 금 오전, 5 = 금 저녁(제출).

Handoff의 상태는 저장하지 않고 매번 계산합니다. 주는 일이 끝나는 시각이 약속보다 늦으면 At risk입니다.

### 4-2. 입력과 규칙

| 표 | 한 행이 뜻하는 것 | 주요 칸 |
|---|---|---|
| `record` | 들어온 기록 한 줄 | `src` (작업 · 저장소 · 메신저 · PM), `who`, `text` |
| `rule` | PM이 정한 규칙 | `deadline` 제출일, `weekly_cap` 한 주 5일, `pm_only` 범위·미루기는 PM만, `rounds` 프록시끼리 3라운드까지, `pref` 받을 사람 기준 |
| `grant` | PM이 한 번 허락한 예외 | `label`, `key` |

### 4-3. 협상

| 표 | 한 행이 뜻하는 것 | 주요 칸 |
|---|---|---|
| `message` | 오간 말 한 줄 | `k` (proxy · hive · person · pm), `frm` → `to`, `act` (견적 · 조건 · 질문 · 약속 · 알림 · 넘김), `fields`, `basis`, `hid` |
| `confirmation` | 사람에게 가는 원터치 확인 | `who`, `prompt` 질문, `status` (pending · confirmed · rejected), `run_id` |
| `ask` | 규칙 안에서 못 풀어 PM에게 간 확인 | `hid`, `why` 이유, `grants` 고를 수 있는 허락, `open` |
| `resolution` | 해결됨 카드 | `hid`, `body`, `why` |
| `run` | 협상 한 건의 진행 상태 | `step` 지금 단계, `status` (running · waiting_confirm · waiting_pm · done), `ctx` |

### 4-4. 기타

| 표 | 용도 |
|---|---|
| `meta` | 현재 시점(`now`), 시연 단계(`phase`), 안내 문구, PM 결정 횟수 |
| `snapshot` | 되돌리기용. PM이 무언가를 정하기 직전의 전체 상태 |

### 4-5. 더미 데이터 (`seed/`)

| 파일 | 내용 |
|---|---|
| `team.yaml` | 사람 6명과 위임 카드 6장, 일 14개, Handoff 4개, 지난 기록 3줄, 규칙 5개 |
| `feed.yaml` | 시연 버튼이 넣는 수요일 · 목요일 기록 |
| `mock_llm.yaml` | Mock LLM 대본. 어떤 기록에 견적이 어떻게 바뀌는지, 무슨 조각을 떼는지, 누가 며칠이라고 답하는지 |

`python seed.py` 또는 화면의 "처음부터" 버튼이 DB를 비우고 이 파일들로 다시 채웁니다.

## 5. AI 파이프라인

### 5-1. 누가 무엇을 정하는가

프록시는 사람마다 하나씩 있고, **자기 사람의 기록 · 일정 · 위임 카드만 보고 답을 고릅니다.** Hive 는 그 답이 규칙 안인지만 검사합니다. 전체 판을 한꺼번에 보는 LLM 은 없습니다.

| 주체 | 하는 일 | LLM 사용 |
|---|---|---|
| 프록시 (사람마다 하나) | 새 기록을 읽고 견적 고치기 · 늦어질 일에서 떼어 낼 조각 정하기 · 요청에 답 유형과 조건을 골라 답하기 | 예 |
| Hive | 일정 다시 계산 · 늦어질 Handoff 찾기 · 프록시 답 검사 · 라운드 진행 · 받을 수 있는 사람 중 PM 규칙으로 한 명 고르기 | 아니오 |
| 사람 | 위임 카드로 한도를 정함. 한도를 넘는 일과 자기 일을 넘기는 것만 확인 또는 거절 | |
| PM | 규칙 하나 허락 · 약속 다시 정하기 · 일 옮기기 | |

### 5-2. 프록시의 답 네 가지

| 답 | 뜻 | 그다음 |
|---|---|---|
| `ACCEPT` | 카드 한도 안이고 일정에 들어감. 프록시가 알아서 맡음 | 받을 수 있는 사람이 됨 |
| `NEEDS_INPUT` | 들어가지만 카드의 `auto_days` 를 넘음 | 이 사람이 뽑히면 본인에게 먼저 물음 |
| `COUNTER` + `help` | 누가 30분 봐 주면 가능 | 다음 라운드에 그 사람의 프록시에게 물음 |
| `COUNTER` + `defer` | 내 일 하나를 2주차로 미루면 가능 | 미루기는 PM 전용이라 PM 확인의 선택지가 됨 |
| `REJECT` | 맡을 수 없음. 이유를 한 줄로 씀 | 이유가 PM 에게 그대로 보임 |

Hive 의 검사(`hive.check_reply`)는 답을 바꾸지 않고 어긋난 것만 찾습니다. 수락했는데 5일을 넘으면 `OVERLOAD`, 조건이 말이 안 되면 `BAD_CONDITION` 을 이유와 함께 프록시에게 돌려보내고, 다시 어긋나면 거절로 적습니다. 반려는 라운드를 쓰지 않습니다. 카드 한도는 코드가 지켜서, 프록시가 `ACCEPT` 라고 해도 한도를 넘으면 본인에게 묻습니다.

### 5-3. 기록 하나가 지나가는 단계

```
기본 경로            ingest -> help -> bids <-> tally -> propose -> confirm -> commit -> finish
한도를 넘으면        tally -> person (본인 확인) -> propose
받을 사람이 없으면   tally -> ask (PM 대기) -> granted
  미루기를 허락하면  granted -> bids (라운드를 새로 셈)
  범위를 줄이면      granted -> cutconfirm -> finish
도움을 받아도 늦으면 commit -> reconfirm -> finish
```

| 단계 | 하는 일 | 주체 |
|---|---|---|
| `ingest` | 새 기록을 읽고 견적을 고침. 일정을 다시 계산해 늦어질 Handoff를 알림 | 프록시 + Hive |
| `help` | 도움 요청을 열고, 담당 프록시가 떼어 낼 조각을 정함 | Hive + 프록시 |
| `bids` | 한 번이 한 라운드. 1라운드는 같은 역할의 프록시들에게 조각을 물음. 다음 라운드는 조건부 답의 `help` 조건을 상대 프록시에게 확인 | 프록시 + Hive(검사) |
| `tally` | 확인할 조건과 라운드가 남았으면 `bids` 로. 받을 수 있는 사람이 있으면 PM 규칙으로 고름. 없으면 `ask` 로 | Hive |
| `person` | 뽑힌 사람의 일수가 카드 한도를 넘으면 본인 답을 기다림. 거절하면 다른 답을 다시 봄 | 사람 |
| `propose` | 가약속을 판에 올리고 규칙 확인. 조각을 넘기는 담당에게 확인을 보냄 | Hive |
| `confirm` | 담당의 확인을 기다림 | 사람 |
| `commit` | 가약속을 굳히고 담당에게 남는 일을 다시 나눔. 그래도 늦으면 받는 사람에게 새 약속을 확인(`reconfirm`) | Hive |
| `ask` | 프록시들이 쓴 이유와, `defer` 조건에서 나온 허락 목록을 PM 에게 올리고 멈춤 | Hive |
| `granted` | PM 이 고른 허락을 적용 | Hive |
| `finish` | 다시 제때가 된 Handoff를 알리고 해결됨 카드를 남김 | Hive |

라운드는 규칙 `rounds`(기본 3)까지입니다. 그 안에 조건을 다 확인하지 못하면 남은 항목과 함께 PM 에게 갑니다. 사람 확인이나 PM 허락을 기다릴 때는 `run.status` 를 `waiting_confirm` 또는 `waiting_pm` 으로 두고 멈췄다가, 답이 오면 같은 `run` 을 멈춘 단계부터 다시 돌립니다.

시드 데이터로 돌린 목요일 예: 1라운드에 Sam 의 프록시는 "버그 고치기를 미루면 가능"(`defer`), Ben 의 프록시는 "Sam 이 30분 봐 주면 가능"(`help`)으로 답합니다. 2라운드에 Ben 의 조건을 Sam 에게 물으면 Sam 은 다시 `defer` 로 답합니다. 프록시끼리 풀 수 있는 조건이 남지 않아 PM 에게 가고, 선택지는 Sam 의 프록시가 낸 "버그 고치기 미루기"와 범위 줄이기입니다.

### 5-4. 규칙 확인 (code gate)

`hive.gate()` 는 통과/실패만이 아니라 무엇이 어긋났는지를 코드와 수치로 돌려줍니다.

| 코드 | 뜻 | 종류 |
|---|---|---|
| `OVERLOAD` | 한 사람의 이번 주 일이 5일을 넘음 | 위반 |
| `HANDOFF_LATE` | 주는 일이 약속 시각보다 늦게 끝남 | 위반 |
| `DEADLINE_SPILL` | 일이 제출일을 걸쳐서 끝남 | 경고 |
| `PUSHED_PAST_DEADLINE` | 일이 제출일 뒤로 통째로 밀림 | 경고 |

### 5-5. Mock과 Live

| | Mock (기본) | Live |
|---|---|---|
| 답의 출처 | 일수와 조각은 `seed/mock_llm.yaml` 대본. 답 유형은 `MockLLM.reply()` 의 규칙(카드 · 일정 · 기록 건수로 고름) | OpenRouter (모델 선택 가능). 실패하면 Mock 의 규칙으로 답함 |
| 결과 | 매번 같음 (시연과 테스트용) | 실행마다 달라질 수 있음 |
| 안전장치 | | 형식은 pydantic으로 강제, 답은 Hive 가 검사해 어긋나면 반려, 일수는 코드가 범위를 자름 |
| 검증 | 시나리오·단위 테스트 통과, 화면에서 전체 흐름 확인 | 형식만 테스트, 실제 연결은 아직 |

## 6. API 요약

모든 POST는 바뀐 전체 상태(`GET /state` 와 같은 모양)를 돌려줍니다.

| 화면 | 메서드와 경로 | 용도 |
|---|---|---|
| 공통 | `GET /state` | 세 화면을 그리는 데 필요한 전부 |
| 공통 | `POST /demo/advance` | 시연: 다음 날 기록 받기 |
| 공통 | `POST /undo`, `POST /reset` | 되돌리기, 처음부터 |
| 입력 | `GET /records`, `POST /records` | 들어온 기록 보기, 새 기록 넣기 |
| 입력 | `GET /rules`, `PUT /rules/pref` | 규칙 보기, 받을 사람 기준 바꾸기 |
| 입력 | `GET /cards`, `PUT /people/{id}/card` | 위임 카드 보기, 고치기 |
| 입력 | `PUT /rules/rounds` | 프록시끼리 주고받는 라운드 수 |
| 입력 | `GET /confirmations`, `POST /confirmations/{id}` | 팀원 확인 목록, 확인 또는 거절 |
| 판 | `GET /board`, `GET /log`, `GET /tasks/{id}` | 판, 오간 말, 일 자세히 |
| 판 | `GET /tasks/{id}/bids`, `POST /tasks/{id}/move` | 옮기면 누가 받을 수 있나, 옮기기 |
| Handoffs | `GET /handoffs`, `GET /handoffs/{id}` | 목록과 걸러 보기, 자세히 |
| Handoffs | `POST /handoffs/{id}/reagree` | 약속 다시 정하기 |
| Handoffs | `GET /asks`, `POST /asks/{id}/grant` | PM 확인 목록, 규칙 허락 |

## 7. 아직 정해지지 않은 것

- **"배우고 싶은 사람" 경로가 제출일을 넘깁니다.** Ben이 맡으면 캐릭터 테스트가 2주차로 밀립니다. 지금은 경고만 띄우며, 규칙 위반으로 막을지 정해야 합니다.
- **Ivy의 무기 그림 1일은 대본 값입니다.** 기록 건수 공식으로는 1½일이 나와 수요일 약속이 깨집니다. 실제 LLM을 붙이면 달라질 수 있습니다.
- **실제 LLM은 OpenRouter로 붙였지만 실제 연결은 아직 확인하지 못했습니다.** 기본 모델 `openai/gpt-4o-mini` 가 지금도 제공되는지도 확인이 필요합니다.
- **배포는 하지 않았습니다.** 화면은 Vercel, 서버는 Render나 Railway로 나누는 것을 가정하고 있습니다.
