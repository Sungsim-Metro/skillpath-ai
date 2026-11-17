"""실제 모드 사전 점검. 화면을 띄울 서버에서 한 번 돌려 AWS 설정이 맞는지 본다.

실행: 저장소 루트에서 `python -m deploy.check_aws` (추천 1건까지 보려면 `--recommend`)
- 화면과 같은 방법으로 .env 를 읽고, 화면이 부르는 backend.api 함수를 그대로 부른다.
- Bedrock 은 짧은 질문 1번(--recommend 를 주면 추천 호출이 더해진다), DynamoDB 는 GetItem 1번을 쓴다.
- 오류는 종류(AWS 오류 코드)만 출력한다. 오류 메시지와 키 값은 출력하지 않는다.
- 하나라도 실패하면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_ENV = ("BEDROCK_MODEL_ID", "DYNAMODB_DEMAND_TABLE")
DEMAND_KEYS = ("total_postings", "skills")
SKILL_KEYS = ("skill", "postings", "required", "preferred", "evidence_samples")


def error_kind(e: Exception) -> str:
    response = getattr(e, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    return code if isinstance(code, str) and code.isidentifier() else type(e).__name__


def check_env() -> str:
    if os.getenv("BEDROCK_MOCK", "1") != "0":
        raise ValueError("BEDROCK_MOCK 이 0 이 아닙니다. 지금 화면은 가짜 데이터로 뜹니다")
    missing = [name for name in REQUIRED_ENV if not os.getenv(name, "").strip()]
    if missing:
        raise ValueError(f"비어 있는 환경 변수: {', '.join(missing)}")
    profile = os.getenv("AWS_PROFILE", "")
    how = f"프로필({profile})" if profile else "프로필 없음(인스턴스 역할이나 환경 변수)"
    return f"리전 {os.getenv('AWS_REGION', 'ap-northeast-2')}, 인증 {how}"


def check_demand(job_category: str) -> str:
    from backend import api

    demand = api.get_demand(job_category)
    missing = [k for k in DEMAND_KEYS if k not in demand]
    if missing:
        raise ValueError(f"수요 집계에 없는 칸: {', '.join(missing)}")
    if not demand["skills"]:
        raise ValueError("수요 집계에 기술이 0개입니다. 배치(pipeline.extraction_batch)를 먼저 돌려야 합니다")
    for s in demand["skills"]:
        absent = [k for k in SKILL_KEYS if k not in s]
        if absent:
            raise ValueError(f"기술 {s.get('skill')!r} 에 없는 칸: {', '.join(absent)}")
    return (f"공고 {demand['total_postings']}건, 기술 {len(demand['skills'])}개, "
            f"수집일 {demand.get('collected') or '없음'}, 출처 {', '.join(demand.get('sources') or []) or '없음'}")


def check_bedrock() -> str:
    from ai.bedrock import converse_json

    def need_ok(data: dict) -> None:
        if data.get("ok") is not True:
            raise ValueError('"ok" 가 true 가 아닙니다')

    result = converse_json(
        "점검용 호출입니다. 설명 없이 JSON 객체 하나만 출력합니다.", '{"ok": true} 를 그대로 출력하세요.',
        mock_file="mock_bedrock_extract.json", mock_key="default", validate=need_ok, max_tokens=50,
    )
    return f"시도 {result.attempts}회, 토큰 입력 {result.usage.get('inputTokens', 0)} · 출력 {result.usage.get('outputTokens', 0)}"


def check_recommend(job_category: str) -> str:
    from backend import api

    rows = [r for r in api.get_gap(job_category, []) if not r["owned"]]
    if not rows:
        raise ValueError("부족 기술이 없어 추천을 확인할 수 없습니다")
    recs = api.get_recommendations(job_category, [rows[0]["skill"]])
    courses = recs[0]["courses"]
    if any(not c.get("reason") for c in courses):
        raise ValueError("추천 이유가 빈 과정이 있습니다")
    return f"{recs[0]['gap_skill']}: 과정 {len(courses)}개"


def run(job_category: str = "cloud_engineer", recommend: bool = False, out=print) -> int:
    steps = [("환경 변수", check_env), ("DynamoDB 수요 집계", lambda: check_demand(job_category)),
             ("Bedrock 호출", check_bedrock)]
    if recommend:
        steps.append(("추천 1건", lambda: check_recommend(job_category)))
    failed = 0
    for name, step in steps:
        try:
            out(f"[통과] {name}: {step()}")
        except (ValueError, LookupError) as e:  # 우리가 쓴 설정 안내는 그대로 보여 준다
            failed += 1
            out(f"[실패] {name}: {e}")
        except Exception as e:  # noqa: BLE001 - AWS 오류는 메시지에 계정 ID 가 들어갈 수 있어 종류만 낸다
            failed += 1
            out(f"[실패] {name}: {error_kind(e)}")
        if failed and name == "환경 변수":
            break  # 설정이 틀리면 AWS 를 부르지 않는다
    out("모두 통과했습니다." if not failed else f"{failed}개 실패. deploy/README.md 의 '안 될 때'를 보세요.")
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="실제 모드 사전 점검")
    parser.add_argument("--job-category", default="cloud_engineer")
    parser.add_argument("--recommend", action="store_true", help="추천 1건까지 확인(Bedrock 호출이 더해진다)")
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")  # 화면(app/main.py)과 같은 방법. 이미 있는 환경 변수는 덮지 않는다
    except ImportError:
        pass
    return run(args.job_category, args.recommend)


if __name__ == "__main__":
    raise SystemExit(main())
