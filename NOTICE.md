# 배포 경계 및 authority

## Public 저장소에 포함되는 항목

Public 저장소는 공개 범용 설치 진입점입니다. 설치기, bootstrap, 설치 프로토콜, 관련 문서와 테스트를 포함합니다. 제품별 Runtime/Execution 패키지와 비공개 릴리스 자산을 포함하지 않습니다.

## 배포 및 소스 authority

- **Distribution** 저장소는 제품 버전 카탈로그와 불변 Runtime/Execution 패키지, release manifest의 authority입니다. 이 저장소는 비공개이며 접근에는 인증과 읽기 권한이 필요합니다. 두 저장소의 owner는 각 환경의 `installer-manifest.json`에 설정합니다.
- **Source**는 제품 소스와 패키지 provenance의 authority입니다. Distribution release manifest와 Runtime/Execution 패키지는 Source 저장소와 commit을 기록하며, Public 설치기는 인증된 release manifest의 provenance 형식을 확인하고 두 패키지와 정확히 일치하는지 검증합니다. 설치기는 특정 Source 저장소 이름을 고정하지 않습니다.
- **Public**은 범용 설치 프로토콜을 제공하며 특정 제품 버전이나 패키지를 authority로 정하지 않습니다.

## 버전 경계

버전별 Distribution release 자산은 불변으로 유지됩니다. Candidate는 개별 검증을 위한 정확한 버전이며 channel 포인터의 대상이 아닙니다. Reviewed release만 channel/default 포인터로 선택될 수 있습니다. 포인터가 가리키는 버전과 Source provenance 검증은 Public 설치기에서 fail-closed 방식으로 처리됩니다.

Public 설치기가 비공개 Distribution에 접근하려면 사용자가 인증한 GitHub identity에 해당 저장소의 읽기 권한이 있어야 합니다. Public 저장소의 공개 여부가 Distribution 패키지에 대한 익명 접근을 허용하지는 않습니다.
