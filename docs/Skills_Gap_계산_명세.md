# Skills Gap 계산 명세

## SkillPath AI의 직군별 시장 Gap

**Gap(%p) = 선택한 직군의 기술 수요 비중(%) − 학습 프로그램의 기술 공급 비중(%)**

수요는 AI 엔지니어와 클라우드 엔지니어 각각의 공고에서 구합니다. 공고마다 해당 기술의 가장 높은 구역 가중치를 적용하고, 그 직군 안에서 비중을 계산합니다. 두 직군에 모두 속한 공고는 각 직군에서 한 번씩 셉니다.

공고의 칸 제목과 가중치는 공통 규칙을 따릅니다. 예를 들어 `[기술역량]`은 자격요건(1.0), `[담당업무]`는 주요업무(0.7), `[우대조건]`은 우대사항(0.5)입니다. 혜택·복지, 회사소개 등 제외 칸은 세지 않습니다. 원문 사전 매칭에는 기술별 필수·우대 판정이 없어 제목이 없거나 미분류인 칸은 0.5를 적용합니다. [공고 칸 규칙](../ai/sections.py)

공고와 과정에서 기술을 찾을 때는 팀 별칭 사전의 대표명과 별칭을 사용합니다. 예를 들어 `docker`와 `도커`는 Docker로 세고, `SQL Server`는 MSSQL로 셉니다. 개인 진단의 수요 집계는 공고 수와 필수 비율을, 시장 Gap은 원문에서 찾은 기술의 가중 비중을 표시합니다. [팀 별칭 사전](../data/aliases.json)

공급은 두 직군에 같은 학습 프로그램 목록을 사용합니다. 제목(`title`), 설명(`description`), 학습 목표(`objectives`)에서 기술을 찾고, 한 프로그램에서 같은 기술은 한 번만 셉니다. 기술별 프로그램 수를 모든 (프로그램, 기술) 쌍의 수로 나눠 비중을 구합니다. 현재 출처는 `data/courses/courses.csv`에 수집한 AWS Skill Builder 과정입니다. [프로그램 목록](../data/courses/courses.csv)

Docker의 공급 비중(%)은 `100 × Docker가 검출된 과정 수 ÷ 모든 기술의 과정 수 합계`입니다. 예시 공고의 Docker 수요 비중에서 이 공급 비중을 뺀 뒤 소수 첫째 자리로 반올림하면 예시 Gap(%p)이 됩니다. 저장소 루트에서 `python -m pipeline.market_gap --example`을 실행하면 현재 과정 목록으로 계산한 결과를 확인할 수 있습니다. [예시 공고](../data/sample/market_postings.json)

## 대학 교과목을 사용한 원본 실습

아래는 대학 교과목을 공급 자료로 사용한 원본 실습의 명세와 검산 예시다. 실습의 Skills Gap은 **한 산업의 채용 수요에서 특정 기술이 차지하는 비중**에서 **전체 대학 교과목의 기술 구성에서 같은 기술이 차지하는 비중**을 뺀 값이다. 산업과 기술을 한 쌍으로 계산하며, 단위는 퍼센트포인트(%p)다.

> **Gap(%p) = 산업 안에서의 기술 수요 비중(%) − 전체 교과목에서의 기술 공급 비중(%)**

예를 들어 현재 표에서 IT서비스의 Kubernetes는 수요 10.1%, 공급 0.0%로 **+10.1%p**다. 같은 산업의 Python은 수요 9.2%, 공급 22.2%로 **−13.0%p**다. 양수는 표본에서 교육이 해당 기술을 상대적으로 적게 다룬다는 뜻이고, 음수는 교육에서 차지하는 비중이 더 크다는 뜻이다. 0에 가까울수록 두 비중이 비슷하다. 분석 단위는 산업이며, 개인의 숙련도나 부족 인원 수는 이 지표로 측정하지 않는다.

### 1. 입력 데이터

