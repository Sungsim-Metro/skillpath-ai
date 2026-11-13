# 공개용 저장소 동기화

개발은 이 저장소(비공개)에서 계속하고, 공개할 수 있는 파일만 골라 공개용 저장소 `Sungsim-Metro/skillpath-ai-public`에 올립니다.
멘토님과 외부에는 공개용 저장소 링크만 보여 줍니다. 결정 이슈: #53

## 흐름

```
개발(비공개) → main 병합 → 공개 파일 추출 → 보안 검사 → 형섭 승인 → 공개용 저장소
```

1. **main에 병합될 때마다** `Public Sync` 워크플로가 공개 파일을 추출하고 보안 검사를 합니다. 게시는 하지 않습니다.
2. **형섭이 검사 결과를 확인합니다.** Actions → Public Sync → 해당 실행의 요약에서 "내보낼 파일 목록"을 봅니다.
3. **게시할 때만** Actions → Public Sync → Run workflow(브랜치 `main`) → 입력칸에 `publish` → 실행.
   검사를 한 번 더 통과해야 올라갑니다. 형섭 계정이 아니면 검사만 하고 끝납니다.

공개용 저장소에는 커밋 기록이 따라가지 않습니다. 게시할 때마다 "동기화: 개발 저장소 abc1234" 커밋 하나가 쌓입니다.

## 무엇이 나가나

[`.github/public-sync/allowlist.txt`](../.github/public-sync/allowlist.txt)에 적은 경로만 나갑니다. 적지 않은 것은 나가지 않습니다.
README는 [`README.public.md`](../.github/public-sync/README.public.md)로 바꿔 넣습니다(이 저장소의 README는 비공개 이슈·보드 링크가 많아서).

| 나감 | 나가지 않음 |
| --- | --- |
| `app/` `backend/` `pipeline/` `ai/` `contracts/` `data/sample/` | `CLAUDE.md`, `.github/` |
| `docs/service-flow.md` `docs/data-sources.md` | `docs/meetings/`(회의록·멘토링), 과제·기획·WBS·점검 문서 |
| `requirements.txt` `.env.example` `.gitignore` | `.env`, `data/raw/` (원래 커밋하지 않음) |

목록을 바꾸려면 `allowlist.txt`를 고치는 PR을 올립니다.

## 보안 검사 (하나라도 걸리면 게시하지 않음)

- 공개 금지 파일: `.env`, `data/raw/`, `*.pem`, `*.key`, `secrets.toml`, `.aws/`
- 키·토큰: gitleaks
- AWS 계정 ID 후보(12자리 숫자), AWS 액세스 키(`AKIA…`), 이메일 주소, 전화번호
- 공개하지 않기로 한 자료: "녹취", "교안", "멘토"가 들어간 줄

검사에 걸리면 로그에 파일과 줄 번호가 나옵니다. 고친 뒤 다시 병합하면 됩니다.
정말 문제없는 값이 걸리면 `build.sh`의 `ALLOW`나 검사 규칙을 고치는 PR을 올립니다.

로컬에서 미리 돌려 볼 수 있습니다(gitleaks 설치 필요).

```bash
bash .github/public-sync/build.sh /tmp/public
```

## 처음 한 번만 할 설정 (형섭)

1. **공개용 저장소 만들기.** Sungsim-Metro 조직에서 New repository → 이름 `skillpath-ai-public` → **Public** → README 등 아무것도 추가하지 않고 생성.
2. **배포 키 만들기.** 내 PC 터미널에서:
   ```bash
   ssh-keygen -t ed25519 -C "skillpath-ai public sync" -f skillpath_public_sync -N ""
   ```
   파일 두 개가 생깁니다. `skillpath_public_sync.pub`(공개 키)와 `skillpath_public_sync`(비밀 키).
3. **공개 키를 공개용 저장소에 등록.** `skillpath-ai-public` → Settings → Deploy keys → Add deploy key →
   제목 `public-sync`, 내용에 `.pub` 파일 내용, **Allow write access 체크** → Add key.
4. **비밀 키를 이 저장소에 등록.** `skillpath-ai` → Settings → Secrets and variables → Actions → New repository secret →
   이름 `PUBLIC_REPO_DEPLOY_KEY`, 내용에 비밀 키 파일 전체(`-----BEGIN` 줄부터 `-----END` 줄까지).
5. **키 파일 두 개를 PC에서 지웁니다.** 저장소 폴더 안에 만들었다면 커밋되지 않게 특히 주의합니다.
6. **첫 게시.** 위 "흐름" 3번대로 Run workflow → `publish`.

배포 키는 공개용 저장소 하나에만 쓰기 권한이 있습니다. 키가 새면 Deploy keys에서 지우고 다시 만들면 됩니다.

## 주의

- 공개용 저장소는 누구나 봅니다. 다른 팀도 발표(11/25) 전에 코드와 프롬프트를 볼 수 있습니다(#44에서 걱정한 점). 게시 전에 파일 목록을 꼭 확인합니다.
- 공개용 저장소에서 직접 고치지 않습니다. 다음 게시 때 덮어써집니다.
- 이 저장소(비공개)는 제출 직전에 공개할지 따로 정합니다(#44). 녹취 전문이 예전 커밋(`024343f`)에 남아 있습니다.
