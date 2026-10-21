# 아키텍처 변경 기록

## 원본 프로젝트와 비교

운영 장애 입력·monitoring/runbook 도구 선택·응답 반복을 자기소개서 분석→구조→부분작성→통합→제목검토→결과전달로 교체했다. FastAPI, LangGraph StateGraph, async 노드/partial 의존성 주입, stdio MCP, SQLite, Vue CDN, 동일 출처 proxy는 유지했다. 새 agent framework나 SPA 빌드 도구는 추가하지 않았다.

MCP는 한 회사·직무 자료 서버에서 search_company_job_materials, writing guide resource, writing prompt를 제공한다. 도메인에 맞지 않는 이전 자료/실행 경로는 정확한 원본 manifest 목록만 제거했다. ChatOpenAI가 실제 provider transport와 strict Structured Outputs를 맡으며 서버 lifespan에서 Fast/Quality 인스턴스를 공유한다.

## 승인된 여섯 단계 설계와 비교

여섯 논리 단계는 유지된다. 실제 StateGraph 노드는 여섯 단계+repair_draft의7개이고 수정 경로는 최대2회다. 추가 critic, 정보 충분성 gate, 질문 대기 노드, 별도 품질 반복은 없다. StageStarted/Completed는 실제 노드 경계에서 발행하며 delivery는 Python 전용이다.

구현 중 원래 요구를 완성하기 위해 내부 참조 계약을 보강했다. 서버가 로드한 부모 메타데이터는 문서/버전 검증에, 이전 AI 초안의 최소 문구 DTO는 작성·통합 편집 참고에만 사용한다. 검증된 일반 fallback 문장은 서버 소유 provenance로 보존한다. 이들은 새 사용자 단계나 새 증거 출처가 아니다.

SQLite 실행 예약·GET 조회 복구·저장 상태·재시작 고아 실행 처리와 구독자 분리는 HTTP/SSE 신뢰성을 위한 서비스 계층이다. 실행 중인 동일 요청의 POST 재전송은 409와 실행 조회 Location을 반환하고, 완료된 동일 요청은 저장된 결과를 재사용한다. 기존 스트림에 POST로 재연결하지 않는다. 화면 단계와 독립적으로 저장 실패/미확정 상태를 전달한다. 실행기는 기존3개만 유지하고 frontend가 동일 supervisor의 proxy mode를 사용한다. 포트 소유자 강제 종료와 DB 초기화는 제거했다.

## 검증의 한계

결정적 fake와 주입 출력은 참조·실행 횟수·복구·저장·표시 계약을 검증한다. 실제 모델이 인과·동기·사건 귀속을 얼마나 잘 판단하는지는 별도 실제 모델/CUA 통합 확인 대상이다. 확인하지 않은 외부 사실 또는 제출 성공을 보증하지 않는다.
