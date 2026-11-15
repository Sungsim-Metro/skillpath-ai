"""로켓펀치 공고를 받아 contracts/ 의 ① 공고(posting) 형식으로 바꾼다.

사용:
  python -m pipeline.rocketpunch codes                       # 직군 코드 목록
  python -m pipeline.rocketpunch search -k 클라우드 --codes <코드> --size 20
  python -m pipeline.rocketpunch fetch 159620 159227 ...     # 상세를 받아 본문 필터 후 posting 저장
  python -m pipeline.rocketpunch collect --codes <코드> -n 10  # 목록 → 상세 → 본문 필터, 통과 10건까지

- 원본 응답은 data/raw/ 에 저장한다(저장소에 올리지 않는다).
- ROCKETPUNCH_S3_BUCKET 이 있으면 목록·상세·전처리 JSON을 구분해 S3에도 저장한다.
- DynamoDB 테이블 설정이 있으면 fetch·collect 후 기술 추출과 수요 집계까지 저장한다.
- python -m pipeline.rocketpunch upload --dry-run 으로 기존 파일 업로드를 확인한다.
- 이미 받은 공고는 API 를 다시 부르지 않는다. 429 가 오면 멈추고, 다시 실행하면 이어서 받는다.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pipeline.storage import S3Target, maybe_upload, target_from_env, upload_json

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.rocketpunch.com/v1"  # 문서의 /api/v1 은 404 라서 /v1 을 쓴다
# 본문 필드 순서. 필드 이름과 내용이 다른 공고가 있어 라벨 없이 본문만 잇는다.
TEXT_FIELDS = ("description", "duty", "minimumQualification", "preferredQualification", "benefit")
DEFAULT_TERMS = ("aws",)  # 본문 필터 기본 단어(소문자 비교). 서비스가 AWS 교육 추천이라 aws 만 쓴다. "클라우드"는 게임 공고도 통과시켜 뺐다.


def load_env_file() -> None:
    """루트 .env 를 환경변수로 읽는다. 값은 출력하지 않는다."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def api_get(path: str, params: dict | None = None) -> dict:
    """GET 1회. 429 면 기다리지 않고 Retry-After 를 알리고 종료한다. 한도 헤더는 stderr 에 남긴다."""
    key = os.getenv("ROCKETPUNCH_API_KEY")
    if not key:
        raise SystemExit(".env 에 ROCKETPUNCH_API_KEY 가 없습니다.")
    url = f"{BASE}{path}" + (f"?{urlencode(params, doseq=True)}" if params else "")
    req = Request(url, headers={"X-RP-API-Key": key, "Accept-Language": "ko"})
    try:
        with urlopen(req, timeout=20) as res:
            limits = {k: v for k, v in res.headers.items() if k.lower().startswith("x-rp-ratelimit")}
            print(f"[한도] {path}: {limits}", file=sys.stderr)
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 429:
            raise SystemExit(f"호출 한도 초과(429). {e.headers.get('Retry-After', '?')}초 뒤에 다시 실행하세요.")
        raise SystemExit(f"HTTP {e.code} {path}: {e.read().decode('utf-8', 'replace')[:300]}")
    except URLError as e:
        raise SystemExit(f"연결 실패: {e.reason}")


def clean(text: str | None) -> str:
    """HTML 태그와 엔티티를 지우고 공백을 정리한다. 빈 값은 빈 문자열."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>|</(p|div|li|h\d)>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def to_posting(raw: dict, role: str = "클라우드 엔지니어") -> dict:
    """로켓펀치 상세 응답 → posting(실습 노트북의 표준 필드 + url). role 은 직무가 하나(M2)라 인자로 받는다."""
    company = raw.get("company") or {}
    started = raw.get("startAt") or raw.get("createdAt")  # 게시일. UTC 로 오므로 한국시간 날짜로 바꾼다
    return {
        "id": f"rp-{raw['jobId']}",
        "company": company.get("name") or "",
        "title": clean(raw["title"]),
        "industry": company.get("industry"),  # 산업 코드 그대로(예: FINANCE_ETC)
        "role": role,
        "career": ",".join(raw.get("seniorities") or []) or None,  # 숙련도 원본. 분석에는 쓰지 않는다
        "region": None,  # 로켓펀치 상세 응답에 지역 필드가 없다
        "posted_at": (
            datetime.fromisoformat(started.replace("Z", "+00:00")).astimezone(KST).date().isoformat()
            if started else None
        ),
        "text": "\n".join(p for p in (clean(raw.get(f)) for f in TEXT_FIELDS) if p),
        "url": raw.get("webUrl"),
    }


def matched_terms(posting: dict, terms=DEFAULT_TERMS) -> list[str]:
    """제목+본문에 나온 필터 단어. 비어 있으면 직무와 무관한 공고일 가능성이 크다."""
    haystack = (posting["title"] + "\n" + posting["text"]).lower()
    # 영문 단어는 단어 경계로 비교한다(aws 가 laws 에 걸리지 않게). 한글은 부분 일치.
    return [t for t in terms if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", haystack)]


def write_json(path: Path, data: dict | list) -> None:
    """JSON을 UTF-8, 줄바꿈 LF로 저장한다.

    S3 키는 파일 바이트의 해시다. 줄바꿈을 OS 기본값에 맡기면 Windows에서는 CRLF가 되어
    같은 응답이 다른 키로 올라간다."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def load_or_fetch(job_id: str) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"rp-{job_id}.raw.json"
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = api_get(f"/jobs/{job_id}")
        write_json(path, raw)
    maybe_upload(path)
    return raw


