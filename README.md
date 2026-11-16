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
from van_article_publishing_system.sources import load_source_registry

registry = load_source_registry("config/sources.yaml")
for issue in registry.issues:
    print(issue.source_id, issue.message)

for source in registry.eligible_sources:
    print(source.source_id, source.collection_method)
```

## RSS 피드 수집기
`van_article_publishing_system.feeds`는 `eligible_for_collection`인 `rss` 출처의 `feed_url`을 요청해 항목을 가져옵니다. 항목은 피드 원문 그대로 반환하며, 정제·공통 형식 변환·저장·주기 실행은 후속 이슈 범위입니다.

```python
from van_article_publishing_system.sources import load_source_registry
from van_article_publishing_system.feeds import collect_rss_feeds

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
