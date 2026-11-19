"""산업별 채용공고의 기술 수요 비중과 학습 프로그램의 기술 공급 비중으로 시장 Gap을 계산한다."""

import csv
import io
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict

# 계산 명세에서 정한 24개 대표명과 66개 별칭을 사용한다.
_ALIASES = {
    "AWS": ("AWS", "Amazon Web Services", "아마존 웹 서비스", "aws"),
    "Azure": ("Azure", "MS Azure", "애저"),
    "GCP": ("GCP", "Google Cloud", "구글 클라우드"),
    "Kubernetes": ("Kubernetes", "쿠버네티스", "k8s", "K8S"),
    "Docker": ("Docker", "도커", "컨테이너(Docker)"),
    "Terraform": ("Terraform", "테라폼", "IaC(Terraform)"),
    "CI/CD": ("CI/CD", "CICD", "지속적 통합·배포"),
    "Linux": ("Linux", "리눅스"),
    "Python": ("Python", "파이썬", "python"),
    "SQL": ("SQL", "sql"),
    "Spark": ("Spark", "Apache Spark", "스파크"),
    "Airflow": ("Airflow", "에어플로우", "Apache Airflow"),
    "PyTorch": ("PyTorch", "파이토치"),
    "TensorFlow": ("TensorFlow", "텐서플로"),
    "LLM": ("LLM", "대규모 언어모델", "거대언어모델"),
    "RAG": ("RAG", "검색증강생성"),
    "MLOps": ("MLOps", "ML Ops", "머신러닝 운영"),
    "Prompt Engineering": ("프롬프트 엔지니어링", "Prompt Engineering"),
    "Amazon Bedrock": ("Amazon Bedrock", "Bedrock", "아마존 베드록"),
    "SageMaker": ("SageMaker", "세이지메이커", "Amazon SageMaker"),
    "Java": ("Java", "자바"),
    "Spring": ("Spring", "Spring Boot", "스프링"),
    "React": ("React", "리액트"),
    "정보보안": ("정보보안", "보안 관제", "클라우드 보안"),
}
_PATTERNS = {
    skill: tuple(
        re.compile(r"(?<![A-Za-z가-힣])" + re.escape(alias) + r"(?![A-Za-z])")
        for alias in sorted(aliases, key=len, reverse=True)
    )
    for skill, aliases in _ALIASES.items()
}
_HEADING = re.compile(r"\s*\[(.+?)\]")
_WEIGHTS = {"자격요건": 1.0, "주요업무": 0.7, "우대사항": 0.5}
CSV_FIELDS = ("industry", "skill", "demand_pct", "supply_pct", "gap_pp")
PROGRAM_TEXT_FIELDS = ("title", "description", "objectives")


class SkillSupply(TypedDict):
    skill: str
    courses: int


class EducationSupply(TypedDict):
    source: str
    total_courses: int
    skills: list[SkillSupply]
    note: NotRequired[str]


class GapRow(TypedDict):
    industry: str
    skill: str
    demand_pct: float
    supply_pct: float
    gap_pp: float


class RankedGap(TypedDict):
    skill: str
    gap_pp: float


class GapAnalysis(TypedDict):
    rows: list[GapRow]
    top3: dict[str, list[RankedGap]]


def extract_skills(text: str) -> list[str]:
    """본문에서 찾은 별칭을 대표명으로 모아 이름순으로 반환한다."""
    return sorted(
        skill for skill, patterns in _PATTERNS.items()
        if any(pattern.search(text) for pattern in patterns)
    )


def posting_weights(text: str) -> dict[str, float]:
    """공고 한 건에서 기술마다 가장 높은 구역 가중치를 구한다."""
    sections: dict[str, list[str]] = {}
    section = "기타"
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            section = heading.group(1)
            sections[section] = []
        elif line.strip():
            sections.setdefault(section, []).append(line.strip("- ").strip())

    weights: dict[str, float] = {}
    for section, lines in sections.items():
        weight = _WEIGHTS.get(section, 0.5)
        for skill in extract_skills("\n".join(lines)):
            weights[skill] = max(weights.get(skill, 0.0), weight)
    return weights


