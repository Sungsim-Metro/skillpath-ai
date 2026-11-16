"""추천 단계의 멀티 에이전트: 추천 에이전트 → 검증 에이전트 → 한 번 수정 → 코드 검사 (2026-11-16 결정).

흐름
1. 추천 에이전트: ai.recommend.build_recommendation 이 과정을 고르고 이유를 쓴다(기존 그대로).
2. 검증 에이전트: 과정마다 반박한다(ai/prompts/review_v1.py). 판정과 근거만 내고 결정은 하지 않는다.
3. 추천 에이전트가 한 번만 고친다: "이유가 학습 목표에 없는 내용을 말한다"(reason)는 반박을 받은 과정만.
4. 코드가 결정한다(_decide). LLM 의 판정을 그대로 믿지 않는다.
   - coverage 반박: 과정 제목·학습 목표에 기술 이름이 실제로 있으면 반박을 기각한다. 없으면 match 를 uncertain 으로 낮춘다(올리지는 않는다).
   - reason 반박: 고친 이유가 형식 검사를 통과하고 지적받은 부분(claim)이 사라졌으면 "수정됨", 아니면 "불확실".
   - level 반박: "불확실".
   - 검증 호출이 실패하면 추천은 그대로 두고 "검증 못 함"으로 표시한다. 검증 때문에 추천이 사라지지 않는다.

켜고 끄기: 환경 변수 RECOMMEND_DEBATE=1 일 때만 2~4 를 한다. 꺼져 있으면 기존 단일 추천과 똑같다.
평가(단일 추천 대 토론 추천 비교)를 위해 둘을 같은 입력으로 돌릴 수 있게 한 것이다.

추출 단계에는 쓰지 않는다. 두 에이전트가 같은 모델이면 같이 틀릴 수 있으므로 효과는 평가로 확인한다.
③ courses[].review 형식은 contracts/README.md 에 있다.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import ai.recommend as rec
from ai.bedrock import USAGE_KEYS, BedrockJSONError, ConverseResult, add_usage, converse_json, is_mock
from ai.prompts import recommend_v1, review_v1
from pipeline.search import _mentions, _names
from pipeline.aliases import normalize_skill

MOCK_FILE = "mock_bedrock_review.json"
PROMPT_VERSION = review_v1.VERSION
ISSUES = ("coverage", "reason", "level")
PASSED, REVISED, UNCERTAIN, UNREVIEWED = "passed", "revised", "uncertain", "unreviewed"
OVERRULED_COMMENT = "검증 에이전트가 반박했지만 과정 제목이나 학습 목표에 이 기술 이름이 있어 코드 검사로 기각했습니다."
REVISE_FAILED_COMMENT = "지적받은 부분을 고치지 못해 불확실로 둡니다."

logger = logging.getLogger(__name__)


def debate_enabled() -> bool:
    return os.getenv("RECOMMEND_DEBATE", "0") == "1"


def review_input_of(skill: str, courses: list[dict], reasons: dict[str, str], user_level: Optional[str]) -> dict:
    return {
        "skill": skill,
        "user_level": user_level,
        "courses": [
            {**{k: c[k] for k in ("course_id", "title", "level", "prerequisites", "objectives")},
             "reason": reasons[c["course_id"]]}
            for c in courses
        ],
    }


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def validate_reviews(data: dict, review_input: dict) -> None:
    """검증 에이전트 출력 검사. 틀리면 ValueError (converse_json 이 한 번 재시도한다).

    지어낸 근거로 반박하지 못하게 한다: quote 는 과정 원문에, claim 은 추천 이유에 글자 그대로 있어야 한다.
    """
    reviews = data.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError('"reviews" 목록이 없습니다')
    by_id = {c["course_id"]: c for c in review_input["courses"]}
    got = [r.get("course_id") if isinstance(r, dict) else None for r in reviews]
    if sorted(map(str, got)) != sorted(by_id):
        raise ValueError(f"course_id 가 입력과 다릅니다: 입력 {sorted(by_id)}, 응답 {got}")
    for r in reviews:
        c = by_id[r["course_id"]]
        verdict, issue = r.get("verdict"), r.get("issue")
        if verdict not in ("pass", "objection"):
            raise ValueError(f"{c['course_id']} verdict 가 {verdict!r} 입니다")
        if verdict == "pass":
            if issue is not None:
                raise ValueError(f"{c['course_id']} verdict 가 pass 인데 issue 가 있습니다")
            continue
        if issue not in ISSUES:
            raise ValueError(f"{c['course_id']} issue 가 {issue!r} 입니다. {ISSUES} 중 하나여야 합니다")
        if issue == "level" and review_input["user_level"] is None:
            raise ValueError(f"{c['course_id']} user_level 이 없는데 level 을 지적했습니다")
        quote, claim, comment = r.get("quote"), r.get("claim"), r.get("comment")
        source = _squash(" / ".join([c["title"], *c["objectives"]]))
        if quote is not None and not (isinstance(quote, str) and quote.strip() and _squash(quote) in source):
            raise ValueError(f"{c['course_id']} quote 가 과정의 title·objectives 에 그대로 있지 않습니다")
        if issue == "reason":
            if not (isinstance(claim, str) and claim.strip() and _squash(claim) in _squash(c["reason"])):
                raise ValueError(f"{c['course_id']} claim 이 reason 안에 그대로 있지 않습니다")
        if not (isinstance(comment, str) and re.search(r"[가-힣]", comment)):
            raise ValueError(f"{c['course_id']} comment 가 한국어 문장이 아닙니다")
        allowed_text = " ".join([review_input["skill"], c["title"], c["level"], c["prerequisites"], *c["objectives"], c["reason"]])
        bad = sorted(rec._numbers(comment) - rec._numbers(allowed_text))
        if bad:
            raise ValueError(f"{c['course_id']} comment 에 입력에 없는 숫자 {bad}")
        haystack = allowed_text.lower()
        unknown = sorted({w for w in rec._LATIN.findall(comment)
                          if len(w) >= 2 and w.lower() not in rec.ALWAYS_ALLOWED_WORDS and w.lower() not in haystack})
        if unknown:
            raise ValueError(f"{c['course_id']} comment 에 입력에 없는 이름 {unknown}")


def _mock_pass(review_input: dict) -> ConverseResult:
    """가짜 모드에서 기술별 가짜 검증 응답이 없을 때: 모두 통과. 검사는 실제 응답과 똑같이 한다."""
    data = {"reviews": [{"course_id": c["course_id"], "verdict": "pass", "issue": None, "claim": None,
                         "quote": None, "comment": None} for c in review_input["courses"]]}
    validate_reviews(data, review_input)
    return ConverseResult(data, 1, {k: 0 for k in USAGE_KEYS}, ())


def _mock_keys() -> frozenset[str]:
    import json

    table = json.loads((rec.SAMPLE_DIR / MOCK_FILE).read_text(encoding="utf-8"))
    return frozenset(k for k in table if k not in ("_note", "default"))


def review(skill: str, courses: list[dict], reasons: dict[str, str], user_level: Optional[str] = None) -> ConverseResult:
    """검증 에이전트를 한 번 부른다. data["reviews"] 는 과정마다 하나씩이고 validate_reviews 를 통과한 것이다."""
    review_input = review_input_of(skill, courses, reasons, user_level)
    if is_mock() and skill not in _mock_keys():
        return _mock_pass(review_input)
    return converse_json(
        review_v1.SYSTEM,
        review_v1.user_message(review_input),
        mock_file=MOCK_FILE,
        mock_key=skill,
        validate=lambda data: validate_reviews(data, review_input),
        max_tokens=2048,
    )


def _revise(skill: str, llm_input: dict, reasons: dict[str, str], objections: list[dict]) -> ConverseResult:
    """추천 에이전트에게 지적받은 과정의 이유만 다시 쓰게 한다. 검사는 처음 쓸 때와 같다(rec.validate_reasons)."""
    previous = [{"course_id": c["course_id"], "reason": reasons[c["course_id"]]} for c in llm_input["courses"]]
    return converse_json(
        recommend_v1.SYSTEM,
        review_v1.revise_message(llm_input, previous, objections),
        mock_file=MOCK_FILE,
        mock_key=f"{skill}#revise",
        validate=lambda data: rec.validate_reasons(data, llm_input),
        max_tokens=2048,
    )


def _names_skill(skill: str, course: dict) -> bool:
    """과정 제목이나 학습 목표에 기술 이름(대표명·별칭)이 실제로 나오는가. 코드로 본다."""
    names = _names(normalize_skill(skill) or skill)
    return _mentions(" / ".join([course["title"], *course["objectives"]]), names)


def _decide(skill: str, course: dict, r: dict, old_reason: str, new_reason: Optional[str]) -> tuple[dict, str, str]:
    """검증 1건을 보고 (review, reason, match) 를 정한다. 결정은 여기(코드)에서만 한다."""
    match = course["match"]
    base = {"status": PASSED, "issue": None, "comment": None, "quote": None}
    if r["verdict"] == "pass":
        return base, old_reason, match
    issue = r["issue"]
    note = {"issue": issue, "comment": r.get("comment"), "quote": r.get("quote")}
    if issue == "coverage":
        if _names_skill(skill, course):
            return {**base, "issue": issue, "comment": OVERRULED_COMMENT, "overruled": True}, old_reason, match
        return {"status": UNCERTAIN, **note}, old_reason, "uncertain"
    if issue == "reason":
        claim = _squash(r["claim"])
        if new_reason is not None and claim not in _squash(new_reason):
            return {"status": REVISED, **note}, new_reason, match
        return {"status": UNCERTAIN, **note, "comment": f"{r.get('comment') or ''} {REVISE_FAILED_COMMENT}".strip()}, old_reason, match
    return {"status": UNCERTAIN, **note}, old_reason, match  # level


def build_recommendation(skill: str, demand: dict, user_level: Optional[str] = None) -> tuple[dict, Optional[ConverseResult]]:
    """ai.recommend.build_recommendation 과 같은 값을 돌려준다. RECOMMEND_DEBATE=1 이면 courses[].review 가 붙는다.

    돌려주는 ConverseResult 의 usage 는 추천·검증·수정 호출의 합이고, calls 에는 호출마다 stage 가 적힌다.
    """
    recommendation, result = rec.build_recommendation(skill, demand)
    if not debate_enabled() or not recommendation["courses"] or result is None:
        return recommendation, result

    courses = rec.candidate_courses(skill)
    by_title = {(c["title"], c["url"]): c for c in courses}
    paired = [(by_title.get((out["title"], out["url"])), out) for out in recommendation["courses"]]
    if any(c is None for c, _ in paired):  # 추천과 후보가 어긋나면 검증하지 않는다(추천은 그대로)
        logger.warning("추천 %s: 과정 후보와 추천이 어긋나 검증을 건너뜁니다", skill)
        return recommendation, result
    courses = [c for c, _ in paired]
    reasons = {c["course_id"]: out["reason"] for c, out in paired}

    usage = dict(result.usage)
    calls = [{"stage": "recommend", **call} for call in result.calls]

    def _add(stage: str, r: ConverseResult) -> None:
        add_usage(usage, r.usage)
        calls.extend({"stage": stage, **call} for call in r.calls)

    try:
        reviewed = review(skill, courses, reasons, user_level)
    except BedrockJSONError as e:
        add_usage(usage, e.usage)
        logger.warning("추천 %s: 검증 호출 실패(%s). 추천은 그대로 둡니다", skill, type(e).__name__)
        for _, out in paired:
            out["review"] = {"status": UNREVIEWED, "issue": None, "comment": None, "quote": None}
        return recommendation, ConverseResult(result.data, result.attempts, usage, tuple(calls))
    _add("review", reviewed)
    by_id = {r["course_id"]: r for r in reviewed.data["reviews"]}

    new_reasons: dict[str, str] = {}
    objections = [
        {k: by_id[c["course_id"]].get(k) for k in ("course_id", "claim", "quote", "comment")}
        for c in courses if by_id[c["course_id"]].get("issue") == "reason"
    ]
    if objections:  # 한 번만 고친다. 다시 검증하지 않는다
        llm_input = rec.llm_input_of(skill, demand, courses)
        try:
            revised = _revise(skill, llm_input, reasons, objections)
            _add("revise", revised)
            new_reasons = {r["course_id"]: r["reason"].strip() for r in revised.data["reasons"]}
        except BedrockJSONError as e:
            add_usage(usage, e.usage)
            logger.warning("추천 %s: 수정 호출 실패(%s)", skill, type(e).__name__)

    for c, out in paired:
        cid = c["course_id"]
        out["review"], out["reason"], out["match"] = _decide(skill, c, by_id[cid], reasons[cid], new_reasons.get(cid))
    logger.info("추천 %s 검증: %s", skill, [out["review"]["status"] for _, out in paired])
    return recommendation, ConverseResult(result.data, result.attempts, usage, tuple(calls))