| 입력 한 행 | 계산에 사용하는 필드 | 읽는 방법 |
|---|---|---|
| 채용공고 한 건 | `industry` 산업명, `text` 줄바꿈을 보존한 본문 | `outputs/postings_clean.json`의 레코드 배열을 우선 사용한다. 제목이나 미리 추출해 둔 `skills_rule`은 합산하지 않는다. |
| 교과목 한 개 | `asubjName` 과목명, `eduText` 교육 내용, `subjGoal` 교육 목표 | `data/ncs/ncs_courses_sample.json`의 `data` 배열 전체를 사용한다. 학과, 학점, 수강 인원에 따른 필터나 가중치는 없다. |
| 기술 사전 | 대표 기술명과 별칭 목록 | 아래 참조 코드에 현재 사전의 24개 대표명과 66개 별칭을 모두 수록했다. 카테고리는 계산에 사용하지 않는다. |

정제 공고 파일이 없으면 `data/raw/job_postings_raw.json`의 `response.items`에서 `indTpNm`을 산업명으로, `jobCont`를 본문으로 가져온다. 본문 정제는 순서대로 정규식 `<[^>]+>`와 `&[a-z]+;`의 일치 부분을 각각 공백으로 바꾸고, `[ \t]+`를 공백 하나로 줄인 뒤 양끝 공백을 제거한다. 원래 줄바꿈은 유지되며 HTML의 `<br>`는 공백이 된다. 이미 정제된 파일을 읽을 때는 이 처리를 반복하지 않는다. 이후 계산은 입력 행을 그대로 세므로 같은 ID의 행이 두 개면 두 건으로 집계한다.

### 2. 본문에서 기술을 세는 규칙

**공고는 구역별로 읽는다.** 줄 시작에서 정규식 `\s*\[(.+?)\]`가 일치하면 대괄호 안의 문자열을 새 구역 이름으로 삼는다. 제목 줄은 통째로 소비하므로 `[자격요건] SQL` 한 줄만 있으면 SQL이 집계되지 않는다. 같은 제목이 다시 나오면 그 이름의 앞선 본문을 지우고 새로 시작한다. 첫 제목 앞의 본문은 `기타`에 속한다. 빈 줄은 건너뛰고, 일반 줄에는 `line.strip("- ").strip()`를 적용한 뒤 같은 구역의 줄들을 줄바꿈으로 연결한다.

| 공고 구역 | 자격요건 | 주요업무 | 우대사항 | 기타·미등록 구역 |
|---|---:|---:|---:|---:|
| 해당 구역에서 검출한 기술의 가중치 | 1.0 | 0.7 | 0.5 | 0.5 |

**공고 한 건은 기술마다 가장 큰 가중치 하나만 기여한다.** 주요업무에 `k8s`, 자격요건에 `Kubernetes`가 두 번 있어도 Kubernetes의 기여도는 1.0이다. 교과목은 세 필드를 순서대로 공백 하나로 연결해 한 번 검색한다. 한 과목의 과목명과 교육 목표에 모두 `Docker`가 있어도 Docker를 다루는 과목은 한 개로 센다. 한 공고나 과목이 여러 기술에 기여할 수 있다.

**두 자료는 같은 사전 검색을 사용한다.** 각 대표명의 별칭을 길이 내림차순으로 확인한다. 첫 일치를 채택하고 다음 대표명으로 넘어간다. 실제 검색식은 Python의 `r"(?<![A-Za-z가-힣])" + re.escape(alias) + r"(?![A-Za-z])"`이며 대소문자를 구분한다. 발견한 표기만 공백·하이픈·밑줄·가운뎃점·마침표·슬래시·괄호를 제거하고 소문자로 바꿔 역색인에서 대표명을 찾는다. 미등록 표기는 제외하고, 대표명은 중복 제거 후 이름순으로 정렬한다.

| 원문 | 추출 결과 | 이유 |
|---|---|---|
| `k8s와 K8S 운영` | Kubernetes 한 개 | 두 별칭이 같은 대표명을 가리킨다. |
| `AWS가 필수 아님` | AWS | 한글 조사는 오른쪽 경계에서 허용된다. 부정문도 표기가 있으면 검출된다. |
| `Dockerfile / 도구Docker / PYTHON` | 없음 | 오른쪽 영문자, 왼쪽 한글 음절, 사전에 없는 대문자 표기가 각각 매칭을 막는다. |

### 3. 등장률을 구성비로 환산하고 Gap 구하기

산업을 하나 고른 뒤 기술별로 다음 순서로 계산한다. 수요의 분모는 해당 산업에서 구하고, 공급의 분모는 전체 교과목에서 한 번만 구해 모든 산업에 공유한다.

