# 화면 배포 (사용자 테스트용)

Streamlit 화면을 서버 한 대(EC2)에 실제 모드(`BEDROCK_MOCK=0`)로 띄우는 가장 단순한 절차다.
새 AWS 서비스는 쓰지 않는다. 서버 1대, 인스턴스 역할 1개, 고정 IP 1개가 전부다.

| 파일 | 쓰임 |
| --- | --- |
| `check_aws.py` | 서버에서 AWS 설정이 맞는지 미리 본다 (`python -m deploy.check_aws`) |
| `skillpath.service` | 서버가 켜지면 화면을 자동으로 띄우는 systemd 단위 |
| `Caddyfile` | HTTPS 주소로 여는 프록시 설정 |
| `iam-app-policy.json` | 화면 서버(인스턴스 역할)에 줄 최소 권한 틀 |
| `iam-batch-policy.json` | 공고 일괄 처리(`pipeline.extraction_batch`)를 돌리는 사람에게 줄 최소 권한 틀 |

정책 파일의 `ACCOUNT_ID`, 테이블·버킷·모델 이름은 자리 표시다. 콘솔에 붙여 넣을 때 바꾸고, 바꾼 파일은 커밋하지 않는다.

## 미리 되어 있어야 하는 것

1. 수요 집계가 DynamoDB 에 있다. 화면은 집계 테이블 한 항목을 읽기만 한다.
   없으면 개발 PC 에서 `python -m backend.dynamodb create-tables` 뒤 `python -m pipeline.extraction_batch --collected <수집일>` 을 먼저 돌린다.
2. 팀 계정에서 `BEDROCK_MODEL_ID` 로 쓸 모델이 호출된다(콘솔의 Bedrock 플레이그라운드에서 한 번 불러 본다).

## 절차

1. **서버 만들기.** EC2 콘솔에서 Ubuntu 24.04 인스턴스 1대(리전 서울). 보안 그룹 인바운드는 80, 443 을 모든 곳에,
   22 는 내 IP 에만 연다. 탄력적 IP 를 하나 받아 인스턴스에 붙인다(재시작해도 주소가 그대로다).
2. **역할 붙이기.** IAM 에서 EC2 용 역할을 만들고 `iam-app-policy.json` 내용을 인라인 정책으로 넣은 뒤 인스턴스에 연결한다.
   서버에 액세스 키를 두지 않는다. boto3 가 역할의 임시 자격 증명을 알아서 쓴다.
