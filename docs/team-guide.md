# 팀 가이드

팀원이 이 저장소에서 일할 때 알아야 하는 것을 한곳에 모았습니다. 명령어는 터미널(Windows는 Git Bash)에서 그대로 따라 치면 됩니다.

- [1. 처음 한 번](#1-처음-한-번)
- [2. 작업 한 바퀴](#2-작업-한-바퀴)
- [3. PR에 뜨는 자동 검사 2개](#3-pr에-뜨는-자동-검사-2개)
- [4. 저장소 규칙](#4-저장소-규칙)
- [5. Dev Map(현황판) 보는 법](#5-dev-map현황판-보는-법)
- [6. 공개용 저장소](#6-공개용-저장소)
- [7. 막혔을 때](#7-막혔을-때)
- [8. 시연 전 준비 (실제 모드)](#8-시연-전-준비-실제-모드)

## 1. 처음 한 번

```bash
git clone https://github.com/Sungsim-Metro/skillpath-ai.git
cd skillpath-ai
python -m venv .venv
source .venv/bin/activate        # Windows Git Bash: source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env             # .env는 내 PC에만 둡니다
streamlit run app/main.py        # 화면이 뜨면 준비 끝
```

`.env`의 `BEDROCK_MOCK=1`을 그대로 두면 AWS 없이 가짜 데이터로 화면이 뜹니다.

## 2. 작업 한 바퀴

이슈 하나를 맡아 PR로 합치기까지의 순서입니다. 하루에 한 번 이상 PR을 올리는 것이 목표입니다. 다 못 끝냈어도 올립니다.

```bash
# 1) 최신 main에서 브랜치를 만든다. 이름은 feat/…, fix/…, docs/… 중 하나
git switch main
git pull
git switch -c feat/extract-prompt

# 2) 작업하고, 화면이 뜨는지 확인한다
BEDROCK_MOCK=1 streamlit run app/main.py

# 3) 바꾼 파일을 확인하고 커밋한다. 메시지는 한국어로
git status
git add ai/prompts/extract_v2.py     # 파일을 지정해서 올리면 엉뚱한 파일이 섞이지 않는다
git commit -m "추출 프롬프트에 3단 구분 추가"

# 4) 올리고 PR을 만든다
git push -u origin feat/extract-prompt
gh pr create --fill                  # gh가 없으면 GitHub 웹에서 "Compare & pull request"
```

PR 본문에는 `Closes #이슈번호`를 적습니다. 병합되면 이슈가 자동으로 닫힙니다. 아직 덜 끝났으면 `Refs #이슈번호`라고 적습니다.

PR을 올린 뒤:

```bash
gh pr checks          # 자동 검사 2개의 결과 보기 (웹에서는 PR 아래쪽)
gh pr merge --merge   # 둘 다 통과하고 리뷰를 확인했으면 올린 사람이 병합
git switch main && git pull
```

작업하는 동안 `main`이 바뀌었으면 내 브랜치에 받아 옵니다.

```bash
git fetch origin
git merge origin/main
```

문서만 고칠 때는 GitHub 웹에서 파일의 연필 아이콘 → 수정 → "Create a new branch"로 PR을 올려도 됩니다.

## 3. PR에 뜨는 자동 검사 2개

| 검사 | 하는 일 | 실패하면 |
| --- | --- | --- |
| **Claude Review** | PR을 `main`과 합친 상태에서 가짜 모드로 테스트·평가·화면을 돌려 보고, 바뀐 코드가 닿는 곳(부르는 쪽, `contracts/`, 예시 데이터)까지 읽은 뒤 [`CLAUDE.md`](../CLAUDE.md)의 리뷰 기준으로 댓글을 답니다 | 아래 "Claude 리뷰 읽는 법"대로 처리합니다 |
| **Public Sync / 공개 검사** | 공개용 저장소로 나갈 파일에 키, 개인정보, 공개하면 안 되는 문구가 없는지 봅니다 | 로그에 나온 `파일:줄번호`를 고쳐 다시 푸시합니다. ❌인 채로 병합하지 않습니다 |

- 다시 푸시하면 두 검사가 자동으로 다시 돕니다. Claude 리뷰는 이전 지적이 해결됐는지부터 적습니다.

**Claude 리뷰 읽는 법**

| 표시 | 뜻 | 할 일 |
| --- | --- | --- |
| 🔴 병합 전 수정 | 실행하거나 코드를 따라가 확인한 버그, 원칙·보안 위반, `contracts/`와 어긋남 | 고쳐서 다시 푸시합니다. 고치지 않으면 이유를 댓글로 남깁니다 |
| 🟡 확인 필요 | 깨질 가능성이 높지만 리뷰가 확인하지 못한 것, 본문과 실제가 다른 것, 빠진 테스트 | 댓글로 답하거나 고칩니다 |
| 🟢 참고 | 지금 고치지 않아도 되지만 다음 마일스톤에서 걸릴 것 | 필요하면 이슈로 남깁니다 |

- 요약 댓글의 "확인 못 한 것"(예: 실제 Bedrock 호출)은 올린 사람이 직접 확인합니다.
- 실행 점검 결과는 PR의 검사 목록에서 "Claude Review" → Details → Summary에 있습니다. 로컬에서는 `bash .github/review/run_checks.sh`로 같은 점검을 돌립니다(Windows는 Git Bash).
- 리뷰는 댓글만 남기고 병합을 막지 않습니다. 🔴가 있는데 합치려면 이유를 댓글로 남깁니다.
- 리뷰 절차를 고치려면 `.github/workflows/claude-review.yml`의 prompt를 PR로 고칩니다. 그 PR 자체에는 리뷰가 돌지 않고 병합한 다음 PR부터 적용됩니다.
- PR이나 이슈 댓글에 `@claude 질문`을 쓰면 Claude가 답합니다.
- 회의록만 바꾸는 PR은 Claude Review를 건너뜁니다. 공개 검사는 돕니다.
- 공개 검사 로그 보기: PR 아래쪽 검사 목록에서 "공개 검사" → Details.

## 4. 저장소 규칙

### 반드시

1. **`main`에 직접 푸시하지 않습니다.** 브랜치 보호가 걸려 있지 않아 막히지 않습니다. 약속으로 지킵니다. `main`은 항상 시연할 수 있는 상태여야 합니다.
2. **비밀 값을 커밋하지 않습니다.** AWS 키, API 키, `.env`, 계정 ID. 새 환경 변수는 `.env.example`에 이름만 추가합니다. 코드와 로그에도 값을 출력하지 않습니다.
3. **수집한 공고 원본(`data/raw/`)과 사용자 정보는 올리지 않습니다.**
4. **`contracts/`를 말없이 바꾸지 않습니다.** 필드를 더하거나 바꾸거나 지우면 같은 PR에서 `contracts/`의 예시와 README를 함께 고치고, PR 설명 맨 위에 "인터페이스 변경"이라고 적습니다. 올리기 전에 팀 채팅방에 알립니다.
5. **두 검사를 확인하고 병합합니다.** 병합하면 곧 공개용 저장소에 올라갑니다(6번).

### 코드

- 세기는 코드, 이해는 AI. 빈도·비율·Gap은 코드로 계산하고 LLM에게 숫자를 세게 하지 않습니다.
- 추출한 기술마다 근거 문장(`evidence`)이 있어야 하고, 확신이 없으면 `uncertain`으로 남깁니다.
- `app/`에는 화면 코드만 둡니다. 로직은 `backend/`, `pipeline/`, `ai/`의 함수로 둡니다.
- 모델 ID는 코드에 적지 않고 `.env`에서 읽습니다. 리전은 `ap-northeast-2`.
- 함수와 변수는 영어, 주석·문서·커밋 메시지는 한국어.
- 11/19 기능 동결 뒤에는 버그 수정만 합니다.

### 기록

- 작업은 이슈에서 시작합니다. 이슈가 없으면 먼저 만듭니다.
- 결정이 바뀌면 관련 이슈에 한 줄 남깁니다. 사람 리뷰가 필수가 아니라서 이슈, PR 설명, 회의록이 협업 근거입니다.
- 진행 상태와 날짜는 보드에만 적습니다. 문서에는 구조와 결정만 적습니다.
- 회의록은 [`docs/meetings/`](meetings/README.md)에 있습니다. 다르게 적힌 곳이 있으면 PR 댓글로 알립니다.

## 5. Dev Map(현황판) 보는 법

Dev Map은 이슈를 카드로 보여주는 GitHub Projects 보드입니다. 조직(Sungsim-Metro) 구성원으로 로그인해야 보입니다.

| 보기 | 언제 보나 |
| --- | --- |
| [마일스톤 별](https://github.com/orgs/Sungsim-Metro/projects/2/views/2) | 이번 마일스톤에 무엇이 남았는지 |
| [담당자 별](https://github.com/orgs/Sungsim-Metro/projects/2/views/3) | 내 할 일이 무엇인지 |
| [로드맵](https://github.com/orgs/Sungsim-Metro/projects/2/views/4) | 날짜 순서로 일정이 겹치거나 밀리는지 |
| [WBS 표](https://github.com/orgs/Sungsim-Metro/projects/2/views/5) | 전체 작업을 표로 |

- **작업을 시작하면** 내 카드의 Status를 `In Progress`로 바꾸고 시작일을 적습니다.
- **기한이 바뀌면** 카드의 기한을 고칩니다. 회의 전에 한 번씩 확인합니다.
- **끝나면** 따로 할 일이 없습니다. PR에 `Closes #번호`를 적어 병합하면 이슈가 닫히고 카드가 `Done`으로 갑니다(안 옮겨지면 직접 옮깁니다).
- 저장소 화면에서는 위쪽 **Projects** 탭 → `skillpath-ai Dev Map`으로 들어갑니다.

터미널에서 내 할 일만 보려면:

```bash
gh issue list --assignee @me
gh issue list --milestone "M2 공고 1건 → 추천 1건"
```

## 6. 공개용 저장소

이 저장소는 비공개입니다. 밖에 보여 줄 때는 공개용 저장소 [skillpath-ai-public](https://github.com/Sungsim-Metro/skillpath-ai-public)을 씁니다. 옮기는 일은 자동입니다.

```
PR 올림 → 공개 검사 → 병합 → 검사 다시 → 통과하면 공개용 저장소에 자동 게시
```

팀원이 알아야 할 것은 세 가지입니다.

1. **`main`에 병합한 내용은 몇 분 안에 공개됩니다.** 나가는 범위는 [`allowlist.txt`](../.github/public-sync/allowlist.txt)에 적힌 경로(코드 폴더, `contracts/`, `data/sample/`, 서비스 플로우, 데이터 출처)와 자동으로 만드는 협업 요약, 회의 결정 사항입니다.
2. **공개되는 파일과 회의록 "결정 사항"에는 "녹취", "교안", "멘토"를 쓰지 않습니다.** 공개 검사에 걸립니다. 출처가 필요하면 "11/13 결정"처럼 날짜로 적습니다. 이메일, 전화번호, 12자리 숫자도 걸립니다.
3. **`.github/` 아래와 `allowlist.txt`를 바꾸는 PR은 형섭이 확인한 뒤 병합합니다.**

처음 설정, 수동 게시, 멘토님과 제출용 공유 방법은 [`public-sync.md`](public-sync.md)에 있습니다.

## 7. 막혔을 때

| 상황 | 방법 |
| --- | --- |
| `git pull`이나 `merge`에서 충돌 | `git status`로 충돌 파일을 열어 `<<<<<<<` 표시를 정리 → `git add 파일` → `git commit`. 모르겠으면 `git merge --abort`로 되돌리고 채팅방에 묻습니다 |
| 실수로 `main`에서 작업함 (커밋 전) | `git switch -c feat/이름`. 바꾼 내용이 새 브랜치로 따라옵니다 |
| 방금 한 커밋 메시지를 고치고 싶음 (푸시 전) | `git commit --amend -m "새 메시지"` |
| `.env`나 키를 커밋함 | **바로 채팅방에 알립니다.** 지우는 커밋을 올려도 기록에 남으므로 그 키는 폐기하고 새로 발급받아야 합니다 |
| 공개 검사가 ❌ | 로그의 `파일:줄번호`를 고칩니다. 정말 문제없는 내용이면 형섭에게 알립니다 |
| 화면이 안 뜸 | `.env`에 `BEDROCK_MOCK=1`이 있는지, 가상환경이 켜져 있는지 확인합니다 |
| Windows에서 `LF will be replaced by CRLF` 경고 | 무시해도 됩니다. 바꾸지 않은 파일이 전부 수정됨으로 보이면 `git config core.autocrlf true` |

## 8. 시연 전 준비 (실제 모드)

시연이나 사용자 테스트 직전, 화면을 띄울 PC(서버)에서 한 번 합니다. 상담 에이전트(#25)의 첫 되묻기 질문이 느리지 않게 임베딩 캐시를 미리 만들고, AWS가 실제로 불리는지 확인하는 절차입니다.

```bash
# 1) AWS 로그인 확인. 만료됐으면 다시 로그인 (AWS_PROFILE은 .env와 같은 값)
aws sts get-caller-identity --profile "$AWS_PROFILE" > /dev/null && echo "로그인 OK" || aws sso login --profile "$AWS_PROFILE"

# 2) .env 확인: BEDROCK_MOCK=0, BEDROCK_MODEL_ID, EMBED_MODEL_ID, DYNAMODB_DEMAND_TABLE
#    EMBED_MODEL_ID는 data/courses/course_vectors.json 의 "model" 과 같아야 과정 검색이 임베딩을 씁니다

# 3) 임베딩 캐시 만들기. 처음이면 호출 약 200번, 40초 안팎. 이미 있으면 0번
python -m ai.agent --warmup

# 4) 질문 1개 시험. 답·도구 순서·토큰·응답 시간이 JSON으로 나옵니다
python -m ai.agent "Python, Docker 해봤는데 클라우드 엔지니어 되려면 뭐부터 공부해요?"

# 5) 가드레일 설정 확인 (#24). 화면 상담과 상담 에이전트가 같은 설정(ai/guardrail.py)을 씁니다.
#    .env 에 GUARDRAIL_ID 와 GUARDRAIL_VERSION(배포된 Guardrail 에 실제로 있는 버전 번호), GUARDRAIL_TOPIC_BLOCK=1
#    코드 검사는 통과하고 주제 정의 수정본(팀 Guardrail 버전 2) 차단 주제가 막는 질문입니다(설정이 맞을 때만 막힘).
#    답이 "이 서비스는 성별, 학력, 출신 지역…" 고정 문장이고 tool_calls 가 비어 있어야 합니다.
#    상담 답이 나오면 GUARDRAIL_VERSION·GUARDRAIL_TOPIC_BLOCK 설정이나 AWS 로그인을 확인합니다
python -m ai.agent "지방대 출신은 대기업 클라우드 직무 지원해도 소용없죠?"
```

- 3)에서 "가짜 모드라 임베딩을 부르지 않습니다"가 나오면 `.env`의 `BEDROCK_MOCK`이 `1`입니다.
- 캐시는 `data/raw/embed_cache.json`에 생깁니다. 커밋하지 않습니다.
- 4)의 답에 `"uncertain": true`가 나오면 `uncertain_reason`을 보고 채팅방에 알립니다(`no_tool`, `max_turns`, `number_check`, `pair_check`, `guardrail`).
- 가드레일 시연 설정은 **팀 Guardrail 버전 2 + 차단 주제 켜기**(`GUARDRAIL_VERSION`에 2, `GUARDRAIL_TOPIC_BLOCK=1`)입니다. `.env.example`에는 버전 기본값이 없으니 직접 적습니다. `GUARDRAIL_ID`를 비우면 예전 이름 `BEDROCK_GUARDRAIL_ID`·`BEDROCK_GUARDRAIL_VERSION` 묶음을 읽습니다(묶음끼리 섞지 않음). 버전 1을 쓰면 `GUARDRAIL_TOPIC_BLOCK=0`으로 둡니다(버전 1은 "비전공자인데…" 질문을 막는 오탐이 있었습니다).
- **SSO 로그인이 만료되거나 ID·버전이 비어 있으면 모든 질문이 검사 실패로 끝납니다.** 화면은 "요청의 가드레일 점검을 완료하지 못했습니다…", 상담 에이전트는 "지금은 안전 검사를 할 수 없어…"가 나옵니다. 시연 전 1)과 5)를 꼭 확인합니다.
- `GUARDRAIL_TOPIC_BLOCK`을 빠뜨리면 1(차단 주제 켜기)로 동작합니다. 버전 1을 쓸 때만 0으로 둡니다.