| 단계 | 수요 | 공급 |
|---|---|---|
| ① 기술별 합계 | 해당 산업 각 공고에서 그 기술이 얻은 최대 가중치의 합 | 그 기술이 검출된 교과목 수 |
| ② 등장률 | ① ÷ 해당 산업의 전체 공고 수 | ① ÷ 전체 교과목 수 |
| ③ 비중(%) | 100 × (그 기술의 수요 등장률 ÷ 해당 산업 모든 기술의 수요 등장률 합) | 100 × (그 기술의 공급 등장률 ÷ 모든 기술의 공급 등장률 합) |

기술이 하나도 검출되지 않은 공고나 과목도 ②의 분모에 포함한다. 한 행에서 여러 기술이 나올 수 있어 등장률의 합은 1로 고정되지 않는다. ③에서 각각 정규화한 뒤에야 값이 있는 쪽의 비중 합이 반올림 전 100%가 된다. 손으로 검산할 때는 ②의 공통 분모가 약분되므로 **해당 기술의 가중치 합 ÷ 산업 전체 기술 가중치 합**, **해당 기술을 다루는 과목 수 ÷ 모든 과목에서 센 (과목, 기술) 쌍 수**와 같다.

**출력 행을 결정하는 규칙**

- 해당 산업에서 검출한 기술과 전체 교과목에서 검출한 기술의 **합집합**에 대해서만 행을 만든다. 한쪽에만 있는 기술의 반대쪽 비중은 0이다. 양쪽 모두에 없는 기술은 행이 없다.
- 매칭된 기술이 한 개도 없는 산업은 수요 사전에 생성되지 않아 출력 행도 없다. 교과목이 비었거나 모든 과목에서 매칭이 없으면 공급 사전은 비고, 수요가 있는 행의 공급 비중은 모두 0이다. 비중 정규화 함수는 값의 합이 0이면 분모 1.0을 사용한다.
- 대시보드 CSV의 열은 순서대로 `industry, skill, demand_pct, supply_pct, gap_pp`다. 산업은 수요가 처음 검출된 순서, 같은 산업 안에서 기술은 Python 문자열 오름차순이다. CSV는 인덱스 없이 UTF-8 BOM(`utf-8-sig`)으로 저장한다.
- CSV에서는 반올림 전 백분율을 `d`, `p`로 두고 `round(d, 1)`, `round(p, 1)`, **`round(d - p, 1)`**를 각각 저장한다. Python의 부동소수점 `round`를 사용한다. 이미 표시한 두 값을 빼면 마지막 자리가 달라질 수 있다.
- 노트북의 Top 3 보고서는 별도 함수 `gap_table`에서 0~1 비중에 먼저 뺄셈을 적용한 `round((demand_share - supply_share) * 100, 1)`을 사용한다. 부동소수점 경계까지 맞추려면 이 연산 순서도 보존한다. 산업별로 반올림된 Gap 내림차순의 앞 세 개를 취하며 양수로 제한하지 않는다. 합집합을 순회해 만든 사전이라 공동 순위 내 기술 순서는 보장되지 않는다.

### 4. 실제 데이터로 검산하기

현재 샘플에는 공고 100건, 교과목 48개가 있다. **유통 산업의 AWS** 한 행에서 두 종류의 분모와 반올림 순서를 함께 확인할 수 있다.

| 항목 | 입력에서 센 값 | 등장률 | 구성비 |
|---|---|---|---|
| 유통의 AWS 수요 | 유통 공고 22건, AWS 가중치 합 9.1, 유통 전체 기술 가중치 합 86.3 | 9.1 / 22 ≈ 0.4136 | 100 × 9.1 / 86.3 ≈ 10.5446% |
| 전체 교과목의 AWS 공급 | 교과목 48개, AWS 과목 2개, 전체 (과목, 기술) 쌍 36개 | 2 / 48 ≈ 0.0417 | 100 × 2 / 36 ≈ 5.5556% |

반올림 전 차이는 약 4.9891%p다. 기대 CSV 행은 **`유통,AWS,10.5,5.6,5.0`**이다. 표시값만 빼서 얻은 4.9%p는 이 행의 저장값과 다르다.

