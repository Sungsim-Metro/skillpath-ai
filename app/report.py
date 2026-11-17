"""진단 보고서(HTML 한 장) 만들기 (2026-11-16 결정).

화면에 나온 값만 담는다. 보고서를 위해 계산을 새로 하거나 LLM 을 다시 부르지 않는다.
받은 값을 HTML 로 옮기기만 하므로 화면 코드로 본다. 모든 글자는 HTML 로 해석되지 않게 바꿔 넣는다(html.escape).
PDF 가 아니라 HTML 로 만든 이유: PDF 를 직접 만들려면 한글 글꼴 파일을 함께 넣어야 한다.
HTML 은 폰과 PC 에서 바로 열리고, 브라우저의 인쇄 → "PDF 로 저장"으로 PDF 가 된다(인쇄용 모양을 넣어 두었다).
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo
from html import escape

LEVEL_LABEL = {"used": "써봄", "learned": "배워봄", "none": "없음"}
STYLE = """
body{font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif;color:#1c2330;
     max-width:820px;margin:0 auto;padding:24px 16px;line-height:1.6;font-size:15px}
h1{font-size:24px;margin:0 0 4px} h2{font-size:18px;margin:28px 0 8px;border-bottom:1px solid #d5dae1;padding-bottom:4px}
h3{font-size:16px;margin:16px 0 4px} .muted{color:#5b6472;font-size:13px}
table{border-collapse:collapse;width:100%;margin:8px 0} th,td{border-bottom:1px solid #e3e7ec;padding:6px 8px;text-align:left;vertical-align:top}
th{font-weight:600;background:#f5f7fa} .num{text-align:right;white-space:nowrap}
.bar{background:#e3ebf8;border-radius:4px;height:10px;min-width:80px} .bar>span{display:block;background:#1f5fbf;height:10px;border-radius:4px}
.cards{display:flex;flex-wrap:wrap;gap:8px} .card{flex:1 1 150px;border:1px solid #d5dae1;border-radius:8px;padding:8px 12px}
.card b{display:block;font-size:22px} .tag{font-size:12px;border-radius:4px;padding:1px 6px;background:#fdebd3;color:#8a4b08}
.course{border:1px solid #d5dae1;border-radius:8px;padding:10px 12px;margin:8px 0;break-inside:avoid}
blockquote{margin:6px 0;padding:2px 10px;border-left:3px solid #d5dae1;color:#5b6472;font-size:13px}
a{color:#1f5fbf} .note{background:#f5f7fa;border-radius:8px;padding:10px 12px;font-size:13px}
.wrap{overflow-x:auto} .course,.note,p{overflow-wrap:anywhere}
@media (max-width:520px){body{font-size:14px} th,td{padding:5px 4px;font-size:13px} .bar{min-width:36px} .num{white-space:normal}}
@media print{body{padding:0;font-size:12px} a{color:inherit} h2,h3,h3+.muted{break-after:avoid} tr{break-inside:avoid}
 .bar,.bar>span,th,.note,.tag{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def _today() -> date:
    """한국 날짜. 서버 시간대가 달라도 사용자가 보는 날짜와 맞춘다."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _e(value) -> str:
    return escape(str(value), quote=True)


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _safe_url(url: str) -> str:
    """http(s) 주소만 링크로 건다. 그 밖의 값은 빈 문자열(링크 없음)."""
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else ""


def build_report(*, job_title: str, demand: dict, gap_rows: list[dict], area_rows: list[dict], recommendations: list[dict],
                 owned: list[str], levels: dict[str, str] | None = None, mock: bool = False, today: date | None = None,
                 recommend_failed: bool = False) -> str:
    """진단 보고서 HTML 문자열. 인자는 모두 화면이 이미 받아 둔 값이다.

    recommend_failed: 추천을 불러오지 못했을 때 참. "추천할 과정이 없다"와 구분해 적는다.
    """
    today = today or _today()
    missing = [r for r in gap_rows if not r["owned"]]
    have = [r for r in gap_rows if r["owned"]]
    levels = levels or {s: "used" for s in owned}
    origin = ", ".join(demand.get("sources") or []) or "표기 없음"

    owned_rows = "".join(
        f"<tr><td>{_e(skill)}</td><td>{_e(LEVEL_LABEL.get(level, level))}</td></tr>" for skill, level in levels.items()
    ) or '<tr><td colspan="2">고른 기술이 없습니다.</td></tr>'

    area_html = "".join(
        f"<tr><td>{_e(r['area'])}</td><td><div class='bar'><span style='width:{min(max(r['coverage'], 0), 1) * 100:.0f}%'></span></div></td>"
        f"<td class='num'>{_pct(r['coverage'])}</td><td class='num'>{_e(r['owned'])} / {_e(r['demand'])}</td>"
        f"<td>{_e(', '.join(r['missing_skills']) or '없음')}</td></tr>"
        for r in area_rows if r["demand"] > 0
    )
    missing_html = "".join(
        f"<tr><td>{_e(r['skill'])}{' <span class=tag>배워봄 · 보강</span>' if r.get('level') == 'learned' else ''}</td>"
        f"<td>{_e(r['area'])}</td><td class='num'>{_e(r['postings'])} / {_e(r['of'])}</td><td class='num'>{_pct(r['ratio'])}</td>"
        f"<td class='num'>{_pct(r['required_ratio'])}</td></tr>"
        for r in missing
    ) or '<tr><td colspan="5">주요 요구 기술을 모두 보유했습니다.</td></tr>'

    rec_html = ""
    for i, rec in enumerate(recommendations, start=1):
        d = rec["demand"]
        rec_html += (f"<h3>{i}. {_e(rec['gap_skill'])}</h3><div class='muted'>공고 {_e(d['of'])}건 중 {_e(d['postings'])}건이 요구 · "
                     f"그중 필수 {_pct(d['required_ratio'])}</div>")
        if not rec["courses"]:
            rec_html += "<p class='muted'>이 기술을 다루는 교육과정을 찾지 못했습니다.</p>"
        for c in rec["courses"]:
            url = _safe_url(c.get("url", ""))
            title = f"<a href='{_e(url)}'>{_e(c['title'])}</a>" if url else _e(c["title"])
            tag = " <span class='tag'>불확실</span>" if c.get("match") == "uncertain" else ""
            evidence = c.get("evidence") or {}
            # 화면과 같은 기준: 이 기술 이름이 나오는 학습 목표 문장만 인용한다. 같은 영역일 뿐인 문장과 제목은 인용하지 않는다
            quotable = evidence.get("text") and evidence.get("about") == "skill" and evidence.get("field") != "title"
            quote = f"<blockquote>{_e(evidence['text'])}</blockquote>" if quotable else ""
            link = f"<div class='muted'>{_e(url)}</div>" if url else ""
            rec_html += (f"<div class='course'><b>{title}</b>{tag}<div class='muted'>난이도 {_e(c['level'])} · 선수지식 {_e(c['prerequisites'])}</div>"
                         f"<div>{_e(c['reason'])}</div>{quote}{link}</div>")
    skipped = [r["skill"] for r in missing if r["skill"] not in {x["gap_skill"] for x in recommendations}]
    if recommend_failed or (missing and not recommendations):
        rec_html = "<p>추천을 불러오지 못해 이 절은 비어 있습니다. 화면의 학습 추천 탭을 다시 확인해 주세요.</p>"
    elif not recommendations:
        rec_html = "<p>부족한 기술이 없어 추천할 과정이 없습니다.</p>"
    elif skipped:
        rec_html += (f"<p class='muted'>수요가 높은 {len(recommendations)}개 기술만 추천했습니다. "
                     f"이번에 추천하지 않은 기술: {_e(', '.join(skipped))}</p>")
    partial_note = " 배워봄으로 고른 기술은 절반만 보유한 것으로 셉니다." if any(v == "learned" for v in levels.values()) else ""

    mock_note = "<p class='note'><b>가짜 데이터 모드에서 만든 보고서입니다.</b> 숫자와 과정은 예시입니다.</p>" if mock else ""
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(job_title)} 역량 진단 보고서</title><style>{STYLE}</style></head><body>
<h1>{_e(job_title)} 역량 진단 보고서</h1>
<div class="muted">만든 날 {today.isoformat()} · skillpath-ai</div>
{mock_note}
<h2>1. 분석한 데이터</h2>
<p>채용공고 {_e(demand['total_postings'])}건에서 뽑은 기술 {_e(len(demand['skills']))}개를 기준으로 했습니다.
수집일 {_e(demand.get('collected') or '표기 없음')}, 출처 {_e(origin)}.{' ' + _e(demand['note']) if demand.get('note') else ''}</p>
<div class="cards">
<div class="card">주요 요구 기술<b>{len(gap_rows)}개</b><span class="muted">공고의 20% 이상이 요구</span></div>
<div class="card">그중 보유<b>{len(have)}개</b></div>
<div class="card">부족<b>{len(missing)}개</b></div>
</div>
<h2>2. 내가 고른 보유 기술</h2>
<div class='wrap'><table><tr><th>기술</th><th>수준</th></tr>{owned_rows}</table></div>
<div class="muted">수준은 스스로 고른 값이며 실력을 검증한 것이 아닙니다.</div>
<h2>3. 영역별 충족률</h2>
<div class='wrap'><table><tr><th>영역</th><th>충족률</th><th class="num"></th><th class="num">보유 / 수요</th><th>부족한 기술</th></tr>{area_html}</table></div>
<div class="muted">수요는 그 영역의 기술을 요구한 공고 건수의 합, 보유는 그중 내가 가진 기술의 몫입니다.{partial_note}</div>
<h2>4. 부족한 기술 (수요 높은 순)</h2>
<div class='wrap'><table><tr><th>기술</th><th>영역</th><th class="num">요구 공고</th><th class="num">요구 비율</th><th class="num">그중 필수</th></tr>{missing_html}</table></div>
<h2>5. 추천 교육과정</h2>
{rec_html}
<h2>읽을 때 주의할 점</h2>
<div class="note">
이 보고서는 무엇을 공부할지 안내하는 자료이며 실력을 검증하거나 합격을 보장하지 않습니다.
수요는 수집한 공고에 한정된 숫자이고, 경력 공고가 섞여 있습니다.
"불확실"로 표시한 과정은 그 기술을 직접 다룬다는 근거를 찾지 못한 관련 과정입니다. 링크에서 내용을 확인하세요.
PDF 로 보관하려면 브라우저의 인쇄에서 "PDF 로 저장"을 고르세요.
</div>
</body></html>"""


def file_name(today: date | None = None) -> str:
    return f"skillpath-report-{(today or _today()).strftime('%Y%m%d')}.html"
