# AgentCollab 개인 사용자 설치 (Beta)

이 공개 beta 경로는 설치 문서와 검증된 bootstrap만 제공합니다. Runtime/Execution 패키지는 private `AgentCollab/AgentCollab-Distribution` 저장소에서 인증된 GitHub CLI를 통해 받습니다.

## 시작

```sh
gh auth login
/path/to/install.sh plan
```

GitHub 계정에 private Distribution 접근 권한이 있어야 합니다. 권한이 없으면 소유자에게 접근을 요청한 뒤 다시 실행하세요. 토큰을 명령행에 붙여 넣거나 저장할 필요가 없습니다. 설치 기본 위치는 실행한 현재 디렉터리의 `./agentcollab`이며 `--installation-root <path>`로 바꿀 수 있습니다.

PLAN은 패키지 provenance와 SHA-256을 검증한 후 setup engine에 연결됩니다. 계획을 검토한 뒤에만 APPLY를 실행하고, 완료 후 VERIFY를 실행하세요. Public metadata candidate identity는 `v0.2.0-beta.2`이며 기존 private package release `v0.2.0-beta.1`을 사용합니다.
