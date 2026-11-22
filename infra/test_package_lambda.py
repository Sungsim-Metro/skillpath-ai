"""배포 ZIP만으로 공고 전처리 Lambda가 시작되는지 검증한다."""
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from infra.package_lambda import build


class PreprocessingPackageTest(unittest.TestCase):
    def test_handlers_import_from_extracted_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "preprocessing.zip"
            build("preprocessing", archive)
            runtime = Path(tmp) / "runtime"
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(runtime)

            # 저장소 소스가 ZIP에서 누락된 모듈을 대신 제공하지 않도록 격리한다.
            bootstrap = (
                "import sys\n"
                "sys.path.insert(0, '.')\n"
                "from pipeline.serverless_batch import prepare, worker, finalize"
            )
            subprocess.run([sys.executable, "-I", "-c", bootstrap], cwd=runtime, check=True)
