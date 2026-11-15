#!/usr/bin/env bash
# Claude Review 가 읽을 실행 결과를 만든다. 사용: bash .github/review/run_checks.sh [결과 파일]
# - PR 을 main 과 합친 상태에서 가짜 모드(BEDROCK_MOCK=1)로만 돌린다. AWS 나 외부 API 는 부르지 않는다.
# - 항목이 실패해도 이 스크립트는 0 으로 끝난다. 합칠지 말지는 정하지 않고, 결과를 리뷰 댓글의 근거로만 쓴다.
# - 로컬에서도 같은 명령으로 돌릴 수 있다(결과 파일은 .gitignore 대상).
set -u
OUT="${1:-.review/checks.md}"
mkdir -p "$(dirname "$OUT")"
export BEDROCK_MOCK=1
PY="${PYTHON:-python}"
LOG="$(mktemp)"
ROWS=""
DETAIL=""
PASS=0
FAIL=0

run() {  # run "이름" 명령...
  local name="$1"; shift
  local code=0
  timeout 180 "$@" >"$LOG" 2>&1 || code=$?
  local mark="통과" lines="${KEEP:-8}"
  if [ "$code" -ne 0 ]; then mark="**실패**"; lines=60; FAIL=$((FAIL + 1)); else PASS=$((PASS + 1)); fi
  ROWS+="| ${name} | \`$*\` | ${mark} | ${code} |"$'\n'
  DETAIL+=$'\n'"### ${name} (${mark}, 종료 코드 ${code})"$'\n\n```\n'"$(tail -n "$lines" "$LOG" | cut -c1-400)"$'\n```\n'
}

run "문법 검사" "$PY" -m compileall -q ai app backend pipeline

# 저장소의 테스트 파일은 `python -m 모듈` 로 실행하는 스크립트다(pytest 는 수집하지 못한다)
while IFS= read -r f; do
  mod="${f%.py}"; mod="${mod//\//.}"
  run "테스트 ${mod}" "$PY" -m "$mod"
done < <(git ls-files 'test_*.py' '**/test_*.py' | sort)

[ -f ai/eval/score.py ] && KEEP=30 run "추출 채점(가짜 모드)" "$PY" -m ai.eval.score --runs 1
[ -f ai/eval/recommend_demo.py ] && KEEP=20 run "추천 이유 데모(가짜 모드)" "$PY" -m ai.eval.recommend_demo
[ -f app/main.py ] && run "화면 띄우기" "$PY" .github/review/smoke_app.py

run "JSON 파싱(data/, contracts/)" "$PY" .github/review/check_json.py

{
  echo "# 실행 점검 결과 (가짜 모드)"
  echo
  echo "- 통과 ${PASS} / 실패 ${FAIL}. 커밋 $(git rev-parse --short HEAD 2>/dev/null), $($PY --version 2>&1), BEDROCK_MOCK=1"
  echo "- 실제 Bedrock·AWS·로켓펀치 호출은 돌리지 않았다. \`BEDROCK_MOCK=0\` 경로는 이 결과로 확인되지 않는다."
  echo "- 통과는 '테스트가 단언한 것이 맞다'는 뜻이다. 이 PR 이 바꾼 로직을 테스트가 실제로 단언하는지는 따로 봐야 한다."
  echo
  echo "| 항목 | 명령 | 결과 | 종료 코드 |"
  echo "| --- | --- | --- | --- |"
  printf '%s' "$ROWS"
  echo
  echo "## 출력 (통과는 마지막 몇 줄, 실패는 마지막 60줄)"
  printf '%s' "$DETAIL"
} >"$OUT"
rm -f "$LOG"
echo "실행 점검: 통과 ${PASS} / 실패 ${FAIL} → ${OUT}"
exit 0
