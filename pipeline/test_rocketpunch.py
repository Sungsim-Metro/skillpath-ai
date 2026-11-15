"""to_posting 확인. 실행: python -m pipeline.test_rocketpunch"""
import re

from pipeline.rocketpunch import _slug, matched_terms, posting_path, to_posting

RAW = {
    "jobId": 1,
    "title": "클라우드 &amp; 백엔드 엔지니어",
    "company": {"name": "가상회사", "industry": "FINANCE_ETC"},
    "seniorities": ["JUNIOR", "MIDLEVEL"],
    "startAt": "2026-10-26T15:00:00Z",  # UTC 15시 = 한국시간 다음 날 0시
    "webUrl": "https://www.rocketpunch.com/jobs/1",
    "description": "<p>AWS 운영</p><p>&nbsp;</p>",
    "duty": None,
    "minimumQualification": "Python 개발 경험<br/>Linux 이해",
    "preferredQualification": "Docker 우대",
    "benefit": "",
}


def demo():
    p = to_posting(RAW)
    # 실습 노트북의 표준 필드 + url (contracts/README.md ①)
    assert set(p) == {"id", "company", "title", "industry", "role", "career", "region", "posted_at", "text", "url"}
    assert p["id"] == "rp-1" and p["company"] == "가상회사" and p["role"] == "클라우드 엔지니어"
    assert p["industry"] == "FINANCE_ETC" and p["career"] == "JUNIOR,MIDLEVEL" and p["region"] is None
    assert p["posted_at"] == "2026-10-27" and p["url"] == "https://www.rocketpunch.com/jobs/1"
    assert p["title"] == "클라우드 & 백엔드 엔지니어"
    empty = to_posting({**RAW, "seniorities": [], "startAt": None, "webUrl": None})
    assert empty["career"] is None and empty["posted_at"] is None and empty["url"] is None  # 값이 없으면 null
    # 칸마다 제목을 한 줄에 단독으로 쓰고, 빈 칸(duty, benefit)은 제목도 쓰지 않는다
    assert p["text"] == (
        "[포지션소개]\nAWS 운영\n[자격요건]\nPython 개발 경험\nLinux 이해\n[우대사항]\nDocker 우대"
    ), p["text"]
    # ai/sections.py 가 이 제목으로 칸을 찾는다
    from ai.sections import find_section
    assert find_section(p["text"], "Python 개발 경험") == "qualification"
    assert find_section(p["text"], "Docker 우대") == "preference"
    assert find_section(p["text"], "AWS 운영") == "other"  # 포지션소개는 표에 없는 칸이라 other
    assert not re.search(r"<[^>]+>|&\w+;", p["text"])
    # 직무 필터는 제목만 본다: 제목의 '클라우드'는 걸리고, 본문에만 있는 aws 는 직무 판단에 쓰지 않는다
    assert matched_terms(p) == ["클라우드"]
    assert matched_terms(p, ["aws"]) == []
    assert matched_terms(p, ["aws"], fields=("title", "text")) == ["aws"]  # 본문까지 보려면 fields 로 지정
    assert matched_terms(p, ["kafka"]) == []
    assert matched_terms({"title": "laws", "text": "flaws, AWS2"}, ["aws"], fields=("title", "text")) == []  # 단어 경계
    # 제목 기준 판정 예: 클라우드 계열 직무는 통과, 개발·보안 직무는 탈락(본문에 aws 가 있어도)
    for title, ok in (("Site Reliability Engineer (DevOps)", True), ("클라우드·서버 운영 엔지니어", True),
                      ("[한패스] 핀테크 IT 인프라 운영 관리 담당", True), ("MLOps Engineer", True),
                      ("SW·인프라 아키텍트", True), ("[ESTsecurity] 시스템 엔지니어 (경력)", True),
                      ("Node.js 개발자", False), ("시니어 풀스택 개발자", False), ("레드팀 엔지니어", False),
                      ("AI 프로덕트 엔지니어 (RN 앱, Node 서버)", False)):
        assert bool(matched_terms({"title": title, "text": "AWS 경험"})) == ok, title


