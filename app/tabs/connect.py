"""현직자 연결 카드: 부족 영역에 맞는 AWS 사용자 모임 소모임, 커피챗 요청 메시지 초안, 사람 찾기 검색 링크.

부족 역량 탭 맨 아래의 한 구역이다. 사람을 조회하거나 추천하지 않는다. 모임은 사람이 고른 목록에서 코드가 고르고,
사람 찾기는 검색 주소만 만들어 사용자가 직접 누른다. 메시지 초안은 버튼을 눌렀을 때만 만든다(호출 1번).
"""
import streamlit as st

from app.common import Ctx, load, md_escape, notice
from ai import coffeechat
from backend import api, communities
from backend.jobs import JOBS


def _community_line(c: dict, areas: list[str] | None = None) -> str:
    why = f" · 부족 영역: {', '.join(areas)}" if areas else ""
    note = f" · {c['note']}" if c.get("note") else ""
    return f"- **{md_escape(c['name'])}** · {c['place']}{why}  \n  :gray[최근 확인한 일정: {c['last_seen']}{md_escape(note)}]"


def render_connect(ctx: Ctx):
    if not ctx.missing:
        st.info("부족한 기술이 없어 연결할 모임을 따로 고르지 않았습니다.")
        return
    owned = getattr(ctx, "levels", None) or ctx.owned
    rows, err = load(api.get_area_gap, ctx.job, owned)
    if err:
        notice("현직자 연결", err)
        return
    found, err = load(communities.suggest, rows)
    if err:
        notice("현직자 연결", err)
        return
    meta = found["meta"]
    missing_skills = [r["skill"] for r in ctx.missing]

    st.markdown("**① 부족한 영역을 다루는 AWS 사용자 모임(AWSKRUG) 소모임**")
    if found["topic"]:
        st.markdown("\n".join(_community_line(t["community"], t["areas"]) for t in found["topic"]))
    else:
        st.write("부족한 영역에 맞는 주제 소모임을 확인하지 못했습니다.")
    with st.expander("처음이거나 지역이 다르면"):
        st.markdown("\n".join(_community_line(c) for c in [*found["general"], *found["region"]]))
    left, right = st.columns(2)
    left.link_button("모임 일정 보기 (Meetup)", found["topic"][0]["community"]["link"] if found["topic"] else found["general"][0]["link"],
                     icon=":material/open_in_new:", width="stretch")
    right.link_button("AWSKRUG Slack", meta["join"]["slack"], icon=":material/open_in_new:", width="stretch")
    st.caption(
        f"{meta['join']['text']} 목록은 사람이 고른 것이고 {meta['checked']}에 확인했습니다. {meta['limits']}"
        + (f" 이번 진단에서 맞는 소모임이 없던 영역: {', '.join(found['unmatched'])}." if found["unmatched"] else "")
    )

    st.markdown("**② 커피챗 요청 메시지 초안과 물어볼 질문**")
    st.caption("부족한 기술을 바탕으로 AI가 초안을 씁니다. 받는 분과 내 정보는 빈칸으로 두니 직접 채워서 보내세요.")
    key = (ctx.job, tuple(missing_skills[:coffeechat.MAX_SKILLS]), tuple(ctx.owned[:coffeechat.MAX_SKILLS]))
    if st.button("초안 만들기", key="coffeechat_btn"):
        result, err = load(coffeechat.draft, JOBS[ctx.job], missing_skills, list(ctx.owned))
        if err:
            notice("메시지 초안", err)
        st.session_state["coffeechat"] = (key, result[0] if result else None)
    saved = st.session_state.get("coffeechat")
    if saved and saved[1]:
        if saved[0] != key:
            st.caption("보유 기술이 바뀌었습니다. 초안을 다시 만들면 지금 진단에 맞게 바뀝니다.")
        st.text_area("메시지 초안 (복사해서 고쳐 쓰세요)", value=saved[1]["message"], height=220, key="coffeechat_text")
        st.markdown("\n".join(f"{i}. {md_escape(q)}" for i, q in enumerate(saved[1]["questions"], start=1)))

    st.markdown("**③ 직접 찾아보기**")
    st.caption("검색 주소만 만들어 드립니다. 이 서비스는 사람 정보를 가져오거나 저장하지 않습니다.")
    for link in communities.people_search_links(JOBS[ctx.job], missing_skills):
        st.link_button(link["label"], link["url"], icon=":material/search:")
