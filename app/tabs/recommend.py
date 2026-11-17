"""탭 3: 학습 추천 (Q3 왜 이 교육과정을 추천했나)."""
import streamlit as st

from app.common import COMMON_AREA, PENDING, UNCERTAIN, Ctx, load, md_escape, notice
from backend import api

def _render_recommendations(ctx: Ctx):
    missing = ctx.missing
    if not missing:
        st.info("부족한 기술이 없어 추천할 과정이 없습니다.")
        return
    recs, err = load(api.get_recommendations, ctx.job, [r["skill"] for r in missing])
    if err:
        notice("학습 추천", err, "부족한 기술마다 AWS 교육과정과 추천 이유가 여기에 나옵니다.")
        return
    area_of = {r["skill"]: r["area"] for r in missing}
    for rec in recs:
        d = rec["demand"]
        with st.container(border=True):
            st.subheader(rec["gap_skill"])
            st.caption(f"공고 {d['of']}건 중 {d['postings']}건이 요구 · 그중 필수 {d['required_ratio']:.0%}")
            if not rec["courses"] and area_of.get(rec["gap_skill"]) == COMMON_AREA:
                st.markdown(f"여러 영역에 걸친 기술이라 한 영역의 과정으로 잇지 않았습니다. "
                            f"AWS 기초·자격증 과정 연결을 준비하고 있습니다. {PENDING}")
            elif not rec["courses"]:
                st.write("이 기술을 다루는 교육과정을 찾지 못했습니다.")
            for i, c in enumerate(rec["courses"]):
                if i:
                    st.divider()
                info, action = st.columns([3, 1], vertical_alignment="center")
                with info:
                    badge = f" {UNCERTAIN}" if c["match"] == "uncertain" else ""
                    st.markdown(f"**{md_escape(c['title'])}**{badge}")
                    st.caption(f"난이도 {c['level']} · 선수지식 {c['prerequisites']}")
                    st.write(c["reason"])
                    _render_evidence(rec["gap_skill"], c)
                with action:
                    st.link_button("Skill Builder 열기", c["url"], icon=":material/open_in_new:",
                                   type="primary", width="stretch")




FIELD_LABEL = {"objectives": "학습 목표", "title": "과정 제목"}


def _render_evidence(skill: str, course: dict):
    """과정 쪽 근거 문장(③ courses[].evidence). 문장은 backend 가 과정 원문에서 골라 검사한 것만 온다."""
    if "evidence" not in course:  # 근거 필드가 없는 예전 형식의 추천은 아무것도 붙이지 않는다
        return
    ev = course["evidence"]
    name = md_escape(skill)
    if not ev:
        st.caption(f"{UNCERTAIN} 과정의 제목과 학습 목표에서 {name} 관련 문장을 찾지 못했습니다. "
                   f"{name} 내용을 다루는지 확인되지 않은 과정입니다. 링크에서 내용을 확인하세요.")
        return
    if ev["about"] != "skill":  # 다른 기술의 문장을 인용 블록으로 보여 주면 근거처럼 읽힌다. 코드가 아는 사실(이름이 없다)만 먼저 적는다
        area = f"({md_escape(ev['subskill'])})" if ev.get("subskill") else ""
        text = f"과정 제목과 학습 목표에 {name} 이름이 없습니다. 같은 영역{area}의 과정입니다."
        if ev["field"] != "title":  # 제목은 바로 위에 있으니 되풀이하지 않는다
            text += f" 과정이 다루는 내용(영문 원문): “{md_escape(ev['text'])}”"
        st.caption(text)
        return
    if ev["field"] == "title":  # 바로 위에 제목이 있으니 되풀이하지 않는다
        st.caption(f"과정 제목에 {name} 이름이 있습니다.")
        return
    st.caption(f"{name} 관련 근거 · 이 과정의 {FIELD_LABEL.get(ev['field'], ev['field'])}(영문 원문)")
    st.markdown(f"> {md_escape(ev['text'])}")


def render(ctx: Ctx):
    if ctx.gap_err:
        notice("학습 추천", ctx.gap_err, "부족한 기술마다 AWS 교육과정과 추천 이유가 여기에 나옵니다.")
    else:
        _render_recommendations(ctx)
