"""화면이 가짜 모드에서 뜨는지 본다. 리뷰 봇이 읽을 결과만 출력하고, 예외가 있으면 종료 코드 1.

화면을 사이드바 메뉴에서 하나씩 열기 때문에(2026-11-20) 메뉴의 화면을 차례로 실행한다.
"""
import os
import sys

os.environ.setdefault("BEDROCK_MOCK", "1")

from streamlit.testing.v1 import AppTest  # noqa: E402

MAIN = os.path.abspath("app/main.py")


def texts(elements) -> list[str]:
    return [str(getattr(e, "value", e))[:300] for e in elements]


def open_view(view: str | None) -> AppTest:
    at = AppTest.from_file(MAIN, default_timeout=90)
    at.session_state["entered"] = True  # 로그인·회원가입 화면을 비회원으로 지난 상태로 메뉴의 화면을 본다
    if view:
        at.query_params["view"] = view
    return at.run()


first = open_view(None)
menu = first.sidebar.radio(key="view")
print("메뉴:", list(menu.options))
failed = False
for view in ("chat", "demand", "gap", "recommend", "saved", "connect", "report"):
    at = first if view == "chat" else open_view(view)
    print(f"[{view}] 예외:", texts(at.exception) or "없음")
    print(f"[{view}] st.error:", texts(at.error) or "없음")
    print(f"[{view}] st.warning:", texts(at.warning) or "없음")
    failed = failed or bool(at.exception)
sys.exit(1 if failed else 0)
