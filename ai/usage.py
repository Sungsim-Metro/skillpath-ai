"""Bedrock 호출 기록 (토큰·비용 화면용, 2026-11-16 결정).

ai/bedrock.py 의 converse_json 이 호출 한 번마다 record() 를 부른다. 한 줄에 호출 하나씩 JSON 으로 덧붙인다.
- 남기는 것: 시각, 단계, 시도 번호, 입력·출력 토큰 수, 모델 ID, 가짜 모드 여부
- 남기지 않는 것: 프롬프트, 응답, 사용자 입력, 닉네임. 내용은 한 글자도 적지 않는다
- 파일은 USAGE_LOG(기본 outputs/usage/usage.jsonl, 커밋되지 않음). 서버 한 대의 로컬 파일이라 서버를 바꾸면 이어지지 않는다
- 기록에 실패해도 호출은 그대로 진행한다(화면이 기록 때문에 멈추지 않게)
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "outputs" / "usage" / "usage.jsonl"
_lock = Lock()
logger = logging.getLogger(__name__)


def log_path() -> Path:
    return Path(os.getenv("USAGE_LOG") or DEFAULT_LOG)


def stage_of(mock_file: str) -> str:
    """가짜 응답 파일 이름에서 단계 이름을 얻는다. mock_bedrock_recommend.json → recommend"""
    stem = Path(mock_file).stem
    return stem.removeprefix("mock_bedrock_") or "unknown"


def record(mock_file: str, attempt: int, usage: dict, mock: bool) -> None:
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stage": stage_of(mock_file),
        "attempt": attempt,
        "inputTokens": int(usage.get("inputTokens", 0)),
        "outputTokens": int(usage.get("outputTokens", 0)),
        "model": "mock" if mock else os.getenv("BEDROCK_MODEL_ID", ""),
        "mock": mock,
    }
    try:
        path = log_path()
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("호출 기록을 쓰지 못했습니다(%s). 호출은 계속합니다", type(e).__name__)
