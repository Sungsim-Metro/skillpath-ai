"""화면이 가짜 모드에서 오류 없이 뜨는지 확인한다. 화면 내용의 옳고 그름은 보지 않는다.

실행: 저장소 루트에서 `python -m pytest app`
"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parent / "main.py")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("BEDROCK_MOCK", "1")
    return AppTest.from_file(MAIN, default_timeout=60)


def test_all_tabs_render_in_mock_mode(app):
    at = app.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["시장 수요", "부족 역량", "학습 추천", "공고 직접 분석"]


def test_extract_button_shows_result(app):
    at = app.run()
    at.button(key="extract_btn").click().run()
    assert not at.exception
    assert "추출 결과" in [h.value for h in at.subheader]


def test_renders_without_owned_skills(app):
    at = app.run()
    at.sidebar.button_group[0].set_value([]).run()
    assert not at.exception
