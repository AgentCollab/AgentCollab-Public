# AgentCollab Public Installer

AgentCollab Public Installer는 AgentCollab을 설치하고 검증하기 위한 공개 설치 진입점입니다. 설치기는 인증된 배포 카탈로그에서 선택한 버전을 확인한 뒤, 해당 버전의 설치 계획을 만듭니다.

## 저장소 역할

- **Public** — 범용 설치기와 설치 프로토콜을 제공합니다.
- **Distribution** — 인증이 필요한 불변 버전 기록과 Runtime/Execution 패키지를 관리합니다.
- **Source** — 제품 소스 코드와 패키지 출처를 관리합니다.

## 시작하기

Git과 GitHub CLI(`gh`)가 필요합니다. GitHub CLI에서 로그인한 계정은 비공개 Distribution 저장소를 읽을 수 있어야 합니다.

```sh
PUBLIC_OWNER="${AGENTCOLLAB_GITHUB_OWNER:-AgentCollab}"
gh repo clone "$PUBLIC_OWNER/AgentCollab-Public"
cd AgentCollab-Public
gh auth login
./install.sh plan
```

Set `AGENTCOLLAB_GITHUB_OWNER` to the organization that owns the environment's Public and Distribution repositories. The default is the production organization.

설치 계획을 검토한 다음 적용하고 검증하는 자세한 절차는 [INSTALL.md](INSTALL.md)를 참고하세요.

설치기는 저장소, 버전, 패키지 출처 또는 권한을 확인할 수 없으면 진행을 차단합니다. 차단을 우회하거나 다른 버전으로 자동 전환하지 않습니다.
