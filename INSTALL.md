# AgentCollab 설치 안내

이 문서는 Public 설치기를 사용해 AgentCollab 설치를 계획하고 적용하는 방법을 설명합니다. 명령은 Public 저장소의 `install.sh`를 실행하는 예입니다.

## 사전 준비

- 지원되는 Linux 환경과 `git`, Python 3, GitHub CLI(`gh`)가 필요합니다.
- `gh auth login`으로 GitHub에 인증하세요.
- 인증한 GitHub 계정은 현재 Public 저장소의 installer manifest가 지정하는 비공개 Distribution 저장소를 읽을 권한이 있어야 합니다.
- 설치기는 Distribution 카탈로그와 선택된 릴리스 자산을 인증된 방식으로 읽습니다.

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

## 설치 계획 만들기: PLAN

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
- Source 저장소, commit SHA, service branch가 올바른지
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

## 업데이트와 제거

업데이트는 기존 `AgentCollab-Public` 체크아웃에서 새 PLAN을 검토하고 같은 installation/runner root를 사용해 APPLY한 뒤 VERIFY합니다. Public checkout을 갱신하거나 다시 clone해도 형제 `agentcollab/` 설치는 자동 이동·삭제되지 않습니다.

Public installer에는 자동 제거 명령이 없습니다. `agentcollab/`는 Runtime, DATA, 서비스 설정, runner를 포함하는 설치 본체이므로 삭제 전에 DATA 보존 및 서비스/runner 해제를 별도로 계획해야 합니다. Public checkout만 삭제해도 설치 본체는 제거되지 않습니다.

## Web 포트

`--web-port`를 생략하면 Public 설치기는 이 선택을 setup에 그대로 전달하지 않습니다. setup이 기본 포트 8080을 확인하고, 기본 포트를 쓸 수 없는 경우 지원 범위 안에서 빈 포트를 결정적으로 선택할 수 있습니다. 기존의 다른 listener는 종료하거나 변경하지 않습니다.

포트를 직접 지정하면 요청한 값 그대로 사용합니다.

```sh
./AgentCollab-Public/install.sh plan --web-port 8080
```

명시한 포트가 사용 중이거나 소유 관계를 확인할 수 없으면 다른 포트로 자동 전환하지 않고 차단합니다.

## 차단된 경우

차단 결과는 인증·권한, 카탈로그, 버전·패키지 provenance, 포트 소유 관계 또는 호스트 상태 확인이 실패했음을 뜻할 수 있습니다. 오류와 PLAN 증거를 보존하고 first-cause를 확인하세요. 검증을 우회하거나, 승인된 버전을 바꾸거나, 기존 프로세스를 임의로 종료하지 마세요. 호스트 상태나 선택자를 바꾼 뒤 진행하려면 새 PLAN을 만들고 다시 검토해야 합니다.
