"""로켓펀치 공고 1건을 받아 contracts/ 의 ① 공고(posting) 형식으로 바꾼다.

사용: python -m pipeline.rocketpunch <jobId> [job_category]
- 원본 응답은 data/raw/rp-<jobId>.raw.json 에 저장한다(저장소에 올리지 않는다).
- 이미 원본이 있으면 API 를 다시 부르지 않는다. job.read 한도가 10회뿐이라서다.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
BASE = "https://openapi.rocketpunch.com/v1"  # 문서의 /api/v1 은 404 라서 /v1 을 쓴다
# 본문 필드 순서. 필드 이름과 내용이 다른 공고가 있어 라벨 없이 본문만 잇는다.
TEXT_FIELDS = ("description", "duty", "minimumQualification", "preferredQualification", "benefit")


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


def fetch_job(job_id: str) -> dict:
    """상세 조회 1회. 429 면 기다리지 않고 Retry-After 를 알리고 종료한다."""
    key = os.getenv("ROCKETPUNCH_API_KEY")
    if not key:
        raise SystemExit(".env 에 ROCKETPUNCH_API_KEY 가 없습니다.")
    req = Request(f"{BASE}/jobs/{job_id}", headers={"X-RP-API-Key": key})
    try:
        with urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 429:
            raise SystemExit(f"호출 한도 초과(429). {e.headers.get('Retry-After', '?')}초 뒤에 다시 시도하세요.")
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
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


def to_posting(raw: dict, job_category: str = "cloud_engineer") -> dict:
    """로켓펀치 상세 응답 → posting. job_category 는 직무가 하나(M2)라 인자로 받는다."""
    parts = [clean(raw.get(f)) for f in TEXT_FIELDS]
    return {
        "posting_id": f"rp-{raw['jobId']}",
        "title": clean(raw["title"]),
        "company": (raw.get("company") or {}).get("name") or "",
        "job_category": job_category,
        "text": "\n".join(p for p in parts if p),
        "source": "rocketpunch",
        "collected_at": date.today().isoformat(),
    }


def load_or_fetch(job_id: str) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"rp-{job_id}.raw.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    load_env_file()
    raw = fetch_job(job_id)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        raise SystemExit("사용: python -m pipeline.rocketpunch <jobId> [job_category]")
    posting = to_posting(load_or_fetch(sys.argv[1]), *sys.argv[2:3])
    out = RAW_DIR / f"{posting['posting_id']}.posting.json"
    out.write_text(json.dumps(posting, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**posting, "text": posting["text"][:200] + "..."}, ensure_ascii=False, indent=2))
    print(f"\n본문 {len(posting['text'])}자. 저장: {out}")


if __name__ == "__main__":
    main()