def load_listing(params: dict) -> dict:
    """목록 응답 전체를 캐시한다. 예전에 저장한 items 배열 형식도 그대로 읽는다.

    목록 호출도 job.read 한도를 쓰므로 받은 결과를 저장해 두고 다시 쓴다.
    새로 받으려면 data/raw/list-*.json 을 지운다."""
    name = "-".join(f"{k}={'+'.join(map(str, v)) if isinstance(v, list) else v}" for k, v in sorted(params.items()))
    path = RAW_DIR / f"list-{name}.json"
    if path.exists():
        res = json.loads(path.read_text(encoding="utf-8"))
    else:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        res = api_get("/jobs", params)
        write_json(path, res)
    maybe_upload(path)
    return {"items": res} if isinstance(res, list) else res


def list_page(params: dict) -> list:
    """수집기에 필요한 items만 돌려준다. 전체 응답 저장은 load_listing이 맡는다."""
    res = load_listing(params)
    items = res["items"]
    total = res.get("totalItems", "미상(기존 캐시)")
    print(f"[목록] 전체 {total}건 중 {len(items)}건 ({params})", file=sys.stderr)
    return items


def cmd_codes(_args) -> None:
    for c in api_get("/codes/job-categories"):
        print(f"{c['code']}\t{c['displayName']}")


def cmd_search(args) -> None:
    params = {"pageSize": args.size, "page": args.page, "sort": args.sort}
    if args.keyword:
        params["keyword"] = args.keyword
    if args.codes:
        params["jobCategories"] = args.codes
    listing = load_listing(params)
    total = listing.get("totalItems", "미상(기존 캐시)")
    pages = listing.get("totalPages", "미상")
    print(f"전체 {total}건 / {pages}쪽, 이번 {len(listing['items'])}건 (요청 {params})")
    for it in listing["items"]:
        print(f"{it['jobId']}\t{it.get('jobCategory')}\t{it['company']['name']}\t{it['title'][:40]}")
    print("\njobId:", " ".join(str(it["jobId"]) for it in listing["items"]))


def process(job_id, role: str, terms) -> bool:
    """상세를 받아(있으면 재사용) 본문 필터를 적용하고, 통과하면 posting 을 저장한다."""
    posting = to_posting(load_or_fetch(str(job_id)), role)
    hits = matched_terms(posting, terms)
    out = RAW_DIR / f"{posting['id']}.posting.json"
    if hits:
        write_json(out, posting)
        maybe_upload(out)
    else:
        out.unlink(missing_ok=True)  # 필터 기준이 바뀌었을 때 예전 통과본을 지운다
    print(f"{'통과' if hits else '탈락'}\t{posting['id']}\t필터 {hits or '없음'}\t본문 {len(posting['text'])}자\t{posting['title'][:40]}")
    return bool(hits)


def batch_options(args) -> dict | None:
    """테이블 설정이 있으면 API 호출 전에 추출 배치의 실행 설정을 검사한다."""
    table_names = (
        os.getenv("DYNAMODB_EXTRACTIONS_TABLE", "").strip(),
        os.getenv("DYNAMODB_DEMAND_TABLE", "").strip(),
    )
    if not any(table_names):
        return None

    from backend.jobs import validate_role
    from pipeline.extraction_batch import (
        parse_exclusions, selection_version_for_terms, validate_configuration,
    )

    job_category = getattr(args, "job_category", "cloud_engineer")
    validate_configuration(job_category)
    validate_role(job_category, args.role)
    collected = getattr(args, "collected", None)
    if not collected or not collected.strip():
        raise ValueError("DynamoDB 저장에는 --collected로 수집일 또는 기간을 지정하세요.")
    return {
        "job_category": job_category,
        "collected": collected.strip(),
        "force": getattr(args, "force", False),
        "exclusions": parse_exclusions(getattr(args, "exclude", [])),
        "selection_version": selection_version_for_terms(
            args.terms, getattr(args, "selection_version", None)
        ),
        "terms": args.terms,
    }


def persist_extractions(options: dict | None) -> None:
    """현재 통과본 전체를 한 배치로 분석하고 완성된 집계만 공개한다."""
    if options is None:
        return
    from pipeline.extraction_batch import run_batch

    summary = run_batch(sorted(RAW_DIR.glob("rp-*.posting.json")), **options)
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["published"]:
        raise SystemExit(1)


def cmd_fetch(args) -> None:
    options = batch_options(args)
    for job_id in args.ids:
        process(job_id, args.role, args.terms)
    persist_extractions(options)


