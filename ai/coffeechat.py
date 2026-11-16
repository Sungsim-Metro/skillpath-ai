"""커피챗 요청 메시지 초안과 물어볼 질문 3개 (2026-11-16 결정: 현직자 연결 카드).

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
ALLOWED_NUMBERS = {20.0}  # "20분 정도"
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9])")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[./-][A-Za-z0-9+#]+)*")


def llm_input_of(job_title: str, missing_skills: list[str], owned_skills: list[str]) -> dict:
    return {"target_job": job_title, "missing_skills": missing_skills[:MAX_SKILLS], "owned_skills": owned_skills[:MAX_SKILLS]}


def validate_draft(data: dict, llm_input: dict) -> None:
    message, questions = data.get("message"), data.get("questions")
    if not (isinstance(message, str) and message.strip()):
        raise ValueError('"message" 문자열이 없습니다')
    if not (isinstance(questions, list) and len(questions) == 3 and all(isinstance(q, str) and q.strip() for q in questions)):
        raise ValueError('"questions" 는 문자열 3개여야 합니다')
    missing_blanks = [b for b in prompt.BLANKS if b not in message]
    if missing_blanks:
        raise ValueError(f"message 에 빈칸 {missing_blanks} 이 없습니다. 이름과 소개는 지어내지 않고 빈칸으로 둡니다")
    allowed_words = " ".join([llm_input["target_job"], *llm_input["missing_skills"], *llm_input["owned_skills"]]).lower()
    for label, text in [("message", message), *[(f"questions[{i}]", q) for i, q in enumerate(questions)]]:
        if not re.search(r"[가-힣]", text):
            raise ValueError(f"{label} 이 한국어가 아닙니다")
        bad = sorted({float(n) for n in _NUMBER.findall(text)} - ALLOWED_NUMBERS)
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
        validate=lambda data: validate_draft(data, llm_input), max_tokens=1024,
    )
    return {"message": result.data["message"].strip(), "questions": [q.strip() for q in result.data["questions"]]}, result