3. **코드 받기.**
   ```bash
   sudo apt update && sudo apt install -y python3-venv git
   git clone <저장소 주소> skillpath-ai && cd skillpath-ai
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
4. **`.env` 쓰기.** `cp .env.example .env` 뒤 아래처럼 고친다.
   ```
   AWS_REGION=ap-northeast-2
   BEDROCK_MOCK=0
   BEDROCK_MODEL_ID=<팀 계정에서 호출되는 모델 또는 추론 프로필 ID>
   DYNAMODB_DEMAND_TABLE=<수요 집계 테이블 이름>
   ```
   **`AWS_PROFILE=kosa` 줄은 지운다.** 서버에는 그 프로필이 없어 모든 AWS 호출이 `ProfileNotFound` 로 실패한다.
   화면 서버에는 `DYNAMODB_EXTRACTIONS_TABLE`, `ROCKETPUNCH_*` 가 필요 없다.
5. **사전 점검.** `.venv/bin/python -m deploy.check_aws --recommend`
   세 줄(환경 변수, DynamoDB, Bedrock)과 추천 1건이 모두 `[통과]` 여야 한다. 실패하면 아래 "안 될 때"를 본다.
6. **서비스로 띄우기.**
   ```bash
   sudo cp deploy/skillpath.service /etc/systemd/system/ && sudo systemctl daemon-reload
   sudo systemctl enable --now skillpath && systemctl status skillpath --no-pager
   ```
   로그는 `journalctl -u skillpath -f`.
7. **주소 연결.** 도메인 관리 화면에서 하위 주소의 A 레코드를 탄력적 IP 로 넣는다. 그다음
   ```bash
   sudo apt install -y caddy
   sudo cp deploy/Caddyfile /etc/caddy/Caddyfile   # 주소를 실제 하위 주소로 고친 뒤
   sudo systemctl restart caddy
   ```
   Streamlit 은 `127.0.0.1:8501` 에만 열려 있고 바깥에서는 Caddy(443)로만 들어온다.
8. **캐시 데우기.** 테스트 시작 전에 주소를 한 번 열어 학습 추천 탭에 과정이 뜨는지 본다.
   추천은 처음 한 번만 Bedrock 을 부르고 그 뒤로는 서버 메모리의 결과를 쓴다. 미리 열어 두지 않으면
   참가자들이 동시에 처음 여는 순간 같은 추천을 사람 수만큼 한꺼번에 요청한다.

## 테스트 당일 점검표

- 폰(LTE)으로 주소를 열어 탭이 모두 뜨는지 본다. 화면이 "Please wait..." 에서 멈추면 웹소켓이 막힌 것이다(프록시 설정을 본다).
- `journalctl -u skillpath -f` 를 켜 둔다. 화면에 "불러오지 못했습니다(…)"가 나오면 괄호 안이 오류 종류다.
- 테스트가 끝나면 인스턴스를 중지한다. 탄력적 IP 는 인스턴스가 꺼져 있어도 요금이 붙으니 발표가 끝나면 반납한다.

## 재시작하면 사라지는 것

| 무엇 | 어디에 있나 | 재시작하면 |
| --- | --- | --- |
| 추천 캐시 | 프로세스 메모리(`backend/api.py`) | 사라진다. 8번을 다시 한다 |
| 수요 집계 캐시 | 프로세스 메모리, 60초 | 사라진다. 다음 요청에서 DynamoDB 를 다시 읽는다 |
| 사용자가 고른 기술, 분석한 공고 | 브라우저 연결별 세션 | 사라진다. 참가자는 새로 고르게 된다 |
| 호출 기록(토큰·비용 화면을 쓰는 경우) | 서버 디스크 `outputs/usage/usage.jsonl` | 남는다. 인스턴스를 새로 만들면 없다 |

프로세스를 둘 이상 띄우거나 서버를 여러 대로 늘리면 캐시와 호출 기록이 프로세스마다 따로 생긴다. 이번 규모에서는 한 프로세스로 둔다.

## 안 될 때

| 화면이나 점검에 나온 종류 | 원인 | 할 일 |
| --- | --- | --- |
| `ProfileNotFound` | `.env` 에 `AWS_PROFILE` 이 남아 있다 | 그 줄을 지우고 `sudo systemctl restart skillpath` |
| `NoCredentialsError` | 인스턴스에 역할이 붙지 않았다 | EC2 콘솔 → 작업 → 보안 → IAM 역할 수정 |
| `AccessDeniedException` | 역할 정책의 테이블·모델 이름이 실제와 다르다. 모델 사용 신청이 안 된 경우도 같다 | 정책의 Resource 와 Bedrock 콘솔의 모델 사용 상태를 확인 |
| `ResourceNotFoundException` | 테이블 이름이나 리전이 다르다 | `.env` 의 `DYNAMODB_DEMAND_TABLE`, `AWS_REGION` |
| `ValidationException` | 모델 ID 가 이 리전에서 그대로는 호출되지 않는다(추론 프로필 ID 가 필요한 모델 등) | Bedrock 콘솔에서 그 모델의 호출 ID 를 확인해 `BEDROCK_MODEL_ID` 를 고친다 |
| `ThrottlingException` | 분당 호출 한도에 걸렸다 | 잠시 뒤 다시 시도. 반복되면 Service Quotas 에서 그 모델의 분당 요청 수를 확인 |
| `LookupError` | 수요 집계 항목이 없다 | "미리 되어 있어야 하는 것" 1번 |

## 비용을 어림하는 틀

단가는 여기 적지 않는다. AWS 요금 페이지에서 쓰는 모델의 입력·출력 토큰 단가를 확인해 넣는다.

```
Bedrock 비용 ≈ 호출 수 × (호출당 입력 토큰 × 입력 단가 + 호출당 출력 토큰 × 출력 단가)
호출 수     ≈ 서로 다른 (부족 기술 상위 3개 조합) 수 × 3 × (검증을 켜면 2~3)
              + 커피챗 초안 버튼 누른 횟수 + 공고 직접 분석 버튼 누른 횟수
```

호출당 토큰은 추측하지 말고 서버 로그의 `Bedrock 호출 … 입력=… 출력=… 토큰` 줄이나 토큰·비용 화면에서 읽는다.
서버(EC2)와 고정 IP 는 켜 둔 시간만큼, DynamoDB 는 읽은 횟수만큼(화면은 60초에 최대 한 번) 든다.

## 확인한 것과 확인하지 못한 것

- 확인: `skillpath.service` 의 Streamlit 실행 옵션으로 서버가 뜨고 `/_stcore/health` 가 200, `/_stcore/stream` 이 웹소켓으로 바뀌는 것(가짜 모드, 로컬).
  `AWS_PROFILE` 이 남아 있을 때 boto3 가 `ProfileNotFound` 를 내는 것. `check_aws.py` 의 실제 모드 분기(가짜 boto3 테스트).
- 확인하지 못함: 실제 EC2·Caddy·도메인에서의 동작, 팀 계정의 모델 호출 한도, 정책 틀이 팀이 쓰는 모델 ID 형식과 맞는지.
  처음 띄울 때 5번 사전 점검으로 확인한다.
