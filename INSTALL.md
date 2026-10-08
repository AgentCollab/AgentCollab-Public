# AgentCollab 설치 안내

이 문서는 Public 설치기를 사용해 AgentCollab 설치를 계획하고 적용하는 방법을 설명합니다. 명령은 Public 저장소의 `install.sh`를 실행하는 예입니다.

## 사전 준비

- 현재 설치 경로는 Linux를 대상으로 합니다. 문서화된 테스트 배포판/버전 목록은 없습니다. native Windows, WSL2, macOS와 특정 Linux 배포판/버전의 지원은 확인되지 않았으므로 지원된다고 가정하지 마세요.
- `git`, Python 3, GitHub CLI(`gh`), `jq`, Codex CLI, Antigravity CLI(`agy`), systemd user service가 동작하는 사용자 로그인 세션이 필요합니다. Codex CLI 로그인, sandbox 및 AppArmor readiness도 필요합니다. `agy`, Codex, `jq`는 interactive shell뿐 아니라 runner job PATH에서도 실행 가능해야 합니다.
- PLAN/APPLY/VERIFY를 같은 사용자로 실행하고 APPLY에는 interactive terminal을 사용하세요. Web과 기본 runner service는 사용자 계정의 systemd service로 설정합니다. 일부 host prerequisite가 부족하면 PLAN이 별도의 관리자 조치를 표시할 수 있습니다. Web UI를 사용할 때 브라우저가 필요합니다.
- GitHub CLI에서 `gh auth login`으로 인증하세요. 인증 계정은 Public 저장소와 installer manifest가 지정하는 private Distribution 저장소를 읽을 수 있어야 합니다. 또한 PLAN에서 표시되는 개인 Execution repository와 Actions 변경을 수행할 권한이 필요합니다.
- 설치기는 Distribution 카탈로그와 선택된 릴리스 자산을 인증된 방식으로 읽습니다. PLAN은 현재 인증 권한을 검사하고 필요한 경우 승인 가능한 `gh auth refresh` 명령을 표시합니다. 권한을 변경한 뒤 PLAN을 다시 실행하세요.

### APPLY 전에 준비할 credential

APPLY는 Web 관리자 비밀번호와 GitHub credential 역할을 확인하고, 값이 아직 없으면 interactive terminal에서 입력을 받습니다. 비밀번호/PAT는 입력 중 화면에 표시되지 않습니다.

- **Web 관리자 비밀번호**: Web UI의 관리자 모드로 전환할 때 쓰는 별도 비밀번호입니다. 설치 시 만들며 GitHub PAT와 달라야 합니다.
- **CONTROL_TOKEN / TASK_REPO_TOKEN**: private control/Execution 및 TASK 저장소 작업을 위한 classic GitHub PAT입니다. 현재 지원 경로에서 기본 scope는 `repo`입니다. PLAN이 Execution workflow 파일을 쓰는 경우에는 인증 계정에 `workflow` scope도 필요하다고 안내할 수 있습니다.
- **AGENTCOLLAB_ORCHESTRATION_TOKEN**: exact workflow dispatch를 위해 쓰는 별도의 classic PAT입니다. 현재 구현은 `repo` scope를 검사합니다. repository credential과 같은 값을 재사용하지 마세요.
- 설치기는 필요한 runtime credential 일부를 local profile에 저장하고, Web 관리자 및 TASK repo credential을 대상 GitHub Actions secret으로 동기화합니다. 값은 출력하지 않습니다. local 설치 저장과 GitHub Actions 저장은 별도 위치입니다.

PAT 권한은 본인이 소유/관리하는 대상 저장소와 필요한 작업 범위로 제한하세요. PLAN이 요구하는 추가 scope나 저장소 권한을 임의로 추측하지 말고 PLAN 결과를 따르세요. credential을 shell 인자, 명령 기록, Issue, 채팅 또는 로그에 붙여넣지 마세요. APPLY의 비밀 입력 프롬프트에만 입력하고 출력 공유 전에는 민감값이 없는지 확인하세요.

## Public 저장소 준비

원하는 작업 디렉터리에서 저장소를 clone하고 인증합니다.

