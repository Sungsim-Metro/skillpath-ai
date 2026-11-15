"""data/ 와 contracts/ 의 JSON 파일이 읽히는지 본다. 깨진 파일이 있으면 종료 코드 1."""
import json
import pathlib
import sys

bad = []
for path in sorted([*pathlib.Path("data").rglob("*.json"), *pathlib.Path("contracts").rglob("*.json")]):
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        bad.append(f"{path}: {e}")
print("\n".join(bad) or "모든 JSON 파일을 읽었습니다")
sys.exit(1 if bad else 0)
