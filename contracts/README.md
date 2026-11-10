# 인터페이스 계약

구간 사이를 오가는 데이터는 아래 세 형식만 씁니다. 예시 파일은 `data/sample/`에 있습니다.
형식을 바꾸려면 코드보다 먼저 팀 채팅방에 알리고, 이 문서와 예시를 같은 PR에서 고칩니다.

## ① 공고 (`posting`) — pipeline → ai

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `posting_id` | string | 출처 접두어 + 번호. 예: `w24-0001` |
| `title` | string | 공고 제목 |
| `company` | string | 회사명 |
| `job_category` | string | 직무 코드. 예: `cloud_engineer` |
| `text` | string | 공고 본문 전체. 근거 문장 검사의 기준 |
| `source` | string | 데이터 출처. 예: `work24`, `manual` |
| `collected_at` | string | 수집일 `YYYY-MM-DD` |

## ② 추출 결과 (`extraction`) — ai → backend

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `posting_id` | string | ①의 id |
| `skills[].raw` | string | 공고에 쓰인 표현 그대로 |
| `skills[].normalized` | string | 표준 이름. 예: `AWS` |
| `skills[].type` | string | `required` 또는 `preferred` |
| `skills[].evidence` | string | 근거 문장. ①의 `text`에 그대로 있어야 함 |
| `skills[].confidence` | string | `high` 또는 `uncertain` |
| `skills[].ncs_unit` | string \| null | 연결된 NCS 능력단위. 없으면 `null` |

## ③ 추천 (`recommendation`) — backend + ai → app

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `gap_skill` | string | 부족한 기술의 표준 이름 |
| `demand.postings` | number | 이 기술을 요구한 공고 수 (코드로 계산) |
| `demand.of` | number | 분석한 전체 공고 수 |
| `demand.required_ratio` | number | 요구한 공고 중 필수로 표기한 비율 |
| `courses[].title` | string | 교육과정 이름 |
| `courses[].url` | string | 링크 |
| `courses[].level` | string | 난이도 |
| `courses[].prerequisites` | string | 선수지식 |
| `courses[].reason` | string | 추천 이유 |
| `courses[].match` | string | `certain` 또는 `uncertain` |
