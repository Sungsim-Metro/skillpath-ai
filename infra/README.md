# SkillPath 서버리스 배포와 복구

| 단계 | 스택 | 실제 호출 경로 | 기존 데이터 |
| --- | --- | --- | --- |
| 1 | 수요·Gap | Streamlit → Lambda → DynamoDB | 공개된 직무별 수요 스냅샷 읽기 |
| 2 | 공고 전처리 | 운영자 → Step Functions Standard → 준비·처리·집계 Lambda | 승인한 S3 공고 읽기, 격리된 추출 행 작성, 완성된 집계 공개 |
| 3 | 과정 추천 | Streamlit → Lambda → Bedrock Knowledge Bases와 모델 | 수요 조회, 과정 검색, 추천 이유 작성·검토 |

각 단계는 별도 CloudFormation 스택으로 배포한다. 앱의 상담 순서, 프로필 인증 및 기록 저장은 Streamlit 프로세스에서 실행한다. 버킷, 테이블, 교육과정 Knowledge Base는 기존 프로젝트 리소스를 사용한다.

## 공통 준비

로컬 배포 호스트에서 저장소 루트로 이동해 Bash를 연다. 아래 명령은 같은 Bash 세션에서 순서대로 실행한다. AWS CLI v2, jq, uv, Python 3.11이 필요하다. 운영 앱이 사용하는 역할에 호출 권한을 연결하려면 첫 배포 전에 `APP_ROLE_NAME`에 실제 IAM 역할 이름을 지정한다. 새 스택에서 생략하면 전용 호출 정책만 만들어지며 스택 출력 `InvokePolicyArn`에서 찾을 수 있다.

```bash
set -euo pipefail
export AWS_PROFILE=kosa AWS_DEFAULT_REGION=ap-northeast-2 AWS_REGION=ap-northeast-2
export AWS_PAGER=""
KB_STACK=skillpath-learning-programs-kb
DEMAND_STACK=skillpath-demand-tool
BATCH_STACK=skillpath-preprocessing
RECOMMEND_STACK=skillpath-recommend-tool
BUILD_DIR=$(mktemp -d)

stack_output() {
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text
}

ARTIFACT_BUCKET=$(aws cloudformation describe-stacks --stack-name "$KB_STACK" \
  --query "Stacks[0].Parameters[?ParameterKey=='DocumentBucket'].ParameterValue | [0]" --output text)
KB_ID=$(stack_output "$KB_STACK" KnowledgeBaseId)
test "$ARTIFACT_BUCKET" != None && test "$KB_ID" != None
export ROCKETPUNCH_S3_BUCKET="$ARTIFACT_BUCKET"
export DYNAMODB_DEMAND_TABLE=skillpath-demand
export DYNAMODB_EXTRACTIONS_TABLE=skillpath-posting-extractions
export BEDROCK_MOCK=0
export BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
HAIKU_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
DEPLOY_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

global_model_arns() {
  local id="$1" model="${1#global.}"
  printf '%s,%s,%s' \
    "arn:aws:bedrock:$AWS_REGION:$DEPLOY_ACCOUNT:inference-profile/$id" \
    "arn:aws:bedrock:$AWS_REGION::foundation-model/$model" \
    "arn:aws:bedrock:::foundation-model/$model"
}
SONNET_ARNS=$(global_model_arns "$BEDROCK_MODEL_ID")
RECOMMEND_ARNS="$SONNET_ARNS,$(global_model_arns "$HAIKU_ID")"

app_role=()
if [[ -n "${APP_ROLE_NAME:-}" ]]; then
  app_role=("AppRoleName=$APP_ROLE_NAME")
fi

package_and_upload() {
  local stage="$1" digest key
  digest=$(uv run --python 3.11 python infra/package_lambda.py "$stage" "$BUILD_DIR/$stage.zip") || return 1
  key="skillpath/releases/lambda/$stage/$digest.zip"
  aws s3 cp "$BUILD_DIR/$stage.zip" "s3://$ARTIFACT_BUCKET/$key" --only-show-errors || return 1
  printf '%s\n' "$key"
}
```

위 함수는 ZIP 내용의 SHA-256을 키에 넣는다. 배포 전후의 `ArtifactKey`를 기록하면 같은 ZIP을 다시 지정해 해당 코드로 돌아갈 수 있다. 모델 권한은 글로벌 추론 프로필·서울 기반 모델·글로벌 기반 모델의 정확한 ARN을 지정한다. 배치는 Sonnet만 사용하며, 추천은 앱이 턴마다 선택할 수 있는 Haiku도 허용한다. [Bedrock 글로벌 추론 IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)

## 1. 수요·Gap 배포

