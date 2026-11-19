"""가드레일 (#24). 상담 입력과 답을 검사한다. 어느 채팅 화면이든 이 두 함수만 부르면 된다.

  check_input(text)  -> GuardResult   사용자 입력. 막히면 BLOCK_MESSAGE 를 보여준다
  check_output(text) -> GuardResult   모델 답. 막히면 OUTPUT_BLOCK_MESSAGE 를 보여준다

팀 결정 (11/10, 11/18 #24)
- 성별·학력·인종(국적)·지역을 근거로 능력이나 채용 가능성을 판단하거나 차별하는 요청은 막는다. 나이는 막지 않는다.
- 속성을 언급만 한 정상 질문은 통과해야 한다("충청 지역에서 취업 준비 중이에요", "비전공자인데").
  그래서 속성 낱말 하나로 막지 않고, 같은 문장에 "판단·차별 요청" 표현이 함께 있을 때만 막는다.
- 프롬프트 공격(이전 지시 무시, 시스템 프롬프트 요구, 제한 없는 AI 역할극)도 막는다(범주 "공격").

두 단계 (둘 다 쓰고, 조합은 테스트 표로 정한다)
1. 코드 검사: 아래 낱말표. 늘 돈다. 비용 0, 가짜 모드에서도 돈다. 답에는 공격 범주만 본다(기술 답의 "지역·유리" 오탐 때문)
2. Bedrock Guardrails(ApplyGuardrail): 환경 변수 GUARDRAIL_ID 가 있고 실제 모드일 때만. 입력은 늘, 답은 GUARDRAIL_OUTPUT=1 일 때만.
   호출이 실패하면(권한, 호출 제한) 코드 검사 결과만 쓰고 로그를 남긴다. 상담을 멈추지 않는다
   GUARDRAIL_TOPIC_BLOCK(기본 0): 0 이면 Guardrails 의 차단 주제 판정은 기록만 하고, 프롬프트 공격·혐오·모욕 필터만 막는다.
   (11/18 개선용 문항에서 차단 주제가 학력 언급 질문을 막은 오탐 때문). 주력은 필터다: 11/18 보지 않은 문항에서
   코드 검사는 막을 질문을 하나도 막지 못했고, 11/19 오탐을 줄이려 판단 표현을 더 좁혔다.
막히는 조건: 코드 검사가 막거나, Guardrails 가 (설정에 따라 쓰는) 정책으로 막으면 막는다.

기록: 막힘 여부, 단계(code/guardrails), 범주, 규칙 이름만 로그에 남긴다. 입력·답 원문은 남기지 않는다(CLAUDE.md 보안).
평가: data/eval/guardrail_cases.json(개선용 33문항, 공개 범위 밖)으로 오탐률·미탐률을 잰다(python -m ai.eval.guardrail_eval).
"""
from __future__ import annotations

import logging
import os
import re
from typing import NamedTuple, Optional

from ai.bedrock import DEFAULT_REGION, is_mock

BLOCK_MESSAGE = (
    "이 서비스는 성별, 학력, 출신 지역, 인종이나 국적 같은 조건으로 직무나 채용 가능성을 판단하지 않습니다. "
    "해 본 기술과 관심 있는 직무를 알려 주시면, 필요한 역량과 AWS 교육과정을 안내해 드릴게요."
)
OUTPUT_BLOCK_MESSAGE = "답을 정리하지 못했습니다. 질문을 바꿔 다시 물어봐 주세요."

CATEGORIES = ("성별", "학력", "인종", "지역", "공격")

