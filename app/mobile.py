"""폰 화면 폭 맞춤 (2026-11-16 결정). Streamlit 을 그대로 쓰고 좁은 화면에서만 모양을 조정한다. 앱을 따로 만들지 않는다.

Streamlit 은 640px 아래에서 칸(columns)을 세로로 쌓는다. 숫자 카드 네 개가 한 줄씩 차지해 첫 화면이 카드로만 차므로
좁은 화면에서는 두 칸씩 놓는다. 제목 크기를 줄이고, 보유 기술 입력이 접힌 사이드바 안에 있다는 안내를 보여준다.

주의: 아래 선택자는 Streamlit 이 만든 요소 이름(data-testid)에 기대고 있다. Streamlit 을 올리면 폰 화면을 다시 확인한다.
선택자가 맞지 않게 되어도 화면이 깨지지는 않고 조정이 풀릴 뿐이다.
"""
import streamlit as st

NARROW = "640px"  # Streamlit 이 칸을 세로로 쌓기 시작하는 폭
CSS = f"""
<style>
.narrow-only {{ display: none; }}
@media (max-width: {NARROW}) {{
  .narrow-only {{ display: block; }}
  h1 {{ font-size: 1.7rem !important; line-height: 1.25 !important; padding-top: 0.5rem !important; }}
  h2 {{ font-size: 1.3rem !important; }}
  h3 {{ font-size: 1.1rem !important; }}
  [data-testid="stMainBlockContainer"] {{ padding-left: 0.75rem; padding-right: 0.75rem; padding-top: 3rem; }}
  /* 숫자 카드가 든 줄은 두 칸씩 놓는다 */
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {{ flex-wrap: wrap; gap: 0.5rem; }}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {{
    flex: 1 1 calc(50% - 0.5rem) !important; min-width: calc(50% - 0.5rem) !important; width: calc(50% - 0.5rem) !important;
  }}
  [data-testid="stMetricValue"] {{ font-size: 1.5rem !important; }}
  /* 탭 이름이 많아지면 옆으로 밀어 볼 수 있게 한다 */
  [data-baseweb="tab-list"] {{ overflow-x: auto; scrollbar-width: none; }}
  [data-baseweb="tab"] {{ white-space: nowrap; }}
}}
</style>
"""
HINT = """
<div class="narrow-only" style="background:#EEF3FB;border-radius:8px;padding:8px 12px;font-size:0.9rem;color:#1F3F7A;">
보유 기술은 화면 왼쪽 위의 <b>»</b> 를 눌러 고릅니다. 고르면 아래 결과가 바로 바뀝니다.
</div>
"""


def inject_css():
    st.html(CSS)


def sidebar_hint():
    """좁은 화면에서만 보이는 안내. 사이드바가 접혀 있어 입력을 못 찾는 일을 막는다."""
    st.html(HINT)
