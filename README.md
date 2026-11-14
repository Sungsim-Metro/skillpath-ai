# skillpath-ai

채용공고에서 기술 수요를 근거 문장과 함께 뽑고, 내 보유 기술과 비교해 부족한 역량과 AWS 교육과정을 추천 이유와 함께 보여주는 AI 에이전트.

AI Bootcamp Innovation Challenger 2026 · 팀 ASAP하게 · 발표 11/25(수)

## 30초 요약

- **누구를 위한 것인가.** 클라우드·AI 엔지니어를 준비하는 취업 준비생. 공고가 실제로 무엇을 요구하는지, 그래서 무엇부터 공부할지 모르는 사람.
- **무엇을 보여주나.** 실제 공고 30건 이상에서 뽑은 요구 기술 순위, 내 기술과의 차이(Gap), 부족한 기술별 AWS 교육과정.
- **발표에서 답할 세 질문.** 우리가 만드는 모든 기능은 이 셋 중 하나에 답합니다.
  1. 어떤 데이터를 분석했나
  2. 어떤 근거로 필요하다고 판단했나
  3. 왜 이 과정을 추천했나

## 어떻게 동작하나

사용자가 보는 순서:

1. 목표 직무를 고르고 보유 기술을 입력한다.
2. 공고에서 뽑은 요구 기술을 수요가 높은 순으로 본다. 기술을 누르면 근거 문장이 나온다.
3. 보유 기술과 비교한 부족 역량(Gap)을 본다.
4. 부족 역량별 AWS 교육과정을 추천 이유, 링크, 난이도와 함께 본다.

데이터가 흐르는 순서와 담당:

```
공고 수집 → 기술 추출 → 표현 표준화 → 분석·Gap → 교육과정 추천 → 화면
(pipeline)    (ai)      (pipeline)   (backend)   (ai + pipeline)   (app)
   종훈        성진        종훈         일현         성진·종훈        형섭
```

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `app/` | Streamlit 화면 | 형섭 |
| `backend/` | Lambda, DynamoDB, 수요 집계와 Gap 계산 | 일현 |
| `pipeline/` | 데이터 수집, 전처리, 별칭 사전, 임베딩 검색 | 종훈 |
| `ai/` | 추출·추천 프롬프트, 에이전트, 가드레일, 정확도 평가 | 성진 |
| `contracts/` | 구간 사이를 오가는 JSON 형식. 이것만 맞추면 각자 따로 만들어도 이어진다 | 전원 합의 |
| `data/sample/` | 개발용 가짜 데이터 | 전원 |

AWS 서비스를 어디에 왜 쓰는지는 [`docs/development.md`](docs/development.md#aws-서비스와-쓰는-이유), 그림은 [`docs/service-flow.md`](docs/service-flow.md)에 있습니다.

## 일정

| 날짜 | 마일스톤 |
| --- | --- |
| 11/12 (목) | M1 가짜 데이터로 화면까지 연결 |
| 11/15 (일) | M2 실제 공고 1건 → 추천 1건 |
| 11/17 (화) | M3 MVP 완성 (공고 30건 이상, Gap, 추천) |
| 11/19 (목) | M4 기능 동결. 이후에는 버그 수정만 |
| 11/22 (일) | 구현 제출 (팀 내부 마감 18시) |
| 11/25 (수) | 발표 |

## 꼭 지킬 것

자세한 설명과 명령어는 **[팀 가이드](docs/team-guide.md)** 에 있습니다. 처음이면 팀 가이드부터 읽습니다.

1. `main`에 직접 푸시하지 않습니다. 브랜치 → PR → 자동 검사 2개 확인 → 병합.
2. 키, `.env`, 수집한 공고 원본(`data/raw/`)은 커밋하지 않습니다.
3. `contracts/`의 JSON 형식을 바꾸면 같은 PR에서 예시와 README를 함께 고치고, PR 맨 위에 "인터페이스 변경"이라고 적습니다.
4. `main`에 병합하면 공개용 저장소에 자동으로 올라갑니다. 공개되는 파일에는 "녹취", "교안", "멘토"를 쓰지 않습니다.
5. 진행 상태와 날짜는 보드(Dev Map)에만 적습니다.

## 바로 가기

| 보고 싶은 것 | 위치 |
| --- | --- |
| 일하는 법, 저장소 규칙 | [`docs/team-guide.md`](docs/team-guide.md) |
| 현황판 (Dev Map) | [마일스톤 별](https://github.com/orgs/Sungsim-Metro/projects/2/views/2) · [담당자 별](https://github.com/orgs/Sungsim-Metro/projects/2/views/3) · [로드맵](https://github.com/orgs/Sungsim-Metro/projects/2/views/4) · [WBS 표](https://github.com/orgs/Sungsim-Metro/projects/2/views/5) |
| 할 일 전체 | [이슈](https://github.com/Sungsim-Metro/skillpath-ai/issues) · [마일스톤](https://github.com/Sungsim-Metro/skillpath-ai/milestones) |
| 과제 내용, 기획, 개발 | [`docs/assignment.md`](docs/assignment.md) · [`docs/planning.md`](docs/planning.md) · [`docs/development.md`](docs/development.md) |
| JSON 형식 | [`contracts/`](contracts/README.md) |
| 회의록 | [`docs/meetings/`](docs/meetings/README.md) |
| 데이터 출처와 한계 | [`docs/data-sources.md`](docs/data-sources.md) |
| 공개용 저장소 | [skillpath-ai-public](https://github.com/Sungsim-Metro/skillpath-ai-public) · 게시와 공유 방법은 [`docs/public-sync.md`](docs/public-sync.md) |
| 작업 원칙, 리뷰 기준 | [`CLAUDE.md`](CLAUDE.md) |

## 실행

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # 값 채우기. .env는 커밋하지 않습니다
streamlit run app/main.py
```

`.env`에 `BEDROCK_MOCK=1`이 있으면 AWS 없이 `data/sample/`의 가짜 데이터로 화면이 뜹니다.
