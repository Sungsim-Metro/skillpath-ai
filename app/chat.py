"""학습 상담 화면과 세션 안에서만 유지하는 대화 표시 기록."""
from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

import streamlit as st

from ai.usage import SessionUsage
from backend import chat_profiles
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


def render(job: str, sidebar_skills: list[str], session: chat_profiles.ProfileSession | None) -> None:
    from backend import chat

    st.title("학습 상담")
    st.caption("직접 맡은 일이나 사용한 기술을 알려주세요. 부족한 기술이나 교육과정은 원할 때 물어보세요.")
    if "chat_conversation" not in st.session_state:
        st.session_state.chat_conversation = chat.Conversation()
        st.session_state.chat_history = []
    conversation = st.session_state.chat_conversation
    if not hasattr(conversation, "usage"):
        conversation.usage = SessionUsage()
    history = st.session_state.chat_history
    message = st.chat_input("경험을 적거나 궁금한 점을 물어보세요.", key="chat_message")
    if message and message.strip():
        try:
            reply = chat.handle_message(
                conversation, message,
                job=job, sidebar_skills=sidebar_skills, session=session,
            )
            response = (reply.text, reply.courses)
        except Exception:
            # 예외에 닉네임, 프로필 또는 원문이 포함될 수 있다.
            response = ("메시지 처리 결과를 확인할 수 없습니다.", [])
        history.append((message, *response))

    usage = conversation.usage
    st.metric("이 대화의 누적 토큰", f"{usage.total_tokens:,}",
              help="기록을 시작한 뒤 모델이 보고한 사용량입니다. 재시도를 포함하며 모의 호출은 0토큰입니다.")
    st.caption(f"입력 {usage.input_tokens:,} · 출력 {usage.output_tokens:,} · 세션 ID `{usage.session_id}`")

    for prompt, answer, courses in history:
        with st.chat_message("user"):
            st.text(prompt)
        with st.chat_message("assistant"):
            st.text(answer)
            for course in courses:
                _render_course(course)
