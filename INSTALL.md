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

설치기는 Public 체크아웃 경로를 통해 호출할 수 있습니다. 기본 설치 위치는 Public 저장소 위치와 무관하게 **명령을 실행한 현재 작업 디렉터리 아래의 `agentcollab/`**입니다.

예를 들어 현재 위치가 `/srv/agentcollab-user`라면 다음처럼 실행할 수 있습니다.

```sh
cd /srv/agentcollab-user
./AgentCollab-Public/install.sh plan
```

이 경우 기본 설치 위치는 `/srv/agentcollab-user/agentcollab`입니다. 다른 위치가 필요하면 `--installation-root <path>`를 지정하세요.

## 설치 계획 만들기: PLAN

먼저 PLAN을 실행해 설치 대상과 변경 사항을 확인합니다.

```sh
./AgentCollab-Public/install.sh plan
```

설치기는 선택된 배포 버전, Source 출처, 패키지 확인 결과, 설치 위치와 필요한 작업을 보여 줍니다. 실제 적용 전에 결과의 `resolved_version`과 `plan_sha256`을 기록하고 전체 계획을 검토하세요.

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

- 요청한 선택자와 `resolved_version`이 의도와 일치하는지
- Source 저장소, commit SHA, service branch가 올바른지
- Runtime, Execution, release manifest의 검증이 통과했는지
- 설치 root와 Web 포트가 의도한 값인지
- PLAN의 모든 작업과 `plan_sha256`

설치기는 version record, release manifest, 패키지 해시와 Source provenance를 서로 대조합니다. 확인이 실패하면 fail-closed 방식으로 차단합니다.

## 설치 적용: APPLY

PLAN 결과를 검토한 뒤, **같은 정확한 버전과 해당 PLAN의 SHA**를 사용해 적용합니다.

```sh
./AgentCollab-Public/install.sh apply \
  --version VERSION \
  --approved-plan-sha256 PLAN_SHA256
```

`VERSION`에는 PLAN에서 확인한 정확한 `resolved_version`을, `PLAN_SHA256`에는 같은 PLAN의 `plan_sha256`을 입력하세요. 계획을 다시 만들거나 호스트 상태가 바뀌면 새 PLAN을 검토해야 합니다. APPLY 중에는 승인된 계획과 달라진 상태를 자동으로 보정하거나 다른 포트를 선택하지 않습니다.

## 설치 검증: VERIFY

APPLY가 성공하면 동일한 정확한 버전을 사용해 설치 상태를 확인합니다.

```sh
./AgentCollab-Public/install.sh verify --version VERSION
```

## Web 포트

`--web-port`를 생략하면 Public 설치기는 이 선택을 setup에 그대로 전달하지 않습니다. setup이 기본 포트 8080을 확인하고, 기본 포트를 쓸 수 없는 경우 지원 범위 안에서 빈 포트를 결정적으로 선택할 수 있습니다. 기존의 다른 listener는 종료하거나 변경하지 않습니다.

포트를 직접 지정하면 요청한 값 그대로 사용합니다.

```sh
./AgentCollab-Public/install.sh plan --web-port 8080
```

명시한 포트가 사용 중이거나 소유 관계를 확인할 수 없으면 다른 포트로 자동 전환하지 않고 차단합니다.

## 차단된 경우

차단 결과는 인증·권한, 카탈로그, 버전·패키지 provenance, 포트 소유 관계 또는 호스트 상태 확인이 실패했음을 뜻할 수 있습니다. 오류와 PLAN 증거를 보존하고 first-cause를 확인하세요. 검증을 우회하거나, 승인된 버전을 바꾸거나, 기존 프로세스를 임의로 종료하지 마세요. 호스트 상태나 선택자를 바꾼 뒤 진행하려면 새 PLAN을 만들고 다시 검토해야 합니다.
