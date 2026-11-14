# 공개용 저장소: 게시와 공유

개발은 이 저장소(비공개)에서 계속하고, 공개할 수 있는 파일만 공개용 저장소 `Sungsim-Metro/skillpath-ai-public`에 자동으로 올립니다.
멘토님, 제출, 발표에는 공개용 저장소 링크만 씁니다. 결정 이슈: #53 (2026-11-13), 자동 게시로 변경: 2026-11-14.

| | 주소 |
| --- | --- |
| 공개용 저장소 | https://github.com/Sungsim-Metro/skillpath-ai-public |
| 소개 페이지 (GitHub Pages) | https://sungsim-metro.github.io/skillpath-ai-public/ |

## 1. 흐름

```
PR 올림 → 공개 검사 → 병합 → 검사 다시 → 통과하면 자동 게시
```

1. **PR을 올리면** `Public Sync / 공개 검사`가 공개 파일을 추출해 보안 검사를 합니다. 걸리면 PR에 ❌가 뜨고 로그에 `파일:줄번호`가 나옵니다. 병합 전에 고칩니다.
2. **`main`에 병합하면** 같은 검사를 다시 하고, 통과하면 공개용 저장소에 바로 게시합니다. 걸리면 게시하지 않고 공개용 저장소는 이전 상태로 남습니다.
3. **수동으로 다시 게시하려면** Actions → Public Sync → Run workflow(브랜치 `main`) → 입력칸에 `publish`.

공개용 저장소에는 이 저장소의 커밋 기록이 따라가지 않습니다. 게시할 때마다 "동기화: 개발 저장소 abc1234" 커밋 하나가 쌓입니다.
공개용 저장소에서 직접 고치지 않습니다. 다음 게시 때 덮어써집니다.

## 2. 무엇이 나가나

| 종류 | 내용 | 고치는 곳 |
| --- | --- | --- |
| 그대로 복사 | `app/` `backend/` `pipeline/` `ai/` `contracts/` `data/sample/`, `docs/service-flow.md`, `docs/data-sources.md`, `requirements.txt`, `.env.example`, `.gitignore` | [`allowlist.txt`](../.github/public-sync/allowlist.txt) |
| 공개용 README | 프로젝트 소개, AWS 서비스와 이유, 설계 원칙, 무엇을 어디서 보나, 실행 방법 | [`README.public.md`](../.github/public-sync/README.public.md) |
| 협업 기록 `COLLABORATION.md` | 역할 분담과 일하는 방식(사람이 씀) + 이슈·PR 수, 마일스톤 진행, 담당자별 이슈, 최근 병합한 PR(자동) | [`COLLABORATION.head.md`](../.github/public-sync/COLLABORATION.head.md), [`collab.py`](../.github/public-sync/collab.py) |
| 회의 결정 사항 `docs/meeting-decisions.md` | 회의록의 "1. 결정 사항" 절만 발췌(자동) | 회의록 원문 |
| Pages 설정 `_config.yml` | 소개 페이지 제목과 테마 | [`pages/_config.yml`](../.github/public-sync/pages/_config.yml) |

나가지 않는 것: `CLAUDE.md`, `.github/`, 회의록의 나머지 절(할 일, 점검표), 멘토링 기록, 과제·기획·WBS·점검 문서, 이슈와 PR 원문, GitHub 아이디.

평가 항목과의 대응:

| 평가 항목 | 공개용 저장소에서 보여 주는 것 |
| --- | --- |
| 문제해결력 | 서비스 플로우, JSON 형식(`contracts/`), 추출·근거 검증·채점 코드(`ai/`) |
| 현장 적용성 | 데이터 출처·수집 범위·한계(`docs/data-sources.md`) |
| 창의성 | 공개용 README의 설계 원칙(근거 문장 검증, "불확실" 표시) |
| 전달력 | 공개용 README, 소개 페이지, 실행 방법 |
| AWS 기술 활용도 및 팀워크 | README의 AWS 서비스 표, `COLLABORATION.md`, `docs/meeting-decisions.md` |

협업 기록에서 조정할 수 있는 것:

- 팀원별 PR 수와 PR 작성자는 지금 공개하지 않습니다. `collab.py`의 `SHOW_PR_AUTHORS`를 `True`로 바꾸면 나갑니다.
- 회의 결정 사항에는 데이터 소스 승인 여부 같은 내부 사정도 들어갑니다. 빼고 싶은 줄은 회의록에서 "결정 사항" 밖으로 옮깁니다.
- "녹취", "교안", "멘토"가 든 PR 제목과 회의록 줄은 자동으로 빠지고, 빠진 개수만 적힙니다.

## 3. 보안 검사 (하나라도 걸리면 게시하지 않음)

- 공개 금지 파일: `.env`, `data/raw/`, `*.pem`, `*.key`, `secrets.toml`, `.aws/`
- 키·토큰: gitleaks
- AWS 계정 ID 후보(12자리 숫자), AWS 액세스 키(`AKIA…`), 이메일 주소, 전화번호
- 공개하지 않기로 한 자료: "녹취", "교안", "멘토"가 들어간 줄

검사에 걸리면 로그에 파일과 줄 번호만 나옵니다(값 자체는 로그에 남기지 않음).
정말 문제없는 값이 걸리면 [`build.sh`](../.github/public-sync/build.sh)의 `ALLOW`나 검사 규칙을 고치는 PR을 올립니다.

로컬에서 미리 돌려 볼 수 있습니다(gitleaks 설치 필요. 커밋한 내용만 검사합니다).

```bash
bash .github/public-sync/build.sh /tmp/public
```

