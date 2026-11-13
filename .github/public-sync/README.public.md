# skillpath-ai

채용공고에서 기술 수요를 근거 문장과 함께 추출하고, 보유 기술과 비교해 부족한 역량과 AWS 교육과정을 추천 이유와 함께 보여주는 AI 에이전트.

AI Bootcamp Innovation Challenger 2026 · 팀 ASAP하게

> 이 저장소는 팀 개발 저장소(비공개)에서 공개할 수 있는 파일만 골라 옮긴 사본입니다. 개발 중이라 내용이 계속 바뀝니다.
> 최종 동기화: {{SYNC_INFO}}

## 무엇을 하나

1. 목표 직무를 고르고 보유 기술을 입력한다.
2. 채용공고에서 뽑은 요구 기술을 빈도순으로 본다. 기술마다 근거 문장이 붙는다.
3. 보유 기술과 비교한 부족 역량(Skills Gap)을 본다.
4. 부족 역량별 AWS 교육과정을 추천 이유와 함께 본다.

## 구조

```
공고 수집 → 기술 추출 → 표현 표준화 → 분석·Gap → 교육과정 추천 → 화면
(pipeline)    (ai)      (pipeline)   (backend)   (ai + pipeline)   (app)
```

| 폴더 | 내용 |
| --- | --- |
| `app/` | Streamlit 화면 |
| `backend/` | Lambda, DynamoDB, 집계·Gap 계산 |
| `pipeline/` | 데이터 수집, 전처리, 별칭 사전, 임베딩 검색 |
| `ai/` | 추출·추천 프롬프트, 가드레일, 평가 |
| `contracts/` | 구간 사이 JSON 형식 |
| `data/sample/` | 개발용 가짜 데이터 |

데이터 출처와 수집 범위, 한계는 [`docs/data-sources.md`](docs/data-sources.md)에 있습니다.

## 실행

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
BEDROCK_MOCK=1 streamlit run app/main.py
```

`BEDROCK_MOCK=1`이면 AWS 없이 `data/sample/`의 가짜 데이터로 화면이 뜹니다.
