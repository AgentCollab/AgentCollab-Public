# 문제 해결 및 운영

이 문서는 Public installer의 설치/운영 경계를 설명합니다. PLAN/APPLY/VERIFY의 `status`, `phase`, `reason`, `next_action`을 먼저 확인하고, 첫 원인을 해결한 뒤 새 PLAN으로 다시 검토하세요. 검증을 우회하거나 기존 process를 임의 종료하지 마세요.

## 자주 발생하는 차단

### GitHub 로그인 또는 저장소 접근

- `gh auth status`로 현재 계정이 로그인되어 있는지 확인합니다.
- Public 및 private Distribution 카탈로그를 읽을 수 있는 계정인지 확인합니다.
- PLAN에 표시된 개인 Execution repository 권한과 필요한 PAT scope를 확인합니다. 현재 classic PAT 경로의 기본 scope는 `repo`이며, workflow 파일 변경이 계획된 경우 PLAN이 `workflow` scope를 요구할 수 있습니다.
- PLAN이 출력한 `gh auth refresh` 조치가 있으면 해당 interactive 명령을 승인해 실행하고, PLAN을 다시 실행합니다.
- 토큰을 명령 인자, Issue, 채팅, 로그에 붙여넣지 마세요.

### 원격 shell에서 systemd user service를 사용할 수 없음

설치와 VERIFY는 현재 사용자 세션의 systemd user manager를 확인합니다. SSH/원격 shell에서 user manager 또는 DBus session이 연결되지 않으면 해당 로그인 환경을 먼저 바로잡아야 합니다. service가 실제로 준비되지 않은 상태에서 APPLY를 반복하거나 system/system-wide service로 임의 전환하지 마세요. 같은 사용자로 interactive terminal을 열어 다시 PLAN하고 표시된 원인을 확인하세요.

### Web port가 사용 중이거나 소유자를 확인할 수 없음

- PLAN의 Web port와 충돌 상세를 확인합니다.
- 명시적으로 요청한 port가 충돌하면 installer는 다른 port로 자동 전환하지 않습니다.
- 기본 port를 사용할 수 없을 때 setup이 선택한 port는 PLAN/VERIFY 출력에서 확인합니다.
- 기존 listener를 임의 종료하지 마세요. 소유자를 확인할 수 없으면 다른 명시 port로 새 PLAN을 만들고 결과를 다시 검토하세요.

### 기존 설치 또는 runner topology 충돌

PLAN의 Installation root, Runner root, service, Execution repo와 CREATE/REUSE/ACTION_REQUIRED/BLOCKED 항목을 비교하세요. 기존 설치가 예상과 다르면 기존 경로를 삭제하거나 `--replace`하지 마세요. 의도한 설치를 선택할 때만 PLAN/APPLY/VERIFY에 동일한 root 옵션을 전달합니다. 기존 runner 등록/작업 경로를 확인할 수 없으면 설치를 중단하고 지원을 요청하세요.

### APPLY의 비밀 입력 또는 권한 오류

APPLY는 Web 관리자 비밀번호, repository credential 역할, 별도 workflow-dispatch PAT가 필요할 수 있습니다. 비밀값은 화면에 표시되지 않는 interactive prompt에만 입력하세요. terminal이 입력을 숨기지 못하거나 사용할 수 없으면 APPLY를 중단하고 interactive terminal에서 다시 시작합니다. 값이 출력되거나 잘못된 계정에 입력됐다고 의심되면 해당 credential을 GitHub에서 폐기/교체한 뒤 PLAN을 다시 실행하세요.

인증 credential을 서로 바꿔 쓰지 마세요. Web 관리자 비밀번호는 Web 관리자 모드용이며 GitHub PAT가 아닙니다. repository PAT와 exact dispatch PAT는 권한 역할이 다르며, 현재 구현은 dispatch PAT에도 `repo` scope를 검사합니다.

### APPLY가 중간에 실패함

부분 적용 후에는 설치 폴더나 DATA를 지우지 마세요. APPLY의 오류와 `phase`를 기록하되 credential/profile 내용은 공유하지 않습니다. 현재 설치 위치에서 새 PLAN을 실행해 각 action과 readiness를 다시 검토하세요. PLAN이 안전하게 재사용/수정할 상태를 표시하면 같은 root/version으로 진행합니다. `BLOCKED`, 소유자가 불명확한 service/port, drift가 있으면 반복 APPLY 대신 해당 원인을 먼저 해결하거나 지원을 요청하세요.