def _shares(totals: Mapping[str, float], record_count: int) -> dict[str, float]:
    rates = {skill: total / record_count for skill, total in totals.items()}
    # Python 3.12 changed float sum(). Preserve the reference's Python 3.11 rounding.
    rate_sum = 0.0
    for rate in rates.values():
        rate_sum += rate
    denominator = rate_sum or 1.0
    return {skill: rate / denominator for skill, rate in rates.items()}


def gap_table(demand: dict[str, float], supply: dict[str, float]) -> list[RankedGap]:
    """0~1 비중의 차이를 %p로 환산해 반올림한 뒤 산업 내 상위 세 기술을 구한다."""
    ranking: list[RankedGap] = []
    for skill in demand.keys() | supply.keys():
        gap = demand.get(skill, 0.0) - supply.get(skill, 0.0)
        ranking.append({"skill": skill, "gap_pp": round(gap * 100, 1)})
    return sorted(ranking, key=lambda row: row["gap_pp"], reverse=True)[:3]


def aggregate_supply(courses: Sequence[Mapping[str, str | None]], source: str) -> EducationSupply:
    """학습 프로그램 전체에서 각 기술을 다루는 과정 수를 세어 교육 공급 집계(⑤)를 만든다."""
    counts: Counter[str] = Counter()
    for program in courses:
        text = " ".join(program[field] or "" for field in PROGRAM_TEXT_FIELDS)
        counts.update(extract_skills(text))
    return {
        "source": source,
        "total_courses": len(courses),
        "skills": [{"skill": skill, "courses": count} for skill, count in counts.items()],
    }


def analyze_gap_from_supply(
    postings: Sequence[Mapping[str, str]], supply: EducationSupply
) -> GapAnalysis:
    """산업별 채용 수요와 교육 공급 집계의 비중을 비교해 시장 Gap과 상위 세 기술을 구한다."""
    posting_counts: Counter[str] = Counter()
    demand_totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for posting in postings:
        industry = posting["industry"]
        posting_counts[industry] += 1
        for skill, weight in posting_weights(posting["text"]).items():
            demand_totals[industry][skill] += weight

    counts = {row["skill"]: row["courses"] for row in supply["skills"]}
    supply_shares = _shares(counts, supply["total_courses"])

    rows: list[GapRow] = []
    top3: dict[str, list[RankedGap]] = {}
    for industry, totals in demand_totals.items():
        demand = _shares(totals, posting_counts[industry])
        top3[industry] = gap_table(demand, supply_shares)
        for skill in sorted(demand.keys() | supply_shares.keys()):
            demand_pct = demand.get(skill, 0.0) * 100
            supply_pct = supply_shares.get(skill, 0.0) * 100
            rows.append({
                "industry": industry,
                "skill": skill,
                "demand_pct": round(demand_pct, 1),
                "supply_pct": round(supply_pct, 1),
                "gap_pp": round(demand_pct - supply_pct, 1),
            })
    return {"rows": rows, "top3": top3}


def analyze_gap(
    postings: Sequence[Mapping[str, str]], courses: Sequence[Mapping[str, str | None]]
) -> GapAnalysis:
    """공고와 프로그램 원본에서 공급 집계와 산업별 시장 Gap을 계산한다."""
    return analyze_gap_from_supply(postings, aggregate_supply(courses, source="학습 프로그램 목록"))


def calculate_gap(
    postings: Sequence[Mapping[str, str]], courses: Sequence[Mapping[str, str | None]]
) -> list[GapRow]:
    """Skills Gap 명세의 대시보드 5열에 해당하는 행을 반환한다."""
    return analyze_gap(postings, courses)["rows"]


def gap_csv(rows: Sequence[GapRow]) -> bytes:
    """빈 결과도 헤더를 갖는 UTF-8 BOM CSV로 직렬화한다."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")
