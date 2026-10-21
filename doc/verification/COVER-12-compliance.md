# COVER-12 / F1 — 계획 준수와 기존 프로젝트 재활용 검증

판정: 통과. COVER-11 최종 구현과 원본 manifest, 최종 계획, 재사용 지도를 대조했다. 기존 서버 장애 Agent의 기술 구조를 재사용했고, 자소서 작성 목적에 맞게 도메인·계약·도구·화면을 교체했다. 새 독립 프레임워크로 대체하지 않았다.

## 원본과 파일 범위

원본 manifest의 47개 파일을 실제 원본과 SHA-256으로 비교한 결과 변경0개다. 복사본의 유지 대상20개는 모두 존재하고, 승인된 제거 대상27개는 모두 제거됐다. 원본 Downloads는 수정하지 않았다. 제거 수는 원본 manifest 기준 물리 파일 수이며, Git에 추적된 삭제 수와 혼동하지 않는다. 결과는 로컬 `final-source-audit.json`에 보존했다.

`doc/reuse-map.md`와 코드의 대응은 다음과 같다.

| 재사용 요소 | 실제 경로 / 실행 증거 |
| --- | --- |
| FastAPI 서버, async 의존성 주입 | `server.py`, `agent/app_runtime.py`, `agent/deps.py`; 실제 JSON/SSE와 health 응답 |
| LangGraph StateGraph | `agent/graph.py`, `agent/graph_state.py`; 0/1/2회 수정 시 실제 완료 노드6/8/10 |
| Fast/Quality 모델 역할 | `agent/openai_llm.py`, `agent/essay_llm.py`; ChatOpenAI의 strict Structured Outputs와 async 호출, 실제 OpenAI 브라우저 생성 |
| stdio MCP | `agent/mcp_client.py`, 기업·직무 자료/작성 가이드 서버; 실제 프로세스 health의 ready와 자료 전달 |
| SQLite 저장 | `agent/session_store.py`와 저장 모듈; 기존 messages 보존, 실행 예약·문서/버전·재시작 조회 |
| Vue CDN과 동일 출처 proxy | `web_chat.html`, `web_assets/`, `web_demo_server.py`; 실제 입력·진행·결과·복사·새 버전·조회 |
| 기존 실행 스크립트 | 유지한 세 sh 파일; 포트 소유자 보존, 자기 PID 종료, DB 보존 및 환경 변수 유지 검사 |

Ollama 실행 경로와 서버 장애 전용 도구/자료는 제거했다. `.env`, 실행 DB, 실제 응답 캡처는 공개 커밋 대상에서 제외했다. `.env.example`만 추적한다.

## 최종 계약 대응

INT-01~03: 현재 원문→사실→답 후보→부분→문장→검토 참조와 근거 버전을 실제 프로세스 trace에서 검증했다. INT-04~05: 최종 개인화/위치 갱신과 현재 문장 검토 없는 supported 판정 금지를 검증했다. INT-06~09: 분석 실패 시 원문 요구 보존, 일반 대체문, 제목 실패의 본문 보존, 불완전 응답의 추가 호출 없는 대체를 검증했다. INT-10: 수정 한도와 실패 경로를 검증했다. INT-11~15: 공통 오류, 별도 저장 상태, 요청 식별, 고아 실행, 후속 원문 정정/질문 이력을 실제 HTTP·SQLite 재시작과 비교했다. 구체적 테스트명과 산출물 대응은 로컬 `task-10-reuse-audit.md`에 있다.

최종 계획의 파일명은 실제 배치에 맞췄다. EssayState는 `agent/graph_state.py`, 검토·수정은 `agent/stage_review_nodes.py`, 전달은 `agent/stage_delivery.py`다. 계획의 route_after_review 역할은 `route_review`와 `review_selection.control_for`가 맡는다. DB 환경 변수명은 실제 `ESSAY_DB_PATH`다.

## 도식에 반영할 내용

여섯 논리 단계는 유지한다. 5단계 내부의 검토와 수정이 별도 노드이므로 물리 노드는7개다. 지정 문장/제목 수정은 검토로 돌아가고, 선택한 결과 확정은6단계로만 이동한다. 정보 부족만 남음, 수정 한도 도달, 개선 없음, 수정 실패는 선택본 전달로 이어진다. 실패한 수정도 최대2회 예산에 포함하며 그 실패 뒤 검토 노드를 경유할 때 새 모델 검토는 호출하지 않는다.

원문 인용 위치의 유일한 정확 일치 보정, Python 분량 계산, 선언된 배움/생각의 근거 유형 검사 등은 단계 내부 계약이다. SSE·실행 예약·저장/재조회·재시작 복구는 여섯 단계 바깥의 서비스 계층이다. 단계 추가나 정보 충분성 승인 절차는 없다.

FAST/QUALITY의 역할 구분을 유지하되 실제 검증 결과를 반영해 기본 모델은 둘 다 gpt-4o다. 두 환경 변수로 개별 변경 가능하며 실제 `.env`는 수정하지 않았다. 모델 변경에 따른 비용·응답 시간·품질은 달라질 수 있다.

근거: 로컬 `final-source-audit.json`, `final-root-trace-audit.json`, `task-10-reuse-audit.md`, `task-10-root-live.md`, 공개 `doc/reuse-map.md`와 `doc/architecture-change-log.md`. 로컬 원시 실행 증거는 비공개이며 이 보고서는 검증 결과만 공개한다.
