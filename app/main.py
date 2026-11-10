"""skillpath-ai 화면.

화면 코드만 둔다. 데이터와 계산은 backend.api 의 함수를 호출해서 받는다.
실행: 저장소 루트에서 `streamlit run app/main.py`
"""
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from backend import api  # noqa: E402

JOBS = {"cloud_engineer": "클라우드 엔지니어"}
SAMPLE_POSTING = (
    "클라우드 엔지니어 채용\n"
    "Python을 활용한 개발 경험과 AWS 환경 운영 경험 필수, Docker 사용 경험 우대.\n"
    "Linux 서버 운영 및 트러블슈팅 경험. 쿠버네티스 운영 경험자 우대."
)
UNCERTAIN = ":orange-badge[불확실]"


def md_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#+\-!|~:$])", r"\\\1", text)


st.set_page_config(page_title="skillpath-ai", layout="wide")

# ── 사이드바: 입력 ─────────────────────────────────────────────
with st.sidebar:
    st.header("내 정보")
    job = st.selectbox("목표 직무", options=list(JOBS), format_func=JOBS.get, key="job")
    demand = api.get_demand(job)
    skill_options = [s["skill"] for s in demand["skills"]]
    owned = st.multiselect(
        "보유 기술",
        options=skill_options,
        default=["Python", "Linux", "Git"],
        key="owned",
        help="이미 다룰 수 있는 기술을 고르세요. 부족 역량과 추천이 바로 바뀝니다.",
    )
    st.divider()
    if api.is_mock():
        st.caption("가짜 데이터 모드입니다 (BEDROCK_MOCK=1). 숫자와 과정은 예시입니다.")

gap_rows = api.get_gap(job, owned)
missing = [r for r in gap_rows if not r["owned"]]

st.title("skillpath-ai")
st.caption(
    f"{JOBS[job]} 채용공고 {demand['total_postings']}건을 분석해 부족한 역량과 AWS 교육과정을 근거와 함께 보여줍니다."
)

tab_demand, tab_gap, tab_rec, tab_extract = st.tabs(
    ["시장 수요", "부족 역량", "학습 추천", "공고 직접 분석"]
)

# ── 탭 1: 시장 수요 (Q1 어떤 데이터를 분석했나) ──────────────────
with tab_demand:
    total = demand["total_postings"]
    c1, c2, c3 = st.columns(3)
    c1.metric("분석한 공고", f"{total}건")
    c2.metric("추출한 기술", f"{len(demand['skills'])}개")
    c3.metric("수집일", demand["collected"])
    st.caption(f"출처: {', '.join(demand['sources'])}" + (f" · {demand['note']}" if demand.get("note") else ""))

    df = pd.DataFrame(
        [{"기술": s["skill"], "필수": s["required"], "우대": s["preferred"]} for s in demand["skills"]]
    )
    st.subheader("이 직무가 요구하는 기술")
    st.bar_chart(df, x="기술", y=["필수", "우대"], horizontal=True, sort=False,
                 color=["#1f5fbf", "#9bbbe8"], height=380, x_label="", y_label="요구한 공고 수 (건)")

    st.subheader("근거 보기")
    pick = st.selectbox("기술을 고르면 공고 원문 근거를 보여줍니다", skill_options, key="evidence_skill")
    s = next(x for x in demand["skills"] if x["skill"] == pick)
    st.write(f"**{pick}**: 공고 {total}건 중 {s['postings']}건 (필수 {s['required']}건, 우대 {s['preferred']}건)")
    for ev in s["evidence_samples"]:
        st.markdown(f"> {md_escape(ev['evidence'])}  \n> `{ev['posting_id']}`")

# ── 탭 2: 부족 역량 (Q2 어떤 근거로 필요하다 판단했나) ─────────────
with tab_gap:
    have = [r for r in gap_rows if r["owned"]]
    c1, c2 = st.columns(2)
    c1.metric("주요 요구 기술", f"{len(gap_rows)}개", help="공고의 20% 이상이 요구한 기술")
    c2.metric("그중 보유", f"{len(have)}개")

    if not missing:
        st.success("주요 요구 기술을 모두 보유했습니다.")
    else:
        st.subheader(f"부족한 기술 {len(missing)}개 (수요 높은 순)")
        st.dataframe(
            pd.DataFrame([
                {
                    "기술": r["skill"],
                    "요구 공고": f"{r['postings']} / {r['of']}",
                    "요구 비율": r["ratio"],
                    "그중 필수": r["required_ratio"],
                }
                for r in missing
            ]),
            hide_index=True,
            width="stretch",
            column_config={
                "요구 비율": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "그중 필수": st.column_config.NumberColumn(format="percent"),
            },
        )
    if have:
        st.caption("이미 보유: " + ", ".join(r["skill"] for r in have))

# ── 탭 3: 학습 추천 (Q3 왜 이 교육과정을 추천했나) ────────────────
with tab_rec:
    if not missing:
        st.info("부족한 기술이 없어 추천할 과정이 없습니다.")
    for rec in api.get_recommendations(job, [r["skill"] for r in missing]):
        d = rec["demand"]
        with st.container(border=True):
            st.subheader(rec["gap_skill"])
            st.caption(f"공고 {d['of']}건 중 {d['postings']}건이 요구 · 그중 필수 {d['required_ratio']:.0%}")
            if not rec["courses"]:
                st.write("이 기술을 다루는 교육과정을 찾지 못했습니다.")
            for c in rec["courses"]:
                badge = f" {UNCERTAIN}" if c["match"] == "uncertain" else ""
                st.markdown(f"**[{md_escape(c['title'])}]({c['url']})**{badge}")
                st.caption(f"난이도 {c['level']} · 선수지식 {c['prerequisites']}")
                st.write(c["reason"])

# ── 탭 4: 공고 직접 분석 (라이브 시연용) ──────────────────────────
with tab_extract:
    st.write("채용공고 본문을 붙여 넣으면 요구 기술과 근거 문장을 뽑습니다.")
    text = st.text_area("공고 본문", value=SAMPLE_POSTING, height=160, key="posting_text")
    if st.button("분석하기", type="primary", key="extract_btn") and text.strip():
        st.session_state["extraction"] = api.extract_posting(text)
        st.session_state["extracted_text"] = text
    result = st.session_state.get("extraction")
    if result and st.session_state.get("extracted_text") == text:
        skills = result["skills"]
        if not skills:
            st.warning("알아볼 수 있는 기술을 찾지 못했습니다.")
        else:
            highlighted = md_escape(text)
            for sk in skills:
                ev = md_escape(sk["evidence"])
                highlighted = highlighted.replace(ev, f":blue-background[{ev}]", 1)
            st.subheader("근거 표시")
            st.markdown(highlighted.replace("\n", "  \n"))
            st.subheader("추출 결과")
            st.dataframe(
                pd.DataFrame([
                    {
                        "기술": sk["normalized"],
                        "공고 표현": sk["raw"],
                        "구분": "필수" if sk["type"] == "required" else "우대",
                        "근거 문장": sk["evidence"],
                        "확신": "높음" if sk["confidence"] == "high" else "불확실",
                    }
                    for sk in skills
                ]),
                hide_index=True,
                width="stretch",
            )
