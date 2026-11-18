"""가드레일(#24)과 추천 불확실 고정 문장 확인. 실행: python -m ai.test_guardrail

가짜 모드라 Bedrock Guardrails 는 부르지 않는다. ApplyGuardrail 응답 처리는 가짜 클라이언트로 확인한다.
예시 문장(차별 판단 요청 포함)은 공개 범위 밖인 data/eval/ 에서 읽는다. 이 파일에는 문장을 적지 않는다.
"""
import io
import json
import logging
import os

os.environ["BEDROCK_MOCK"] = "1"
os.environ.pop("GUARDRAIL_ID", None)

from ai import agent, guardrail  # noqa: E402
from ai import recommend as rec  # noqa: E402
from ai.eval import guardrail_eval  # noqa: E402

for _name in ("GUARDRAIL_ID", "GUARDRAIL_VERSION", "GUARDRAIL_OUTPUT", "GUARDRAIL_TOPIC_BLOCK"):
    os.environ.pop(_name, None)  # guardrail_eval 이 .env 를 읽어 올린 값을 지운다(테스트는 .env 에 영향받지 않게)

S =json.loads(guardrail_eval.TEST_SENTENCES.read_text(encoding="utf-8"))
QUESTION = "Python, Docker 해봤는데 클라우드 엔지니어 되려면 뭐부터 공부해요?"