```bash
DEMAND_KEY=$(package_and_upload demand)
aws cloudformation deploy --stack-name "$DEMAND_STACK" \
  --template-file infra/templates/demand-tool.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides "ArtifactBucket=$ARTIFACT_BUCKET" "ArtifactKey=$DEMAND_KEY" \
    "DemandTable=$DYNAMODB_DEMAND_TABLE" "ExtractionsTable=$DYNAMODB_EXTRACTIONS_TABLE" "${app_role[@]}"
DEMAND_ARN=$(stack_output "$DEMAND_STACK" FunctionArn)
aws lambda invoke --function-name "$DEMAND_ARN" --cli-binary-format raw-in-base64-out \
  --payload '{"operation":"get_demand","arguments":{"job_category":"cloud_engineer"}}' \
  "$BUILD_DIR/demand-response.json"
jq -e '.error == null and (.result.total_postings > 0)' "$BUILD_DIR/demand-response.json"
```

Lambda가 수요와 Gap 모두에서 사용하는 DynamoDB 권한은 수요 테이블의 `GetItem`이다. IAM 호출 권한과 앱 코드 버전을 확인한 뒤, 앱 서비스의 환경에 `SKILLPATH_DEMAND_FUNCTION`을 출력된 `FunctionArn` 또는 기본값 `skillpath-demand-tool`로 지정한다.

## 2. 공고 처리와 공개 검증

```bash
BATCH_KEY=$(package_and_upload preprocessing)
aws cloudformation deploy --stack-name "$BATCH_STACK" \
  --template-file infra/templates/preprocessing.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides "ArtifactBucket=$ARTIFACT_BUCKET" "ArtifactKey=$BATCH_KEY" \
    "DataBucket=$ROCKETPUNCH_S3_BUCKET" "DemandTable=$DYNAMODB_DEMAND_TABLE" \
    "ExtractionsTable=$DYNAMODB_EXTRACTIONS_TABLE" "ModelId=$BEDROCK_MODEL_ID" \
    "ModelResources=$SONNET_ARNS"
WORKFLOW_ARN=$(stack_output "$BATCH_STACK" StateMachineArn)

run_batch() {
  local input="$1" execution state
  execution=$(aws stepfunctions start-execution --state-machine-arn "$WORKFLOW_ARN" \
    --input "file://$input" --query executionArn --output text) || return 1
  printf 'Execution ARN %s\n' "$execution"
  while true; do
    state=$(aws stepfunctions describe-execution --execution-arn "$execution" \
      --query status --output text) || return 1
    case "$state" in
      SUCCEEDED) aws stepfunctions describe-execution --execution-arn "$execution" --query output --output text; return ;;
      RUNNING) sleep 5 ;;
      *) printf '%s\n' "$state" >&2; return 1 ;;
    esac
  done
}

for job in cloud_engineer ai_engineer; do
  uv run --python 3.11 --with-requirements requirements.txt python -m pipeline.batch_manifest \
    --job-category "$job" --upload > "$BUILD_DIR/verify-$job.json"
  jq -e '.verify_only == true' "$BUILD_DIR/verify-$job.json"
  run_batch "$BUILD_DIR/verify-$job.json"
done
```

이 명령은 현재 공개된 직무별 공고 목록을 복원해 원본 해시, 추출 지문 및 집계가 일치하는지 검증한다. `--upload`는 검증용 불변 매니페스트 한 개를 S3에 저장한다. 상태 머신에서 `verify_only=true`이면 Bedrock 호출과 DynamoDB 쓰기가 모두 0이고, 성공 출력은 `verified=true`, `published=false`다. 워커는 공고 4건씩 최대 두 묶음을 병렬 처리한다.

새 집계를 공개할 때는 **해당 직무 전체**의 검토된 공고 S3 키 목록(JSON 배열), 수집 기간, 선정 버전을 준비한다. 공고 하나만 추가할 때도 전체 목록에 그 키를 포함한다. 제외 사유가 있으면 `--exclusions`에 공고 ID를 사유로 매핑한 JSON 파일을 준다. 아래 명령은 입력이 검토된 뒤 운영자가 발행할 때 실행한다.

```bash
: "${REVIEWED_KEYS:?Set REVIEWED_KEYS to a JSON file containing all approved keys for this job}"
: "${COLLECTED_PERIOD:?Set COLLECTED_PERIOD to the actual collection period}"
: "${SELECTION_VERSION:?Set SELECTION_VERSION to the reviewed selection version}"
uv run --python 3.11 --with-requirements requirements.txt python -m pipeline.batch_manifest \
  --job-category cloud_engineer --reviewed-keys "$REVIEWED_KEYS" \
  --collected "$COLLECTED_PERIOD" --selection-version "$SELECTION_VERSION" \
  --output "$BUILD_DIR/reviewed-manifest.json" --upload > "$BUILD_DIR/publish.json"
jq -e '.verify_only == false' "$BUILD_DIR/publish.json"
run_batch "$BUILD_DIR/publish.json"
```

매니페스트 CLI에서 `--upload`를 생략하면 원본 검증과 로컬 출력만 수행한다. 발행 실행은 입력 지문이 달라진 공고에서 모델을 호출하고 실행별 DynamoDB 파티션에 추출 결과를 적재한다. 마지막 단계에서 전체 결과와 `expected_base_snapshot`을 확인하고 공개 포인터를 교체한다. 실패한 실행과 같은 입력을 재시도하면 이미 준비한 추출을 재사용한다. 다른 배치가 먼저 공개해 기준 스냅샷이 바뀌었으면 두 입력의 차이를 확인한 뒤 새 기준에서 매니페스트를 생성한다.

