"""화면 진입점. 지금은 data/sample 의 가짜 데이터가 화면까지 오는지만 확인한다 (M1)."""
import json
from pathlib import Path

import streamlit as st

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def load(name: str) -> dict:
    return json.loads((SAMPLE / name).read_text(encoding="utf-8"))


st.set_page_config(page_title="skillpath-ai", layout="wide")
st.title("skillpath-ai")
st.caption("가짜 데이터로 연결을 확인하는 화면입니다.")

posting = load("posting.json")
extraction = load("extraction.json")
recommendation = load("recommendation.json")

st.subheader("공고")
st.write(posting["text"])

st.subheader("추출 결과")
st.dataframe(extraction["skills"], use_container_width=True)

st.subheader("추천")
st.json(recommendation)
