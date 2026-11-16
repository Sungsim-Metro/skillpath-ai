"""영역 레이더 차트: 공고 수요 / 지금 내 보유 / 추천 과정을 마친 뒤(예상).

부족 역량 탭 안의 한 구역이다. 값은 backend 가 계산하고 여기서는 좌표로 옮겨 그리기만 한다.
레이더 차트는 Altair 에 기본으로 없어 꼭짓점 좌표를 만들어 선으로 그린다(새 라이브러리를 더하지 않는다).
"""
import math

import altair as alt
import pandas as pd
import streamlit as st

from app.common import ACCENT, MARKET_DEMAND, Ctx, load, notice
from backend import api

AFTER = "#2E9E6B"  # "마친 뒤"에만 쓰는 색
SERIES = ["공고 수요", "지금", "추천 과정을 마친 뒤(예상)"]
RINGS = (0.25, 0.5, 0.75, 1.0)


def _xy(i: int, n: int, r: float) -> tuple[float, float]:
    """n 개 축 중 i 번째 축에서 반지름 r 인 점. 0번 축이 위쪽이고 시계 방향으로 돈다."""
    angle = 2 * math.pi * i / n
    return r * math.sin(angle), r * math.cos(angle)


def render_radar(ctx: Ctx):
    owned = getattr(ctx, "levels", None) or ctx.owned  # 보유 수준 기능이 있으면 수준까지 넘긴다
    now, err = load(api.get_area_gap, ctx.job, owned)
    if err:
        notice("영역 레이더", err)
        return
    recs, rec_err = load(api.get_recommendations, ctx.job, [r["skill"] for r in ctx.missing]) if ctx.missing else ([], None)
    covered = [r["gap_skill"] for r in recs or [] if r["courses"]]
    after, err = load(api.get_area_gap_after, ctx.job, owned, covered)
    if err:
        notice("영역 레이더", err)
        return
    after_by = {r["area_id"]: r for r in after}
    areas = [r for r in now if r["demand"] > 0 and r["area_id"] != "UNCLASSIFIED"]
    if len(areas) < 3:
        st.info("수요가 있는 영역이 3개 미만이라 레이더 차트를 그리지 않습니다. 위의 막대 차트를 보세요.")
        return

    n = len(areas)
    points, labels, grid, spokes = [], [], [], []
    for i, r in enumerate(areas):
        values = {SERIES[0]: 1.0, SERIES[1]: r["coverage"], SERIES[2]: after_by[r["area_id"]]["coverage"]}
        for name, v in values.items():
            x, y = _xy(i, n, v)
            points.append({"구분": name, "영역": r["area"], "순서": i, "x": x, "y": y, "충족률": f"{v:.0%}"})
        lx, ly = _xy(i, n, 1.12)
        side = "center" if abs(lx) < 0.2 else ("left" if lx > 0 else "right")  # 옆쪽 이름은 차트 바깥으로 뻗게 맞춘다
        labels.append({"영역": r["area"], "x": lx, "y": ly + (0.08 if ly > 0 else -0.08) * (side == "center"), "맞춤": side})
        sx, sy = _xy(i, n, 1.0)
        spokes += [{"축": i, "x": 0.0, "y": 0.0}, {"축": i, "x": sx, "y": sy}]
        for ring in RINGS:
            gx, gy = _xy(i, n, ring)
            grid.append({"고리": ring, "순서": i, "x": gx, "y": gy})

    scale = alt.Scale(domain=[-1.25, 1.25])
    x_scale = alt.Scale(domain=[-2.1, 2.1])  # 좌우에 영역 이름이 들어갈 자리
    x = alt.X("x:Q", scale=x_scale, axis=None)
    y = alt.Y("y:Q", scale=scale, axis=None)
    closed = {"interpolate": "linear-closed"}
    grid_layer = alt.Chart(pd.DataFrame(grid)).mark_line(color="#D5DAE1", strokeWidth=1, **closed).encode(
        x=x, y=y, detail="고리:N", order="순서:Q")
    spoke_layer = alt.Chart(pd.DataFrame(spokes)).mark_line(color="#D5DAE1", strokeWidth=1).encode(x=x, y=y, detail="축:N")
    color = alt.Color("구분:N", scale=alt.Scale(domain=SERIES, range=[MARKET_DEMAND, ACCENT, AFTER]),
                      legend=alt.Legend(orient="bottom", title=None, labelLimit=300))
    df = pd.DataFrame(points)
    shapes = []
    for name in SERIES:  # 뒤에 그린 것이 위에 온다: 수요 → 지금 → 마친 뒤 순서로 겹친다
        one = alt.Chart(df[df["구분"] == name]).encode(x=x, y=y, order="순서:Q", color=color)
        if name != SERIES[0]:
            shapes.append(one.mark_line(filled=True, fillOpacity=0.14, strokeWidth=0, **closed).encode(fill=color))
        shapes.append(one.mark_line(strokeWidth=2.5, strokeDash=[5, 4] if name == SERIES[0] else [1, 0], **closed))
    point_layer = alt.Chart(df).mark_point(filled=True, size=55, opacity=1).encode(
        x=x, y=y, color=color, tooltip=["영역", "구분", "충족률"])
    label_df = pd.DataFrame(labels)
    label_layers = [
        alt.Chart(label_df[label_df["맞춤"] == side]).mark_text(fontSize=12, color="#3B4350", align=side).encode(
            x=x, y=y, text="영역:N")
        for side in ("left", "center", "right") if (label_df["맞춤"] == side).any()
    ]
    chart = alt.layer(grid_layer, spoke_layer, *shapes, point_layer, *label_layers).properties(height=420)
    # 가운데 칸에 그려 가로로 늘어지지 않게 한다. 폰 화면에서는 칸이 세로로 쌓여 전체 폭을 쓴다
    _, middle, _ = st.columns([1, 6, 1])
    with middle:
        st.altair_chart(chart.configure_view(stroke=None), width="stretch")

    st.dataframe(
        pd.DataFrame([
            {"영역": r["area"], "지금": r["coverage"], "마친 뒤(예상)": after_by[r["area_id"]]["coverage"],
             "늘어나는 기술": ", ".join(s for s in covered if s in r["skills"]) or "-"}
            for r in areas
        ]),
        hide_index=True, width="stretch",
        column_config={"지금": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                       "마친 뒤(예상)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
    )
    note = (
        "바깥 점선은 공고 수요(100%), 안쪽은 그 수요 가운데 내가 가진 몫(충족률)입니다. "
        "'마친 뒤'는 학습 추천 탭의 과정이 붙은 기술을 배운 것으로 쳤을 때의 예상이며, 과정을 마쳤다고 그 기술을 다룰 수 있다는 보장은 아닙니다."
    )
    if rec_err:
        note += " 추천을 불러오지 못해 '마친 뒤'가 지금과 같게 나옵니다."
    elif len(covered) < len(ctx.missing):
        note += f" 부족 기술 {len(ctx.missing)}개 중 과정이 붙은 {len(covered)}개만 반영했습니다."
    st.caption(note)
