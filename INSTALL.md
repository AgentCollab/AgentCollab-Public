# 설치 안내 (v0.2.0-beta.1 Beta)

1. GitHub CLI를 설치하고 `gh auth login`으로 인증합니다.
2. 계정이 private `lkhkhk/AgentCollab-Distribution` 저장소에 접근할 수 있는지 확인합니다. 접근 권한이 없으면 저장소 소유자에게 요청하세요.
3. 원하는 디렉터리로 이동하고 `install.sh plan`을 실행합니다. 기본 설치 위치는 현재 디렉터리의 `./agentcollab`입니다. `--installation-root <path>`를 지정하면 해당 경로를 사용합니다.
4. 출력된 계획과 필요한 prerequisite를 검토합니다. 설치 진행 시 `install.sh apply --approved-plan-sha256 <PLAN_SHA256>`을 실행합니다.
5. 설치 후 `install.sh verify`를 실행합니다.

Private package 접근은 `gh`의 기존 인증을 사용합니다. PAT를 복사해 넣거나 비밀번호를 자동 전달하지 않습니다. PLAN은 Runtime/Execution ZIP의 전체 SHA-256, release provenance, 상호 호환성, packaged `deploy/setup.py` digest를 확인한 뒤 setup engine을 실행합니다. 다운로드/검증 자료는 임시 디렉터리에서 처리하고 종료 시 정리합니다.