def cmd_collect(args) -> None:
    """목록 → 상세 → 본문 필터. 통과가 --n 건이 되거나 429 가 오면 멈춘다. 다시 실행하면 이어서 한다."""
    options = batch_options(args)
    kept = seen = 0
    for page in range(1, args.pages + 1):
        params = {"pageSize": args.size, "page": page, "sort": args.sort}
        if args.keyword:
            params["keyword"] = args.keyword
        if args.codes:
            params["jobCategories"] = args.codes
        items = list_page(params)
        for it in items:
            seen += 1
            kept += process(it["jobId"], args.role, args.terms)
            if kept >= args.n:
                break
        if kept >= args.n or not items:
            break
    print(f"\n후보 {seen}건 확인, 통과 {kept}건, 탈락 {seen - kept}건 (목표 {args.n}건)")
    persist_extractions(options)


def cmd_upload(args) -> None:
    """API를 다시 부르지 않고 기존 로컬 공고 JSON을 S3에 올린다."""
    configured = target_from_env()
    bucket = args.bucket or (configured.bucket if configured else None)
    if not bucket:
        raise SystemExit("--bucket 또는 ROCKETPUNCH_S3_BUCKET으로 대상 버킷을 지정하세요.")
    prefix = args.prefix
    if prefix is None:
        prefix = configured.prefix if configured else S3Target(bucket).prefix
    target = S3Target(bucket, prefix)
    patterns = ("list-*.json", "rp-*.raw.json", "rp-*.posting.json")
    paths = sorted({path for pattern in patterns for path in RAW_DIR.glob(pattern)})
    uploaded = existing = 0
    for path in paths:
        result = upload_json(path, target, dry_run=args.dry_run)
        if args.dry_run:
            print(f"{path.name} -> s3://{bucket}/{result.key}")
        elif result.uploaded:
            uploaded += 1
        else:
            existing += 1
    if args.dry_run:
        print(f"\n업로드 예정 {len(paths)}개 (실제 업로드 없음)")
    else:
        print(f"\nS3 동기화 완료: 업로드 {uploaded}개, 이미 있음 {existing}개, 대상 {len(paths)}개")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("codes").set_defaults(run=cmd_codes)
    s = sub.add_parser("search")
    s.add_argument("-k", "--keyword")
    s.add_argument("--codes", nargs="+", help="API 직군 코드(jobCategories)")
    s.add_argument("--sort", default="DATE_DESC", choices=["RELEVANCE_DESC", "DATE_DESC", "POPULARITY_DESC"])
    s.add_argument("--size", type=int, default=10, help="문서는 50이라지만 실제 최대는 10")
    s.add_argument("--page", type=int, default=1)
    s.set_defaults(run=cmd_search)
    f = sub.add_parser("fetch")
    f.add_argument("ids", nargs="+")
    c = sub.add_parser("collect", help="목록 → 상세 → 본문 필터, 통과 n건까지")
    c.add_argument("-k", "--keyword")
    c.add_argument("--codes", nargs="+", help="API 직군 코드(jobCategories)")
    c.add_argument("--sort", default="DATE_DESC", choices=["RELEVANCE_DESC", "DATE_DESC", "POPULARITY_DESC"])
    c.add_argument("--size", type=int, default=10, help="문서는 50이라지만 실제 최대는 10")
    c.add_argument("--pages", type=int, default=1)
    c.add_argument("-n", type=int, default=10, help="통과 목표 건수")
    u = sub.add_parser("upload", help="기존 로컬 공고 JSON을 S3에 업로드 (API 재호출 없음)")
    u.add_argument("--bucket", help="대상 S3 버킷. 기본값은 ROCKETPUNCH_S3_BUCKET")
    u.add_argument("--prefix", help="S3 경로 접두사. 기본값은 ROCKETPUNCH_S3_PREFIX 또는 skillpath/rocketpunch")
    u.add_argument("--dry-run", action="store_true", help="업로드 경로만 확인")
    u.set_defaults(run=cmd_upload)
    for sp, run in ((f, cmd_fetch), (c, cmd_collect)):
        sp.add_argument("--role", default="클라우드 엔지니어", help="posting 의 role(직무 이름)")
        sp.add_argument("--terms", nargs="+", default=list(DEFAULT_TERMS), help="본문 필터 단어")
        sp.add_argument("--job-category", default="cloud_engineer", help="DynamoDB에 저장할 서비스 직무 코드")
        sp.add_argument("--collected", help="수집일 또는 기간. DynamoDB 저장 시 필수")
        sp.add_argument("--force", action="store_true", help="저장된 동일 입력의 추출 결과도 다시 분석")
        sp.add_argument("--exclude", action="append", default=[], metavar="ID=REASON", help="집계에서 제외할 공고와 사유")
        sp.add_argument("--selection-version", help="선정 규칙 버전. 기본 AWS 규칙은 cloud-aws-v1")
        sp.set_defaults(run=run)
    args = p.parse_args()
    load_env_file()
    args.run(args)


if __name__ == "__main__":
    main()