### Web 관리자 비밀번호를 잊음

관리자 모드는 설치 때 설정한 Web 관리자 비밀번호로 전환합니다. 일반 사용자 화면에는 관리자 비밀번호를 재설정하는 self-service 기능이 없습니다. profile 파일을 직접 편집하거나 Web admin token을 GitHub PAT로 대체하지 마세요. credential 재설정은 현재 자동화된 Public 복구 기능이 아니므로 비밀값을 포함하지 않고 GitHub Issues로 지원을 요청하세요.

### 설치 readiness와 TASK workflow 실패 구분

VERIFY는 설치된 Runtime, Web health, runner 및 설치 readiness를 검사합니다. 설치가 READY여도 특정 TASK의 Execution repository, workflow, Actions credentials 또는 workflow run이 실패할 수 있습니다. 해당 TASK의 readiness/error와 해당 저장소 GitHub Actions run을 확인하세요. 설치 VERIFY가 실패하면 먼저 install readiness를 해결하고, 설치 VERIFY는 READY인데 workflow만 실패하면 설치를 반복하지 말고 TASK/Actions 원인을 조사하세요. 로그를 공유할 때 private URL, token, 비밀번호, profile 값을 제거하세요.

## 업데이트와 데이터

- 설치기의 현재/선택 버전은 PLAN/VERIFY의 `resolved_version`에서 확인합니다. 배포 채널은 PLAN에서 확인하고, 필요하면 정확한 version을 명시해 새 PLAN을 만듭니다.
- 업데이트는 새 PLAN을 검토한 후 그 exact version과 digest를 사용해 APPLY하고 VERIFY합니다. Public checkout과 설치 root는 형제 경로이며, checkout 갱신은 설치 Runtime을 자동 갱신하지 않습니다.
- DATA는 persistent 사용자 데이터입니다. 업데이트/재설치 이유로 삭제하지 마세요. 별도 backup이 있는지 확인하고 계획된 설치 root를 유지하세요.
- 자동 rollback 명령은 제공되지 않습니다. 이전 version을 재적용하면 DATA/profile 호환성이 보장된다는 근거가 없으므로 rollback으로 간주하지 마세요. 복구가 필요하면 설치 정보를 보존하고 지원을 요청하세요.

## 제거 전 확인

자동 uninstall 명령은 없습니다. 수동 제거를 결정한 경우에만 다음을 순서대로 확인하세요.

1. PLAN/VERIFY 출력으로 정확한 설치 root, Web service, Runner root, GitHub runner/repository identity를 기록합니다.
2. DATA를 보존해야 한다면 설치 경로 밖의 안전한 위치에 별도 백업하고 백업 내용을 확인합니다. DATA가 필요 없다는 판단이 끝나기 전에는 삭제하지 않습니다.
3. 해당 설치에 속함이 확실한 Web user service와 runner를 중지하고, GitHub runner registration을 해제합니다. 확인되지 않은 service나 runner는 건드리지 않습니다.
4. service와 runner가 더 이상 실행/등록되지 않는 것을 확인합니다. 확인할 수 없으면 디렉터리를 삭제하지 말고 지원을 요청합니다.
5. 마지막으로 설치 Runtime과 runner 파일을 정리합니다. DATA를 보존한다면 DATA를 삭제하지 말고, 필요한 경우 Public checkout도 별도로 정리합니다.

이 문서는 임의의 service 이름이나 runner를 제거하는 명령을 제공하지 않습니다. 설치별 identity를 확인하지 않고 system-wide/systemd 또는 GitHub 자원을 삭제하지 마세요.

## 지원 및 버전 정보

- 설치 오류/기능 문의: [AgentCollab-Public Issues](https://github.com/AgentCollab/AgentCollab-Public/issues)
- Public installer 릴리스/변경 내역: [AgentCollab-Public Releases](https://github.com/AgentCollab/AgentCollab-Public/releases)
- 설치된/선택된 제품 버전: installer PLAN/VERIFY의 `resolved_version`

문의에는 OS 정보, installer 버전, 비밀값을 제거한 `phase`, `reason`, `next_action`과 first-cause만 포함하세요. token, Web 관리자 비밀번호, 환경 profile, private URL/query는 게시하지 마세요.
