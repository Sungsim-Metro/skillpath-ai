"""공개용 저장소에 넣을 협업 근거 문서를 만든다.

사용법: python3 .github/public-sync/collab.py 출력폴더

만드는 파일
- COLLABORATION.md: 역할 분담과 일하는 방식(COLLABORATION.head.md) + GitHub 기록 요약
- docs/meeting-decisions.md: 회의록의 "1. 결정 사항" 절만 발췌

숫자는 전부 GitHub API 결과를 코드로 센 것이다(세기는 코드).
공개하지 않기로 한 문구(FORBIDDEN)가 든 제목과 줄은 빼고, 뺀 개수만 적는다.
GitHub 아이디는 공개 문서에 적지 않고 TEAM의 이름으로 바꾼다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "Sungsim-Metro/skillpath-ai")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KST = timezone(timedelta(hours=9))
FORBIDDEN = re.compile("녹취|교안|멘토")
RECENT_PRS = 15
# 팀원별 PR 수와 PR 작성자를 공개 문서에 적을지. 지금은 PR이 한 사람에게 몰려 있어 끈다.
# 팀원 PR이 고르게 쌓이면 True로 바꾼다(형섭 결정).
SHOW_PR_AUTHORS = False

# 팀원이 바뀌면 여기를 고친다. 공개 문서에는 아이디 대신 이름과 역할만 나간다.
TEAM = {
    "simhyeongseop": ("형섭", "팀장·PM·프론트엔드"),
    "IlhyeonChoo": ("일현", "AWS 백엔드"),
    "202202571": ("종훈", "데이터·RAG"),
    "baeseongjin123": ("성진", "AI"),
}


def api(path: str) -> list[dict]:
    """gh api로 목록을 끝 페이지까지 받는다."""
    sep = "&" if "?" in path else "?"
    out = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{REPO}/{path}{sep}per_page=100", "--jq", ".[]"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def who(login: str | None) -> str:
    if login in TEAM:
        return TEAM[login][0]
    if login and login.endswith("[bot]"):
        return "자동 리뷰(Claude)" if login.startswith("claude") else "자동화"
    return "기타"


def day(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST).strftime("%m/%d")


def cell(text: str) -> str:
    return text.replace("|", "\\|").strip()


def github_summary() -> str:
    items = api("issues?state=all")
    issues = [i for i in items if "pull_request" not in i]
    prs = api("pulls?state=all")
    milestones = api("milestones?state=all")
    comments = api("issues/comments") + api("pulls/comments")

    merged = [p for p in prs if p.get("merged_at")]
    closed_issues = [i for i in issues if i["state"] == "closed"]
    by_kind = Counter("bot" if (c["user"]["login"] or "").endswith("[bot]") else "team" for c in comments)

    lines = [
        "## GitHub 기록 요약",
        "",
        f"{datetime.now(KST).strftime('%Y-%m-%d %H:%M')} 기준. 개발 저장소의 이슈와 PR을 코드로 센 숫자이며, 게시할 때마다 새로 만듭니다.",
        "",
        "| 항목 | 수 |",
        "| --- | --- |",
        f"| 이슈 | {len(issues)}개 (닫힘 {len(closed_issues)}) |",
        f"| PR | {len(prs)}개 (병합 {len(merged)}) |",
        f"| PR·이슈 댓글 | 팀원 {by_kind['team']}개, 자동 리뷰 {by_kind['bot']}개 |",
        "",
        "### 마일스톤 진행",
        "",
        "| 마일스톤 | 기한 | 닫힌 이슈 / 전체 |",
        "| --- | --- | --- |",
    ]
    for m in sorted(milestones, key=lambda m: m.get("due_on") or ""):
        total = m["open_issues"] + m["closed_issues"]
        lines.append(f"| {cell(m['title'])} | {day(m.get('due_on'))} | {m['closed_issues']} / {total} |")

    head = "| 팀원 | 역할 | 맡은 이슈 (닫힘 / 전체) |" + (" 올린 PR (병합 / 전체) |" if SHOW_PR_AUTHORS else "")
    lines += ["", "### 담당자별", "", head, "| --- | --- | --- |" + (" --- |" if SHOW_PR_AUTHORS else "")]
    for login, (name, role) in TEAM.items():
        mine = [i for i in issues if any(a["login"] == login for a in i.get("assignees", []))]
        done = [i for i in mine if i["state"] == "closed"]
        row = f"| {name} | {role} | {len(done)} / {len(mine)} |"
        if SHOW_PR_AUTHORS:
            my_prs = [p for p in prs if p["user"]["login"] == login]
            row += f" {len([p for p in my_prs if p.get('merged_at')])} / {len(my_prs)} |"
        lines.append(row)

    head = "| 번호 | 병합일 |" + (" 작성 |" if SHOW_PR_AUTHORS else "") + " 제목 |"
    lines += ["", f"### 최근 병합한 PR ({RECENT_PRS}개까지)", "", head, "| --- | --- |" + (" --- |" if SHOW_PR_AUTHORS else "") + " --- |"]
    shown = hidden = 0
    for p in sorted(merged, key=lambda p: p["merged_at"], reverse=True):
        if shown >= RECENT_PRS:
            break
        if FORBIDDEN.search(p["title"]):
            hidden += 1
            continue
        author = f" {who(p['user']['login'])} |" if SHOW_PR_AUTHORS else ""
        lines.append(f"| #{p['number']} | {day(p['merged_at'])} |{author} {cell(p['title'])} |")
        shown += 1
    if hidden:
        lines += ["", f"공개 범위 밖 자료를 다룬 PR {hidden}개는 제목을 적지 않았습니다."]
    lines += ["", "이슈와 PR 원문은 개발 저장소(비공개)에 있습니다. 필요하면 팀이 읽기 권한으로 초대합니다."]
    return "\n".join(lines) + "\n"


LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def meeting_decisions() -> str:
    out = [
        "# 회의 결정 사항",
        "",
        "정기 회의록에서 \"결정 사항\" 절만 옮긴 것입니다. 할 일, 점검표, 그 밖의 기록은 개발 저장소(비공개)에 있습니다.",
        "공개 범위 밖 자료를 언급한 줄은 뺐습니다.",
    ]
    files = sorted((ROOT / "docs" / "meetings").glob("20??-??-??.md"), reverse=True)
    for f in files:
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^## 1\. 결정 사항\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        if not m:
            continue
        kept, dropped = [], 0
        for line in m.group(1).rstrip().splitlines():
            if FORBIDDEN.search(line):
                dropped += 1
                continue
            kept.append(LINK.sub(r"\1", line))
        out += ["", f"## {f.stem} 회의", ""] + kept
        if dropped:
            out += ["", f"(공개 범위 밖 {dropped}줄 생략)"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)) + "\n"


def main() -> int:
    dest = Path(sys.argv[1])
    head = (HERE / "COLLABORATION.head.md").read_text(encoding="utf-8").rstrip() + "\n\n"
    try:
        summary = github_summary()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        if os.environ.get("CI"):
            print(f"❌ GitHub 기록을 읽지 못했습니다: {type(e).__name__}")
            return 1
        print("알림: gh로 GitHub 기록을 읽지 못해 요약 없이 만듭니다(로컬 실행).")
        summary = "## GitHub 기록 요약\n\n게시할 때 자동으로 채워집니다.\n"
    (dest / "COLLABORATION.md").write_text(head + summary, encoding="utf-8")
    (dest / "docs").mkdir(exist_ok=True)
    (dest / "docs" / "meeting-decisions.md").write_text(meeting_decisions(), encoding="utf-8")
    print("협업 문서 2개 생성: COLLABORATION.md, docs/meeting-decisions.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
