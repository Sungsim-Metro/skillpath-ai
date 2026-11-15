# 개발 내용

2026-11-12 회의 반영. 무엇을 어떤 구조로 만드는지 정리했습니다. 작업별 진행 상태는 [보드](https://github.com/orgs/Sungsim-Metro/projects/2)에서 봅니다.

## 폴더와 담당

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `app/` | Streamlit 화면. 화면 코드만 두고 로직은 다른 폴더의 함수를 호출 | 형섭 |
| `backend/` | Lambda, DynamoDB, 수요 집계·Gap 계산 | 일현 |
| `pipeline/` | 공고·NCS·교육과정 수집, 전처리, 별칭 사전, 임베딩 검색 | 종훈 |
| `ai/` | 추출·추천 프롬프트, 가드레일, 평가 | 성진 |
| `contracts/` | 구간 사이를 오가는 JSON 형식과 예시 | 전원 합의 |
| `data/sample/` | 개발용 가짜 데이터 | 전원 |

실행 방법은 [README](../README.md#시작하기)에 있습니다. `BEDROCK_MOCK=1`이면 AWS 없이 가짜 데이터로 화면이 뜹니다.

## AWS 서비스와 쓰는 이유

| 서비스 | 어디에 | 왜 |
| --- | --- | --- |
| Amazon Bedrock (Claude) | 기술 추출, 추천 이유 생성 | 표현이 일정하지 않은 공고 문장을 읽고 설명하는 일 |
| Titan Embeddings | 표현 표준화 | 같은 뜻의 다른 표현을 의미로 묶기 |
| Bedrock Knowledge Base (S3 Vectors) | 교육과정 검색. 수업 6주차 CloudFormation 템플릿 재사용, 실패하면 FAISS | 부족 기술에 맞는 과정 설명을 의미로 찾기. S3 Vectors는 저장·질의한 만큼만 과금 |
| Bedrock Agents | 학습 상담 | 수요 조회와 과정 검색 함수를 도구로 불러 답 구성. 팀 계정에서 Bedrock 사용 확인(11/13). 생성이 막히면 AgentCore나 Converse API 도구 호출로 대체([AWS 안내](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html)) |
| Bedrock Guardrails | 추출, 학습 상담 | 주제 밖 질문과 차별 조건 차단 |
| S3 | API 응답 JSON 저장 | 요약 정보와 원본 공고 링크. 근거 검증, 프롬프트 재실행, 정확도 측정에 같은 데이터 사용. 웹페이지 원문 전체는 저장하지 않음 |
| Lambda | 수집·추출 자동 처리 | 쓰임새 확정 전. S3에 원본이 들어오면 추출을 돌리는 안 |
| DynamoDB | 추출 결과, 사용자 정보와 대화 기록 | 닉네임별 학습 계획·대화 기록 조회. 로그인 없음. 저장 항목은 미정 |
| CloudWatch | Lambda·Bedrock 로그와 대시보드 | E2E 7단계의 마지막 단계. 호출 수·오류·토큰 확인 |

API Gateway는 쓰지 않습니다(2026-11-13). 수업 교안에 없고, 화면은 `backend/api.py` 함수를 직접 부릅니다.

서비스가 어디에 놓이는지는 [서비스 플로우](service-flow.md#2-시스템-구조)의 그림을 봅니다.

## 인터페이스 계약

구간 사이 데이터는 아래 형식만 씁니다. 필드 정의와 예시는 [`contracts/README.md`](../contracts/README.md)에 있습니다.

| 형식 | 흐름 | 핵심 필드 |
| --- | --- | --- |
| ① 공고 | pipeline → ai | `id`, `title`, `company`, `role`, `text`, `url` |
| ② 추출 결과 | ai → backend | `skills[].normalized`, `type`, `evidence`, `confidence` |
| ③ 추천 | backend + ai → app | `gap_skill`, `demand`, `courses[].reason`, `match` |
| ④ 수요 집계 | backend → app | `total_postings`, `skills[].postings`, `required`, `preferred` |

형식을 바꾸는 PR은 설명 맨 위에 "인터페이스 변경"이라고 적고, 문서와 예시를 같은 PR에서 고칩니다.

**바뀔 예정(2026-11-12 회의, 값 확정 뒤 별도 PR).**

- ② `skills[].type`: `required`, `preferred` 2개에서 자격 요건·주요 업무·우대 사항 3개로
- ① 공고에 원본 링크 필드(`url`) 추가
- 가중치를 쓰면 ③ `demand`와 ④ 수요 집계 숫자가 건수인지 가중 합인지 정해야 함

## 개발 원칙

전문은 [`CLAUDE.md`](../CLAUDE.md)에 있습니다.

1. 인터페이스 계약 우선
2. 세기는 코드, 이해는 AI. LLM에게 숫자를 세게 하지 않는다
3. 근거 없는 결과 금지. 추출한 기술마다 근거 문장이 있고, 그 문장이 원문에 있는지 코드로 검사한다
4. 확신이 없으면 "불확실"
5. 화면과 로직 분리
6. 가장 단순한 구현

## 지금 코드에 있는 것

| 위치 | 내용 |
| --- | --- |
| `app/main.py` | 사이드바와 탭 4개(시장 수요, 부족 역량, 학습 추천, 공고 분석). 가짜 데이터로 동작 |
| `backend/api.py` | 화면이 부르는 함수 4개: `get_demand`, `get_gap`, `get_recommendations`, `extract_posting`. 지금은 가짜 데이터를 돌려주고, 담당자가 실제 구현으로 교체 |
| `data/sample/` | ①~④ 형식의 예시 JSON |
| `.github/workflows/` | PR 자동 리뷰(`claude-review.yml`), 댓글 호출(`claude.yml`) |

`pipeline/`은 아직 README만 있습니다. `ai/`의 추출 정답지 10건과 추출 v1은 PR #46에 있습니다.

## 품질 확인 계획

| 확인할 것 | 방법 | 이슈 |
| --- | --- | --- |
| 추출 정확도 | 정답셋 20건과 비교해 정밀도·재현율·F1(목표 F1 0.7). 규칙 기반·v2·v3 비교표 | [#8](https://github.com/Sungsim-Metro/skillpath-ai/issues/8), [#21](https://github.com/Sungsim-Metro/skillpath-ai/issues/21) |
| 근거 검증 | 근거 문장이 공고 원문에 있는지 코드로 검사, 통과율 기록 | [#16](https://github.com/Sungsim-Metro/skillpath-ai/issues/16) |
| 표준화 | 같은 표현은 묶고(아마존 웹 서비스 = AWS) 다른 것은 안 묶는지(Java ≠ JavaScript) | [#13](https://github.com/Sungsim-Metro/skillpath-ai/issues/13) |
| 과정 검색 | 부족 기술별 Top-5 적중률 | [#14](https://github.com/Sungsim-Metro/skillpath-ai/issues/14) |
| NCS 매칭 | 기술 → 능력단위 hit@5, 설명을 붙인 질의 | [#20](https://github.com/Sungsim-Metro/skillpath-ai/issues/20) |
| 공정성 | 속성 하나만 바꿔 추천 겹침(Jaccard) 비교 | [#24](https://github.com/Sungsim-Metro/skillpath-ai/issues/24) |
| 가드레일 | 차단해야 할 질문과 정상 질문으로 차단·오차단 수 | [#24](https://github.com/Sungsim-Metro/skillpath-ai/issues/24) |
| 끝까지 연결 | 공고 1건이 추천까지 가는 자동 테스트와 실제 AWS 7단계 표 | [#38](https://github.com/Sungsim-Metro/skillpath-ai/issues/38) |
| 사용자 테스트 | 취업 준비생 3~5명 | [#39](https://github.com/Sungsim-Metro/skillpath-ai/issues/39) |

목표치는 [기획 내용](planning.md#숫자로-잡은-목표)에 있고, 측정 결과가 나오면 이 문서에 표로 더합니다.

추출 검증에는 AI를 한 번 더 부르지 않습니다(2026-11-12). 근거 문장이 원문에 있는지는 코드로 검사하고, 함정 문장 시험은 평가 사례로 남깁니다.

## 비용

팀 계정의 사용 한도는 약 80만 원입니다. 발표에서는 "테스트"가 아니라 운영하는 서비스로 설명합니다(1차 멘토링).

| 정리할 것 | 상태 |
| --- | --- |
| 데이터 갱신 주기와 그에 따른 월 운영비 추정 | 작성 전 |
| 비용을 줄인 방법: 세기는 코드로, 추출 검증에 추가 호출 없음, 벡터 저장소 선택 | 작성 전 |
| 줄이기 전과 후의 비교 수치 | 작성 전 |

## 시연 준비

- 라이브 시연이 1순위이고 백업 영상은 대안입니다.
- 시나리오를 10번 이상 돌려 같은 결과가 나오게 합니다.
- 발표장 네트워크에 기대지 않고 휴대폰 테더링으로도 시험합니다.

## 협업 방식

- 작업은 이슈에서 시작하고, 브랜치 → PR → Claude 자동 리뷰 → 올린 사람이 병합합니다.
- 회의록은 [`meetings/`](meetings/README.md)에 남기고 팀원이 검토합니다.
- 데이터 출처, 수집 범위, 한계는 [`data-sources.md`](data-sources.md)에 기록합니다.
