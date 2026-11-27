# AI 기사 제작·발행 시스템

수집·검증·작성·편집·발행 파이프라인 기획 및 구현 저장소입니다.

## 목표
- 공식 보도자료와 사용 허가된 외신 피드 수집
- 근거가 연결된 기사 초안 생성 및 편집자 승인 후 CMS 발행
- 보도자료에서 외신·데이터·리서치 기사로 단계적 확장

## 초기 원칙
- 초기 외부 발행은 사람 승인 필수
- 출처·저작권·이용약관·인용 기준 준수
- 기사 주장마다 근거와 편집 이력 보존
- 비밀값을 저장소에 커밋하지 않음

## 문서
- [초기 설계 및 운영 방식 조사](PLAN.md)
- [5인 역할 분담](TEAM.md)
- [기여 가이드](CONTRIBUTING.md)
- [GitHub 초기 설정](GITHUB_SETUP.md)

초기 구현 언어는 Python입니다. 배포 대상과 The Sheerit 연동 방식은 운영환경 및 CMS 규격 확인 후 결정합니다.

## 출처 등록부
출처 설정은 [`config/sources.yaml`](config/sources.yaml)의 데이터로 관리합니다. 기획안에 있는 외신 179개 항목(고유 매체 152곳)과 국내 보도자료 출처 157곳을 초기 목록으로 등록했습니다. 코드를 수정하지 않고 이 파일에 출처 항목을 추가·수정·비활성화할 수 있습니다.

기획안의 수집 방식과 개별 우선순위·주기는 비어 있어 초기 항목은 비활성 상태입니다. 수집 방식은 `rss` 또는 `api`로 설정하고, 우선순위는 1~3, 주기는 `poll_interval_seconds`에 초 단위로 입력합니다. 출처 목록에 있다는 사실만으로 이용 약관이나 재사용 권한이 확인된 것은 아니므로 `usage_terms_confirmed`도 확인 후 설정해야 합니다. 세부 설정과 편집 측 승인이 갖춰진 활성 출처만 `eligible_sources`에 포함됩니다. 이 기능은 설정을 읽고 검증하며, 실제 수집이나 일정 실행은 후속 기능입니다.

프로젝트 루트에서 의존성을 설치합니다.

```powershell
python -m pip install -e .
```

Python 코드에서 다음처럼 읽을 수 있습니다.

```python
from van_article_publishing_system.sources.registry import load_source_registry

registry = load_source_registry("config/sources.yaml")
for issue in registry.issues:
    print(issue.source_id, issue.message)

for source in registry.eligible_sources:
    print(source.source_id, source.collection_method)
```
## 프로젝트 패키지 구조 및 관리 규칙

본 프로젝트는 기능별 책임에 따라 패키지를 분리하는 구조를 사용합니다.

이슈 단위로 별도의 패키지나 폴더를 생성하지 않으며, 모든 구현 코드는 메인 패키지 내에서 해당 기능의 책임에 맞는 디렉터리에 배치합니다.

### 메인 패키지 구조

```text
src/van_article_publishing_system/
├── sources/
├── collection/
├── processing/
├── editorial/
├── publishing/
└── operations/
```

| 패키지 | 담당 기능 |
|---|---|
| `sources` | 데이터 출처 및 수집 대상 관리 |
| `collection` | RSS 등 외부 데이터 수집 |
| `processing` | 수집 데이터 정규화 및 후처리 |
| `editorial` | 기사 검토, 편집 및 승인 관리 |
| `publishing` | 승인된 기사의 외부 플랫폼 발행 |
| `operations` | 실행 이력, 오류 및 운영 관리 |

### 패키지 관리 원칙

1. 이슈 번호 또는 이슈명을 기준으로 별도의 패키지 폴더를 생성하지 않습니다.
2. 신규 구현 코드는 기존 메인 패키지의 기능별 디렉터리에 배치합니다.
3. 각 모듈은 해당 디렉터리의 책임 범위에 맞게 작성합니다.
4. 모듈 이동 및 구조 변경 시 관련 import 경로와 테스트 코드도 함께 수정합니다.
5. 기존 기능과 테스트가 정상적으로 유지되는지 확인한 후 변경 사항을 반영합니다.

이를 통해 기능별 책임을 명확히 분리하고, 코드 통합 및 유지보수의 효율성을 높입니다.

## RSS 피드 수집기
`van_article_publishing_system.feeds`는 `eligible_for_collection`인 `rss` 출처의 `feed_url`을 요청해 항목을 가져옵니다. 항목은 피드 원문 그대로 반환하며, 정제·공통 형식 변환·저장·주기 실행은 후속 이슈 범위입니다.

```python
from van_article_publishing_system.sources.registry import load_source_registry
from van_article_publishing_system.collection.feeds import collect_rss_feeds

registry = load_source_registry("config/sources.yaml")
for result in collect_rss_feeds(registry.sources):
    if result.ok:
        print(result.source_id, len(result.items))
    else:
        print(result.source_id, result.failure.kind.value, result.failure.message)
```

- 비활성·미승인·이용조건 미확인 출처는 요청하지 않으며 결과에도 나타나지 않습니다.
- `rss`가 아닌 활성 출처는 `unsupported_method`로 기록하고 크롤링하지 않습니다.
- 실패 유형: `network`(연결·시간 초과·HTTP 오류), `invalid_format`(RSS 2.0 아님·크기 초과), `invalid_url`(피드 주소 없음·공개 주소 아님), `unsupported_method`, `internal`.
- 한 출처가 실패해도 나머지 출처는 계속 수집합니다.
- 지원 형식은 RSS 2.0입니다. Atom 등 다른 피드 형식은 `invalid_format`으로 처리됩니다.
