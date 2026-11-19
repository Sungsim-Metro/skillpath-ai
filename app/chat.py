"""학습 상담 화면과 세션 안에서만 유지하는 대화 표시 기록.

답마다 좋아요·별로예요 평가를 받고, 과정 추천이 두 가지 방식으로 왔으면 A/B 로 나란히 보여 주고 선택을 받는다
(비교 실험, backend/experiments.py). 어떤 모델·구조인지는 화면에 보여 주지 않는다. 기록에는 내용을 넣지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlsplit

import streamlit as st

from ai.usage import SessionUsage
from backend import chat_history, chat_profiles
from pipeline.aliases import skill_aliases


@lru_cache(maxsize=1)
def skill_options() -> tuple[str, ...]:
    """채팅 입장 시 수요 조회 없이 고를 수 있는 기술 대표 이름."""
    return tuple(skill_aliases())


def _clear_private_state() -> None:
    """Clear account data and widget drafts before the next screen renders."""
    for key in list(st.session_state):
        if key != "view":
            del st.session_state[key]


def _authenticate(register: bool) -> None:
    nickname = st.session_state.auth_nickname
    password = st.session_state.auth_password
    st.session_state.auth_password = ""
    authenticate = chat_profiles.create_profile if register else chat_profiles.sign_in
    try:
        session = authenticate(nickname, password)
    except chat_profiles.ProfileAuthError as exc:
        st.session_state.auth_error = str(exc)
    except Exception:
        st.session_state.auth_error = "프로필에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
    else:
        st.session_state.pop("auth_error", None)
        st.session_state.profile_session = session


def profile_access() -> chat_profiles.ProfileSession | None:
    """Authenticate a profile without sending credentials to the chat."""
    if st.session_state.pop("chat_identity", ""):
        # Open sessions from the nickname-only UI must authenticate again.
        _clear_private_state()
    session = st.session_state.get("profile_session")
    if session is not None:
        st.text(f"로그인한 프로필 · {session.nickname}")
        st.button("로그아웃", key="auth_logout", on_click=_clear_private_state)
        return session

    with st.form("profile_access"):
        st.text_input("닉네임", key="auth_nickname")
        st.text_input("비밀번호", type="password", key="auth_password",
                      help="앞뒤 공백도 비밀번호에 포함됩니다.")
        login, register = st.columns(2)
        login.form_submit_button("로그인", key="auth_login", on_click=_authenticate, args=(False,))
        register.form_submit_button("새 프로필 만들기", key="auth_register", on_click=_authenticate, args=(True,))
    if error := st.session_state.get("auth_error"):
        st.error(error)
    return None


def _render_course(course: dict) -> None:
    with st.container(border=True):
        st.text(course["title"])
        details = [course["gap_skill"]] if course.get("gap_skill") else []
        details.append("매칭 불확실" if course["match"] == "uncertain" else "매칭 확실")
        if course.get("level"):
            details.append(f"난이도 {course['level']}")
        if course.get("prerequisites"):
            details.append(f"선수지식 {course['prerequisites']}")
        st.text(" · ".join(details))
        if course.get("reason"):
            st.text(course["reason"])
        url = course.get("url") or ""
        try:
            target = urlsplit(url)
            if target.scheme == "https" and target.hostname:
                st.link_button("교육과정 열기", url)
        except ValueError:
            pass


def _save(entry: dict, **fields) -> None:
    """평가 한 건을 기록한다. 기록 실패는 상담을 막지 않고 한 줄로만 알린다."""
    from backend import experiments

    try:
        experiments.save_feedback(entry["session_id"], entry["turn_id"], job=entry["job"],
                                  action=entry["action"] or None, model=entry["model"] or None, **fields)
    except Exception:
        st.toast("평가를 저장하지 못했습니다. 상담은 계속할 수 있습니다.")


def _on_rating(entry: dict) -> None:
    value = st.session_state.get(f"fb_{entry['turn_id']}")
    if value is not None:  # 썸 업 1, 썸 다운 0
        _save(entry, rating="up" if value == 1 else "down")


def _on_pick(entry: dict) -> None:
    from backend import experiments

    choice = st.session_state.get(f"ab_{entry['turn_id']}")
    left, right = entry["alternatives"]
    picked = {"A": left["structure"], "B": right["structure"], "비슷해요": experiments.TIE}.get(choice)
    if picked:
        _save(entry, left=left["structure"], right=right["structure"], picked=picked,
              tokens={side["structure"]: side["tokens"] for side in (left, right)})


def _render_answer(entry: dict) -> None:
    from backend import experiments

    st.text(entry["answer"])
    if len(entry["alternatives"]) == 2:
        for column, label, side in zip(st.columns(2), ("추천 A", "추천 B"), entry["alternatives"]):
            with column:
                st.markdown(f"**{label}**")
                for course in side["courses"]:
                    _render_course(course)
        st.radio("어느 쪽 추천이 더 도움이 되나요?", ["A", "B", "비슷해요"], index=None, horizontal=True,
                 key=f"ab_{entry['turn_id']}", on_change=_on_pick, args=(entry,))
    else:
        for course in entry["courses"]:
            _render_course(course)
    if entry["turn_id"] and experiments.active():  # 실험이 꺼져 있으면 평가를 받지 않는다(화면이 전과 같다)
        st.feedback("thumbs", key=f"fb_{entry['turn_id']}", on_change=_on_rating, args=(entry,))


KST = timezone(timedelta(hours=9))
PANEL_REM = 17
# 패널이 열려 있을 때만 쓴다. 고정 문자열이라 사용자 입력이 들어가지 않는다.
# - 패널 열: 너비를 rem 으로 고정한다. 패널은 화면 높이만큼 길게(입력창 높이까지) 늘리고 스크롤해도 따라오게 sticky 로 둔다.
#   Streamlit 이 붙이는 height:auto 보다 이기려고 선택자에 .stVerticalBlock 을 함께 쓰고, flex-basis 가 0% 면 height 가 무시되므로 flex: 0 0 auto 로 둔다.
#   아래쪽 음수 여백은 상자는 입력창 높이까지 보이되 페이지 전체는 화면보다 길어지지 않게(스크롤 방지) 한다.
#   z-index 100 은 화면 아래 고정 입력창 영역(99) 위로 올려 상자 테두리가 입력창 높이까지 끊기지 않게 한다.
# - 입력창: 화면 아래에 고정된 입력창을 패널 너비만큼 오른쪽으로 민다(접으면 이 CSS 를 쓰지 않아 전체 폭이 된다).
PANEL_CSS = f"""<style>
[data-testid="stColumn"]:has(.st-key-history_panel) {{ flex: 0 0 {PANEL_REM}rem; width: {PANEL_REM}rem; min-width: {PANEL_REM}rem; align-self: stretch; }}
.stVerticalBlock.st-key-history_panel {{ flex: 0 0 auto; position: sticky; top: 4rem; height: calc(100vh - 8.5rem); margin-bottom: -7.5rem; z-index: 100; overflow-y: auto; background: #ffffff;
  border: 1px solid rgba(49, 51, 63, 0.2); border-radius: 0.5rem; padding: 1rem; }}
