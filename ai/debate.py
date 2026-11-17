"""추천 단계의 멀티 에이전트: 추천 에이전트 → 검증 에이전트 → 한 번 수정 → 코드 검사 (2026-11-16 결정).

흐름
1. 추천 에이전트: ai.recommend.build_recommendation 이 과정을 고르고 이유를 쓴다(기존 그대로).
2. 검증 에이전트: 과정마다 반박한다(ai/prompts/review_v1.py). 판정과 근거만 내고 결정은 하지 않는다.
3. 추천 에이전트가 한 번만 고친다: "이유가 학습 목표에 없는 내용을 말한다"(reason)는 반박을 받은 과정만.
4. 코드가 결정한다(_decide). LLM 의 판정을 그대로 믿지 않는다.
   - coverage 반박: 학습 목표가 기술 이름을 말하고, 제목에도 있거나 두 곳 이상이거나 절반 이상이면 기각한다("반박 기각"으로 따로 표시).
     그 밖에는 받아들여 match 를 uncertain 으로 낮춘다(올리지는 않는다). 학습 목표 열 개 중 한 줄에만 스친 과정이 여기서 걸린다.
   - reason 반박: 고친 이유가 형식 검사를 통과하고, 지적받은 부분(claim)의 낱말이 남아 있지 않고, 수요 숫자를 잃지 않았으면 "수정됨".
     하나라도 아니면 원래 이유를 두고 "불확실".
   - level 반박: "불확실".
   - 검증 호출이 실패하면 추천은 그대로 두고 "검증 못 함"으로 표시한다. 검증 때문에 추천이 사라지지 않는다.

역할마다 보는 정보가 다르다. 추천 에이전트는 제목·학습 목표·수요만 보고 이유를 쓴다. 검증 에이전트는 거기에 더해
과정 설명·대상·시간과 코드가 미리 센 값(code_check: 제목에 이름이 있는지, 이름이 나오는 학습 목표 수)을 받는다.
수요 숫자는 코드가 계산한 값이라 검증 대상이 아니다(claim 으로 삼으면 형식 검사에서 떨어진다).

2026-11-17 반대편 검토를 받아 고친 것: coverage 기각 조건(예전에는 certain 판정과 같은 검사라 한 번도 낮추지 못했다),
"수정됨" 판정(예전에는 조사 하나만 바꿔도 통과), 검증 입력의 demand, 실패 호출 기록.

켜고 끄기: 환경 변수 RECOMMEND_DEBATE=1 일 때만 2~4 를 한다. 꺼져 있으면 기존 단일 추천과 똑같다.
평가(단일 추천 대 토론 추천 비교)를 위해 둘을 같은 입력으로 돌릴 수 있게 한 것이다.

추출 단계에는 쓰지 않는다. 두 에이전트가 같은 모델이면 같이 틀릴 수 있으므로 효과는 평가로 확인한다.
③ courses[].review 형식은 contracts/README.md 에 있다.
"""
from __future__ import annotations

import logging
import os
import re
import time
from copy import deepcopy
from typing import Optional

import ai.recommend as rec
from ai.bedrock import USAGE_KEYS, BedrockJSONError, ConverseResult, add_usage, converse_json, is_mock
from ai.prompts import recommend_v1, review_v1
from pipeline.search import _mentions, _names
from pipeline.aliases import normalize_skill