```sh
PUBLIC_OWNER="${AGENTCOLLAB_GITHUB_OWNER:-AgentCollab}"
gh repo clone "$PUBLIC_OWNER/AgentCollab-Public"
gh auth login
```

`AGENTCOLLAB_GITHUB_OWNER`는 Public 및 Distribution 저장소를 소유한 환경 조직으로 설정합니다. 지정하지 않으면 운영 조직을 기본값으로 사용합니다.

설치기는 Public 체크아웃 경로를 통해 호출할 수 있습니다. 기본 설치 위치는 현재 셸의 작업 디렉터리가 아니라 **Public 체크아웃의 부모에 있는 `agentcollab/`**입니다. 따라서 README Quick Start처럼 Public 저장소 안으로 이동해 실행해도 installer와 설치 본체가 형제 디렉터리로 유지됩니다.

예를 들어 `/srv/agentcollab-user`에 Public 저장소를 clone했다면 다음 두 방식 모두 같은 설치 위치를 사용합니다.

```sh
cd /srv/agentcollab-user/AgentCollab-Public
./install.sh plan
# 또는 /srv/agentcollab-user 에서:
./AgentCollab-Public/install.sh plan
```

기본 설치 위치는 `/srv/agentcollab-user/agentcollab`이고 기본 runner 위치는 `/srv/agentcollab-user/agentcollab/runner`입니다. 다른 위치가 필요하면 `--installation-root <path>` 또는 `--runner-root <path>`를 지정하세요. 명시적 root는 Public checkout 기준 기본값보다 우선합니다.

```text
/srv/agentcollab-user/
├─ AgentCollab-Public/  # installer/update entrypoint
└─ agentcollab/         # installed product authority
   ├─ RUN/              # Runtime, DATA, and service logs
   └─ runner/           # managed self-hosted runner
```

Public 체크아웃은 설치 프로그램을 업데이트하거나 다시 clone할 때 사용하는 디렉터리입니다. `agentcollab/`에는 설치된 Runtime, persistent DATA, 서비스 설정, runner가 있으므로 checkout 정리 목적으로 삭제하지 마세요. 현재 Public installer는 자동 uninstall 단계를 제공하지 않습니다.

## 빠른 설치: install

일반 설치는 Public checkout에서 다음을 한 번 실행합니다.

```sh
./install.sh install
```

설치기는 exact Distribution package pair를 확인하고 canonical PLAN을 실행합니다. `PLAN_READY`와 요약을 확인한 뒤 `yes`를 입력하면 해당 PLAN의 정확한 `plan_sha256`으로 APPLY를 진행하고, 같은 버전과 경로 선택으로 VERIFY를 자동 실행합니다. 확인을 거절하거나 PLAN/APPLY/VERIFY 중 하나라도 실패하면 뒤 단계를 실행하지 않습니다. 비밀번호 입력이 필요한 경우 APPLY에서 제공되는 숨김 입력을 사용하세요.

VERIFY가 `READY`이면 설치기는 선택된 포트의 `http://127.0.0.1:<port>/`와 첫 TASK 안내를 출력합니다. 로컬 그래픽 세션에서는 브라우저 열기를 best-effort로 시도합니다. Headless/SSH 환경에서는 URL 출력만 하며, 브라우저 오류는 READY 결과를 실패로 바꾸지 않습니다. 자동 열기를 끄려면 `--no-open-browser`를 지정하세요.

```sh
./install.sh install --no-open-browser
```

이 명령은 기존 설치, DATA, service, runner 또는 Execution repository를 이동·삭제·초기화하지 않습니다. 이미 설치한 환경은 PLAN을 먼저 검토하고 필요한 경우 아래 고급 절차를 사용하세요.

## 고급 설치: 계획/적용/검증

아래 절차는 PLAN, APPLY, VERIFY를 각각 실행해 검토하려는 경우에 사용합니다. 각 단계의 안전 계약은 `install`과 동일합니다.

### 설치 계획 만들기: PLAN

먼저 PLAN을 실행해 설치 대상과 변경 사항을 확인합니다.

```sh
./AgentCollab-Public/install.sh plan
```

