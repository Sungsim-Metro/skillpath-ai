공고·NCS·교육과정 수집, 전처리, 별칭 사전, 임베딩 검색. (담당: 종훈)

## 채용공고 수집과 S3 보관

`rocketpunch.py`는 로켓펀치 API 응답을 먼저 로컬 `data/raw/`에 저장한다.
`ROCKETPUNCH_S3_BUCKET`을 설정하면 `search`, `fetch`, `collect` 실행 중에도 S3에 자동 업로드한다.
버킷을 설정하지 않으면 기존처럼 로컬에만 저장한다. AWS 인증은 `AWS_PROFILE` 등 SDK 기본 설정을 따른다.
계정·버킷 이름과 API 키는 코드에 넣지 않고, 저장소에서 제외된 루트 `.env`에 설정한다.

```dotenv
AWS_PROFILE=<your-profile>
AWS_REGION=ap-northeast-2
ROCKETPUNCH_API_KEY=<your-api-key>
ROCKETPUNCH_S3_BUCKET=<your-bucket>
ROCKETPUNCH_S3_PREFIX=skillpath/rocketpunch
```

S3 경로는 다음과 같다. S3의 디렉터리는 객체 키의 접두사다.

```text
<prefix>/
  raw/lists/list-<검색조건>/<내용의 SHA-256>.json
  raw/details/rp-<공고ID>/<내용의 SHA-256>.json
  processed/postings/rp-<공고ID>/<내용의 SHA-256>.json
```

- `raw/lists`: 채용공고 목록 API 응답. 새로 수집한 목록은 `items`, `totalItems`, `totalPages` 등 응답 전체를 보존한다.
- `raw/details`: 공고별 상세 API 응답. AWS 키워드 필터에서 탈락한 공고도 원본은 보관한다.
- `processed/postings`: 필터를 통과해 `contracts/`의 공고 형식으로 변환한 결과.
- 같은 파일 내용은 같은 키를 사용해 중복 저장하지 않는다. 내용이 달라지면 새 객체로 남기므로 이전 근거를 재현할 수 있다.
  [S3 조건부 PUT](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html)으로 기존 객체 덮어쓰기를 막는다.
- JSON은 줄바꿈을 `\n`으로 고정해 저장한다. 키가 파일 바이트의 해시라서, OS 기본 줄바꿈에 맡기면 Windows에서 저장한 파일만 다른 키가 된다.
  고정하기 전에 Windows에서 저장한 파일은 CRLF 그대로다. 전처리 공고는 `fetch`나 `collect`를 다시 실행하면 `\n`으로 다시 저장되어 새 키로 올라가고,
  목록·상세 원본은 다시 쓰지 않으므로 기존 키를 그대로 쓴다.
- 기존 로컬 파일은 이동하거나 삭제하지 않는다. 캐시를 읽을 때도 S3 업로드를 시도하므로 이전 업로드 실패를 재시도할 수 있다.
- S3 실패 시 로컬 파일을 남기고 오류를 보고한다. 같은 명령이나 `upload` 명령으로 다시 시도한다.
- 예전에 저장한 목록 7개는 `items` 배열만 남아 있다. 그대로 보관하고 호환해서 읽으며, 없어진 총 건수·총 페이지 수는 추정하지 않는다.

### 기존 파일 업로드

다음 명령은 API를 다시 호출하지 않는다. `.env`가 없으면 `--bucket <your-bucket>`과 `AWS_PROFILE` 환경변수로도 지정할 수 있다.

```powershell
uv run --python 3.11 --with boto3 python -m pipeline.rocketpunch upload --dry-run
uv run --python 3.11 --with boto3 python -m pipeline.rocketpunch upload
```

대상은 `data/raw/` 바로 아래의 `list-*.json`, `rp-*.raw.json`, `rp-*.posting.json`이다.
`data/raw/courses/`의 교육과정 파일은 이 명령의 대상이 아니다.

### 이후 수집

```powershell
uv run --python 3.11 --with boto3 python -m pipeline.rocketpunch search -k DevOps --codes dev
uv run --python 3.11 --with boto3 python -m pipeline.rocketpunch collect -k DevOps --codes dev -n 10
```

기존 캐시는 API를 다시 호출하지 않는다. 새 공고 응답을 가져오면 로컬 저장 후 S3에도 보관한다.
현재는 수집기를 실행할 때 동작하며 자동 실행 스케줄이나 S3에서 분석기로 이어지는 처리는 포함하지 않는다.

### 저장 경로 검증

```powershell
uv run --python 3.11 --with boto3 python -m unittest pipeline.test_storage pipeline.test_rocketpunch_storage
uv run --python 3.11 --with boto3 python -m pipeline.test_rocketpunch
```

단위 테스트는 임시 파일과 모의 S3를 사용하며 실제 API나 AWS를 호출하지 않는다.