MOCK_FILE = "mock_bedrock_review.json"
PROMPT_VERSION = review_v1.VERSION
ISSUES = ("coverage", "reason", "level")
PASSED, REVISED, UNCERTAIN, UNREVIEWED, OVERRULED = "passed", "revised", "uncertain", "unreviewed", "overruled"
OVERRULED_COMMENT = "검증 에이전트가 이 기술을 다루지 않는다고 반박했지만, 과정 제목이나 학습 목표 여러 곳에 이 기술 이름이 있어 코드 검사로 기각했습니다."
REVISED_COMMENT = "추천 이유에 학습 목표에서 확인되지 않는 내용이 있어 그 부분을 빼고 다시 썼습니다."
REVISE_FAILED_COMMENT = "추천 이유에 학습 목표에서 확인되지 않는 내용이 있습니다. 고쳐 쓰지 못해 불확실로 둡니다."
CLAIM_MIN, COMMENT_MAX = 4, 120
_CLAIM_WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*|[가-힣]{2,}")
# 추천 이유에 늘 나오는 낱말. 남아 있어도 "지적받은 주장이 남았다"는 증거가 아니다
COMMON_WORDS = frozenset("과정은 과정 다룹니다 배웁니다 설명합니다 익힙니다 소개합니다 방법을 방법 내용을 내용 등을 그리고 대한 위한 통해 있습니다 합니다".split())
RETRY_AFTER = 60  # 초. 검증 호출이 실패한 추천은 이 시간 동안만 다시 쓴다(화면을 건드릴 때마다 Bedrock 을 다시 부르지 않게)
_recent: dict = {}

logger = logging.getLogger(__name__)


def debate_enabled() -> bool:
    return os.getenv("RECOMMEND_DEBATE", "0") == "1"


def coverage_check(skill: str, course: dict) -> dict:
    """과정이 기술 이름(대표명·별칭)을 어디서 몇 번 말하는지 코드로 센다. 검증 에이전트 입력과 기각 판단에 같이 쓴다."""
    names = _names(normalize_skill(skill) or skill)
    return {
        "skill_in_title": _mentions(course["title"], names),
        "objectives_naming_skill": sum(_mentions(o, names) for o in course["objectives"]),
        "objectives_total": len(course["objectives"]),
    }


def review_input_of(skill: str, demand: dict, courses: list[dict], reasons: dict[str, str], user_level: Optional[str]) -> dict:
    """검증 에이전트 입력. 추천 에이전트가 보지 못한 설명·대상·시간과 코드가 센 값을 더한다."""
    out = []
    for c in courses:
        raw = rec._courses().get(c["course_id"], {})
        out.append({
            **{k: c[k] for k in ("course_id", "title", "level", "prerequisites", "objectives")},
            "description": raw.get("description", ""), "audience": raw.get("audience", ""),
            "duration_min": raw.get("duration_min", ""),
            "code_check": {**coverage_check(skill, c), "match": c["match"]},
            "reason": reasons[c["course_id"]],
        })
    return {"skill": skill, "user_level": user_level,
            "demand": rec.llm_input_of(skill, demand, courses)["demand"], "courses": out}


def _demand_numbers(review_input: dict) -> set[float]:
    return {float(v) for v in review_input["demand"].values() if isinstance(v, (int, float))}


def _same(a: str, b: str) -> bool:
    return _squash(a).rstrip(".") == _squash(b).rstrip(".")


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
        quotable = [c["title"], *c["objectives"], *([c["prerequisites"]] if issue == "level" else [])]
        if quote is not None and not (isinstance(quote, str) and quote.strip() and any(_same(quote, q) for q in quotable)):
            raise ValueError(f"{c['course_id']} quote 는 title 전체나 objectives 의 한 항목 전체와 같아야 합니다(줄이거나 고치지 않습니다)")
        if issue == "reason":
            if not (isinstance(claim, str) and len(_squash(claim)) >= CLAIM_MIN and _squash(claim) in _squash(c["reason"])):
                raise ValueError(f"{c['course_id']} claim 은 reason 안에 그대로 있는 {CLAIM_MIN}자 이상의 구절이어야 합니다")
            if rec._numbers(claim) & _demand_numbers(review_input):
                raise ValueError(f"{c['course_id']} claim 에 수요 숫자가 들어 있습니다. 공고 수와 비율은 코드가 계산한 값이라 검토 대상이 아닙니다")
        if not (isinstance(comment, str) and re.search(r"[가-힣]", comment) and len(comment) <= COMMENT_MAX):
            raise ValueError(f"{c['course_id']} comment 는 {COMMENT_MAX}자 이하의 한국어 문장이어야 합니다")
        allowed_text = " ".join([review_input["skill"], c["title"], c["level"], c["prerequisites"], *c["objectives"], c["reason"],
                                 str(c.get("description", "")), str(c.get("audience", ""))])
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


