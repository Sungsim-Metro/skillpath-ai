"""화면이 가짜 모드에서 뜨는지 본다. 리뷰 봇이 읽을 결과만 출력하고, 예외가 있으면 종료 코드 1."""
import os
import sys

os.environ.setdefault("BEDROCK_MOCK", "1")

from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file(os.path.abspath("app/main.py"), default_timeout=90).run()


def texts(elements) -> list[str]:
    return [str(getattr(e, "value", e))[:300] for e in elements]


print("탭:", [t.label for t in at.tabs])
print("예외:", texts(at.exception) or "없음")
print("st.error:", texts(at.error) or "없음")
print("st.warning:", texts(at.warning) or "없음")
sys.exit(1 if at.exception else 0)