# 속성 낱말. 하나만 있으면 막지 않는다(언급만 한 정상 질문). 나이는 넣지 않는다(팀 결정)
ATTRIBUTES = {
    "성별": r"여자|남자|여성|남성|성별|여직원|남직원",
    "학력": r"지방대|고졸|대졸|명문대|학벌|학력|전문대|서울대|인서울|스카이|SKY|출신\s*학교",
    "인종": r"외국인|한국인|흑인|백인|동남아|인종|국적|조선족|아시아인",
    "지역": r"전라도|경상도|충청도|강원도|제주도|호남|영남|지방\s*출신|지방|수도권|출신\s*지역|출신지|지역",
}
# 판단·차별 요청 표현. 속성 낱말과 같은 문장에 있을 때만 막는다. 입력 검사에서만 쓴다
# 11/19 리뷰: "유리·불리·안 맞·더 맞·포기·떨어지·소용 없·의미 없·피하는"은 상담·기술 문장에도 흔해 뺐다
# ("남자인데 포기하지 않고 준비 중", "지방에 살아서 오프라인 수업은 안 맞아요", "다중 AZ 구성이 지역 장애에 유리").
# 판단을 분명히 요구하는 표현만 남긴다. 그만큼 놓치는 요청은 Bedrock Guardrails 필터가 맡는다
JUDGMENT = (
    r"안\s*뽑|뽑지\s*않|만\s*뽑|뽑아\s*주지|걸러|거르|성향|실력이\s*떨어|"
    r"피해야|피하라|기준으로\s*추천|따라\s*.{0,10}다르게|합격\s*확률|숨기"
)
# 프롬프트 공격
ATTACKS = {
    "지시 무시": r"(이전|앞의|위의|기존)\s*(지시|명령|규칙|지침)\S*\s*(은|는|을|를)?\s*(모두\s*)?(무시|잊)",
    "시스템 프롬프트": r"시스템\s*프롬프트|system\s*prompt|숨겨진\s*(설정|지침|프롬프트)|내부\s*(지침|프롬프트)",
    "제한 해제": r"(제한|규칙|필터|검열)\s*(이\s*)?(없는|없이|풀린|해제)|탈옥|jailbreak|개발자\s*모드|DAN\b",
    "영어 지시 무시": r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+instructions",
}
_SENTENCE = re.compile(r"[.?!。\n]+")

logger = logging.getLogger(__name__)


class GuardResult(NamedTuple):
    blocked: bool
    source: Optional[str] = None    # "code" 또는 "guardrails"
    category: Optional[str] = None  # CATEGORIES 중 하나. Guardrails 는 정책 이름
    rule: Optional[str] = None      # 걸린 규칙 이름(원문 아님)


PASS = GuardResult(False)


def code_check(text: str, judgment: bool = True) -> GuardResult:
    """낱말표 검사. 공격 표현은 어디에 있어도, 차별 판단은 속성 낱말과 판단 표현이 같은 문장에 있을 때만 막는다.

    judgment=False 면 공격 범주만 본다(답 검사). 기술 답에는 "리전·지역·유리" 같은 낱말이 흔해
    낱말표로 차별을 가리면 정상 답을 막는다. 답의 차별 검사는 GUARDRAIL_OUTPUT=1 일 때 Guardrails 가 맡는다.
    """
    for name, pattern in ATTACKS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            return GuardResult(True, "code", "공격", name)
    if not judgment:
        return PASS
    for sentence in _SENTENCE.split(text):
        if not re.search(JUDGMENT, sentence):
            continue
        for category, pattern in ATTRIBUTES.items():
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                return GuardResult(True, "code", category, "속성+판단")
    return PASS


def _guardrails_enabled(source: str) -> bool:
    if is_mock() or not os.getenv("GUARDRAIL_ID", "").strip():
        return False
    return source == "INPUT" or os.getenv("GUARDRAIL_OUTPUT", "0") == "1"


def topic_block_enabled() -> bool:
    """Guardrails 차단 주제 결과로도 막을지. 기본은 끔(기록만): 차별 판단은 코드 검사가 맡는다.

    11/18 개선용 33문항에서 차단 주제가 학력을 언급만 한 정상 질문을 막아(오탐), 시연에서는 Guardrails 를
    프롬프트 공격·혐오·모욕 필터로만 막기에 쓴다. GUARDRAIL_TOPIC_BLOCK=1 이면 차단 주제로도 막는다.
    """
    return os.getenv("GUARDRAIL_TOPIC_BLOCK", "0") == "1"


