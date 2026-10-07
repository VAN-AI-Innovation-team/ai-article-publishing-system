# GitHub 초기 설정

현재 코드와 호스팅 플랫폼이 미정이므로 앱 배포 workflow는 만들지 않았습니다. 기사 CMS 발행과 애플리케이션 배포는 별도 절차입니다.

1. 조직 `VAN-AI-Innovation-team`에 `ai-article-publishing-system` private 저장소 생성
2. 초기 커밋 push 후 `main` 보호: PR 필수, 1명 이상 리뷰, force push/delete 금지
3. 팀원에게 최소 권한 부여, MFA 확인
4. Actions 기본 권한은 읽기 전용, 필요한 workflow에만 권한 확대
5. 호스팅·모델·CMS 확정 후 Environments별 비밀값과 승인 게이트 구성
6. 앱 코드/스택이 확정되면 빌드·배포·롤백 workflow 추가