def review(skill: str, demand: dict, courses: list[dict], reasons: dict[str, str], user_level: Optional[str] = None) -> ConverseResult:
    """검증 에이전트를 한 번 부른다. data["reviews"] 는 과정마다 하나씩이고 validate_reviews 를 통과한 것이다."""
    review_input = review_input_of(skill, demand, courses, reasons, user_level)
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


def _overrules_coverage(skill: str, course: dict) -> bool:
    """coverage 반박을 기각할 만큼 과정이 이 기술을 분명히 다루는가.

    학습 목표가 이름을 한 번도 말하지 않으면 기각하지 않는다(제목에만 있는 이름은 다른 제품일 수 있다).
    학습 목표 한 곳 이상에 있고, 제목에도 있거나 두 곳 이상이거나 절반 이상이면 기각한다. 프롬프트의 coverage 기준과 같다.
    """
    check = coverage_check(skill, course)
    hits, total = check["objectives_naming_skill"], check["objectives_total"]
    return hits >= 1 and (check["skill_in_title"] or hits >= 2 or hits * 2 >= total)


def _claim_remains(skill: str, course: dict, claim: str, new_reason: str) -> bool:
    """지적받은 주장이 고친 이유에 남아 있는가. 조사만 바꾼 수정을 통과시키지 않으려고 낱말 단위로도 본다.

    과정 원문이나 기술 이름에 있는 낱말, 추천 이유에 늘 나오는 낱말(COMMON_WORDS)은 남아도 된다. 그 밖의 낱말이 절반 넘게 남으면 고치지 않은 것으로 본다.
    """
    new = _squash(new_reason)
    if _squash(claim) in new:
        return True
    grounded = " ".join([course["title"], *course["objectives"], *_names(normalize_skill(skill) or skill)]).lower()
    words = [w for w in dict.fromkeys(_CLAIM_WORD.findall(claim)) if w.lower() not in grounded and w not in COMMON_WORDS]
    left = [w for w in words if w.lower() in new.lower()]
    return bool(words) and len(left) * 2 > len(words)


def _decide(skill: str, course: dict, r: dict, old_reason: str, new_reason: Optional[str],
            demand_numbers: frozenset = frozenset()) -> tuple[dict, str, str]:
    """검증 1건을 보고 (review, reason, match) 를 정한다. 결정은 여기(코드)에서만 한다."""
    match = course["match"]
    base = {"status": PASSED, "issue": None, "comment": None, "quote": None}
    if r["verdict"] == "pass":
        return base, old_reason, match
    issue = r["issue"]
    note = {"issue": issue, "comment": r.get("comment"), "quote": r.get("quote")}
    if issue == "coverage":
        if _overrules_coverage(skill, course):
            return {"status": OVERRULED, "issue": issue, "comment": OVERRULED_COMMENT, "quote": None}, old_reason, match
        return {"status": UNCERTAIN, **note}, old_reason, "uncertain"
    if issue == "reason":
        failed = {"status": UNCERTAIN, **note, "comment": REVISE_FAILED_COMMENT}
        if new_reason is None or _claim_remains(skill, course, r["claim"], new_reason):
            return failed, old_reason, match
        if (rec._numbers(old_reason) & demand_numbers) - rec._numbers(new_reason):  # 고치다가 수요 숫자를 잃었다
            return failed, old_reason, match
        return {"status": REVISED, **note, "comment": REVISED_COMMENT}, new_reason, match
    return {"status": UNCERTAIN, **note}, old_reason, match  # level


