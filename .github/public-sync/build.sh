#!/usr/bin/env bash
# 공개 파일 추출과 보안 검사.
# 사용법: .github/public-sync/build.sh 출력폴더
# - allowlist.txt에 적힌 경로만, 커밋된 파일만(git archive) 꺼낸다. 커밋 기록은 나가지 않는다.
# - 검사에 하나라도 걸리면 종료 코드 1. 이때는 Public 레포에 아무것도 올리지 않는다.
set -euo pipefail

OUT="${1:?출력 폴더를 지정하세요}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
GITLEAKS="${GITLEAKS:-gitleaks}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"

rm -rf "$OUT" && mkdir -p "$OUT"
cd "$ROOT"

# 1. 추출
mapfile -t PATHS < <(grep -vE '^\s*(#|$)' "$HERE/allowlist.txt")
EXISTING=()
for p in "${PATHS[@]}"; do
  if [ -n "$(git ls-files -- "$p")" ]; then EXISTING+=("$p"); else echo "알림: $p 는 아직 커밋된 파일이 없어 건너뜀"; fi
done
# 경로가 하나도 없으면 git archive가 저장소 전체를 꺼내므로 여기서 멈춘다
[ "${#EXISTING[@]}" -gt 0 ] || { echo "❌ 내보낼 경로가 없습니다. allowlist.txt를 확인하세요."; exit 1; }
git archive --format=tar HEAD -- "${EXISTING[@]}" | tar -x -C "$OUT"

SHA="$(git rev-parse --short HEAD)"
DATE="$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
sed "s|{{SYNC_INFO}}|$DATE (개발 저장소 커밋 $SHA)|" "$HERE/README.public.md" > "$OUT/README.md"

FILES="$(cd "$OUT" && find . -type f | sed 's|^\./||' | sort)"
echo "추출한 파일 $(echo "$FILES" | wc -l)개"

# 2. 보안 검사
FAIL=0
fail() { echo "❌ $1"; FAIL=1; }

# 2-1. 나가면 안 되는 파일
BAD_FILES="$(echo "$FILES" | grep -E '(^|/)\.env($|\.(local|prod|dev))|(^|/)data/raw/|\.pem$|\.key$|secrets\.toml$|(^|/)\.aws/' || true)"
[ -n "$BAD_FILES" ] && fail "공개 금지 파일: $BAD_FILES"

# 2-2. 키·토큰 (gitleaks)
if ! "$GITLEAKS" dir "$OUT" --redact --no-banner --exit-code 1 > /tmp/gitleaks.txt 2>&1; then
  fail "gitleaks가 비밀 값 후보를 찾음"; cat /tmp/gitleaks.txt
fi

# 2-3. 계정 ID, AWS 키, 이메일, 전화번호, 공개하지 않기로 한 자료
check() { # 이름 정규식. 걸린 값이 로그에 남지 않게 "파일:줄번호"만 출력한다
  local hits; hits="$(grep -rnIE "$2" "$OUT" | sed "s|^$OUT/||" | grep -vE "$ALLOW" | cut -d: -f1,2 || true)"
  [ -n "$hits" ] && fail "$1"$'\n'"$hits"
  return 0
}
ALLOW='example\.com|noreply@'
check "AWS 계정 ID 후보(12자리 숫자)" '(^|[^0-9])[0-9]{12}([^0-9]|$)'
check "AWS 액세스 키" '(AKIA|ASIA)[A-Z0-9]{16}'
check "이메일 주소" '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
check "전화번호" '01[016789][- ]?[0-9]{3,4}[- ]?[0-9]{4}'
check "공개하지 않기로 한 자료(녹취·교안·멘토링)" '녹취|교안|멘토'

# 3. 결과
{
  echo "## 공개 동기화 검사 ($SHA)"
  if [ "$FAIL" = 0 ]; then echo "✅ 검사 통과. 내보낼 파일 $(echo "$FILES" | wc -l)개"; else echo "❌ 검사 실패. Public 레포에 올리지 않습니다. 로그를 확인하세요."; fi
  echo; echo "<details><summary>내보낼 파일 목록</summary>"; echo; echo '```'; echo "$FILES"; echo '```'; echo "</details>"
} | tee -a "$SUMMARY"

exit "$FAIL"
