# skillpath-ai

채용공고에서 기술 수요를 추출해 부족한 역량과 AWS 교육과정을 근거와 함께 추천하는 AI 에이전트.
AI Bootcamp Innovation Challenger 2026 · 팀 ASAP하게

## 무엇을 하나

1. 목표 직무를 고르고 보유 기술을 입력한다.
2. 해당 직무 채용공고에서 뽑은 요구 기술을 빈도순으로 본다. 기술마다 필수/우대 구분과 근거 문장이 붙는다.
3. 보유 기술과 비교한 부족 역량(Skills Gap)을 본다.
4. 부족 역량별 AWS 교육과정을 추천 이유, 링크, 난이도, 선수지식과 함께 본다.

## 구조

```
공고 수집 → 기술 추출 → 표현 표준화 → 분석·Gap → 교육과정 추천
(pipeline)    (ai)      (pipeline)   (backend)     (ai + pipeline)
                                                        ↓
                                                   화면 (app)
```

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `app/` | Streamlit 화면 | 형섭 |
| `backend/` | Lambda, DynamoDB, 집계·Gap 계산 | 일현 |
| `pipeline/` | 데이터 수집, 전처리, 별칭 사전, 임베딩 검색 | 종훈 |
| `ai/` | 추출·추천 프롬프트, 가드레일, 평가 | 성진 |
| `contracts/` | 구간 사이 JSON 형식 | 전원 |
| `data/sample/` | 개발용 가짜 데이터 | 전원 |

## 시작하기

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 값 채우기. .env는 커밋하지 않습니다
streamlit run app/main.py
```

`BEDROCK_MOCK=1`이면 AWS 없이 `data/sample/`의 가짜 데이터로 화면이 뜹니다.

## 일하는 방식

- 작업은 이슈에서 시작합니다. 이슈마다 담당자, 마일스톤, 완료 기준이 있습니다.
- `main`에 직접 푸시하지 않고 브랜치 → PR로 합칩니다. PR 본문에 `Closes #이슈번호`를 적습니다.
- 구간 사이 데이터 형식은 [`contracts/`](contracts/README.md)를 따릅니다. 바꾸려면 먼저 팀에 알립니다.
- 작업 원칙과 리뷰 기준은 [`CLAUDE.md`](CLAUDE.md)에 있습니다.

## 일정

| 날짜 | 마일스톤 |
| --- | --- |
| 11/12 (목) | M1 가짜 데이터로 화면까지 연결 |
| 11/15 (일) | M2 실제 공고 1건 → 추천 1건 |
| 11/17 (화) | M3 MVP 완성 |
| 11/19 (목) | M4 기능 동결 |
| 11/22 (일) | 구현 제출 |
| 11/25 (수) | 발표 |

## 데이터 출처

활용한 데이터의 출처, 수집 범위, 한계는 [`docs/data-sources.md`](docs/data-sources.md)에 기록합니다. 발표 자료에 그대로 들어갑니다.