## 3. 과정 검색·추천 배포

```bash
RECOMMEND_KEY=$(package_and_upload recommend)
aws cloudformation deploy --stack-name "$RECOMMEND_STACK" \
  --template-file infra/templates/recommend-tool.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides "ArtifactBucket=$ARTIFACT_BUCKET" "ArtifactKey=$RECOMMEND_KEY" \
    "DemandTable=$DYNAMODB_DEMAND_TABLE" "ExtractionsTable=$DYNAMODB_EXTRACTIONS_TABLE" \
    "KnowledgeBaseId=$KB_ID" "ModelId=$BEDROCK_MODEL_ID" "ModelResources=$RECOMMEND_ARNS" "${app_role[@]}"
RECOMMEND_ARN=$(stack_output "$RECOMMEND_STACK" FunctionArn)
aws lambda invoke --function-name "$RECOMMEND_ARN" --cli-read-timeout 320 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation":"get_recommendations","arguments":{"job_category":"cloud_engineer","gap_skills":["EC2"],"review":true}}' \
  "$BUILD_DIR/recommend-response.json"
jq -e '.error == null and ([.result[]?.courses[]?] | length > 0)' "$BUILD_DIR/recommend-response.json"
```

위 추천 점검은 실제 KB를 조회하고, 캐시에 없는 추천은 모델 사용료가 발생한다. 함수 응답의 `usage`에는 모델 호출별 단계·모델·토큰이 포함된다. 앱은 이를 현재 상담의 사용량 집계에 반영한다. `SKILLPATH_RECOMMEND_FUNCTION`에는 스택 출력 `FunctionArn` 또는 기본값 `skillpath-recommend-tool`을 지정한다.

## 앱 연결과 복구

1. **실행 중인 앱 버전 확인.** 운영 Streamlit이 실행하는 체크아웃에 `backend/lambda_tools.py`와 변경된 `backend/api.py`, `backend/experiments.py`, `ai/usage.py`가 포함되어야 한다. 이전 버전은 새 환경 변수를 설정해도 로컬 함수를 호출한다. 스택 배포와 앱 환경 변경은 독립 작업이다.
2. **단계별 전환.** 실제 모드(`BEDROCK_MOCK=0`)인 앱의 서비스 환경에 해당 단계의 함수 이름을 설정하고 서비스 관리 방식으로 반영한다. 셸에서만 `export`해도 이미 실행 중인 서비스는 기존 환경으로 계속 동작한다. 수요 질의와 추천 질의를 각각 한 번 보내고 Lambda 호출 지표 증가, 앱 출력, 사용량 기록을 확인한다. 서비스 재시작 시 메모리의 비회원 세션은 초기화된다.
3. **채팅 도구 복구.** 문제가 생긴 단계의 환경 변수(`SKILLPATH_DEMAND_FUNCTION` 또는 `SKILLPATH_RECOMMEND_FUNCTION`)를 서비스 설정에서 비우고 같은 방식으로 반영한다. 앱이 기존 로컬 호출 경로를 사용한다. 로컬 경로에 필요한 기존 앱 역할의 권한을 유지한다. 코드 회귀라면 해당 스택 배포 명령에 보관한 이전 `ArtifactKey`를 넣어 재배포한다.
4. **배치 복구.** 미완료 실행은 공개 스냅샷을 바꾸지 않는다. 잘못된 목록이 이미 공개되었으면 복구 대상이 되는 기존 공고 키·수집 기간·선정 규칙을 검토한 뒤, 현재 스냅샷을 기준으로 해당 목록을 새 배치로 공개한다. 재발행으로 기준 버전을 바꾸는 작업과 단순 검증을 구분한다.

## 비용과 보관

- 수요는 Lambda 실행과 DynamoDB 읽기, 추천은 추가로 KB 검색과 Bedrock 모델 호출을 사용한다. Standard 배치는 재시도를 포함한 상태 전환 수, Lambda 요청 및 실행 시간, 원본 S3 접근과 DynamoDB 사용량이 과금 기준이다. 실제 요청 수, 사용한 모델, 서울 리전 단가로 계산한다. [Lambda 요금](https://aws.amazon.com/lambda/pricing/) · [Step Functions 요금](https://aws.amazon.com/step-functions/pricing/) · [Bedrock 요금](https://aws.amazon.com/bedrock/pricing/)
- 함수별 CloudWatch 로그는 14일 보관한다. 스택이 생성하는 리소스와 기존 KB·고객 데이터의 생명주기는 별개다. ZIP, 매니페스트, 실행별 추출 행은 운영 버킷과 테이블에 남는다. 정리를 검토할 때 현재 공개 파티션, 진행 중인 실행, 롤백에 사용할 ZIP·공고 키를 우선 식별한다. 리소스 사용을 중단하려면 앱 라우팅과 신규 배치 시작을 먼저 중단한다.
