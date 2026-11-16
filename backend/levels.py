"""보유 수준 3단계와 Gap 에 치는 값 (2026-11-16 결정, 형섭 임시 결정).

| 값        | 화면 이름 | 뜻                     | Gap 에 치는 값 |
| --------- | --------- | ---------------------- | -------------- |
| "none"    | 없음      | 다뤄 본 적 없음        | 0              |
| "learned" | 배워봄    | 강의·실습으로 배워 봄  | 0.5            |
| "used"    | 써봄      | 프로젝트에서 직접 써 봄 | 1.0            |

0.5 는 팀이 정한 값이다. 근거 자료가 있는 수치가 아니므로 화면과 발표에 그렇게 적는다.
수준은 사용자가 스스로 고른 값이고 실력을 검증한 것이 아니다.
"""
from __future__ import annotations

NONE, LEARNED, USED = "none", "learned", "used"
LEVEL_WEIGHT = {NONE: 0.0, LEARNED: 0.5, USED: 1.0}
LEVEL_LABEL = {NONE: "없음", LEARNED: "배워봄", USED: "써봄"}
# 부족 기술의 수준 → 먼저 추천할 과정 난이도(data/courses/courses.csv 의 level 값)
COURSE_LEVEL_FIRST = {NONE: "기초", LEARNED: "중급"}


def normalize_owned(owned) -> dict[str, str]:
    """보유 기술 입력을 {소문자 기술 이름: 수준} 으로 바꾼다.

    - 이름 목록(예전 형식) ["Python", "Linux"] → 모두 "used". 예전 호출은 결과가 달라지지 않는다.
    - {기술: 수준} {"Python": "used", "Docker": "learned"} → 그대로. "none" 은 뺀다.
    모르는 수준 값은 오류를 낸다(조용히 0 으로 치지 않는다).
    """
    if owned is None:
        return {}
    if isinstance(owned, dict):
        out = {}
        for skill, level in owned.items():
            if level not in LEVEL_WEIGHT:
                raise ValueError(f"보유 수준 값이 {level!r} 입니다. {sorted(LEVEL_WEIGHT)} 중 하나여야 합니다")
            if level != NONE:
                out[skill.lower()] = level
        return out
    return {skill.lower(): USED for skill in owned}


def whole(x: float):
    """7.0 → 7. 화면과 예전 테스트가 정수를 그대로 받게 한다."""
    return int(x) if float(x).is_integer() else round(x, 1)
