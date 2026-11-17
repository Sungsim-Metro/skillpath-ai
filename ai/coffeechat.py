"""커피챗 요청 메시지 초안과 물어볼 질문 3개 (2026-11-16 결정: 현직자 연결 카드).

검사가 막는 것은 빈칸 누락과 지어낸 영문 이름·숫자다. 한글로 쓴 지어낸 소개나 말투까지는 막지 못한다(사용자가 고쳐 쓰는 초안이다).
AI 초안을 만들지 못하면 fallback_draft 의 고정 문안을 준다(화면이 오류만 보여 주고 끝나지 않게).
LLM 은 문장만 쓴다. 누구에게 보낼지는 다루지 않는다(사람을 조회하거나 추천하지 않는다).
출력 검사는 코드로 한다: 빈칸 유지, 질문 3개, 입력에 없는 숫자·영문 이름 금지, 한국어.
실패하면 converse_json 이 1회 재시도하고, 그래도 실패하면 BedrockJSONError 를 그대로 낸다.
"""
from __future__ import annotations

import re

from ai.bedrock import ConverseResult, converse_json
from ai.prompts import coffeechat_v1 as prompt

MOCK_FILE = "mock_bedrock_coffeechat.json"
PROMPT_VERSION = prompt.VERSION
MAX_SKILLS = 3  # 메시지에 넣을 부족·보유 기술 수
ALLOWED_NUMBERS = {20.0, 30.0}  # "20분 정도", "20~30분". 그 밖의 숫자(경력 연수 등)는 지어낸 것으로 본다
# 입력에 없어도 지어낸 이름이 아닌 흔한 말. 이런 낱말 하나 때문에 초안 전체를 버리지 않는다
COMMON_WORDS = frozenset({"aws", "it", "ci", "cd", "devops", "k8s", "linkedin", "zoom", "ai", "sns"})
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[./-][A-Za-z0-9+#]+)*")


def llm_input_of(job_title: str, missing_skills: list[str], owned_skills: list[str]) -> dict:
    return {"target_job": job_title, "missing_skills": missing_skills[:MAX_SKILLS], "owned_skills": owned_skills[:MAX_SKILLS]}


def validate_draft(data: dict, llm_input: dict, known_skills: tuple[str, ...] = ()) -> None:
    """known_skills: 프롬프트에는 앞의 몇 개만 넣지만 사용자의 부족·보유 기술 전체는 지어낸 이름이 아니다."""
    message, questions = data.get("message"), data.get("questions")
    if not (isinstance(message, str) and message.strip()):
        raise ValueError('"message" 문자열이 없습니다')
    if not (isinstance(questions, list) and len(questions) == 3 and all(isinstance(q, str) and q.strip() for q in questions)):
        raise ValueError('"questions" 는 문자열 3개여야 합니다')
    missing_blanks = [b for b in prompt.BLANKS if b not in message]
    if missing_blanks:
        raise ValueError(f"message 에 빈칸 {missing_blanks} 이 없습니다. 이름과 소개는 지어내지 않고 빈칸으로 둡니다")
    # 입력에 있는 이름을 낱말 단위로 모은다. 부분 문자열로 비교하면 입력에 없는 이름의 조각이 통과한다
    allowed_words = COMMON_WORDS | {
        w.lower() for text in [llm_input["target_job"], *llm_input["missing_skills"], *llm_input["owned_skills"], *known_skills]
        for w in [text, *_LATIN.findall(text), *re.findall(r"[A-Za-z][A-Za-z0-9+#]*", text)]}  # "CI/CD" 의 "CI" 도 허용
    for label, text in [("message", message), *[(f"questions[{i}]", q) for i, q in enumerate(questions)]]:
        if not re.search(r"[가-힣]", text):
            raise ValueError(f"{label} 이 한국어가 아닙니다")
        body = re.sub(r"^\s*\d[.)]\s*", "", text) if label != "message" else text  # 질문 앞의 "1." 번호는 숫자로 세지 않는다
        bad = sorted({float(n) for n in _NUMBER.findall(body)} - ALLOWED_NUMBERS)
        if bad:
            raise ValueError(f"{label} 에 입력에 없는 숫자 {bad}")
        unknown = sorted({w for w in _LATIN.findall(text) if len(w) >= 2 and w.lower() not in allowed_words})
        if unknown:
            raise ValueError(f"{label} 에 입력에 없는 이름 {unknown}")
    if len(message) > 600:
        raise ValueError("message 가 너무 깁니다(600자 초과)")


def draft(job_title: str, missing_skills: list[str], owned_skills: list[str]) -> tuple[dict, ConverseResult]:
    """{"message", "questions"} 와 호출 결과(시도 횟수·usage)를 돌려준다. 부족 기술이 없으면 ValueError."""
    if not missing_skills:
        raise ValueError("부족 기술이 없으면 초안을 만들지 않습니다")
    llm_input = llm_input_of(job_title, missing_skills, owned_skills)
    result = converse_json(
        prompt.SYSTEM, prompt.user_message(llm_input), mock_file=MOCK_FILE, mock_key="default",
        validate=lambda data: validate_draft(data, llm_input, (*missing_skills, *owned_skills)), max_tokens=1024,
    )
    return {"message": result.data["message"].strip(), "questions": [q.strip() for q in result.data["questions"]]}, result


def fallback_draft(job_title: str, missing_skills: list[str]) -> dict:
    """AI 를 쓰지 않는 기본 문안. 직무와 부족 기술 이름만 끼워 넣는다."""
    skills = ", ".join(missing_skills[:MAX_SKILLS])
    b_to, b_me, b_intro = prompt.BLANKS
    return {
        "message": (f"{b_to}님, 안녕하세요. 저는 {b_me}입니다. {b_intro} {job_title} 직무를 준비하면서 채용공고가 요구하는 기술 가운데 "
                    f"{skills}이(가) 아직 부족해, 어떻게 공부하면 좋을지 현직자의 경험을 듣고 싶어 연락드렸습니다. "
                    "괜찮으시다면 20분 정도 온라인으로 이야기를 나눌 수 있을까요? 바쁘시면 편하게 거절하셔도 괜찮습니다. 읽어 주셔서 감사합니다."),
        "questions": [
            f"실무에서 {missing_skills[0]}을(를) 어떻게 쓰시고, 신입에게는 어느 수준까지 기대하시나요?",
            f"{skills}을(를) 어떤 순서로 공부하는 것이 좋을까요?",
            "처음 일을 시작했을 때 가장 도움이 된 공부나 경험은 무엇이었나요?",
        ],
    }
