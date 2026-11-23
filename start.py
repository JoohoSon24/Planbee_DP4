"""Start the interactive Plan Bee demo dashboard and open it in a browser."""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit(
            f"Python 3.10 이상이 필요합니다. 현재 버전은 {sys.version.split()[0]}입니다. "
            "이 프로젝트 환경에서는 `python3.13 -m pip install -r requirements.txt`와 "
            "`python3.13 start.py`를 사용하세요."
        )

    parser = argparse.ArgumentParser(description="Plan Bee 데모 화면 실행")
    parser.add_argument("--host", default="127.0.0.1", help="접속 주소 (기본: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="포트 (기본: 8000)")
    parser.add_argument("--demo", help="처음 열 시나리오 (생략하면 m4_t1_rescheduling)")
    parser.add_argument("--llm", choices=("mock", "live"), help="프록시 모드 (기본: 기존 환경값 또는 mock)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    parser.add_argument('--negotiation-mode', choices=('candidate_discussion','legacy'),default='candidate_discussion',help='기본: 후보 생성·토론·PM 최종 선택')
    args = parser.parse_args()

    # app/__init__.py loads .env with setdefault. Set the default before importing
    # the app so a .env value cannot silently turn the reproducible demo into Live.
    os.environ["PLANBEE_LLM"] = args.llm or os.environ.get("PLANBEE_LLM", "mock")
    os.environ['PLANBEE_NEGOTIATION_MODE'] = args.negotiation_mode
    # Members' confirmations are settled by their proxies; only the PM decides by hand (set 0 to require clicks).
    os.environ.setdefault('PLANBEE_AUTO_CONFIRM', '1')
    os.environ.setdefault('PLANBEE_RUNS_DIR', str(ROOT / 'runs' / 'v2'))

    # Imports are delayed so a missing dependency can show a useful setup command.
    try:
        import uvicorn
        from app import store
    except ImportError as exc:
        raise SystemExit(
            f"필요한 패키지가 없습니다 ({exc.name}). 먼저 실행하세요: python3 -m pip install -r requirements.txt"
        ) from exc

    available = store.service_demos() if args.negotiation_mode=='candidate_discussion' else store.demos()
    demo = args.demo or os.environ.get("PLANBEE_DEMO", store.DEFAULT_DEMO if args.negotiation_mode=='candidate_discussion' else 'demo1')
    if demo not in available:
        raise SystemExit(f"알 수 없는 데모: {demo}\n선택 가능: {', '.join(available)}")

    os.environ["PLANBEE_DEMO"] = demo
    store.use_demo(demo)
    # Keep interactive experiments away from the named demo databases.
    playground='planbee_v2_playground.db' if args.negotiation_mode=='candidate_discussion' else 'planbee_playground.db'
    os.environ.setdefault("PLANBEE_DB", f"sqlite:///{ROOT / playground}")

    url = f"http://{args.host}:{args.port}"
    print(f"Plan Bee 대시보드: {url}")
    print(f"시작 데모: {demo} | LLM: {os.environ['PLANBEE_LLM']}")
    print("화면에서 데모와 배정 기준(fast / learn / fair)을 바꿀 수 있습니다. 종료: Ctrl+C")

    if not args.no_browser:
        def open_browser() -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    urllib.request.urlopen(url, timeout=0.5).close()
                    webbrowser.open(url)
                    return
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)

        threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run("app.api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