PLAN은 앞부분에 Installer checkout, Installation root, Runner root, Execution repo, Web port를 요약하고 이어서 선택된 배포 버전, Source 출처, 패키지 확인 결과, 필요한 작업을 보여 줍니다. 실제 적용 전에 결과의 `resolved_version`과 `plan_sha256`을 기록하고 전체 계획을 검토하세요. 승인 digest는 실제 installation root와 runner root를 포함합니다.

### 버전 선택자

선택자를 생략하면 Distribution의 `channels/default.json`이 가리키는 버전을 사용합니다.

```sh
./AgentCollab-Public/install.sh plan
```

특정 채널을 선택할 수 있습니다.

```sh
./AgentCollab-Public/install.sh plan --channel beta
./AgentCollab-Public/install.sh plan --channel stable
```

정확한 버전은 channel 포인터를 거치지 않고 해당 불변 버전을 선택합니다.

```sh
./AgentCollab-Public/install.sh plan --version VERSION
```

`--version`과 `--channel`은 함께 지정할 수 없습니다. Candidate는 정확한 `--version`으로만 선택할 수 있습니다. Channel/default 포인터가 가리키는 버전은 `kind=release`여야 하고 Source `main`에서 만들어져야 합니다. 현재 사용 가능한 stable 버전이 없다면 `stable` 선택은 차단될 수 있습니다.

버전이 결정된 뒤에는 설치기가 다른 버전으로 다시 선택하거나 대체하지 않습니다.

### PLAN 결과 검토

적용 전에 다음 항목을 확인하세요.

- Installer checkout과 설치 본체가 형제 디렉터리인지
- Installation root와 Runner root가 의도한 위치인지
- Execution repo와 Web port가 의도한 값인지
- 요청한 선택자와 `resolved_version`이 의도와 일치하는지
- Source commit SHA와 service branch가 선택된 package provenance와 일치하는지
- Runtime, Execution, release manifest의 검증이 통과했는지
- PLAN의 모든 작업과 `plan_sha256`

설치기는 version record, release manifest, 패키지 해시와 Source provenance를 서로 대조합니다. 확인이 실패하면 fail-closed 방식으로 차단합니다.

## 설치 적용: APPLY

PLAN 결과를 검토한 뒤, **같은 정확한 버전과 해당 PLAN의 SHA**를 사용해 적용합니다.

```sh
./AgentCollab-Public/install.sh apply \
  --version VERSION \
  --approved-plan-sha256 PLAN_SHA256
```

`VERSION`에는 PLAN에서 확인한 정확한 `resolved_version`을, `PLAN_SHA256`에는 같은 PLAN의 `plan_sha256`을 입력하세요. 명시적 `--installation-root` 또는 `--runner-root`를 PLAN에 사용했다면 APPLY와 VERIFY에도 같은 값을 전달해야 합니다. 기본값을 쓴 경우에는 같은 Public checkout에서 실행하면 세 단계가 같은 경로를 계산합니다. 계획을 다시 만들거나 호스트 상태가 바뀌면 새 PLAN을 검토해야 합니다. APPLY 중에는 승인된 계획과 달라진 상태를 자동으로 보정하거나 다른 포트를 선택하지 않습니다.

## 설치 검증: VERIFY

APPLY가 성공하면 동일한 정확한 버전을 사용해 설치 상태를 확인합니다.

```sh
./AgentCollab-Public/install.sh verify --version VERSION
```

VERIFY 결과에서 선택된 Web port, Web service/health, runner 상태와 전체 readiness를 확인하세요. Web 화면은 같은 컴퓨터의 브라우저에서 `http://127.0.0.1:<확인한 Web port>/`로 엽니다. 기본 화면은 일반 사용자 모드이며, TASK 사용은 일반 사용자 권한 범위로 제한됩니다. 관리자 작업이 필요할 때만 화면의 관리자 비밀번호 입력란에 APPLY 때 설정한 Web 관리자 비밀번호를 입력해 관리자 모드로 전환하세요. 일반 사용자와 관리자는 별도 GitHub 로그인 계정이 아니라 Web 권한 모드입니다.