def names():
    # 사람이 열어 볼 파일 이름: id 가 맨 앞, 회사와 제목이 읽을 수 있게 들어간다
    p = {"id": "rp-159502", "company": "한패스", "title": "[ 한패스 ] 핀테크 IT 인프라 운영 관리 담당 경력"}
    assert posting_path(p).name == "rp-159502_한패스_핀테크-IT-인프라-운영-관리-담당-경력.posting.json", posting_path(p).name
    # 윈도우에서 못 쓰는 문자(/ : ? " 등)와 [꼬리표]는 빠지고, 길이는 제한된다
    assert _slug('Redis/DevOps: "Engineer"?', 40) == "Redis-DevOps-Engineer"
    assert _slug("[KR] Customer On-prem Engineer (DevOps)", 40) == "Customer-On-prem-Engineer-DevOps"
    assert len(_slug("가" * 100, 30)) == 30 and _slug("", 10) == "무제" and _slug("[전부 꼬리표]", 10) == "무제"
    assert _slug("(주)허드슨에이아이", 12) == "허드슨에이아이" and _slug("더선한 주식회사", 12) == "더선한"
    # 같은 회사의 다른 공고는 id 가 달라 이름이 겹치지 않는다
    assert posting_path({**p, "id": "rp-159503"}).name != posting_path(p).name


def export_eval():
    """채점용 내보내기: 튜닝에 쓴 공고는 빼고, AWS 언급 공고를 먼저(직무 통과 우선), 나머지는 직무 통과 공고로 채운다."""
    import contextlib
    import csv
    import io
    import json
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace

    import pipeline.rocketpunch as rp

    def raw(job_id, title, body):
        return {"jobId": job_id, "title": title, "company": {"name": f"회사{job_id}"}, "description": body,
                "webUrl": f"https://example.com/{job_id}"}

    jobs = [raw(1, "클라우드 엔지니어", "AWS 운영"),            # 튜닝에 쓴 공고라 빠진다
            raw(2, "클라우드 엔지니어", "AWS 운영 경험"),       # 직무 통과 + AWS
            raw(3, "DevOps Engineer", "쿠버네티스 운영"),        # 직무 통과
            raw(4, "백엔드 개발자", "AWS 사용 경험"),            # 직무 밖 + AWS
            raw(5, "프론트엔드 개발자", "React 개발"),           # 직무 밖, AWS 없음 → 안 뽑힌다
            raw(6, "SRE", "모니터링 운영")]                      # 직무 통과
    old = rp.RAW_DIR, rp.EVAL_DIR, rp.TUNING_FILE
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        rp.RAW_DIR, rp.EVAL_DIR, rp.TUNING_FILE = tmp, tmp / "eval", tmp / "tuning_ids.json"
        try:
            rp.TUNING_FILE.write_text(json.dumps({"ids": [1]}), encoding="utf-8")
            for j in jobs:
                (tmp / f"rp-{j['jobId']}.raw.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
            (tmp / "eval").mkdir()
            (tmp / "eval" / "eval-99_예전.json").write_text("{}", encoding="utf-8")  # 다시 내보내면 지워진다
            args = SimpleNamespace(n=4, min_aws=2, role="클라우드 엔지니어", terms=list(rp.ROLE_TERMS))
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rp.cmd_export_eval(args)
            files = sorted(p.name for p in (tmp / "eval").glob("eval-*.json"))
            assert len(files) == 4 and not any("99" in f for f in files), files
            rows = list(csv.DictReader((tmp / "eval" / "eval-목록.csv").open(encoding="utf-8-sig", newline="")))
            ids = [r["id"] for r in rows]
            assert ids[:2] == ["rp-2", "rp-4"], ids          # AWS 언급 공고 2건이 먼저(직무 통과가 앞)
            assert set(ids) == {"rp-2", "rp-4", "rp-6", "rp-3"}  # 튜닝에 쓴 1번, AWS 없는 직무 밖 5번은 없다
            assert [r["직무 필터"] for r in rows[:2]] == ["통과", "밖"] and rows[1]["AWS 언급"] == "있음"
            # 직무 필터 밖 공고는 role 을 바꿔 수요 집계에 섞이지 않게 표시한다
            out_file = next(p for p in (tmp / "eval").glob("eval-*_rp-4_*.json"))
            assert json.loads(out_file.read_text(encoding="utf-8"))["role"] == rp.NOT_ROLE
            # 목표에 못 미치면 경고를 낸다
            args.n, args.min_aws = 10, 4
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rp.cmd_export_eval(args)
            assert "목표" in out.getvalue() and "부족" in out.getvalue()
        finally:
            rp.RAW_DIR, rp.EVAL_DIR, rp.TUNING_FILE = old


if __name__ == "__main__":
    demo()
    names()
    export_eval()
    print("통과")