def _record_failure(stage: str, skill: str, e: Exception, usage: dict, calls: list) -> None:
    """실패한 호출도 토큰과 함께 남긴다. 추천은 막지 않지만 원인은 로그에 전부 남긴다."""
    spent = getattr(e, "usage", None) or {}
    add_usage(usage, spent)
    calls.append({"stage": stage, "failed": True, **{k: spent.get(k, 0) for k in USAGE_KEYS}})
    if isinstance(e, BedrockJSONError):
        logger.warning("추천 %s: %s 응답이 형식 검사를 통과하지 못했습니다: %s", skill, stage, e)
    else:  # 호출 제한·시간 초과, 또는 코드 오류. 화면은 "검증 못 함"으로 가되 원인을 찾을 수 있게 호출 경로를 남긴다
        logger.error("추천 %s: %s 호출 실패(%s)", skill, stage, type(e).__name__, exc_info=True)


def build_recommendation(skill: str, demand: dict, user_level: Optional[str] = None) -> tuple[dict, Optional[ConverseResult]]:
    """ai.recommend.build_recommendation 과 같은 값을 돌려준다. RECOMMEND_DEBATE=1 이면 courses[].review 가 붙는다.

    돌려주는 ConverseResult 의 usage 는 추천·검증·수정 호출의 합이고, calls 에는 호출마다 stage 가 적힌다(실패한 호출은 failed: true).
    data 와 attempts 는 첫 추천 호출의 값이다. 최종 이유는 recommendation 에서 읽는다.
    """
    if not debate_enabled():
        return rec.build_recommendation(skill, demand)
    memo_key = (skill, demand["postings"], demand["of"], demand["required_ratio"], user_level)
    kept = _recent.get(memo_key)
    if kept and time.monotonic() - kept[0] < RETRY_AFTER:
        return deepcopy(kept[1]), kept[2]
    recommendation, result = _build(skill, demand, user_level)
    _recent.pop(memo_key, None)
    if any((c.get("review") or {}).get("status") == UNREVIEWED for c in recommendation["courses"]):
        # 검증에 실패한 결과만 잠깐 붙잡아 둔다. backend 는 이런 결과를 캐시하지 않고 다시 부르는데, 그때마다 Bedrock 을 부르지 않게 한다
        _recent[memo_key] = (time.monotonic(), deepcopy(recommendation), result)
    return recommendation, result


def _build(skill: str, demand: dict, user_level: Optional[str]) -> tuple[dict, Optional[ConverseResult]]:
    recommendation, result = rec.build_recommendation(skill, demand)
    if not recommendation["courses"] or result is None:
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
        reviewed = review(skill, demand, courses, reasons, user_level)
    except Exception as e:  # noqa: BLE001 - 형식 검사 실패뿐 아니라 호출 제한·시간 초과도 추천을 막지 않게 한다
        _record_failure("review", skill, e, usage, calls)
        for _, out in paired:
            out["review"] = {"status": UNREVIEWED, "issue": None, "comment": None, "quote": None}
        return recommendation, ConverseResult(result.data, result.attempts, usage, tuple(calls))
    _add("review", reviewed)
    by_id = {r["course_id"]: r for r in reviewed.data["reviews"]}
    demand_numbers = frozenset(_demand_numbers({"demand": rec.llm_input_of(skill, demand, courses)["demand"]}))

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
        except Exception as e:  # noqa: BLE001 - 수정에 실패하면 원래 이유를 두고 불확실로 표시한다
            _record_failure("revise", skill, e, usage, calls)

    for c, out in paired:
        cid = c["course_id"]
        out["review"], out["reason"], out["match"] = _decide(skill, c, by_id[cid], reasons[cid], new_reasons.get(cid), demand_numbers)
    logger.info("추천 %s 검증: %s", skill, [out["review"]["status"] for _, out in paired])
    return recommendation, ConverseResult(result.data, result.attempts, usage, tuple(calls))