첫 실행은 Web UI에서 첫 TASK를 만들고 표시되는 readiness를 확인하는 것입니다. 필수 Execution 저장소, workflow, Actions credential 또는 runner 상태가 준비되지 않았다면 TASK 시작을 반복하지 말고 아래 문제 해결 안내에서 먼저 해당 readiness 원인을 해결하세요. 설치가 READY라는 사실만으로 외부 TASK workflow의 성공까지 보장되지는 않습니다.

## 업데이트와 제거

현재 버전은 PLAN 또는 VERIFY 출력의 `resolved_version`에서 확인합니다. 새 버전은 배포된 Distribution channel 또는 확인한 정확한 버전으로 선택합니다. 업데이트는 기존 `AgentCollab-Public` 체크아웃에서 새 PLAN을 검토하고 같은 installation/runner root를 사용해 APPLY한 뒤 VERIFY합니다. Public checkout을 갱신하거나 다시 clone해도 형제 `agentcollab/` 설치는 자동 이동·삭제되지 않습니다. Runtime 업데이트를 되돌리는 별도 자동 rollback 명령은 제공되지 않습니다. 이전 버전 재적용을 rollback으로 간주하지 마세요. 버전 간 DATA/profile 호환성이 보장된다는 근거가 없으므로 복구가 필요하면 먼저 운영자 지원을 요청하세요.

Public installer에는 자동 제거 명령이 없습니다. `agentcollab/`는 Runtime, DATA, 서비스 설정, runner를 포함하는 설치 본체이므로 삭제 전에 DATA 보존 및 서비스/runner 해제를 별도로 계획해야 합니다. Public checkout만 삭제해도 설치 본체는 제거되지 않습니다.

수동 제거를 진행한다면 먼저 PLAN/VERIFY 출력과 실제 service/runner 경로를 대조하고, DATA를 별도 안전한 위치에 백업했는지 확인하세요. 그 다음 해당 설치가 소유한 user Web service와 runner를 명시적으로 중지·해제하고 runner 등록 해제를 확인한 뒤, DATA를 보존할지 삭제할지 결정하세요. 관리 대상임을 확인할 수 없는 service/runner는 중지·삭제하지 마세요. 현재 Public installer는 자동화된 완전 제거·복구 절차를 제공하지 않으므로 서비스/runner 해제 방법이 분명하지 않으면 설치 폴더를 지우지 말고 [문제 해결 및 운영](TROUBLESHOOTING.md)에서 지원을 요청하세요.

## Web 포트

`--web-port`를 생략하면 Public 설치기는 이 선택을 setup에 그대로 전달하지 않습니다. setup이 기본 포트 8080을 확인하고, 기본 포트를 쓸 수 없는 경우 지원 범위 안에서 빈 포트를 결정적으로 선택할 수 있습니다. 기존의 다른 listener는 종료하거나 변경하지 않습니다.

포트를 직접 지정하면 요청한 값 그대로 사용합니다.

```sh
./AgentCollab-Public/install.sh plan --web-port 8080
```

명시한 포트가 사용 중이거나 소유 관계를 확인할 수 없으면 다른 포트로 자동 전환하지 않고 차단합니다.

## 차단된 경우

차단 결과는 인증·권한, 카탈로그, 버전·패키지 provenance, 포트 소유 관계 또는 호스트 상태 확인이 실패했음을 뜻할 수 있습니다. 오류와 PLAN 증거를 보존하고 first-cause를 확인하세요. 검증을 우회하거나, 승인된 버전을 바꾸거나, 기존 프로세스를 임의로 종료하지 마세요. 호스트 상태나 선택자를 바꾼 뒤 진행하려면 새 PLAN을 만들고 다시 검토해야 합니다.

원인별 확인 순서와 업데이트·credential 복구·수동 제거의 제한은 [문제 해결 및 운영](TROUBLESHOOTING.md)을 참고하세요. 설치기 버전과 공개 변경 내역은 [GitHub Releases](https://github.com/AgentCollab/AgentCollab-Public/releases)에서 확인할 수 있고, 문의는 [GitHub Issues](https://github.com/AgentCollab/AgentCollab-Public/issues)에 남길 수 있습니다. 로그를 올릴 때 token, 비밀번호, private URL/query, profile 내용은 제거하세요.