def test_dev_cases_code_check():
    # 개선용 33문항. 규칙을 이 문항으로 고쳤으므로 회귀 확인용이다(점수는 과대평가, 보지 않은 문항은 holdout 으로)
    cases = json.loads(guardrail_eval.CASES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 33 and sum(c["expect"] == "block" for c in cases) == 18
    r = guardrail_eval.evaluate(cases, use_bedrock=False)["code"]
    assert r["false_positive_ids"] == [] and r["false_negative_ids"] == [], r
    for c in cases:  # 막은 범주도 맞아야 한다
        got = guardrail.code_check(c["text"])
        if c["expect"] == "block":
            assert got.category == c["category"], (c["id"], got)


def test_case_files_are_outside_public_scope():
    allow = [x.strip() for x in (guardrail_eval.ROOT / ".github" / "public-sync" / "allowlist.txt")
             .read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
    for path in (guardrail_eval.CASES, guardrail_eval.HOLDOUT, guardrail_eval.TEST_SENTENCES):
        rel = path.relative_to(guardrail_eval.ROOT).as_posix()
        assert not any(rel == a or rel.startswith(a + "/") for a in allow), rel


def test_mention_only_and_age_pass():
    # 지역·학력·성별 언급, 나이(팀 결정으로 막지 않음), 판단 표현만 있고 속성은 없는 문장, 다른 문장에 있는 속성과 판단 표현
    for text in S["pass"]:
        assert not guardrail.code_check(text).blocked, text
    assert guardrail.code_check(S["block_region"]).category == "지역"


def test_attacks():
    for text in S["attacks"]:
        assert guardrail.code_check(text).category == "공격", text


def test_rates_math():
    cases = [{"id": "a", "expect": "block"}, {"id": "b", "expect": "block"}, {"id": "c", "expect": "pass"}]
    r = guardrail_eval.rates(cases, {"a": True, "b": False, "c": True})
    assert (r["false_negative"], r["false_negative_rate"], r["false_positive"], r["false_positive_rate"]) == (1, 0.5, 1, 1.0)


def test_bedrock_off_in_mock_and_without_id():
    assert guardrail.bedrock_check("아무 말", "INPUT") == guardrail.PASS
    old = os.environ.get("BEDROCK_MOCK")
    os.environ["BEDROCK_MOCK"] = "0"
    try:
        assert not guardrail._guardrails_enabled("INPUT")  # GUARDRAIL_ID 가 없으면 끔
        os.environ["GUARDRAIL_ID"] = "g-test"
        assert guardrail._guardrails_enabled("INPUT") and not guardrail._guardrails_enabled("OUTPUT")
        os.environ["GUARDRAIL_OUTPUT"] = "1"
        assert guardrail._guardrails_enabled("OUTPUT")
    finally:
        os.environ["BEDROCK_MOCK"] = old
        os.environ.pop("GUARDRAIL_ID", None)
        os.environ.pop("GUARDRAIL_OUTPUT", None)


class FakeGuardrails:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def apply_guardrail(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.response


def _with_bedrock(fake, fn):
    old_env, old_client = dict(os.environ), guardrail._client_cache
    os.environ.update({"BEDROCK_MOCK": "0", "GUARDRAIL_ID": "g-test"})
    guardrail._client_cache = fake
    try:
        return fn()
    finally:
        guardrail._client_cache = old_client
        os.environ.clear()
        os.environ.update(old_env)


TOPIC = {"action": "GUARDRAIL_INTERVENED",
         "assessments": [{"topicPolicy": {"topics": [{"name": "Personal attribute judgment", "type": "DENY", "action": "BLOCKED"}]}}]}


def test_topic_block_setting():
    # 기본(GUARDRAIL_TOPIC_BLOCK=0): 차단 주제 판정은 기록만 하고 막지 않는다. 차별 판단은 코드 검사가 맡는다
    fake = FakeGuardrails(TOPIC)
    assert _with_bedrock(fake, lambda: guardrail.check_input("코드 검사는 통과하는 문장")) == guardrail.PASS
    assert fake.calls[0]["source"] == "INPUT" and fake.calls[0]["guardrailVersion"] == "DRAFT"
    # GUARDRAIL_TOPIC_BLOCK=1 이면 차단 주제로도 막는다
    os.environ["GUARDRAIL_TOPIC_BLOCK"] = "1"
    try:
        r = _with_bedrock(FakeGuardrails(TOPIC), lambda: guardrail.check_input("코드 검사는 통과하는 문장"))
    finally:
        os.environ.pop("GUARDRAIL_TOPIC_BLOCK", None)
    assert r == guardrail.GuardResult(True, "guardrails", "주제", "Personal attribute judgment")
    # 차단 주제와 필터가 함께 막으면, 주제를 쓰지 않아도 필터로 막는다
    both = [("주제", "Personal attribute judgment"), ("콘텐츠", "HATE")]
    assert guardrail.decide(both, topic_block=False) == guardrail.GuardResult(True, "guardrails", "콘텐츠", "HATE")
    assert guardrail.decide([], topic_block=True) == guardrail.PASS and guardrail.decide(None, topic_block=True) == guardrail.PASS


def test_bedrock_check_parses_response():
    attack = {"action": "GUARDRAIL_INTERVENED",
              "assessments": [{"contentPolicy": {"filters": [{"type": "PROMPT_ATTACK", "confidence": "HIGH", "action": "BLOCKED"}]}}]}
    assert _with_bedrock(FakeGuardrails(attack), lambda: guardrail.check_input("x")).category == "공격"
    assert _with_bedrock(FakeGuardrails({"action": "NONE"}), lambda: guardrail.check_input("x")) == guardrail.PASS
    # 이메일·전화번호를 가리기만 한 개입(ANONYMIZE)은 막지 않는다
    masked = {"action": "GUARDRAIL_INTERVENED",
              "assessments": [{"sensitiveInformationPolicy": {"piiEntities": [{"type": "EMAIL", "action": "ANONYMIZED"}]}}]}
    assert _with_bedrock(FakeGuardrails(masked), lambda: guardrail.check_input("x")) == guardrail.PASS
    # 호출이 실패해도 상담을 멈추지 않는다(코드 검사 결과만)
    assert _with_bedrock(FakeGuardrails(error=RuntimeError("AccessDenied")), lambda: guardrail.check_input("x")) == guardrail.PASS
    # 코드 검사가 먼저 막으면 Guardrails 는 부르지 않는다
    fake = FakeGuardrails(TOPIC)
    assert _with_bedrock(fake, lambda: guardrail.check_input(S["block_gender"])).source == "code" and fake.calls == []
    # 답 검사는 GUARDRAIL_OUTPUT=1 일 때만 Guardrails 를 부른다
    fake = FakeGuardrails(TOPIC)
    assert _with_bedrock(fake, lambda: guardrail.check_output("평범한 답")) == guardrail.PASS and fake.calls == []


def test_agent_blocks_input_without_model_call():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    log = logging.getLogger("ai.guardrail")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        r = agent.chat(S["block_agent_input"])
    finally:
        log.removeHandler(handler)
    assert r["answer"] == guardrail.BLOCK_MESSAGE and r["tool_calls"] == [] and r["usage"]["totalTokens"] == 0
    assert r["uncertain"] is False
    text = buf.getvalue()
    assert "가드레일 막음" in text and "성별" in text and S["agent_input_word"] not in text  # 원문은 남기지 않는다


def test_agent_blocks_output():
    old = agent.guardrail.check_output
    agent.guardrail.check_output = lambda answer: guardrail.GuardResult(True, "code", "성별", "속성+판단")
    try:
        r = agent.chat(QUESTION)
    finally:
        agent.guardrail.check_output = old
    assert r["answer"] == guardrail.OUTPUT_BLOCK_MESSAGE and r["uncertain_reason"] == "guardrail"
    assert agent.chat(QUESTION)["uncertain"] is False  # 평소 답은 답 검사를 통과한다


def test_uncertain_note():
    assert rec.uncertain_note("Kubernetes", {"match": "certain", "course_id": "x"}) is None
    note = rec.uncertain_note("쿠버네티스", {"match": "uncertain", "course_id": "x"})
    assert note.startswith("이 과정이 Kubernetes을(를) 직접 다루는지는 확실하지 않습니다")
    aws_id = rec._foundation_ids()["AWS"][0]
    assert rec.uncertain_note("AWS", {"match": "uncertain", "course_id": aws_id}).startswith("AWS은(는) 범위가 넓어 입문 과정")
    # 추천의 reason 끝에 붙는다(③ 형식은 그대로). 가짜 모드 Docker: certain 1개, uncertain 2개
    r, _ = rec.build_recommendation("Docker", {"postings": 20, "of": 40, "required_ratio": 0.45})
    for c in r["courses"]:
        assert set(c) == {"title", "url", "level", "prerequisites", "reason", "match"}
        assert c["reason"].endswith("직접 다룬다는 내용을 확인하지 못했습니다.") == (c["match"] == "uncertain"), c
    # 상담 에이전트의 과정 검색 도구에도 note 로 들어간다
    courses = agent.tool_search_courses("Docker")["courses"]
    assert all(("note" in c) == (c["match"] == "uncertain") for c in courses)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("통과")