| 산업 | 샘플 공고 수 | 출력 행 수 | Gap 1위 | Gap(%p) |
|---|---:|---:|---|---:|
| 유통 | 22 | 22 | Docker | +9.7 |
| 금융 | 20 | 23 | Docker | +11.1 |
| 공공 | 14 | 23 | AWS | +9.7 |
| IT서비스 | 19 | 23 | Kubernetes | +10.1 |
| 제조 | 25 | 24 | Docker | +11.6 |
| **합계** | **100** | **115** | | |

### 5. 독립 실행용 참조 구현

아래 두 Python 블록을 순서대로 `skills_gap.py`에 붙여 넣고 `uv run --no-project --python 3.11 skills_gap.py`로 실행하면 된다. 첫 블록은 정제된 공고와 교과목 레코드를 받아 대시보드 CSV에 대응하는 행을 반환한다. 두 번째 블록은 외부 파일 없이 실행되는 검산 예시다. 두 블록 모두 Python 표준 라이브러리만 사용한다.

```python
import re
from collections import Counter, defaultdict


ALIASES = {
    "AWS": ["AWS", "Amazon Web Services", "아마존 웹 서비스", "aws"],
    "Azure": ["Azure", "MS Azure", "애저"],
    "GCP": ["GCP", "Google Cloud", "구글 클라우드"],
    "Kubernetes": ["Kubernetes", "쿠버네티스", "k8s", "K8S"],
    "Docker": ["Docker", "도커", "컨테이너(Docker)"],
    "Terraform": ["Terraform", "테라폼", "IaC(Terraform)"],
    "CI/CD": ["CI/CD", "CICD", "지속적 통합·배포"],
    "Linux": ["Linux", "리눅스"],
    "Python": ["Python", "파이썬", "python"],
    "SQL": ["SQL", "sql"],
    "Spark": ["Spark", "Apache Spark", "스파크"],
    "Airflow": ["Airflow", "에어플로우", "Apache Airflow"],
    "PyTorch": ["PyTorch", "파이토치"],
    "TensorFlow": ["TensorFlow", "텐서플로"],
    "LLM": ["LLM", "대규모 언어모델", "거대언어모델"],
    "RAG": ["RAG", "검색증강생성"],
    "MLOps": ["MLOps", "ML Ops", "머신러닝 운영"],
    "Prompt Engineering": ["프롬프트 엔지니어링", "Prompt Engineering"],
    "Amazon Bedrock": ["Amazon Bedrock", "Bedrock", "아마존 베드록"],
    "SageMaker": ["SageMaker", "세이지메이커", "Amazon SageMaker"],
    "Java": ["Java", "자바"],
    "Spring": ["Spring", "Spring Boot", "스프링"],
    "React": ["React", "리액트"],
    "정보보안": ["정보보안", "보안 관제", "클라우드 보안"],
}
WEIGHTS = {"자격요건": 1.0, "주요업무": 0.7, "우대사항": 0.5}


def alias_key(name: str) -> str:
    return re.sub(r"[\s\-_·./()]", "", name).lower()


CANONICAL = {
    alias_key(name): skill
    for skill, aliases in ALIASES.items()
    for name in [skill, *aliases]
}


def extract_skills(text: str) -> list[str]:
    found = set()
    for aliases in ALIASES.values():
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = r"(?<![A-Za-z가-힣])" + re.escape(alias) + r"(?![A-Za-z])"
            if re.search(pattern, text):
                found.add(CANONICAL[alias_key(alias)])
                break
    return sorted(found)


def posting_weights(text: str) -> dict[str, float]:
    sections = {}
    section = "기타"
    for line in text.splitlines():
        heading = re.match(r"\s*\[(.+?)\]", line)
        if heading:
            section = heading.group(1)
            sections[section] = []
        elif line.strip():
            sections.setdefault(section, []).append(line.strip("- ").strip())

    weights = {}
    for section, lines in sections.items():
        weight = WEIGHTS.get(section, 0.5)
        for skill in extract_skills("\n".join(lines)):
            weights[skill] = max(weights.get(skill, 0), weight)
    return weights


def to_share(rates: dict[str, float]) -> dict[str, float]:
    total = sum(rates.values()) or 1.0
    return {skill: rate / total for skill, rate in rates.items()}


def calculate_gap(postings: list[dict], courses: list[dict]) -> list[dict]:
    posting_counts = Counter()
    demand_totals = defaultdict(lambda: defaultdict(float))
    for posting in postings:
        industry = posting["industry"]
        posting_counts[industry] += 1
        for skill, weight in posting_weights(posting["text"]).items():
            demand_totals[industry][skill] += weight

    course_counts = Counter()
    for course in courses:
        text = f"{course['asubjName']} {course['eduText']} {course['subjGoal']}"
        course_counts.update(extract_skills(text))
    supply_rates = {s: count / len(courses) for s, count in course_counts.items()}
    supply = to_share(supply_rates)

    rows = []
    for industry, totals in demand_totals.items():
        demand_rates = {
            s: value / posting_counts[industry] for s, value in totals.items()
        }
        demand = to_share(demand_rates)
        for skill in sorted(demand.keys() | supply.keys()):
            demand_pct = demand.get(skill, 0) * 100
            supply_pct = supply.get(skill, 0) * 100
            rows.append({
                "industry": industry,
                "skill": skill,
                "demand_pct": round(demand_pct, 1),
                "supply_pct": round(supply_pct, 1),
                "gap_pp": round(demand_pct - supply_pct, 1),
            })
    return rows
```

