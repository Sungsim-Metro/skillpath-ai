"""상담 구조 비교(#93·#94). 같은 질문 세트를 구조마다 한 번씩 돌려 코드 지표를 센다. 계산은 전부 코드로 한다.

실행 (저장소 루트에서)
  python -m ai.eval.agent_compare                       개선용 문항(data/eval/agent_cases.json), 구조 0, 가짜 모드
  python -m ai.eval.agent_compare --structures 0 A 3    구조 0(화면 경로), A(상담 에이전트), 3(팀장형)
  python -m ai.eval.agent_compare --bedrock             실제 모드(BEDROCK_MOCK=0 과 모델·가드레일·DynamoDB 설정 필요)
  python -m ai.eval.agent_compare --set holdout         보지 않은 문항. 숫자만 출력(문항 id·원문 없음). 채점 직전에 한 번만
  python -m ai.eval.agent_compare --judge <답 파일> [--rounds 2] [--human-sheet] [--bedrock --max-judge-calls N]
                                                        상담 답 채점(ai/eval/judge_answer.py, 기준표 ai/eval/JUDGE_ANSWER.md)
  python -m ai.eval.agent_compare --agreement <채점 결과 파일> <사람 채점 CSV>   LLM·사람 채점 일치율

구조
- 0 화면 경로: backend.chat.handle_message(가드레일 → 발화 해석 → 코드 분기 → Gap 또는 검토 추천). 지금 화면이 쓰는 경로
- A 상담 에이전트 + 추천 도구: ai.agent.chat(도구 호출 반복, 과정은 recommend_courses = 화면과 같은 검증 추천)
- 3 팀장형(일현 구조): backend.chat.handle_message(architecture="supervised"). 화면의 --supervised 경로와 같다(app/main.py).
  의도는 팀장 계획(ai.supervisor.interpret_turn)으로 정하고, 팀장이 되물으면 clarify 로 센다
- 참고 문항(AI 엔지니어 R1·R2)은 구조 0·3 만 돌리고 점수에서는 뺀다
- 모든 구조의 입력 검사는 ai.guardrail.check_input 하나다. 가드레일 문항(regression)은 비교 점수에서 빼고 결과가 같은지만 본다

지표 (문항마다 기록하고 코드로 합친다)
- 의도 정확도: 관찰한 의도(gap·demand·courses·out_of_scope·blocked 등)가 expect_intent 와 같은 비율(가드레일·참고 문항 제외).
  그 구조에 없는 의도를 기대하는 문항(구조 0 의 demand)은 "해당 없음"으로 따로 세고 분모에서 뺀다
- 되묻기 정확도: 표기 애매 문항에서 되묻기 여부가 expect_ask_back 과 같은 비율(답 문장의 되묻기 표현으로 판정).
  기술 표기를 되묻는 기능이 없는 구조(구조 0)는 "해당 없음"으로 따로 세고 분모에서 뺀다
- 가드레일: 정책상 차단·통과·검사 실패를 따로 센다. 검사 실패를 차단으로 세지 않는다
- 불확실 비율: 보여 준 과정 중 match 가 uncertain 인 비율
- 모델 호출 수(Guardrails 호출은 포함하지 않음), 토큰, 시간(중앙값·최대). 두 구조 모두 모델 호출 응답의 토큰을 직접 더한다(가짜 모드는 0, 가짜 대본 차례는 mock_turns)
결과는 outputs/eval/agent_compare_*.json 에 저장한다(.gitignore 대상).
상담 답 원문과 근거 자료(그 답을 만들 때 코드·도구가 낸 결과 요약)는 채점용으로 outputs/eval/agent_answers_*.json 에만 저장한다.
화면에는 출력하지 않는다(보지 않은 문항도 파일에만).

캐시: 추천(backend.api 의 추천 캐시)·수요(60초 캐시) 같은 메모리 캐시가 구조·문항 사이에 남으면 뒤에 도는 쪽의 호출 수와
시간이 줄어 비교가 틀어진다. backend 에 캐시를 비우는 공개 함수가 없어(내부 변수는 건드리지 않는다), (구조, 문항)마다
이 스크립트를 새 프로세스(--one)로 띄워 늘 빈 캐시에서 시작한다. 그만큼 DynamoDB 수요 조회가 문항마다 한 번씩 더 일어난다.
하위 프로세스는 Lambda 도구와 비교 실험 설정(LOCAL_ENV)을 비워 로컬에서만 돈다. 문항마다 Probe 가 센 모델 호출 수와
호출 기록(ai.usage) 수를 대조해 다르면 멈춘다. 보지 않은 문항은 구조마다 실제 모드 한 번만 돈다(outputs/eval/agent_holdout_runs.log).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # 이미 설정된 환경 변수는 덮어쓰지 않는다
except ImportError:
    pass

from ai import bedrock, guardrail  # noqa: E402
from ai import chat as intake  # noqa: E402

EVAL_DATA = ROOT / "data" / "eval"  # 공개 범위 밖
CASES = EVAL_DATA / "agent_cases.json"
HOLDOUT = EVAL_DATA / "agent_cases_holdout.json"
OUT_DIR = ROOT / "outputs" / "eval"
INTENTS = ("gap", "demand", "courses", "out_of_scope", "blocked")
# 구조마다 고를 수 있는 의도. 없는 의도를 기대하는 문항은 "해당 없음"으로 따로 세고 의도 정확도 분모에서 뺀다.
# 구조 0(화면 경로)의 해석 action 에는 "기술 하나 수요"(demand)가 없다(gap·courses·note·summary)
SUPPORTED_INTENTS = {"0": {"gap", "courses", "out_of_scope", "blocked"},
                     "3": {"gap", "courses", "out_of_scope", "blocked"}}  # 3번도 화면 경로의 해석 action 을 쓴다
# 참고 문항(AI 엔지니어 R1·R2)을 돌리는 구조. 점수(summarize)에서는 늘 뺀다
REFERENCE_STRUCTURES = {"0", "3"}
# 사전에 없는 기술 표기를 되묻는 기능이 있는 구조. 구조 0(화면 경로)은 없다: backend/chat.py 의 _skill 이 모르는 표기를
# 그대로 두고, ai/chat.py 의 status(clarify_role·incomplete)는 직무·미완성 입력 확인이지 기술 표기 되묻기가 아니다(11/19 확인).
# 없는 구조는 표기 애매 문항의 되묻기를 "해당 없음"으로 따로 세고 분모에서 뺀다
ASK_BACK_STRUCTURES = {"A", "B"}
RESULT_NOTES = [
    "모델 호출 수에 Guardrails(ApplyGuardrail) 호출은 포함하지 않음",
    "구조·문항마다 새 프로세스로 실행해 캐시가 비어 있음, DynamoDB 수요 조회가 문항마다 한 번씩 더 일어남",
    "KB Retrieve(과정 검색)·임베딩 호출은 상한 없이 개수만 기록함(kb_retrieve_calls, embedding_calls)",
    "구조 0은 이름 댄 기술 대신 상위 부족 기술을 추천함(backend/chat.py _analyze). 구조 A 는 이름 댄 기술을 먼저 추천함(수요에 없으면 공고 수 정보 없음)",
    "Lambda 도구 호출(SKILLPATH_*_FUNCTION)과 비교 실험(EXPERIMENT_MODELS·AB_STRUCTURES)은 끄고 로컬에서 돌림(11/22부터)",
    "문항마다 Probe 가 센 모델 호출 수와 호출 기록(usage) 수가 같은지 대조하고, 다르면 멈춤(11/22부터)",
]
# 하위 프로세스에서 강제로 비우는 환경 변수. Lambda 로 가면 그 안의 모델 호출을 Probe 가 세지도, 한도로 막지도 못한다
LOCAL_ENV = {"SKILLPATH_DEMAND_FUNCTION": "", "SKILLPATH_RECOMMEND_FUNCTION": "",
             "EXPERIMENT_MODELS": "", "AB_STRUCTURES": ""}
COUNT_MISMATCH_EXIT = 4            # 호출 수 대조가 어긋난 하위 프로세스의 종료 코드
# 보지 않은 문항 실제 실행 기록. 구조마다 "완료" 줄이 있으면 다시 돌리지 않는다
HOLDOUT_LOG = OUT_DIR / "agent_holdout_runs.log"
HOLDOUT_DONE_BEFORE = {"0": "agent_compare_holdout_bedrock_20261121-222945.json",  # 잠금을 만들기 전에 끝낸 실행
                       "A": "agent_compare_holdout_bedrock_20261121-222945.json"}
ROW_MARK = "AGENT_COMPARE_ROW "  # 하위 프로세스가 결과 한 줄 앞에 붙이는 표시(다른 출력과 섞이지 않게)
CHILD_TIMEOUT = 600                # 문항 하나의 하위 프로세스 시간 한도(초)
# 호출 한도: 부모가 남은 한도를 하위 프로세스에 환경 변수로 넘기고, 하위 프로세스는 호출 직전에 한도를 넘으면 멈춘다
MODEL_BUDGET_ENV = "AGENT_COMPARE_MODEL_BUDGET"
GUARDRAIL_BUDGET_ENV = "AGENT_COMPARE_GUARDRAIL_BUDGET"
LIMIT_EXIT = 3                     # 한도에 걸려 멈춘 하위 프로세스의 종료 코드


class BudgetExceeded(BaseException):
    """호출 한도를 넘기 직전. BaseException 이라 상담 코드의 except Exception 이 삼키지 않고 바로 멈춘다."""


class LimitReached(RuntimeError):
    """부모: 호출 한도에 걸려 측정을 멈춤(그때까지의 결과만 저장)."""


class CountMismatch(RuntimeError):
    """Probe 가 센 모델 호출 수와 호출 기록 수가 다르거나, Lambda 쪽 호출 기록이 있음."""
# 답에 되묻기가 있는지(표기 애매 문항). 상담 에이전트의 보충 문장 "OO는 XX를 말씀하신 건가요?" 와 같은 꼴
ASK_BACK = re.compile(r"말씀하신\s*건가요|무엇을\s*말씀|어떤\s*기술을\s*말씀|맞나요\?")
EVIDENCE_MAX = 6000  # 근거 자료 요약 글자 수 상한(채점 입력이 너무 길어지지 않게)
ANSWER_KEYS = ("answer", "evidence")  # 결과 행에서 떼어 답 파일에만 저장하는 칸


def evidence_text(parts: dict) -> str:
    """근거 자료를 JSON 문자열로. 상한을 넘으면 자르고 잘렸다고 적는다."""
    text = json.dumps(parts, ensure_ascii=False)
    return text if len(text) <= EVIDENCE_MAX else text[:EVIDENCE_MAX] + " …(잘림)"


class Probe:
    """한 문항을 도는 동안 입력 검사 결과·발화 해석·모델 호출·추천 도구 결과를 옆에서 적는다(원문은 적지 않음)."""

    def __init__(self):
        self.guard = None
        self.turn = None
        self.model_calls = 0   # 실제 모델 호출(가짜 모드는 세지 않음)
        self.mock_turns = 0    # 가짜 대본 차례
        self.tokens = 0
        self.recommendations = []  # 상담 에이전트 recommend_courses 결과
        self.guardrail_calls = 0   # 실제 ApplyGuardrail 호출(모델 호출 수와 따로 셈)
        self.kb_retrieve_calls = 0  # 과정 검색의 KB Retrieve 호출(상한 없음, 개수만)
        self.embedding_calls = 0    # 임베딩 호출(상한 없음, 개수만. 캐시에 있으면 부르지 않음)
        self.usage_records = 0         # 실제 모델 응답의 호출 기록(ai.bedrock → ai.usage). model_calls 와 같아야 한다
        self.mock_usage_records = 0    # 가짜 대본 차례의 호출 기록. mock_turns 와 같아야 한다
        self.remote_usage_records = 0  # Lambda 가 돌려준 호출 기록(usage.record). 로컬로 돌리므로 0 이어야 한다
        self._embed_before = 0
        self._saved = None
        # 카운터와 한도 검사를 한 덩어리로 묶는다. 스레드로 동시에 불려도 수가 맞고 한도를 넘지 않게
        # (한도는 호출 전에 자리를 잡아 두는 _reserved 로 보고, 수는 응답을 받은 뒤 센다)
        self._lock = threading.Lock()
        self._reserved = {"model": 0, "guardrail": 0}

    @staticmethod
    def _budget(name: str):
        value = os.getenv(name, "").strip()
        return int(value) if value else None

    def __enter__(self):
        check, interpret, call, call_tools, assess = (guardrail.check_input, intake.interpret,
                                                     bedrock._call, bedrock._call_tools, guardrail.bedrock_assess)
        self._saved = (check, interpret, call, call_tools, assess)
        from pipeline import embed, search

        self._embed, self._search = embed, search
        self._embed_before = embed.usage()["calls"]
        kb_scores = search._kb_scores
        self._saved_kb = kb_scores

        def counted_kb(*a, **k):
            self.kb_retrieve_calls += 1  # 실제 모드에서만 불린다(가짜 모드는 규칙 검색)
            return kb_scores(*a, **k)

        search._kb_scores = counted_kb
        model_budget, guard_budget = self._budget(MODEL_BUDGET_ENV), self._budget(GUARDRAIL_BUDGET_ENV)

        def reserve(kind: str, budget: int | None, label: str) -> None:
            with self._lock:
                if budget is not None and self._reserved[kind] >= budget:
                    raise BudgetExceeded(label)  # 호출하기 전에 멈춘다
                self._reserved[kind] += 1

        def watched_assess(text, source):
            if not bedrock.is_mock() and guardrail._guardrails_enabled(source):
                reserve("guardrail", guard_budget, "ApplyGuardrail 호출 한도")
                with self._lock:
                    self.guardrail_calls += 1
            return assess(text, source)

        def watched_check(text):
            self.guard = check(text)
            return self.guard

        def watched_interpret(*a, **k):
            self.turn = interpret(*a, **k)
            return self.turn

        def counted(fn):
            def wrapper(*a, **k):
                mock = bedrock.is_mock()
                if not mock:
                    reserve("model", model_budget, "모델 호출 한도")
                result = fn(*a, **k)
                with self._lock:
                    if mock:
                        self.mock_turns += 1
                    else:
                        self.model_calls += 1
                        usage = result[2] or {}
                        self.tokens += usage.get("totalTokens", usage.get("inputTokens", 0) + usage.get("outputTokens", 0))
                return result
            return wrapper

        # 호출 기록 대조: ai.bedrock 은 응답마다 record_usage 를 부르고, Lambda 도구는 usage.record 로 기록을 넘긴다
        from ai import usage as usage_log

        self._usage_log = usage_log
        local_record, remote_record = bedrock.record_usage, usage_log.record
        self._saved_records = (local_record, remote_record)

        def watched_local_record(stage, attempt, call_usage, mock, **k):
            with self._lock:
                if mock:
                    self.mock_usage_records += 1
                else:
                    self.usage_records += 1
            return local_record(stage, attempt, call_usage, mock, **k)

        def watched_remote_record(*a, **k):
            with self._lock:
                self.remote_usage_records += 1
            return remote_record(*a, **k)

        guardrail.check_input = watched_check
        intake.interpret = watched_interpret
        bedrock._call, bedrock._call_tools = counted(call), counted(call_tools)
        guardrail.bedrock_assess = watched_assess
        bedrock.record_usage, usage_log.record = watched_local_record, watched_remote_record
        return self

    def __exit__(self, *exc):
        (guardrail.check_input, intake.interpret, bedrock._call, bedrock._call_tools,
         guardrail.bedrock_assess) = self._saved
        bedrock.record_usage, self._usage_log.record = self._saved_records
        self._search._kb_scores = self._saved_kb
        self.embedding_calls = self._embed.usage()["calls"] - self._embed_before
        return False

    def count_fields(self) -> dict:
        """결과 행에 남길 호출 수 대조 칸."""
        return {"usage_records": self.usage_records, "mock_usage_records": self.mock_usage_records,
                "remote_usage_records": self.remote_usage_records}


def check_counts(row: dict) -> None:
    """Probe 가 센 수와 호출 기록 수가 같은지 본다. 다르면 CountMismatch(어느 칸이 다른지만, 내용 없음)."""
    wrong = []
    if row.get("usage_records", row["model_calls"]) != row["model_calls"]:
        wrong.append(f"모델 호출 {row['model_calls']} ≠ 호출 기록 {row['usage_records']}")
    if row.get("mock_usage_records", row["mock_turns"]) != row["mock_turns"]:
        wrong.append(f"가짜 차례 {row['mock_turns']} ≠ 가짜 기록 {row['mock_usage_records']}")
    if row.get("remote_usage_records", 0):
        wrong.append(f"Lambda 호출 기록 {row['remote_usage_records']}건(로컬로 돌려야 함)")
    if wrong:
        raise CountMismatch("호출 수 대조 실패: " + ", ".join(wrong))


def guard_kind(result) -> str:
    if result is None:
        return "none"
    if guardrail.is_check_failure(result):
        return "check_failed"
    return "blocked" if result.blocked else "pass"


def screen_intent(probe: Probe) -> str:
    """구조 0 이 고른 의도. 막히면 blocked, 해석 결과의 status·action 으로 나머지를 정한다."""
    kind = guard_kind(probe.guard)
    if kind in ("blocked", "check_failed"):
        return kind
    turn = probe.turn
    if turn is None:
        return "no_turn"
    if turn.status != "ok":
        return turn.status  # out_of_scope, unsupported, clarify_role, incomplete, blocked
    return turn.action      # gap, courses, note, summary(구조 0 에는 demand 가 따로 없다)


def supervised_intent(probe: Probe, plans: list) -> str:
    """구조 3 이 고른 의도. 막히면 blocked, 팀장이 되물으면 clarify, 나머지는 팀장 계획의 Turn 으로 구조 0 과 같게 정한다."""
    kind = guard_kind(probe.guard)
    if kind in ("blocked", "check_failed"):
        return kind
    if not plans:
        return "no_turn"
    plan = plans[-1]
    if plan.question:
        return "clarify"
    turn = plan.turn
    return turn.status if turn.status != "ok" else turn.action


def run_screen(case: dict) -> dict:
    """구조 0: 화면 경로 handle_message. 문항마다 새 대화."""
    return _run_chat(case, "screen")


def run_supervised(case: dict) -> dict:
    """구조 3(팀장형): 화면의 --supervised 경로(app/main.py)와 같은 handle_message(architecture="supervised"). 문항마다 새 대화."""
    return _run_chat(case, "supervised")


def _run_chat(case: dict, architecture: str) -> dict:
    from ai import supervisor
    from backend import api
    from backend import chat as screen

    state = screen.Conversation()
    gaps, plans = [], []
    original_gap, original_plan = api.get_gap, supervisor.interpret_turn

    def watched_gap(*a, **k):
        rows = original_gap(*a, **k)
        gaps.append(rows)
        return rows

    def watched_plan(*a, **k):  # backend/chat.py 가 부를 때 supervisor 모듈에서 이 이름을 찾는다
        plan = original_plan(*a, **k)
        plans.append(plan)
        return plan

    api.get_gap, supervisor.interpret_turn = watched_gap, watched_plan
    try:
        with Probe() as probe:
            start = time.perf_counter()
            reply = screen.handle_message(state, case["text"], job=case["job"], sidebar_skills=[],
                                          architecture=architecture)
            seconds = time.perf_counter() - start
    finally:
        api.get_gap, supervisor.interpret_turn = original_gap, original_plan
    courses = reply.courses or []
    gap_keys = ("skill", "owned", "postings", "of", "required_pct", "user_level", "required_level")
    evidence = {
        "gap": [{k: r[k] for k in gap_keys if k in r} for rows in gaps for r in rows],
        "courses": [{k: c.get(k) for k in ("gap_skill", "title", "level", "match", "reason")} for c in courses],
    }
    return {
        "guard": guard_kind(probe.guard),
        "intent": supervised_intent(probe, plans) if architecture == "supervised" else screen_intent(probe),
        "decisions": list(reply.supervisor_decisions),  # 3번 팀장 판정 코드(continue·clarify·result_approved 등). 0번은 빈 목록
        "ask_back": bool(ASK_BACK.search(reply.text)),
        "courses": len(courses),
        "uncertain_courses": sum(1 for c in courses if c.get("match") == "uncertain"),
        "model_calls": probe.model_calls,
        "mock_turns": probe.mock_turns,
        "guardrail_calls": probe.guardrail_calls,
        "kb_retrieve_calls": probe.kb_retrieve_calls,
        "embedding_calls": probe.embedding_calls,
        **probe.count_fields(),
        "tokens": probe.tokens,
        "seconds": round(seconds, 3),
        "answer_chars": len(reply.text),
        "answer": reply.text,
        "evidence": evidence_text(evidence),
    }


def agent_intent(probe: Probe, result: dict) -> str:
    """구조 A 가 고른 의도. 막히면 blocked, 도구로 정한다. 도구 없이 범위 안 질문에 답하면 no_tool(에이전트가 표시)."""
    kind = guard_kind(probe.guard)
    if kind in ("blocked", "check_failed"):
        return kind
    names = [c["name"] for c in result["tool_calls"]]
    if "recommend_courses" in names:
        return "courses"
    if "get_gap" in names:
        return "gap"
    if "get_skill_demand" in names:
        return "demand"
    if result.get("uncertain_reason") == "no_tool":
        return "no_tool"
    return "out_of_scope"


def run_agent(case: dict) -> dict:
    """구조 A: 상담 에이전트 + recommend_courses. 문항마다 새 대화(기록 없음)."""
    from ai import agent

    tool_log = []
    saved_tools = dict(agent.TOOL_FUNCS)

    def logged(name, fn):
        def call(inp):
            out = fn(inp)
            tool_log.append({"tool": name, "input": inp, "output": out})
            return out
        return call

    with Probe() as probe:
        original = agent.tool_recommend_courses

        def watched(skills):
            out = original(skills)
            probe.recommendations.append(out)
            return out

        agent.tool_recommend_courses = watched  # TOOL_FUNCS 의 람다가 부를 때 이 이름을 찾는다
        for name, fn in list(agent.TOOL_FUNCS.items()):  # 근거 자료: 도구 이름·입력·출력
            agent.TOOL_FUNCS[name] = logged(name, fn)
        try:
            start = time.perf_counter()
            result = agent.chat(case["text"])
            seconds = time.perf_counter() - start
        finally:
            agent.tool_recommend_courses = original
            agent.TOOL_FUNCS.clear()
            agent.TOOL_FUNCS.update(saved_tools)
    courses = [c for out in probe.recommendations for r in out["recommendations"] for c in r["courses"]]
    return {
        "guard": guard_kind(probe.guard),
        "intent": agent_intent(probe, result),
        "ask_back": bool(ASK_BACK.search(result["answer"])),
        "courses": len(courses),
        "uncertain_courses": sum(1 for c in courses if c["match"] == "uncertain"),
        "model_calls": probe.model_calls,
        "mock_turns": probe.mock_turns,
        "guardrail_calls": probe.guardrail_calls,
        "kb_retrieve_calls": probe.kb_retrieve_calls,
        "embedding_calls": probe.embedding_calls,
        **probe.count_fields(),
        "tokens": probe.tokens,
        "seconds": round(seconds, 3),
        "answer_chars": len(result["answer"]),
        "tools": [c["name"] for c in result["tool_calls"]],
        "not_found": [s for out in probe.recommendations for s in out.get("not_found", [])],  # 수요 집계에 없어 추천하지 않은 기술
        "uncertain_reason": result.get("uncertain_reason"),
        "answer": result["answer"],
        "evidence": evidence_text({"tools": tool_log}),
    }


STRUCTURES = {"0": run_screen, "A": run_agent, "3": run_supervised}


def summarize(cases: list[dict], rows: dict[str, dict], structure: str = "") -> dict:
    """구조 하나의 지표. 비교 점수는 가드레일(regression)·참고(reference) 문항을 뺀 문항으로 센다.

    그 구조에 없는 의도를 기대하는 문항은 의도 정확도에서 "해당 없음"으로 빼고 따로 센다(SUPPORTED_INTENTS).
    """
    supported = SUPPORTED_INTENTS.get(structure)
    compared = [c for c in cases if not c.get("regression") and not c.get("reference")]
    not_applicable = [c for c in compared if supported is not None and c["expect_intent"] not in supported]
    scored = [c for c in compared if c not in not_applicable]
    ambiguous_all = [c for c in compared if c["category"] == "표기 애매"]
    ask_back_na = [] if structure in ASK_BACK_STRUCTURES or not structure else ambiguous_all
    ambiguous = [c for c in ambiguous_all if c not in ask_back_na]
    guarded = [c for c in cases if c.get("regression")]
    shown = sum(rows[c["id"]]["courses"] for c in cases)
    seconds = [rows[c["id"]]["seconds"] for c in cases]
    return {
        "intent_correct": sum(rows[c["id"]]["intent"] == c["expect_intent"] for c in scored), "intent_total": len(scored),
        "intent_wrong_ids": [c["id"] for c in scored if rows[c["id"]]["intent"] != c["expect_intent"]],
        "intent_not_applicable": len(not_applicable),
        "intent_not_applicable_ids": [c["id"] for c in not_applicable],
        "ask_back_correct": sum(rows[c["id"]]["ask_back"] == c["expect_ask_back"] for c in ambiguous),
        "ask_back_total": len(ambiguous),
        "ask_back_not_applicable": len(ask_back_na),
        "guard_blocked": sum(rows[c["id"]]["guard"] == "blocked" for c in guarded), "guard_total": len(guarded),
        "guard_check_failed": sum(rows[c["id"]]["guard"] == "check_failed" for c in cases),
        "uncertain_ratio": round(sum(rows[c["id"]]["uncertain_courses"] for c in cases) / shown, 3) if shown else None,
        "courses_shown": shown,
        "model_calls": sum(rows[c["id"]]["model_calls"] for c in cases),
        "guardrail_calls": sum(rows[c["id"]].get("guardrail_calls", 0) for c in cases),
        "kb_retrieve_calls": sum(rows[c["id"]].get("kb_retrieve_calls", 0) for c in cases),
        "embedding_calls": sum(rows[c["id"]].get("embedding_calls", 0) for c in cases),
        "tokens": sum(rows[c["id"]]["tokens"] for c in cases),
        "seconds_median": round(statistics.median(seconds), 3) if seconds else None,
        "seconds_max": max(seconds) if seconds else None,
    }


def run_isolated(structure: str, case_set: str, case_id: str, budgets: dict | None = None) -> dict:
    """(구조, 문항) 하나를 새 프로세스로 돌려 결과 행을 받는다. 메모리 캐시가 늘 비어 있다.

    하위 프로세스는 같은 환경 변수(BEDROCK_MOCK 등)를 물려받는다. 실패하면 멈춘다(통과로 세지 않음).
    오류 원문은 문항 내용이 섞일 수 있어 출력하지 않고 종료 코드만 알린다.
    """
    cmd = [sys.executable, "-m", "ai.eval.agent_compare", "--one", structure, case_id, "--set", case_set]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **LOCAL_ENV,
           **{k: str(v) for k, v in (budgets or {}).items() if v is not None}}
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env, timeout=CHILD_TIMEOUT)
    if proc.returncode == LIMIT_EXIT:
        raise LimitReached(f"구조 {structure} 문항 {case_id} 에서 호출 한도에 걸려 멈췄습니다")
    if proc.returncode == COUNT_MISMATCH_EXIT:
        raise CountMismatch(f"구조 {structure} 문항 {case_id} 에서 호출 수 대조가 어긋나 멈춥니다")
    rows = [line[len(ROW_MARK):] for line in proc.stdout.splitlines() if line.startswith(ROW_MARK)]
    if proc.returncode != 0 or len(rows) != 1:
        raise RuntimeError(f"구조 {structure} 문항 {case_id} 하위 프로세스 실패(종료 코드 {proc.returncode}). 멈춥니다")
    return json.loads(rows[0])


def evaluate(cases: list[dict], structures: list[str], isolate: bool = False, case_set: str = "dev",
             max_model_calls: int | None = None, max_guardrail_calls: int | None = None,
             partial: dict | None = None) -> dict:
    """구조마다 문항을 돌려 지표를 낸다. isolate=True 면 (구조, 문항)마다 새 프로세스(실행 명령의 기본).

    max_* 는 이번 실행 전체의 호출 한도(구조·문항 합계)다. 남은 한도를 하위 프로세스에 넘기고, 넘기 직전에 멈춘다(LimitReached).
    partial 을 주면 멈출 때까지 끝난 행을 거기에 담는다(구조 → {문항 id → 행}).
    """
    out = {}
    used = {"model": 0, "guardrail": 0}
    partial = {} if partial is None else partial
    for name in structures:
        mine = [c for c in cases if not c.get("reference") or name in REFERENCE_STRUCTURES]  # 참고 문항은 0·3 만
        rows = partial.setdefault(name, {})
        for c in mine:
            if isolate:
                budgets = {MODEL_BUDGET_ENV: None if max_model_calls is None else max_model_calls - used["model"],
                           GUARDRAIL_BUDGET_ENV: None if max_guardrail_calls is None else max_guardrail_calls - used["guardrail"]}
                rows[c["id"]] = run_isolated(name, case_set, c["id"], budgets)
            else:
                rows[c["id"]] = STRUCTURES[name](c)
                check_counts(rows[c["id"]])
            used["model"] += rows[c["id"]]["model_calls"]
            used["guardrail"] += rows[c["id"]].get("guardrail_calls", 0)
        out[name] = {"summary": summarize(mine, rows, name), "rows": rows}
    return out


def run_one(structure: str, case_set: str, case_id: str) -> int:
    """하위 프로세스: 문항 하나를 돌려 결과 행을 ROW_MARK 한 줄로 출력한다(문항 원문은 출력하지 않음)."""
    path = HOLDOUT if case_set == "holdout" else CASES
    case = next((c for c in json.loads(path.read_text(encoding="utf-8"))["cases"] if c["id"] == case_id), None)
    if case is None or structure not in STRUCTURES:
        return 2
    os.environ.update(LOCAL_ENV)  # 부모가 넘겼더라도 한 번 더: Lambda·비교 실험을 끄고 로컬에서만 돈다
    try:
        row = STRUCTURES[structure](case)
        check_counts(row)
    except BudgetExceeded as e:
        print(f"호출 한도에 걸려 멈춥니다: {e}")
        return LIMIT_EXIT
    except CountMismatch as e:
        print(str(e))
        return COUNT_MISMATCH_EXIT
    print(ROW_MARK + json.dumps(row, ensure_ascii=False))
    return 0


GUARD_CASES = EVAL_DATA / "guardrail_cases.json"  # 가드레일 개선용 33문항만. 보지 않은 문항 파일은 이 모드에서 읽지 않는다
GUARD_PURPOSE = "개선용, 연결 확인 목적"


class GuardStop(BaseException):
    """가드레일을 통과한 직후 멈춤(답변 생성까지 가지 않음). 상담 코드의 except Exception 이 삼키지 않는다."""


def guard_outcome(result) -> str:
    kind = guard_kind(result)
    return {"pass": "pass", "blocked": "blocked", "check_failed": "check_failed"}.get(kind, "none")


def run_guard_wiring(structure: str, case: dict) -> dict:
    """한 문항을 구조의 입구(가드레일)까지만 돌린다. "standalone" 은 check_input 을 직접 부른 단독 결과.

    check_input 을 이 평가 코드 안에서만 감싼다(ai/guardrail.py·backend 는 그대로). 통과면 GuardStop 으로 멈추고,
    막히거나 검사 실패면 끝까지 진행시켜 구조가 차단·실패 안내로 끝나는지(wired) 본다. 원문·답은 남기지 않는다.
    """
    from ai import agent
    from backend import chat as screen

    seen = []
    with Probe() as probe:
        inner = guardrail.check_input  # Probe 가 감싼 것(결과를 probe.guard 에 적음)

        def stopper(text):
            result = inner(text)
            seen.append(result)
            if structure != "standalone" and not result.blocked:
                raise GuardStop
            return result

        guardrail.check_input = stopper
        stopped, reply, answer = False, None, None
        try:
            if structure == "standalone":
                guardrail.check_input(case["text"])
            elif structure == "A":
                answer = agent.chat(case["text"])["answer"]
            else:
                reply = screen.handle_message(screen.Conversation(), case["text"], job="cloud_engineer", sidebar_skills=[],
                                              architecture="supervised" if structure == "3" else "screen")
        except GuardStop:
            stopped = True
        finally:
            guardrail.check_input = inner  # Probe 가 나갈 때 원래 함수로 되돌린다
    outcome = guard_outcome(seen[0]) if seen else "none"
    if structure == "standalone":
        wired = len(seen) == 1
    elif outcome == "pass":
        wired = stopped
    elif structure == "A":
        wired = answer == guardrail.message_for(seen[0], guardrail.BLOCK_MESSAGE)
    else:
        wired = reply is not None and reply.action == ("blocked" if outcome == "blocked" else "intake")
    return {"id": case["id"], "expect": case["expect"], "outcome": outcome,
            "wired": bool(wired and len(seen) == 1 and probe.model_calls == 0 and probe.mock_turns == 0),
            "check_calls": len(seen), "model_calls": probe.model_calls, "guardrail_calls": probe.guardrail_calls}


def summarize_guard(rows: list[dict], standalone: dict[str, str] | None = None) -> dict:
    """미탐(막을 문항이 통과) · 오탐(통과할 문항이 정책상 막힘) · 검사 실패는 따로. 단독 결과와 다른 문항 id."""
    block = [r for r in rows if r["expect"] == "block"]
    allow = [r for r in rows if r["expect"] == "pass"]
    return {
        "miss": sum(r["outcome"] == "pass" for r in block), "block_total": len(block),
        "false_positive": sum(r["outcome"] == "blocked" for r in allow), "pass_total": len(allow),
        "check_failed": sum(r["outcome"] == "check_failed" for r in rows),
        "differs_from_standalone": [] if standalone is None else [r["id"] for r in rows if r["outcome"] != standalone[r["id"]]],
        "not_wired": [r["id"] for r in rows if not r["wired"]],
        "model_calls": sum(r["model_calls"] for r in rows),
        "guardrail_calls": sum(r["guardrail_calls"] for r in rows),
    }


def guard_wiring(structures: list[str], max_model_calls: int | None, max_guardrail_calls: int | None,
                 cases: list[dict] | None = None) -> dict:
    """단독 결과를 먼저 재고, 구조마다 같은 문항을 입구까지 돌린다. 한도는 실행 전체(단독 포함) 합계."""
    os.environ.update(LOCAL_ENV)  # Lambda·비교 실험 끄기(구조 비교와 같은 조건)
    if cases is None:
        cases = json.loads(GUARD_CASES.read_text(encoding="utf-8"))["cases"]
    used = {"model": 0, "guardrail": 0}
    rows: dict[str, list[dict]] = {}
    saved_env = {k: os.environ.get(k) for k in (MODEL_BUDGET_ENV, GUARDRAIL_BUDGET_ENV)}
    try:
        for name in ["standalone", *structures]:
            rows[name] = []
            for c in cases:
                for env, limit, key in ((MODEL_BUDGET_ENV, max_model_calls, "model"),
                                        (GUARDRAIL_BUDGET_ENV, max_guardrail_calls, "guardrail")):
                    if limit is None:
                        os.environ.pop(env, None)
                    else:
                        os.environ[env] = str(limit - used[key])
                try:
                    row = run_guard_wiring(name, c)
                except BudgetExceeded as e:
                    raise LimitReached(f"{name} 문항 {c['id']} 에서 호출 한도({e})에 걸려 멈췄습니다") from None
                used["model"] += row["model_calls"]
                used["guardrail"] += row["guardrail_calls"]
                rows[name].append(row)
    finally:
        for k, v in saved_env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    standalone = {r["id"]: r["outcome"] for r in rows["standalone"]}
    summary = {name: summarize_guard(r, None if name == "standalone" else standalone) for name, r in rows.items()}
    return {"purpose": GUARD_PURPOSE, "cases": GUARD_CASES.name, "summary": summary, "rows": rows}


def run_guard_wiring_cli(args, structures: list[str]) -> int:
    if args.set != "dev":
        print("--guard-wiring 은 가드레일 개선용 33문항만 씁니다(보지 않은 문항 금지). --set 을 빼세요. 멈춥니다.")
        return 1
    if args.bedrock and (args.max_model_calls is None or args.max_guardrail_calls is None):
        print("실제 모드는 --max-model-calls 와 --max-guardrail-calls 를 함께 줘야 합니다. 멈춥니다.")
        return 1
    if not GUARD_CASES.exists():
        print(f"문항 파일이 없어 건너뜁니다: {GUARD_CASES.relative_to(ROOT).as_posix()}")
        return 0
    try:
        result = guard_wiring(structures, args.max_model_calls, args.max_guardrail_calls)
    except LimitReached as e:
        print(f"{e}. 결과는 저장하지 않았습니다.")
        return LIMIT_EXIT
    s = result["summary"]
    print(f"{GUARD_PURPOSE} ({GUARD_CASES.name} {s['standalone']['block_total'] + s['standalone']['pass_total']}문항: "
          f"막을 {s['standalone']['block_total']}, 통과할 {s['standalone']['pass_total']})")
    for name, v in s.items():
        label = "단독" if name == "standalone" else f"구조 {name}"
        extra = "" if name == "standalone" else (f"  단독과 다른 문항: {', '.join(v['differs_from_standalone']) or '없음'}")
        print(f"[{label}] 미탐 {v['miss']}/{v['block_total']}  오탐 {v['false_positive']}/{v['pass_total']}  검사 실패 {v['check_failed']}"
              f"{extra}  연결 불일치: {', '.join(v['not_wired']) or '없음'}  모델 호출 {v['model_calls']}  ApplyGuardrail {v['guardrail_calls']}")
    mode = "bedrock" if args.bedrock else "mock"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"guard_wiring_dev_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT).as_posix()}")
    bad = any(v["not_wired"] or v["differs_from_standalone"] for k, v in s.items() if k != "standalone")
    return 1 if bad else 0


def holdout_done(structures: list[str], log: Path = HOLDOUT_LOG) -> dict[str, str]:
    """보지 않은 문항을 실제 모드로 이미 끝낸 구조 → 근거(기록 줄 또는 잠금 전 결과 파일)."""
    done = {s: f"잠금 전 실행 {HOLDOUT_DONE_BEFORE[s]}" for s in structures if s in HOLDOUT_DONE_BEFORE}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            words = line.split()
            if len(words) >= 5 and words[2] == "완료" and words[3] == "mode=bedrock" and words[4].startswith("structure="):
                name = words[4].split("=", 1)[1]
                if name in structures:
                    done[name] = line.strip()
    return done


def mark_holdout_done(structures: list[str], log: Path = HOLDOUT_LOG) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        for name in structures:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 완료 mode=bedrock structure={name}\n")


def split_answers(rows_by_structure: dict) -> dict:
    """결과 행에서 답 원문·근거 자료를 떼어 낸다(행은 바뀜). {구조: {문항 id: {"answer", "evidence"}}}."""
    answers = {}
    for name, rows in rows_by_structure.items():
        for cid, row in rows.items():
            picked = {k: row.pop(k) for k in ANSWER_KEYS if k in row}
            if picked:
                answers.setdefault(name, {})[cid] = picked
    return answers


def save_answers(answers: dict, case_set: str, mode: str, cases_name: str) -> Path:
    """채점용 답 파일(outputs/ 에만). 화면에는 경로만 알린다."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"agent_answers_{case_set}_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"set": case_set, "mode": mode, "cases": cases_name, "answers": answers},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def run_judge(args) -> int:
    """--judge: 답 파일을 채점한다. 화면에는 숫자만(구조별 평균, 잡음, 0·A 차이) 출력한다."""
    from ai.eval import judge_answer

    answers_path = Path(args.judge)
    data = json.loads(answers_path.read_text(encoding="utf-8"))
    if args.bedrock == bedrock.is_mock():
        print("--bedrock 은 BEDROCK_MOCK=0 일 때만, 가짜 모드는 BEDROCK_MOCK=1 일 때만 씁니다. 멈춥니다.")
        return 1
    if args.bedrock and args.max_judge_calls is None:
        print("실제 모드 채점은 --max-judge-calls 를 줘야 합니다. 멈춥니다.")
        return 1
    cases = json.loads((HOLDOUT if data.get("set") == "holdout" else CASES).read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    if not any(cid in by_id and judge_answer.judged_case(by_id[cid]) for rows in data["answers"].values() for cid in rows):
        print("채점 대상이 없습니다(기대 의도가 gap·demand·courses 인 문항의 답이 답 파일에 없음). 채점하지 않고 끝냅니다.")
        return 0
    try:
        out, result = judge_answer.judge_file(answers_path, cases, args.rounds, args.max_judge_calls, OUT_DIR,
                                             human_sheet=args.human_sheet)
    except judge_answer.JudgeLimitReached as e:
        print(f"채점 한도에 걸려 멈췄습니다: {e}")
        return LIMIT_EXIT
    except ValueError as e:
        print(f"채점을 시작하지 못했습니다: {e}")
        return 1
    used = result["judge_calls"]
    print(f"채점 항목 {result['items']}개 × {result['rounds']}회  채점 호출 {used['calls']}번  토큰 {used['tokens']}  형식 실패 {used['failed']}")
    for structure, per_round in result["summary"]["by_structure"].items():
        for rnd, s in per_round.items():
            print(f"  [구조 {structure} {rnd}회차] n={s['n']} 평균 " + ", ".join(f"{k} {v}" for k, v in s["mean"].items()))
    noise, effect = result["summary"].get("noise"), result["summary"].get("effect")
    if noise:
        print(f"  채점 잡음(같은 답 두 번): 쌍 {noise['identical']['pairs']}개 중 합계가 달라진 쌍 {noise['noise']}개")
    for e in ([effect] if effect else []) + result["summary"].get("effects", []):
        print(f"  구조 차이(1회차, 같은 질문): {e['labels']['b']} 가 {e['labels']['a']} 보다 높음 {e['higher']}·같음 {e['same']}·낮음 {e['lower']}")
    print(f"저장: {out.relative_to(ROOT).as_posix()}" + ("  (사람 채점 양식도 같은 폴더)" if args.human_sheet else ""))
    return 0


def run_agreement(judge_path: str, human_csv: str) -> int:
    """--agreement: LLM 채점(1회차)과 사람 채점 CSV 의 일치율. 숫자만 출력하고 결과 파일에 저장한다."""
    from ai.eval import judge_answer

    result = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    agr = judge_answer.human_agreement(result, Path(human_csv))
    for k, v in agr["by_criterion"].items():
        print(f"  {k}: n={v['n']} 정확 일치 {v['exact']}  ±1 일치 {v['within_one']}  kappa({agr['kappa_weight']}) {v['kappa']}"
              f"  평균 차이(LLM−사람) {v['mean_diff']}" + ("  (한쪽 점수가 하나뿐)" if v["single_valued"] else ""))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"agent_judge_agreement_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"judge_file": Path(judge_path).name, "human_csv": Path(human_csv).name, **agr},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out.relative_to(ROOT).as_posix()}")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="상담 구조 비교 코드 지표")
    ap.add_argument("--structures", nargs="+", default=["0"], help="비교할 구조(0, A, 3)")
    ap.add_argument("--set", choices=("dev", "holdout"), default="dev")
    ap.add_argument("--bedrock", action="store_true", help="실제 모드(BEDROCK_MOCK=0 이어야 함)")
    ap.add_argument("--max-model-calls", type=int, help="이번 실행 전체의 모델 호출 한도(넘기 직전에 멈춤)")
    ap.add_argument("--max-guardrail-calls", type=int, help="이번 실행 전체의 ApplyGuardrail 호출 한도(넘기 직전에 멈춤)")
    ap.add_argument("--one", nargs=2, metavar=("STRUCTURE", "CASE_ID"), help=argparse.SUPPRESS)  # 하위 프로세스용
    ap.add_argument("--judge", metavar="ANSWERS_FILE", help="답 파일(agent_answers_*.json)을 채점")
    ap.add_argument("--rounds", type=int, default=1, choices=(1, 2), help="같은 답을 몇 번 채점할지(2면 채점 잡음)")
    ap.add_argument("--max-judge-calls", type=int, help="채점 호출 한도(재시도 포함, 넘기 직전에 멈춤)")
    ap.add_argument("--human-sheet", action="store_true", help="사람 채점 양식(CSV)도 만듦")
    ap.add_argument("--agreement", nargs=2, metavar=("JUDGE_FILE", "HUMAN_CSV"), help="LLM·사람 채점 일치율")
    ap.add_argument("--guard-wiring", action="store_true",
                    help="가드레일 개선용 33문항을 구조 입구에 넣어 단독 결과와 같은지(통과면 답 생성 전에 멈춤)")
    args = ap.parse_args()
    if args.one:
        return run_one(args.one[0], args.set, args.one[1])
    if args.judge:
        return run_judge(args)
    if args.agreement:
        return run_agreement(*args.agreement)
    unknown = [s for s in args.structures if s not in STRUCTURES]
    if unknown:
        print(f"아직 없는 구조라 건너뜁니다: {', '.join(unknown)}")
    structures = [s for s in args.structures if s in STRUCTURES]
    if args.bedrock == bedrock.is_mock():
        print("--bedrock 은 BEDROCK_MOCK=0 일 때만, 가짜 모드는 BEDROCK_MOCK=1 일 때만 씁니다. 멈춥니다.")
        return 1
    if args.guard_wiring:
        return run_guard_wiring_cli(args, structures) if structures else 1
    path = HOLDOUT if args.set == "holdout" else CASES
    if not path.exists():
        print(f"문항 파일이 없어 건너뜁니다: {path.relative_to(ROOT).as_posix()} (공개 범위 밖, 팀 저장소에만 있음)")
        return 0
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    if not cases:
        print(f"문항이 없어 건너뜁니다: {path.relative_to(ROOT).as_posix()}")
        return 0
    if not structures:
        return 1
    if args.bedrock and (args.max_model_calls is None or args.max_guardrail_calls is None):
        print("실제 모드는 --max-model-calls 와 --max-guardrail-calls 를 함께 줘야 합니다. 멈춥니다.")
        return 1
    if args.bedrock and args.set == "holdout":
        done = holdout_done(structures)
        if done:
            for name, why in done.items():
                print(f"구조 {name} 는 보지 않은 문항을 이미 실제 모드로 돌렸습니다: {why}")
            print("보지 않은 문항은 구조마다 한 번만 돌립니다. 다시 하려면 기록 줄을 직접 지우고 이유를 남기세요. 멈춥니다.")
            return 1
    partial: dict = {}
    try:
        result = evaluate(cases, structures, isolate=True, case_set=args.set, max_model_calls=args.max_model_calls,
                          max_guardrail_calls=args.max_guardrail_calls, partial=partial)
    except LimitReached as e:
        done = {k: len(v) for k, v in partial.items()}
        used_m = sum(r["model_calls"] for v in partial.values() for r in v.values())
        used_g = sum(r.get("guardrail_calls", 0) for v in partial.values() for r in v.values())
        print(f"{e}. 끝난 문항 {done}, 쓴 호출: 모델 {used_m}번, ApplyGuardrail {used_g}번")
        answers = split_answers(partial)
        if answers:
            print(f"답 파일: {save_answers(answers, args.set, 'bedrock' if args.bedrock else 'mock', path.name).relative_to(ROOT).as_posix()}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"agent_compare_{args.set}_stopped_{time.strftime('%Y%m%d-%H%M%S')}.json"
        kept = partial if args.set == "dev" else {k: len(v) for k, v in partial.items()}  # 보지 않은 문항은 개수만
        out.write_text(json.dumps({"cases": path.name, "notes": RESULT_NOTES, "stopped": str(e), "partial": kept},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"멈출 때까지의 결과: {out.relative_to(ROOT).as_posix()}")
        return LIMIT_EXIT
    if args.bedrock and args.set == "holdout":
        mark_holdout_done(structures)  # 숫자를 화면에 찍기 전에 잠근다
    answers = split_answers({name: r["rows"] for name, r in result.items()})
    for name, r in result.items():
        s = r["summary"]
        print(f"\n[구조 {name}] 의도 {s['intent_correct']}/{s['intent_total']}(해당 없음 {s['intent_not_applicable']})  되묻기 {s['ask_back_correct']}/{s['ask_back_total']}(해당 없음 {s['ask_back_not_applicable']})"
              f"  가드레일 차단 {s['guard_blocked']}/{s['guard_total']}(검사 실패 {s['guard_check_failed']})"
              f"  불확실 {s['uncertain_ratio']}  모델 {s['model_calls']}번  ApplyGuardrail {s['guardrail_calls']}번  KB 검색 {s['kb_retrieve_calls']}번  임베딩 {s['embedding_calls']}번  토큰 {s['tokens']}"
              f"  시간 중앙값 {s['seconds_median']}초 최대 {s['seconds_max']}초")
        if args.set == "dev":  # 보지 않은 문항은 숫자만
            print(f"  의도가 다른 문항: {', '.join(s['intent_wrong_ids']) or '없음'}"
                  f"  해당 없음: {', '.join(s['intent_not_applicable_ids']) or '없음'}")
            for cid, row in r["rows"].items():
                print(f"  {cid}: 의도 {row['intent']}, 입력 {row['guard']}, 되묻기 {row['ask_back']}, 과정 {row['courses']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mode = "bedrock" if args.bedrock else "mock"
    out = OUT_DIR / f"agent_compare_{args.set}_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    saved = result if args.set == "dev" else {  # 보지 않은 문항은 숫자만 저장(문항 id 없음)
        k: {"summary": {m: n for m, n in v["summary"].items() if m not in ("intent_wrong_ids", "intent_not_applicable_ids")}} for k, v in result.items()}
    out.write_text(json.dumps({"cases": path.name, "notes": RESULT_NOTES, "result": saved}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT).as_posix()}")
    if answers:
        print(f"답 파일(채점용, 답 원문 포함): {save_answers(answers, args.set, mode, path.name).relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