검사는 실수를 막는 장치이지 강제 잠금이 아닙니다. 쓰기 권한이 있는 팀원은 워크플로 파일을 고쳐 우회할 수 있으므로 팀원을 믿는다는 전제입니다.
`.github/` 아래와 `allowlist.txt`를 바꾸는 PR은 형섭이 확인한 뒤 병합합니다.

## 4. 처음 한 번만 할 설정 (형섭, 약 10분)

설정 전에는 `main`에 병합해도 검사만 하고 게시하지 않습니다.

1. **공개용 저장소 만들기.** https://github.com/organizations/Sungsim-Metro/repositories/new → 이름 `skillpath-ai-public` → **Public** →
   README, .gitignore, license는 아무것도 추가하지 않고 Create repository.
2. **배포 키 만들기.** Git Bash에서(저장소 폴더 밖, 예를 들어 바탕 화면):
   ```bash
   cd ~/Desktop
   ssh-keygen -t ed25519 -C "skillpath-ai public sync" -f skillpath_public_sync -N ""
   ```
   파일 두 개가 생깁니다. `skillpath_public_sync.pub`(공개 키)와 `skillpath_public_sync`(비밀 키).
3. **공개 키를 공개용 저장소에 등록.** `skillpath-ai-public` → Settings → Deploy keys → Add deploy key →
   Title `public-sync`, Key에 `cat skillpath_public_sync.pub` 결과 한 줄, **Allow write access 체크** → Add key.
4. **비밀 키를 이 저장소에 등록.** `skillpath-ai` → Settings → Secrets and variables → Actions → New repository secret →
   Name `PUBLIC_REPO_DEPLOY_KEY`, Secret에 `cat skillpath_public_sync` 결과 전체(`-----BEGIN` 줄부터 `-----END` 줄까지).
5. **키 파일 두 개를 PC에서 지웁니다.** `rm skillpath_public_sync skillpath_public_sync.pub`
6. **첫 게시.** Actions → Public Sync → Run workflow(`main`) → `publish`. 끝나면 공개용 저장소에 파일이 보입니다.
7. **소개 페이지 켜기.** `skillpath-ai-public` → Settings → Pages → Source `Deploy from a branch` → Branch `main`, 폴더 `/ (root)` → Save.
   1~2분 뒤 https://sungsim-metro.github.io/skillpath-ai-public/ 이 열립니다. 공개용 README가 첫 화면입니다.
8. **저장소 소개 채우기(선택).** 공개용 저장소 첫 화면 오른쪽 About의 톱니바퀴 → Description에 한 줄 소개, Website에 소개 페이지 주소.

배포 키는 공개용 저장소 하나에만 쓰기 권한이 있습니다. 키가 새면 Deploy keys에서 지우고 2번부터 다시 합니다.

## 5. 공유 방법

공유하기 전에 항상 확인합니다.

1. Actions → Public Sync의 최근 `main` 실행이 ✅인지
2. 공개용 저장소 README의 "최종 동기화" 시각이 방금인지
3. 로그아웃한 창(시크릿 모드)에서 링크가 열리는지

### 멘토님께

멘토링 전날까지 링크를 보냅니다(2차는 11/17, 전달은 11/16까지). 보낼 내용 예시:

> 안녕하세요, ASAP하게 팀입니다. 진행 상황을 아래에서 보실 수 있습니다.
> - 저장소: https://github.com/Sungsim-Metro/skillpath-ai-public
> - 협업 기록: 저장소의 COLLABORATION.md
> - 흐름 그림: docs/service-flow.md
>
> 개발 저장소에서 자동으로 옮긴 사본이라 이슈와 PR 원문은 보이지 않습니다. 필요하시면 GitHub 아이디를 알려 주세요. 읽기 권한으로 초대드리겠습니다.

이슈·PR·회의록 원문까지 보여 드려야 하면 이 저장소(비공개)에 Read 권한으로 초대합니다.
`skillpath-ai` → Settings → Collaborators and teams → Add people → 아이디 입력 → Role `Read`.

### 결과물 제출

- 제출 양식에 저장소 링크를 적는 칸이 있는지, 공개 저장소여야 하는지는 LMS에서 확인합니다(확인 전에는 추측하지 않습니다).
- 링크를 낸다면 공개용 저장소 주소를 냅니다. 제출 직전 순서:
  1. 제출할 내용을 모두 `main`에 병합하고 Public Sync ✅를 확인합니다.
  2. 위 "공유하기 전에" 3가지를 확인합니다.
  3. 공개용 저장소 주소와 마지막 "동기화" 커밋 번호를 제출 기록(#30)에 적습니다.
- 제출 뒤에 `main`에 병합하면 공개용 저장소도 바뀝니다. 제출 시점 그대로 남겨야 하면 제출 직후 공개용 저장소에서 Releases → Draft a new release로 태그(`submit-1122`)를 찍습니다.
- 이 저장소(비공개) 자체를 공개할지는 따로 정합니다(#44). 예전 커밋에 공개하면 안 되는 자료가 남아 있어 그대로는 공개하지 않습니다.

### 발표 자료와 QR

- 발표 장표 마지막에 소개 페이지 주소와 QR을 넣습니다. 저장소 주소보다 소개 페이지가 휴대폰에서 읽기 쉽습니다.
- QR 만들기:
  ```bash
  pip install "qrcode[pil]"
  qr "https://sungsim-metro.github.io/skillpath-ai-public/" > qr.png
  ```
- 리허설 때 휴대폰으로 찍어 열리는지 확인합니다. 행사장 네트워크가 느릴 수 있으니 소개 페이지 캡처도 장표에 넣습니다.
- 소개 페이지는 지금 공개용 README를 그대로 보여 주는 뼈대입니다. 화면 캡처, 시연 영상, 결과 수치는 M3(11/17) 뒤에 `README.public.md`에 채웁니다.
