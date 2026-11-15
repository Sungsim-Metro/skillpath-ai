"""채용공고(①) → 추출 결과(②). (#9)

LLM 은 raw, normalized, type, evidence 만 낸다. posting_id, confidence, ncs_unit 은 코드가 채운다.
- evidence 가 비면 버린다.
- evidence 가 공고에 없거나, normalized 가 대표명 목록에 없으면 confidence = "uncertain".
"""
from __future__ import annotations

import hashlib
import json
import os

from ai.bedrock import ConverseResult, converse_json
from ai.evidence import evidence_in_text
from ai.prompts import extract_v1 as prompt

PROMPT_VERSION = prompt.VERSION
EXTRACTOR_VERSION = "extractor-v2"
MOCK_FILE = "mock_bedrock_extract.json"
TYPES = ("required", "preferred")
MAX_TOKENS = 4096
TEMPERATURE = 0.0


def _json_sha256(value: object) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def extraction_settings() -> dict:
    """현재 추출 설정을 DynamoDB에 저장할 수 있는 값으로 돌려준다."""
    model_id = os.getenv("BEDROCK_MODEL_ID", "")
    if not model_id.strip():
        raise ValueError("BEDROCK_MODEL_ID를 설정해야 추출 결과를 저장할 수 있습니다.")
    return {
        "model_id": model_id,
        "prompt_version": PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "canonical_skills_sha256": _json_sha256(sorted(prompt.CANONICAL_SKILLS)),
        "inference_config": {
            "temperature": str(TEMPERATURE),
            "max_tokens": MAX_TOKENS,
        },
    }


def input_fingerprint(
    posting: dict, job_category: str, settings: dict | None = None
) -> str:
    """현재 분석 입력과 설정의 해시로 저장된 성공 결과의 재사용 여부를 판단한다."""
    return _json_sha256({
        "job_category": job_category,
        "posting_id": posting["id"],
        "text": posting["text"],
        "system": prompt.SYSTEM,
        "user_message": prompt.user_message(posting["text"]),
        "settings": extraction_settings() if settings is None else settings,
    })


def validate_llm_output(data: dict) -> None:
    """LLM 출력 형식 검사. 틀리면 ValueError (converse_json 이 한 번 재시도한다)."""
    skills = data.get("skills")
    if not isinstance(skills, list):
        raise ValueError('"skills" 목록이 없습니다')
    for i, s in enumerate(skills):
        if not isinstance(s, dict):
            raise ValueError(f"skills[{i}] 가 객체가 아닙니다")
        for key in ("raw", "normalized", "type", "evidence"):
            if not isinstance(s.get(key), str):
                raise ValueError(f"skills[{i}].{key} 가 문자열이 아닙니다")
        if s["type"] not in TYPES:
            raise ValueError(f"skills[{i}].type 이 {s['type']!r} 입니다")


def to_contract(llm_skills: list[dict], text: str) -> list[dict]:
    """같은 기술은 근거 검증을 통과한 후보, 그중 required 순서로 하나를 남긴다."""
    by_name: dict[str, dict] = {}
    for s in llm_skills:
        name = s["normalized"].strip()
        evidence = s["evidence"].strip()
        if not name or not evidence:
            continue  # 근거 없는 결과는 내보내지 않는다
        found = evidence_in_text(evidence, text)
        item = {
            "raw": s["raw"].strip(),
            "normalized": name,
            "type": s["type"],
            "evidence": evidence,
            "confidence": "high" if found and name in prompt.CANONICAL_SKILLS else "uncertain",
            "ncs_unit": None,
        }
        prev = by_name.get(name)
        priority = (item["confidence"] == "high", item["type"] == "required")
        if prev is None or priority > (
            prev["confidence"] == "high", prev["type"] == "required"
        ):
            by_name[name] = item
    return list(by_name.values())


def extract_with_meta(posting: dict) -> tuple[dict, ConverseResult]:
    """평가용. 추출 결과와 함께 시도 횟수·토큰 사용량을 돌려준다."""
    result = converse_json(
        prompt.SYSTEM,
        prompt.user_message(posting["text"]),
        mock_file=MOCK_FILE,
        mock_key=posting["id"],
        validate=validate_llm_output,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    extraction = {
        "posting_id": posting["id"],  # ②의 posting_id 는 ①의 id 를 가리킨다
        "skills": to_contract(result.data["skills"], posting["text"]),
    }
    return extraction, result


def extract_skills(posting: dict) -> dict:
    """공고 ① 를 받아 추출 결과 ② 를 돌려준다."""
    return extract_with_meta(posting)[0]
