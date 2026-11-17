"""탭: 진단 보고서 내려받기. 다른 탭에 나온 값을 한 장으로 모아 HTML 파일로 준다(app/report.py)."""
import streamlit as st

from app.common import Ctx, load, notice
from app.report import build_report, file_name
from backend import api
from backend.jobs import JOBS


def render(ctx: Ctx):
    if ctx.demand_err or ctx.gap_err:
        notice("진단 보고서", ctx.demand_err or ctx.gap_err, "진단 결과가 나오면 여기서 한 장으로 내려받을 수 있습니다.")
        return
    owned = getattr(ctx, "levels", None) or ctx.owned
    areas, err = load(api.get_area_gap, ctx.job, owned)
    if err:
        notice("진단 보고서", err)
        return
    levels = getattr(ctx, "levels", None)  # 보유 수준이 있으면 학습 추천 탭과 같은 인자로 불러 과정 순서를 화면과 맞춘다
    recs, rec_err = (load(api.get_recommendations, ctx.job, [r["skill"] for r in ctx.missing], *([levels] if levels else []))
                     if ctx.missing else ([], None))
    st.write("지금 화면의 진단 결과를 한 장으로 내려받습니다: 분석한 데이터, 보유 기술, 영역별 충족률, 부족한 기술, 추천 교육과정.")
    if rec_err:
        st.caption("추천을 불러오지 못해 보고서의 추천 교육과정 절은 비어 있습니다.")
    html = build_report(job_title=JOBS[ctx.job], demand=ctx.demand, gap_rows=ctx.gap_rows, area_rows=areas,
                        recommendations=recs or [], owned=list(ctx.owned), levels=getattr(ctx, "levels", None) or None,
                        mock=api.is_mock(), recommend_failed=bool(rec_err))
    st.download_button("진단 보고서 내려받기 (HTML)", data=html.encode("utf-8"), file_name=file_name(), mime="text/html",
                       type="primary", icon=":material/download:", key="report_btn")
    st.caption("받은 파일은 폰과 PC의 브라우저에서 바로 열립니다. PDF가 필요하면 브라우저의 인쇄에서 \"PDF로 저장\"을 고르세요. "
               "보고서에는 화면에 나온 값만 담기며, 이 서비스는 보고서를 따로 저장하지 않습니다.")
    with st.expander("보고서 미리 보기"):
        # 내려받는 파일과 같은 모양으로 보여 준다(틀 안에 문서째 넣는다). 값은 모두 이스케이프돼 있다(app/report.py)
        if hasattr(st, "iframe"):
            st.iframe(html, height=600)
        else:  # 예전 Streamlit
            import streamlit.components.v1 as components

            components.html(html, height=600, scrolling=True)
