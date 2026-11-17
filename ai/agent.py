"""학습 상담 에이전트 (#25). Converse 도구 호출 반복으로 직접 구현한다(Bedrock Agents 리소스는 만들지 않음).

"Python, Docker 해봤는데 클라우드 엔지니어 되려면 뭐부터 공부해요?" 같은 질문에, 모델이 도구를 골라 부르고
그 결과(코드가 계산한 숫자)로 답한다.

도구 (숫자는 모두 코드가 만든다. 직무는 클라우드 엔지니어 하나)
- get_gap(user_skills): 보유 기술 → 부족 기술 상위 TOP_GAP 개와 공고 수. backend.api.get_gap 을 감싼다.
  표기는 pipeline.aliases.normalize_skill 로만 맞춘다. 사전에 없는 표기는 unrecognized 로 돌려주고 자동으로 바꾸지 않는다.
- get_skill_demand(skill): 공고 n건 중 m건, 그중 필수 비율(%).
- search_courses(skill): ai.recommend.candidate_courses(= pipeline.search.search_courses) 의 과정과 match.

코드가 하는 검사
- 답의 숫자는 이번 대화의 도구 결과와 사용자 메시지(이전 대화 포함)에 있는 것만 허용한다(ai.recommend 의 숫자 검사 방식).
  실패하면 이유를 알려 한 번 다시 묻고, 그래도 실패하면 근거 없는 숫자가 든 문장을 지운다(uncertain_reason "number_check").
- 마지막 답은 JSON {"answer", "scope"}. 두 번 모두 JSON 이 아니면 BedrockJSONError 를 그대로 낸다(CLAUDE.md 코드 규칙).
- unrecognized 표기가 있는데 답에 되묻기가 없으면 코드가 "OO는 XX를 말씀하신 건가요?" 를 덧붙인다.
- 취업 준비 질문(scope "in")인데 도구를 한 번도 성공적으로 부르지 않았으면 uncertain_reason "no_tool".
- 도구만 부르다 MAX_TURNS 에 걸리면 정해진 안내와 uncertain_reason "max_turns".
- 가드레일(#24)은 guard_input 자리만 있다. 지금은 항상 통과한다.

명령 (저장소 루트에서)
  python -m ai.agent --warmup        시연 전 준비. 사전 이름 임베딩 캐시를 만든다(실제 모드). 호출 수와 걸린 시간을 출력
  python -m ai.agent "질문"           한 번 물어보고 결과를 JSON 으로 출력

기록: 대화 1건마다 도구 순서·횟수, 모델 호출 수, 재질문 여부와 이유(number / format), 토큰, 응답 시간을 로그에 남긴다.
사용자 메시지와 답 원문, 도구 입력(보유 기술)은 로그에 남기지 않는다(CLAUDE.md 보안: 대화 기록은 로그에 출력하지 않음).
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import time
from typing import Optional

from ai.bedrock import BedrockJSONError, SAMPLE_DIR, USAGE_KEYS, add_usage, converse_tools, is_mock, parse_json_object
from ai.prompts import agent_v1 as prompt
from ai.recommend import candidate_courses
from ai.recommend import extract_numbers as _numbers
from backend import api
from pipeline.aliases import _index, _key, normalize_skill, normalize_skills

JOB = "cloud_engineer"
TOP_GAP = 3          # get_gap 이 돌려주는 부족 기술 수 (도구 결과가 대화에 쌓여 토큰이 늘어 5 → 3, 11/17)
TOP_COURSES = 3      # search_courses 가 돌려주는 과정 수
MAX_TURNS = 4        # 도구 호출 반복 한도(모델 호출 수)
MAX_SKILLS = 30      # get_gap 입력 기술 수 한도
CLOSE_MIN = 0.5      # 문자열 비교 후보의 최소 비슷도 (도카↔도커 0.5, 파이선↔파이썬 0.67)
MAX_SUGGEST = 5      # get_gap 한 번에 maybe 후보를 찾는 표기 수. 실제 모드는 표기마다 임베딩 호출이 들어서 나머지는 null
MOCK_FILE = "mock_bedrock_agent.json"
PROMPT_VERSION = prompt.VERSION

MAX_TURNS_ANSWER = "질문을 정리하는 데 시간이 걸려 답을 마치지 못했습니다. 해 본 기술과 궁금한 점을 조금 더 짧게 알려 주세요."
NO_NUMBER_ANSWER = "근거를 확인할 수 있는 숫자 없이 답을 정리하지 못했습니다. 다시 한번 물어봐 주세요."
ASK_BACK = "'{input}'은(는) '{maybe}'을(를) 말씀하신 건가요?"
ASK_BACK_UNKNOWN = "'{input}'은(는) 아직 사전에 없는 기술이라 부족 기술 계산에 넣지 않았습니다. 다른 이름으로 알려 주시겠어요?"
ASK_BACK_MARK = "말씀하신 건가요"

_LIST_MARK = re.compile(r"(?m)^\s*\d+[.)]\s+")   # "1. " 같은 목록 번호는 숫자 검사에서 뺀다
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

logger = logging.getLogger(__name__)


# ── 도구 ────────────────────────────────────────────────────────────
def maybe_skill(raw: str) -> Optional[str]:
    """사전에 없는 표기의 대표명 후보 하나(되묻기용). 바꾸지 않고 묻기만 한다.

    실제 모드는 pipeline.suggest(임베딩)에서 confidence 가 candidate 인 1위만 쓴다. 가짜 모드이거나 suggest 가
    실패하면 사전 표기와의 문자열 비교(difflib)로 찾는다. 둘 다 없으면 None.
    """
    if not is_mock():
        try:
            from pipeline.suggest import suggest

            top = suggest(raw, top=1)
            return top[0]["canonical"] if top and top[0]["confidence"] == "candidate" else None
        except Exception as e:  # noqa: BLE001 - 후보는 되묻기용이라 실패해도 문자열 비교로 넘어간다
            logger.warning("pipeline.suggest 실패, 문자열 비교로 후보를 찾습니다: %s", type(e).__name__)
    return _close_name(raw)


def _close_name(raw: str) -> Optional[str]:
    """문자열 비교 후보. 비슷도 하나로는 가를 수 없어(자바스크립트↔셸스크립트 0.73 > 도카↔도커 0.5) 조건을 셋 둔다.

    1) 첫 글자가 같은 사전 표기만 본다. 2) 비슷도(difflib ratio)가 CLOSE_MIN 이상. 3) 사전 표기 뒤에 두 글자 이상이
    더 붙은 표기는 다른 기술일 수 있어 후보로 내지 않는다(Java ≠ JavaScript, 자바 ≠ 자바스크립트). 못 찾으면 None.
    """
    key = _key(raw)
    if not key:
        return None
    index = _index()
    best, best_score = None, CLOSE_MIN
    for name in index:
        if name[0] != key[0] or (key.startswith(name) and len(key) - len(name) >= 2):
            continue
        score = difflib.SequenceMatcher(None, key, name).ratio()
        if score >= best_score and (best is None or score > best_score):
            best, best_score = name, score
    return index[best] if best else None


def _pct(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


def tool_get_gap(user_skills: list) -> dict:
    if not isinstance(user_skills, list):
        raise ValueError("user_skills 는 목록이어야 합니다")
    known, unknown = normalize_skills([str(s).strip() for s in user_skills if str(s).strip()][:MAX_SKILLS])
    total = api.get_demand(JOB)["total_postings"]
    rows = api.get_gap(JOB, known)
    # 답에 필요한 칸만 둔다(공고 수 of 는 위에 한 번만). 도구 결과는 대화에 쌓여 다음 호출마다 입력 토큰이 된다
    return {
        "of": total,
        "basis": "recognized_skills" if known else "no_skills",  # 부족 기술을 무엇 기준으로 셌는지
        "recognized_skills": known,
        "unrecognized": [{"input": u, "maybe": maybe_skill(u) if i < MAX_SUGGEST else None}
                         for i, u in enumerate(unknown)],
        "missing_top": [
            {"skill": r["skill"], "postings": r["postings"], "required_pct": round(r["required_ratio"] * 100)}
            for r in rows if not r["owned"]
        ][:TOP_GAP],
    }


def tool_get_skill_demand(skill: str) -> dict:
    canon = normalize_skill(skill)
    demand = api.get_demand(JOB)
    total = demand["total_postings"]
    name = (canon or skill).lower()
    s = next((x for x in demand["skills"] if x["skill"].lower() == name), None)
    if s is None:
        return {"skill": canon or skill, "found": False, "of": total,
                "maybe": None if canon else maybe_skill(skill)}
    return {"skill": s["skill"], "found": True, "postings": s["postings"], "of": total,
            "required_pct": _pct(s["required"], s["postings"])}


def tool_search_courses(skill: str) -> dict:
    canon = normalize_skill(skill) or skill
    courses = candidate_courses(canon)[:TOP_COURSES]
    return {"skill": canon, "courses": [  # 선수지식(prerequisites)은 길어서 뺀다. 화면의 추천 탭이 보여준다
        {k: c[k] for k in ("title", "level", "match")} for c in courses
    ]}


TOOL_FUNCS = {
    "get_gap": lambda inp: tool_get_gap(inp.get("user_skills", [])),
    "get_skill_demand": lambda inp: tool_get_skill_demand(str(inp.get("skill", ""))),
    "search_courses": lambda inp: tool_search_courses(str(inp.get("skill", ""))),
}


# ── 검사 ────────────────────────────────────────────────────────────
def guard_input(message: str) -> Optional[str]:
    """가드레일(#24) 자리. 막아야 하면 사용자에게 보여줄 안내 문장, 통과면 None. 지금은 항상 통과한다."""
    return None


def _walk_numbers(value) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    if isinstance(value, str):
        return _numbers(value)
    if isinstance(value, dict):
        return set().union(*(_walk_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_walk_numbers(v) for v in value)) if value else set()
    return set()


def answer_numbers(answer: str) -> set[float]:
    return _numbers(_LIST_MARK.sub("", answer))


def check_answer(text: str, allowed: set[float]) -> tuple[Optional[dict], list[float], Optional[str]]:
    """(읽은 답, 근거 없는 숫자, 오류 설명). 오류가 없으면 설명이 None."""
    try:
        data = parse_json_object(text)
    except ValueError as e:
        return None, [], f"JSON 객체가 아닙니다({type(e).__name__})"
    if not isinstance(data.get("answer"), str) or not data["answer"].strip():
        return None, [], '"answer" 가 비었거나 문자열이 아닙니다'
    if data.get("scope") not in ("in", "out"):
        return None, [], '"scope" 는 "in" 또는 "out" 이어야 합니다'
    bad = sorted(answer_numbers(data["answer"]) - allowed)
    if bad:
        shown = ", ".join(f"{b:g}" for b in bad)
        return data, bad, f"답에 도구 결과에 없는 숫자가 있습니다: {shown}. 도구 결과에 있는 숫자만 그대로 쓰세요"
    return data, [], None


def strip_numbers(answer: str, allowed: set[float]) -> str:
    """근거 없는 숫자가 든 문장을 지운다(줄 단위로 나눈 뒤 문장 단위)."""
    lines = []
    for line in answer.splitlines():
        kept = [s for s in _SENTENCE.split(line) if not (answer_numbers(s) - allowed)]
        if " ".join(kept).strip():
            lines.append(" ".join(kept))
    return "\n".join(lines).strip()


# ── 대화 ────────────────────────────────────────────────────────────
def _history_messages(history: Optional[list]) -> list:
    out = []
    for i, turn in enumerate(history or []):
        role = turn.get("role") if isinstance(turn, dict) else None
        want = "user" if i % 2 == 0 else "assistant"
        if role != want or not isinstance(turn.get("content"), str):
            raise ValueError(f"history[{i}] 는 role {want!r} 와 문자열 content 여야 합니다(user 부터 번갈아)")
        out.append({"role": role, "content": [{"text": turn["content"]}]})
    if out and out[-1]["role"] != "assistant":
        raise ValueError("history 는 assistant 답으로 끝나야 합니다")
    return out


def _mock_key(message: str) -> str:
    """가짜 모드에서 쓸 대본: mock 파일 _when 의 낱말이 메시지에 있으면 그 대본, 없으면 default."""
    table = json.loads((SAMPLE_DIR / MOCK_FILE).read_text(encoding="utf-8"))
    for key, words in table.get("_when", {}).items():
        if any(w in message for w in words):
            return key
    return "default"


def _result(answer: str, calls: list, usage: dict, started: float, uncertain_reason: Optional[str]) -> dict:
    return {
        "answer": answer,
        "tool_calls": calls,
        "usage": usage,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "uncertain": uncertain_reason is not None,
        "uncertain_reason": uncertain_reason,
    }


def chat(message: str, history: Optional[list] = None) -> dict:
    """화면용. {"answer", "tool_calls", "usage", "latency_ms", "uncertain", "uncertain_reason"}.

    history 는 [{"role": "user"|"assistant", "content": str}] (user 부터 번갈아, assistant 로 끝남).
    tool_calls 는 호출 순서대로 {"name", "input", "ok"}.
    """
    started = time.monotonic()
    message = (message or "").strip()
    if not message:
        raise ValueError("message 가 비었습니다")
    usage = {k: 0 for k in USAGE_KEYS}
    blocked = guard_input(message)
    if blocked is not None:
        return _result(blocked, [], usage, started, None)

    msgs = _history_messages(history) + [{"role": "user", "content": [{"text": message}]}]
    outputs: list[dict] = []

    def run_tool(name: str, inp: dict) -> dict:
        if name not in TOOL_FUNCS:
            raise ValueError(f"없는 도구: {name}")
        out = TOOL_FUNCS[name](inp)
        outputs.append(out)
        return out

    key = _mock_key(message) if is_mock() else "real"
    loop = converse_tools(prompt.SYSTEM, msgs, prompt.TOOLS, run_tool,
                          mock_file=MOCK_FILE, mock_key=key, max_turns=MAX_TURNS)
    add_usage(usage, loop.usage)
    calls, model_calls = list(loop.tool_calls), loop.model_calls

    reason = None
    retried = None  # 재질문 이유: None(없음), "number"(숫자 검사), "format"(JSON 형식). 로그에만 남긴다
    bad_numbers: dict[str, list[float]] = {}  # 검사에 걸린 숫자만(원문 없이) 로그에 남긴다. {"1차": [...], "2차": [...]}
    if loop.stop == "max_turns":
        answer, scope, reason = MAX_TURNS_ANSWER, "in", "max_turns"
    else:
        said = [message, *((h or {}).get("content", "") for h in (history or []))]
        allowed = _walk_numbers(outputs) | set().union(*(_numbers(t) for t in said))
        data, bad, error = check_answer(loop.text, allowed)
        if bad:
            bad_numbers["1차"] = bad
        if error is not None:
            retried = "number" if bad else "format"
            retry = converse_tools(
                prompt.SYSTEM, loop.messages + [{"role": "user", "content": [{"text": prompt.RETRY_MESSAGE.format(error=error)}]}],
                prompt.TOOLS, run_tool, mock_file=MOCK_FILE, mock_key=key, max_turns=1, mock_turn_start=model_calls + 1,
            )
            add_usage(usage, retry.usage)
            calls += list(retry.tool_calls)
            model_calls += retry.model_calls
            allowed |= _walk_numbers(outputs)
            data2, bad2, error2 = check_answer(retry.text, allowed) if retry.stop == "end_turn" else (None, [], "도구를 다시 불렀습니다")
            if bad2:
                bad_numbers["2차"] = bad2
            if error2 is None:
                data = data2
            else:
                data = data2 if data2 is not None else data
                if data is None:
                    raise BedrockJSONError(f"상담 답이 두 번 모두 형식 검사를 통과하지 못했습니다: {error} / {error2}", usage)
                data = {**data, "answer": strip_numbers(data["answer"], allowed) or NO_NUMBER_ANSWER}
                reason = "number_check"
        answer, scope = data["answer"].strip(), data["scope"]

        unknown = [u for out in outputs for u in out.get("unrecognized", [])]
        if unknown and ASK_BACK_MARK not in answer:
            asks = [ASK_BACK.format(**u) if u["maybe"] else ASK_BACK_UNKNOWN.format(input=u["input"]) for u in unknown]
            answer = answer + "\n\n" + " ".join(dict.fromkeys(asks))
        if reason is None and scope == "in" and not any(c["ok"] for c in calls):
            reason = "no_tool"

    result = _result(answer, calls, usage, started, reason)
    logger.info(
        "상담 1건: 도구 %s, 도구 %d회, 모델 %d회, 재질문 %s, 근거 없는 숫자 %s, 토큰 %s, %dms, 불확실 %s (prompt=%s)",
        [c["name"] for c in calls], len(calls), model_calls, retried or "없음",
        {k: [f"{n:g}" for n in v] for k, v in bad_numbers.items()} or "없음",
        usage.get("totalTokens", 0), result["latency_ms"], reason, PROMPT_VERSION,
    )
    return result


# ── 시연 전 준비와 한 번 물어보기 ─────────────────────────────────────
def warmup() -> int:
    """pipeline.suggest 가 쓰는 사전 이름 임베딩을 모두 캐시(data/raw/embed_cache.json)에 만든다. 실제 모드에서만.

    캐시가 없으면 첫 되묻기 질문에서 사전 이름 200개를 임베딩하느라 40초 넘게 걸린다(11/17 실측 39.5초).
    이미 캐시에 있는 이름은 다시 부르지 않으므로 여러 번 돌려도 된다.
    """
    from pipeline import embed
    from pipeline.suggest import suggest

    if embed.is_mock():  # .env 를 읽어 BEDROCK_MOCK·EMBED_MODEL_ID 를 올린다
        print("가짜 모드(BEDROCK_MOCK=1)라 임베딩을 부르지 않습니다. BEDROCK_MOCK=0 과 EMBED_MODEL_ID 를 설정한 뒤 다시 실행하세요.")
        return 1
    before, started = embed.usage()["calls"], time.monotonic()
    top = suggest("도커", top=1)  # 사전 이름 전체와 질의 1개를 임베딩한다
    calls = embed.usage()["calls"] - before
    print(f"임베딩 호출 {calls}번, {time.monotonic() - started:.1f}초. 캐시: {embed.CACHE_FILE.name} (data/raw/, 커밋하지 않음)")
    print(f"확인: '도커' → {top[0]['canonical']} (점수 {top[0]['score']})")
    return 0


def main() -> int:
    import argparse
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="학습 상담 에이전트 (#25)")
    ap.add_argument("message", nargs="?", help="한 번 물어볼 질문. 결과(답, 도구, 토큰, 시간)를 JSON 으로 출력한다")
    ap.add_argument("--warmup", action="store_true", help="시연 전 준비: 사전 이름 임베딩 캐시를 만든다(실제 모드)")
    args = ap.parse_args()
    if args.warmup:
        return warmup()
    if args.message:
        print(json.dumps(chat(args.message), ensure_ascii=False, indent=1))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(SAMPLE_DIR.parent.parent / ".env")  # 이미 설정된 환경 변수는 덮어쓰지 않는다
    except ImportError:
        pass
    raise SystemExit(main())