.st-key-chat_message {{ margin-left: {PANEL_REM + 1}rem; width: calc(100% - {PANEL_REM + 1}rem); }}
</style>"""
GUEST_NOTICE = "비회원의 대화는 저장되지 않습니다. 왼쪽에서 로그인하면 대화가 저장됩니다."
MEMBER_NOTICE = "로그인했으므로 이 대화는 저장되고 왼쪽 '최근'에서 다시 볼 수 있습니다. 이메일·전화번호는 가려서 저장합니다."


def _when(iso: str) -> str:
    """저장 시각(UTC)을 한국 시간 '월/일 시:분'으로 보인다."""
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%m/%d %H:%M")


def _new_chat() -> None:
    for key in ("chat_conversation", "chat_history", "viewing_session"):
        st.session_state.pop(key, None)


def _current_session_id() -> str | None:
    conversation = st.session_state.get("chat_conversation")
    return getattr(getattr(conversation, "usage", None), "session_id", None)


def _open_past(session_id: str) -> None:
    if session_id == _current_session_id():  # 지금 하고 있는 대화를 누르면 그대로 돌아온다
        st.session_state.pop("viewing_session", None)
    else:
        st.session_state.viewing_session = session_id


def _back_to_current() -> None:
    st.session_state.pop("viewing_session", None)


def _toggle_history() -> None:
    st.session_state.history_open = not st.session_state.get("history_open", True)


def _toggle_button(opened: bool) -> None:
    """패널을 접고 펼치는 버튼. 새 채팅 버튼과 같은 글자·아이콘 크기를 쓴다."""
    st.button("대화 기록 접기" if opened else "대화 기록 펼치기", key="history_toggle", on_click=_toggle_history,
              icon=":material/left_panel_close:" if opened else ":material/left_panel_open:",
              width="stretch" if opened else "content")


def _history_panel(session: chat_profiles.ProfileSession | None) -> None:
    """학습 상담 왼쪽 패널: 새 채팅 버튼과 '최근' 대화 목록. 누르면 그 대화를 읽기 전용으로 연다(이어 쓰기는 아직 없다)."""
    _toggle_button(True)
    st.button("새 채팅", key="chat_new", on_click=_new_chat, icon=":material/edit_square:", width="stretch")
    st.caption("최근")
    if session is None:
        st.caption("로그인하면 대화 기록이 저장됩니다.")
        return
    try:
        sessions = chat_history.list_sessions(session.nickname)
    except Exception:  # 예외에 닉네임이나 대화가 섞일 수 있어 문구만 보인다
        st.caption("대화 기록을 불러오지 못했습니다.")
        return
    if not sessions:
        st.caption("저장된 대화가 아직 없습니다.")
        return
    shown = st.session_state.get("viewing_session") or _current_session_id()
    for item in sessions:
        st.button(item["title"], key=f"history_{item['session_id']}", help=_when(item["updated_at"]),
                  on_click=_open_past, args=(item["session_id"],), width="stretch",
                  type="secondary" if item["session_id"] == shown else "tertiary")


def _render_entries(entries: list) -> None:
    for entry in entries:
        if isinstance(entry, tuple):  # 평가 기능 이전의 열린 세션에는 턴 ID가 없다.
            prompt, answer, courses = entry
            entry = {"prompt": prompt, "answer": answer, "courses": courses, "alternatives": [], "turn_id": ""}
        with st.chat_message("user"):
            st.text(entry["prompt"])
        with st.chat_message("assistant"):
            _render_answer(entry)


def _render_past(nickname: str, session_id: str) -> None:
    st.info("지난 대화를 보고 있습니다. 새 질문을 입력하면 현재 대화로 돌아갑니다.")
    st.button("현재 대화로 돌아가기", key="history_back", on_click=_back_to_current)
    try:
        turns = chat_history.load_session(nickname, session_id)
    except Exception:
        st.caption("이 대화를 불러오지 못했습니다.")
        return
    _render_entries([{"prompt": q, "answer": a, "courses": c, "alternatives": [], "turn_id": ""}
                     for q, a, c in turns])


def render(job: str, sidebar_skills: list[str], session: chat_profiles.ProfileSession | None) -> None:
    from backend import chat

    nickname = session.nickname if session else None
    opened = st.session_state.get("history_open", True)
    panel, body = st.columns([1, 4]) if opened else (None, st.container())  # 패널은 메시지를 처리한 뒤 채운다
    with body:
        if not opened:
            _toggle_button(False)
        st.title("학습 상담")
        st.caption("직접 맡은 일이나 사용한 기술을 알려주세요. 부족한 기술이나 교육과정은 원할 때 물어보세요.")
        st.caption(MEMBER_NOTICE if nickname else GUEST_NOTICE)
    if "chat_conversation" not in st.session_state:
        st.session_state.chat_conversation = chat.Conversation()
        st.session_state.chat_history = []
    conversation = st.session_state.chat_conversation
    if not hasattr(conversation, "usage"):
        conversation.usage = SessionUsage()
    history = st.session_state.chat_history
    message = st.chat_input("경험을 적거나 궁금한 점을 물어보세요.", key="chat_message")
    if message and message.strip():
        st.session_state.pop("viewing_session", None)  # 새 질문은 현재 대화에 이어진다
        try:
            reply = chat.handle_message(
                conversation, message,
                job=job, sidebar_skills=sidebar_skills, session=session,
            )
            # 실험용 항목은 없을 수도 있다(없으면 평가 위젯을 붙이지 않는다)
            entry = {"answer": reply.text, "courses": reply.courses, "turn_id": getattr(reply, "turn_id", ""),
                     "model": getattr(reply, "model", ""), "action": getattr(reply, "action", ""),
                     "alternatives": getattr(reply, "alternatives", [])}
        except Exception:
            # 예외에 닉네임, 프로필 또는 원문이 포함될 수 있다.
            entry = {"answer": "메시지 처리 결과를 확인할 수 없습니다.", "courses": [], "turn_id": "", "model": "",
                     "action": "", "alternatives": []}
        history.append({"prompt": message, "job": job, "session_id": conversation.usage.session_id, **entry})
        chat_history.append_turn(nickname, conversation.usage.session_id, message, entry["answer"], entry["courses"])

    # 패널은 메시지를 처리하고 저장한 뒤에 채운다. 그래야 방금 보낸 첫 대화도 목록에 바로 뜬다.
    if opened:
        with panel, st.container(key="history_panel"):
            _history_panel(session)
    with body:
        viewing = st.session_state.get("viewing_session")
        if nickname and viewing:
            _render_past(nickname, viewing)
        else:
            usage = conversation.usage
            st.metric("이 대화의 누적 토큰", f"{usage.total_tokens:,}",
                      help="기록을 시작한 뒤 모델이 보고한 사용량입니다. 재시도를 포함하며 모의 호출은 0토큰입니다.")
            st.caption(f"입력 {usage.input_tokens:,} · 출력 {usage.output_tokens:,} · 세션 ID `{usage.session_id}`")
            _render_entries(history)
    if opened:  # 빈 요소가 남는 자리가 화면 맨 끝이 되도록 마지막에 둔다
        st.markdown(PANEL_CSS, unsafe_allow_html=True)