#### 파일 없이 실행하는 검산 예시

첫 공고에서 Docker는 주요업무와 우대사항에 모두 나오므로 0.7을 얻는다. Kubernetes는 두 별칭을 합쳐 1.0, AWS는 우대사항에 나와 0.5다. 두 공고를 합하면 Docker 1.7, Kubernetes 1.0, AWS 1.2로 전체 가중치는 3.9다. 두 과목에서 검출한 (과목, 기술) 쌍은 Docker 한 번과 Python 두 번, 총 세 쌍이다.

```python
postings = [
    {
        "industry": "예시",
        "text": "[주요업무]\nDocker, k8s\n[자격요건]\nKubernetes, K8S\n"
                "[우대사항]\nDocker, AWS (필수 아님)",
    },
    {"industry": "예시", "text": "[자격요건]\nDocker\n[주요업무]\naws"},
]
courses = [
    {"asubjName": "도커 기초", "eduText": "Docker", "subjGoal": "Python"},
    {"asubjName": "분석 실습", "eduText": "파이썬", "subjGoal": ""},
]

rows = calculate_gap(postings, courses)
assert posting_weights(postings[0]["text"]) == {"Docker": 0.7, "Kubernetes": 1.0, "AWS": 0.5}
assert [(r["skill"], r["demand_pct"], r["supply_pct"], r["gap_pp"]) for r in rows] == [
    ("AWS",        30.8,  0.0,  30.8),
    ("Docker",     43.6, 33.3,  10.3),
    ("Kubernetes", 25.6,  0.0,  25.6),
    ("Python",      0.0, 66.7, -66.7),
]
print("OK")
```

### 6. 프로젝트에서 결과를 쓰는 곳

06 노트북은 `demand_rates`와 `supply_rates`로 등장률을 만든 뒤, `long_table` 결과를 `outputs/gap_table.csv`에, `gap_table`의 산업별 Top 3를 `outputs/week5_gap_report.md`에 저장한다. 대시보드는 CSV가 있으면 그 값을 읽고 없으면 같은 기본 가중치로 다시 계산한다. 입력을 바꾼 뒤 기존 CSV가 남아 있다면 노트북의 집계·저장 셀을 다시 실행해야 새 값이 표시된다.

대시보드의 막대그래프는 선택한 산업에서 **수요 비중**이 높은 기술을, 히트맵은 각 기술의 **산업별 Gap 중 최댓값**이 큰 기술을 보여준다. NCS 능력단위 연결과 교육과정 추천은 계산된 Gap을 활용하는 후속 단계다. Gap 계산 자체는 사전과 두 입력 표만으로 실행된다.

프로젝트에서 대조할 위치는 [06 노트북](../notebooks/06_SkillsGap_대시보드.ipynb), [Gap 집계](../src/labutil/gap.py), [구역 파서](../src/labutil/textprep.py), [기술 추출과 정규화](../src/labutil/skills.py), [별칭 원본](../data/dict/skill_aliases.json), [입력 로더](../src/labutil/data.py), [대시보드](../app/week5_dashboard.py)다.
