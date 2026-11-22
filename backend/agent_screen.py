"""화면 상담을 구조 A(상담 에이전트, ai/agent.py)로 처리하는 길. CHAT_ARCHITECTURE=agent 일 때만 쓴다.

backend/chat.handle_message 가 부른다. 화면(app/)은 고치지 않는다: 돌려주는 값이 구조 0 과 같은 Reply 이기 때문이다.

- 보유 기술: 저장된 프로필과 사이드바 기술을 코드가 합쳐 A 의 get_gap 입력에 더한다(ai.agent.chat 의 base_skills). 프롬프트는 그대로
- 입력 검사: A 안의 ai.guardrail.check_input 결과를 구조 0 과 같은 문구·action 으로 바꾼다(막힘 blocked, 검사 실패 intake)
- 과정 카드: A 가 받은 과정 원본을 구조 0 의 카드 검사(backend.chat._verified_course_cards)로 그대로 옮긴다
- 대신 처리: 클라우드 엔지니어가 아닌 턴(A 는 클라우드만)과 A 실행 중 예외가 난 턴은 None 을 돌려주고, 그 턴은 구조 0 이 처리한다.
  가드레일 차단은 예외가 아니라 대신 처리하지 않는다. 예외는 종류만 로그에 남긴다(발화·답 원문은 남기지 않음)
- 이전 대화: A 가 처리한 턴만 Conversation.agent_history 에 쌓아 다음 턴에 넘긴다(막힌 턴은 넣지 않음)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend import chat_profiles

if TYPE_CHECKING:
    from backend.chat import Conversation, Reply

logger = logging.getLogger(__name__)
HISTORY_TURNS = 6  # A 에 넘기는 이전 대화(질문·답 쌍) 수. 대화가 길어져도 입력 토큰이 끝없이 늘지 않게


def base_skills(state: Conversation, sidebar_skills: list[str]) -> list[str]:
    """저장된 프로필 기술 + 사이드바 기술(중복 없이). 프로필을 못 읽으면 사이드바만(구조 0 과 같다)."""
    if state.session is not None and state.profile is None:
        try:
            state.profile = chat_profiles.load_profile(state.session)
        except Exception:
            pass
    names = [*(state.profile or {}).get("skills", []), *sidebar_skills]
    return list(dict.fromkeys(str(n).strip() for n in names if str(n).strip()))


def _action(result: dict, courses: list[dict]) -> str:
    """화면의 이동 버튼과 대화 기록 저장 규칙이 읽는 요청 종류. 부른 도구로 정한다."""
    if result.get("scope") == "out":
        return "out_of_scope"
    if courses:
        return "courses"
    called = {c["name"] for c in result["tool_calls"] if c.get("ok")}
    if "get_gap" in called:
        return "gap"
    return "demand" if "get_skill_demand" in called else "note"


def reply_for(state: Conversation, message: str, job: str, sidebar_skills: list[str]) -> Reply | None:
    """구조 A 로 한 턴을 처리한 Reply. None 이면 이 턴은 구조 0 이 대신 처리한다."""
    from ai import agent
    from backend import chat

    if not message.strip():
        return None
    skills = base_skills(state, sidebar_skills)
    target = state.job or (state.profile or {}).get("job") or job
    if target != agent.JOB:
        return None
    history = state.agent_history[-HISTORY_TURNS * 2:]
    try:
        result = agent.chat(message, history, base_skills=skills)
        if result["guard"] == "blocked":
            return chat.Reply(chat.BLOCKED_TEXT, action="blocked")
        if result["guard"] == "check_failed":
            return chat.Reply(chat.CHECK_FAILED_TEXT, action="intake", failed=True)
        courses = [card for row in result["course_rows"]
                   for card in chat._verified_course_cards(row["gap_skill"], row["courses"])]
        action = _action(result, courses)
    except Exception as e:  # 시연 중 화면이 깨지지 않게 이 턴만 구조 0 으로
        logger.warning("상담 구조 A 처리 실패(%s). 이 턴은 구조 0 으로 처리합니다", type(e).__name__)
        return None
    state.agent_history += [{"role": "user", "content": message}, {"role": "assistant", "content": result["answer"]}]
    return chat.Reply(result["answer"], courses=courses, action=action)