def bedrock_assess(text: str, source: str) -> Optional[list[tuple[str, str]]]:
    """ApplyGuardrail 을 한 번 부르고 BLOCKED 로 판정한 정책 목록 [(범주, 이름)] 을 돌려준다.

    꺼져 있거나 실패하면 None. 이메일·전화번호를 가리기만(ANONYMIZE) 한 개입은 목록에 넣지 않는다.
    범주는 "주제"(차단 주제), "공격"(프롬프트 공격 필터), "콘텐츠"(혐오·모욕 등). 원문은 꺼내지 않는다.
    """
    if not _guardrails_enabled(source):
        return None
    try:
        resp = _client().apply_guardrail(
            guardrailIdentifier=os.environ["GUARDRAIL_ID"].strip(),
            guardrailVersion=os.getenv("GUARDRAIL_VERSION", "DRAFT").strip() or "DRAFT",
            source=source,
            content=[{"text": {"text": text}}],
        )
    except Exception as e:  # noqa: BLE001 - 가드레일 호출 실패로 상담을 멈추지 않는다
        logger.warning("Bedrock Guardrails 호출 실패(%s). 코드 검사 결과만 씁니다", type(e).__name__)
        return None
    if resp.get("action") != "GUARDRAIL_INTERVENED":
        return []
    return blocked_policies(resp.get("assessments", []))


def blocked_policies(assessments: list) -> list[tuple[str, str]]:
    """ApplyGuardrail 판정에서 BLOCKED 인 정책 [(범주, 이름)]."""
    out = []
    for a in assessments:
        for t in (a.get("topicPolicy") or {}).get("topics", []):
            if t.get("action") == "BLOCKED":
                out.append(("주제", t.get("name", "")))
        for f in (a.get("contentPolicy") or {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                out.append(("공격" if f.get("type") == "PROMPT_ATTACK" else "콘텐츠", f.get("type", "")))
    return out


def decide(policies: Optional[list[tuple[str, str]]], topic_block: bool) -> GuardResult:
    """Guardrails 판정으로 막을지 정한다. topic_block 이 꺼져 있으면 차단 주제는 기록만 하고 필터만 막는다."""
    if not policies:
        return PASS
    usable = [p for p in policies if topic_block or p[0] != "주제"]
    if not usable:
        logger.info("Guardrails 차단 주제 판정(기록만, 막지 않음): %s", [p[1] for p in policies])
        return PASS
    return GuardResult(True, "guardrails", *usable[0])


def bedrock_check(text: str, source: str) -> GuardResult:
    """Bedrock Guardrails(ApplyGuardrail). 꺼져 있거나 실패하면 통과로 둔다(코드 검사가 남아 있다)."""
    return decide(bedrock_assess(text, source), topic_block_enabled())


_client_cache = None


def _client():
    global _client_cache
    if _client_cache is None:
        import boto3  # 가짜 모드에서는 불러오지 않는다

        _client_cache = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", DEFAULT_REGION))
    return _client_cache


def _check(text: str, source: str) -> GuardResult:
    result = code_check(text, judgment=source == "INPUT")
    if not result.blocked:
        result = bedrock_check(text, source)
    if result.blocked:
        logger.info("가드레일 막음: 대상 %s, 단계 %s, 범주 %s, 규칙 %s", source, result.source, result.category, result.rule)
    return result


def check_input(text: str) -> GuardResult:
    """사용자 입력 검사. 막히면 화면은 BLOCK_MESSAGE 를 보여주고 모델을 부르지 않는다."""
    return _check(text or "", "INPUT")


def check_output(text: str) -> GuardResult:
    """모델 답 검사. 코드 검사는 공격 범주만 늘, 차별 검사는 GUARDRAIL_OUTPUT=1 일 때 Bedrock Guardrails 가. 막히면 OUTPUT_BLOCK_MESSAGE."""
    return _check(text or "", "OUTPUT")
