# AgentCollab Public Installer

AgentCollab Public Installer는 AgentCollab을 설치하고 검증하기 위한 공개 설치 진입점입니다. 설치기는 인증된 배포 카탈로그에서 선택한 버전을 확인한 뒤, 해당 버전의 설치 계획을 만듭니다.

## 저장소 역할

- **Public** — 범용 설치기와 설치 프로토콜을 제공합니다.
- **Distribution** — 인증이 필요한 불변 버전 기록과 Runtime/Execution 패키지를 관리합니다.
- **Source** — 제품 소스 코드와 패키지 출처를 관리합니다.

## 시작하기

설치는 현재 **Linux 환경**을 대상으로 합니다. 검증된 배포판/버전 범위가 문서화되어 있지 않으므로 특정 배포판 버전이나 native Windows, WSL2, macOS 지원을 보장하지 않습니다. 설치에는 Git, Python 3, GitHub CLI(`gh`), `jq`, Codex CLI와 로그인, Codex sandbox/AppArmor readiness, Antigravity CLI(`agy`), systemd user service가 동작하는 로그인 세션, 그리고 APPLY 중 비밀값을 입력할 수 있는 interactive terminal이 필요합니다. Codex/Antigravity runner 실행 환경에도 해당 CLI가 PATH에 있어야 합니다. 준비 사항과 제한은 [설치 안내](INSTALL.md#사전-준비)를 확인하세요.

브라우저는 설치에는 필요하지 않지만 설치 후 Web UI를 열 때 필요합니다. Web과 기본 runner service는 사용자 계정의 systemd service로 설정합니다. 일부 host prerequisite가 부족하면 PLAN이 관리자 권한이 필요한 조치를 별도로 표시할 수 있습니다. GitHub CLI 계정은 Public/Distribution의 private catalog를 읽고, 설치 대상 개인 Execution repository와 Actions 설정을 수행할 권한이 있어야 합니다. 실제 필요 권한은 PLAN이 확인하며, 부족한 권한은 표시된 조치를 완료한 뒤 PLAN을 다시 실행하세요.

```sh
PUBLIC_OWNER="${AGENTCOLLAB_GITHUB_OWNER:-AgentCollab}"
gh auth login
gh auth status
gh repo clone "$PUBLIC_OWNER/AgentCollab-Public"
cd AgentCollab-Public
./install.sh install
```

일반 설치는 `install` 한 번으로 진행합니다. 설치기가 먼저 PLAN과 요약을 표시하고, 사용자가 `yes`로 확인한 경우에만 APPLY한 뒤 자동 VERIFY를 실행합니다. VERIFY가 `READY`일 때 Web URL과 첫 TASK 안내를 출력합니다. 브라우저 열기는 로컬 그래픽 세션에서만 best-effort로 시도하며, `--no-open-browser`로 끌 수 있습니다.

PLAN/APPLY/VERIFY를 각각 확인하는 고급 절차는 [설치 안내](INSTALL.md#고급-설치-계획적용검증)를 참고하세요.

Set `AGENTCOLLAB_GITHUB_OWNER` to the organization that owns the environment's Public and Distribution repositories. The default is the production organization.

The installer checkout and installed product are separate sibling directories:

```text
<workspace>/
├─ AgentCollab-Public/  # installer checkout; safe to update or reclone
└─ agentcollab/         # installed product authority
   ├─ RUN/              # Runtime and persistent DATA
   └─ runner/           # managed self-hosted runner
```

By default, PLAN/APPLY/VERIFY use `<parent-of-Public-checkout>/agentcollab`, regardless of the shell's current directory. Use the same `--installation-root` and, if supplied, `--runner-root` on every phase to override those paths. The installation root contains Runtime, DATA, and the runner; deleting it is not an installer cleanup or uninstall operation.

설치 계획을 검토한 다음 적용하고 검증하는 자세한 절차는 [INSTALL.md](INSTALL.md)를 참고하세요.

설치기는 저장소, 버전, 패키지 출처 또는 권한을 확인할 수 없으면 진행을 차단합니다. 차단을 우회하거나 다른 버전으로 자동 전환하지 않습니다.

설치 후 PLAN/VERIFY에서 확인한 Web port를 사용해 `http://127.0.0.1:<Web port>/`를 브라우저에서 여세요. 기본 화면은 일반 사용자 모드입니다. Web UI의 **New Task**에서 요청을 입력하고 **Hand off task**를 선택해 첫 TASK를 등록한 뒤 readiness를 확인하세요. 준비가 완료되면 화면의 안내에 따라 시작할 수 있습니다. 관리자 작업이 필요한 경우에만 설치 중 정한 Web 관리자 비밀번호를 화면의 관리자 전환 입력란에 입력하세요. 자세한 운영·복구 절차는 [문제 해결 및 운영](TROUBLESHOOTING.md)을 참고하세요.

현재 버전은 설치기의 PLAN/VERIFY 결과에 표시됩니다. 공개 설치기 문의는 [GitHub Issues](https://github.com/AgentCollab/AgentCollab-Public/issues), 설치기 릴리스는 [GitHub Releases](https://github.com/AgentCollab/AgentCollab-Public/releases)를 이용하세요. 설치 관련 Issue에는 비밀값이나 credential이 포함된 로그를 올리지 마세요.
