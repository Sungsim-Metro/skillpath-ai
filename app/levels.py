"""사이드바 마이페이지와 보유 수준 진단 모달 (#90).

화면 코드만 둔다. 단계 예시는 backend.levels.level_guide(), 저장은 backend.chat_profiles 가 맡는다.
세션 값:
- levels: {세부 능력 id: 0~5}. 대시보드 Gap 과 상담 채팅의 보유 판정에 쓴다
- levels_example: True 면 아직 진단 전이라 예시 값이다(상담 채팅에는 넘기지 않는다)
- levels_owner: levels 를 불러온 닉네임
"""
import logging

import streamlit as st

from backend import chat_profiles
from backend.levels import level_guide

# 진단 전에 보여줄 예시: 예전 기본 보유 기술 Python·Linux·Git 에 해당하는 세부 능력 3단계
EXAMPLE_LEVELS = {"C5-2": 3, "C1-2": 3, "C5-3": 3}
logger = logging.getLogger("skillpath.app")


def _areas() -> dict[str, str]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "skill_areas.json"
    areas = json.loads(path.read_text(encoding="utf-8"))["areas"]
    return {k: v for k, v in areas.items() if k != "COMMON"}


def _set(levels: dict[str, int], example: bool) -> None:
    st.session_state.levels = dict(levels)
    st.session_state.levels_example = example


def sync_with_profile(nickname: str) -> None:
    """닉네임이 바뀌면 그 닉네임에 저장한 수준을 불러온다.

    저장한 수준이 없으면: 손님 → 닉네임은 지금 고른 값을 이어 쓰고, 다른 닉네임으로 바꾸거나 지우면 예시 값으로 되돌린다.
    """
    if "levels" not in st.session_state:
        _set(EXAMPLE_LEVELS, True)
        st.session_state.levels_owner = ""
    previous = st.session_state.get("levels_owner", "")
    if nickname == previous:
        return
    st.session_state.levels_owner = nickname
    saved = {}
    if nickname:
        try:
            saved = chat_profiles.load_profile(nickname)["levels"]
        except Exception:  # noqa: BLE001 - 저장소 오류로 화면 전체가 멈추지 않게. 닉네임은 로그에 남기지 않는다
            logger.exception("프로필 수준을 불러오지 못했습니다")
            st.session_state.levels_notice = "저장한 수준을 불러오지 못했습니다."
    if saved:
        _set(saved, False)
    elif previous:
        _set(EXAMPLE_LEVELS, True)


@st.dialog("보유 수준 진단", width="large")
def diagnose_dialog(nickname: str) -> None:
    """영역별로 세부 능력마다 0~5단계를 고른다. 단계마다 '이 정도면 할 수 있는 일' 예시를 보여준다."""
    guide = level_guide()
    names = guide["level_names"]
    current = st.session_state.get("levels", {})
    st.caption("세부 능력마다 지금 할 수 있는 일에 가장 가까운 단계를 고르세요. 스스로 고르는 값이며 시험이 아닙니다. "
               "예시 문장은 AI 초안을 팀이 확인하는 중입니다.")
    by_area: dict[str, list[tuple[str, dict]]] = {}
    for sid, row in guide["subskills"].items():
        by_area.setdefault(row["area_id"], []).append((sid, row))
    for area_id, area_name in _areas().items():
        rows = by_area.get(area_id, [])
        chosen = [current.get(sid, 0) for sid, _ in rows]
        with st.expander(f"{area_name} ({sum(1 for v in chosen if v)}/{len(rows)} 선택)"):
            for sid, row in rows:
                st.radio(
                    row["name"], options=list(range(6)), index=current.get(sid, 0), key=f"lv_{sid}",
                    format_func=lambda v: f"{v}단계 · {names[str(v)]}" if v else names["0"],
                    captions=["", *(row["levels"][str(v)] for v in range(1, 6))],
                )
    st.caption("저장하면 부족 역량과 추천이 이 단계로 다시 계산됩니다."
               + (" 닉네임 프로필에도 저장합니다." if nickname else " 닉네임을 입력하면 다음에도 불러올 수 있습니다."))
    if st.button("저장", type="primary", width="stretch"):
        save_levels(nickname, {sid: st.session_state[f"lv_{sid}"] for sid in guide["subskills"]})
        st.rerun()


def save_levels(nickname: str, chosen: dict[str, int]) -> None:
    """진단 결과를 세션에 두고, 닉네임이 있으면 프로필에도 저장한다."""
    _set({sid: v for sid, v in chosen.items() if v}, False)
    if not nickname:
        return
    try:
        # 0으로 바꾼 세부 능력도 덮어쓰게 고른 값 전체를 넘긴다
        chat_profiles.update_profile(nickname, levels=dict(chosen))
    except Exception:  # noqa: BLE001
        logger.exception("프로필 수준을 저장하지 못했습니다")
        st.session_state.levels_notice = "수준을 프로필에 저장하지 못했습니다. 이번 화면에서만 사용합니다."


def sidebar_summary(nickname: str) -> dict[str, int]:
    """사이드바에 영역별 내 수준을 보여주고 진단 버튼을 둔다. 지금 쓰는 {세부 능력 id: 단계} 를 돌려준다."""
    sync_with_profile(nickname)
    levels = st.session_state.levels
    guide = level_guide()["subskills"]
    st.markdown("**내 보유 수준**")
    if st.session_state.get("levels_example"):
        st.caption("아직 진단 전이라 예시 값(스크립트·자동화, Linux, Git 3단계)으로 보여줍니다.")
    lines = []
    for area_id, area_name in _areas().items():
        values = [levels.get(sid, 0) for sid, row in guide.items() if row["area_id"] == area_id]
        avg = sum(values) / len(values) if values else 0
        lines.append(f"{area_name} {avg:.1f}")
    st.caption(" · ".join(lines) + " (영역 평균, 0~5)")
    if st.button("수준 진단하기", key="open_levels", icon=":material/checklist:", width="stretch"):
        diagnose_dialog(nickname)
    notice = st.session_state.pop("levels_notice", None)
    if notice:
        st.warning(notice)
    return dict(levels)


def chat_skills(job: str, levels: dict[str, int]) -> list[str]:
    """상담 채팅에 넘길 보유 기술 이름. 예시 값은 넘기지 않는다(사용자가 고른 값만 보유로 본다)."""
    if st.session_state.get("levels_example") or not levels:
        return []
    from app.common import load
    from backend import api

    names, _ = load(api.owned_skill_names, job, levels)
    return names or []
