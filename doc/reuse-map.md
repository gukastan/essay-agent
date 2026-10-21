# 원본 → 최종 재사용 지도

원본 복사본47개 파일 중27개를 정확한 경로와 최초 SHA-256으로 확인한 뒤 제거했고20개는 유지·개조했다. 원본 Downloads, 사용자 환경, DB, 새 파일은 삭제 대상이 아니다. 복사와 삭제 증거는 작업 산출물 `task-1-source-manifest.json`, `task-9-removed-paths.json`에 있다. 라이브러리 이름만 같은 것을 재사용 근거로 삼지 않고 아래 호출 경로를 확인한다.

| 원본 경로 | 유지한 구조 → 현재 책임 | 검증 위치 |
| --- | --- | --- |
| agent/__init__.py | Python 패키지 경계 유지 | 계약/노드 import 테스트 |
| server.py | FastAPI lifespan·JSON/SSE → create_app와 공통 RunService | test_api_http.py, test_api_adversarial.py |
| agent/graph.py | StateGraph·partial 주입·async 노드·조건부 edge → 6단계+수정 | test_graph.py, test_graph_progress.py |
| agent/deps.py | SupervisorDeps 데이터 구조 → 모델/MCP 의존성 | 분석·작성 노드 테스트 |
| agent/openai_llm.py | Fast/Quality 모델 역할 → ChatOpenAI strict async structured 호출 | test_llm_adapters.py |
| agent/fake_llm.py | 키 없는 테스트 adapter → 현재 payload를 사용하는 주입 factory | test_llm_adapters.py, test_composition.py |
| agent/retry.py | 비동기 재시도 경계 → 최초 포함2회·usage·typed recovery | test_retry.py, test_llm_recovery.py |
| agent/mcp_client.py | stdio·ClientSession·AsyncExitStack → 자료/가이드/절차 client | test_mcp.py, test_analysis_mcp.py |
| mcp_server.py | FastMCP tool/resource/prompt → 회사직무 catalog·writing guide | test_mcp.py |
| agent/session_store.py | SQLite 연결·messages 호환 → essay_runs 예약/조회/저장 | test_api_store.py, API 저장 테스트 |
| web_demo_server.py | HTML 제공·동일 출처 proxy → POST SSE/JSON/실행·버전 조회 | test_proxy.py |
| web_chat.html | Vue CDN·반응형 입력/출력 → 원문·진행·결과·수정 UI | 실제 브라우저 통합 QA |
| requirements.txt | 동일 Python 런타임 계열 → 호환 버전 고정 | 패키지 import, provider transport 테스트 |
| .env.example | 환경 설정 예시 → OpenAI 두 역할·선택 추적·DB/port | launcher 설정 보존 테스트 |
| .gitignore | 비밀/런타임 제외 → env, DB sidecar, cache 제외 유지 | 게시 snapshot 보안 확인 |
| sh/setup_venv.sh | 프로젝트 로컬 환경 설치 → uv, Python3.11, 런타임 설치 | bash -n, 임시 uv 실행기 테스트 |
| sh/run_agent_openai.sh | 백엔드 시작·health 확인 → 단일 소유 PID·loopback·DB 보존 | test_launchers.py |
| sh/run_frontend.sh | 백엔드 준비 확인·proxy 시작 → 별도 소유 proxy만 종료 | 실제 fake backend/proxy smoke |
| doc/README.md | 실행 안내 진입점 → 공개 API·저장·수정 계약 | 문서 경로/DTO 대조 |
| doc/regression_test_queries.md | 사람이 실행하는 회귀 사례 → 자기소개서 검증 시나리오 | 수동 회귀·통합 QA |

신규 contracts·stage helper·run service·catalog·Vue assets는 이 구조 안에서 역할을 분리한다. 원본 도메인의 supervisor v1, 로컬 모델 adapter/setup, docs MCP, monitoring/runbooks, 이전 수동 문서·스크린샷, 배포 ZIP 스크립트는 더 이상 런타임 호출 경로에 없다. 삭제 디렉터리 전체를 지우지 않았으며 새 사용자 파일은 보존한다.

원본 구현과의 구조 차이는 [architecture-change-log.md](architecture-change-log.md)에 구분한다. 실제 모델 품질·브라우저 QA 결과는 통합 검증 보고서에서 확인하며 이 지도 자체가 품질 통과 증거는 아니다.
