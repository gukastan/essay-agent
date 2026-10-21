# 자기소개서 서비스 API와 상태 계약

설치와 실행은 [프로젝트 README](../README.md), 변경 대응은 [재사용 지도](reuse-map.md)를 참고한다. 화면은 선택 입력 → 여섯 단계 진행 → 소제목/본문/구조/보완 제안 → 원문 보완과 새 버전 생성 순서다. 정보가 적어도 제출 가능하며 질문 답변을 강제하지 않는다.

FAST와 QUALITY 역할의 기본 모델은 모두 `gpt-4o`이며, 역할 구분은 유지한다. `OPENAI_FAST_MODEL`과 `OPENAI_QUALITY_MODEL` 환경 변수로 각각 변경할 수 있다. 모델과 입력에 따라 비용, 응답 시간, 생성 품질은 달라진다.

## 공개 경로

| 메서드·경로 | 응답 |
| --- | --- |
| GET `/health` | backend, 모델명, MCP 상태, lifespan 생성 수, 활성 실행 수 |
| POST `/chat` | `{result: EssayResult, metadata: {persistence_status}}` |
| POST `/chat/stream` | `data: <JSON>` SSE; 마지막 `data: [DONE]` |
| GET `/runs/{request_id}` | request_id, status, result, error, persistence_status, input |
| GET `/documents/{document_id}/versions` | document_id와 저장된 완료 버전 목록 |

`GET /runs/...`의 `input`이 편집 가능한 정규화 원본 폼이다. 별도 `/input` 경로는 없다. 프록시도 같은 경로·상태·오류를 보존한다. 원문, 키, 서버 내부 revision_context는 브라우저 저장소에 보관하지 않는다. localStorage에는 복원용 ID만 둔다.

## 요청과 수정

```bash
curl -sS http://127.0.0.1:8100/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"협업 경험을 설명하세요.","experiences":[{"source_id":"experience-1","text":"자료 취합을 담당하고 공통 양식을 만들었습니다."}]}'
```

`{}`도 유효하다. request_id/thread_id/document_id는 생략 시 생성된다. 재전송·연결 복구에는 호출자가 동일 UUID를 보존하는 편이 좋다. 동일 document/request와 동일 정규화 입력을 POST로 다시 보내면 실행 중에는 409와 `Location: /runs/{request_id}`를 반환한다. 해당 경로의 GET으로 상태·결과를 조회하며, POST가 기존 스트림에 재연결되지는 않는다. 완료된 동일 요청은 저장된 결과를 재사용한다. 같은 ID에 다른 입력 또는 다른 문서를 넣어도 409다. 실제 수정은 새로운 request_id와 같은 document_id, 저장된 parent_version_id를 보낸다. 전체 원문 스냅샷을 포함하며 빠진 원문을 이전 AI 문장에서 채우지 않는다.

선택적 질문 응답은 현재 입력의 `question_updates`에 넣는다. 실제 응답에서 받은 question_key를 그대로 사용한다.

```json
{"question_updates":[{"question_key":"응답에서 받은 키","response_kind":"unavailable","text":null}]}
```

`answer`는 빈 값이 아닌 text를, `unavailable`/`not_needed`는 null을 사용한다. 수정 시에는 저장된 부모와 전체 입력을 함께 보낸다. 서버가 답변을 원문으로 정규화하고 질문 이력을 관리한다. `previous_draft`, `revision_context`, `stored_parent`는 요청 필드가 아니며 클라이언트가 주입할 수 없다. 이전 AI 본문은 서버가 같은 문서의 저장된 부모에서 읽어 작성/통합의 편집 참고로만 전달한다.

## 진행과 결과

SSE는 `StageStarted`, `StageCompleted`의 request_id/stage(1..6)/repair_count(0..2)를 전달한다. 제목 검토와 수정은 모두 stage5이고 수정 루프가 실제로 실행될 때만 반복한다. 정상 종료는 정확히 한 `FinalResult`와 `[DONE]`, 실행 오류는 한 `RunError`와 `[DONE]`이다. 형식·식별자 오류는 SSE 시작 전 일반 HTTP 422/409/404 등으로 반환한다. 연결이 끊겨도 실행은 계속되며 GET 조회로 복구한다.

최종 result의 subtitle/body/copy_text, structure, suggestions, quality_report를 함께 읽는다. structure의 위치와 발췌는 최종 문장을 가리키며 미작성 행은 계획만 나타낸다. `source_supported` 등 현재 문장 검토가 없는 개인 표현을 검증 완료로 표시하지 않는다. 화면의 복사는 서버 copy_text를 그대로 사용한다.

`generation_status=completed|completed_with_fallback`은 생성 완료 유형이고 `quality_report.display_status`의 `reviewed_draft|needs_attention|review_incomplete`와 다르다. `review_status=performed|partial|unavailable`은 검토 수행 범위다. `pending_review`는 수정 후보의 내부 이력 상태로, 최종 전달 전에 accepted/rejected/no_change/failed로 확정된다.

길이는 서버에서 NFC·LF로 정규화한 계수 대상에 대해 계산하되 실제 표시·복사 문자는 보존한다. 공백/줄바꿈 포함과 제목 포함 정책, 실제 길이, 초과/미평가 조건을 함께 보여 준다. 제목 금지의 `display_only` 제목은 화면 참고용이며 제출 복사에서는 빠진다. 미상 최대 길이에 임의 목표를 만들지 않는다.

## 오류와 저장

모든 기술 오류의 `RunErrorPayload` 모양은 같다. 원문/SQL/키/모델 진단을 오류 메시지에 노출하지 않는다.

```json
{"error":{"request_id":null,"generation_status":"technical_error","code":"invalid_request","message":"요청 형식을 확인해 주세요.","last_result":null}}
```

SSE 오류는 이 payload를 `{event:"RunError", error:...}`로 감싼다. 가능한 경우 last_result는 사용 가능한 이전 초안이며 UI는 기존 결과를 보존한다. `persistence_status=stored|failed|unknown|pending`은 저장 결과다. 생성 성공 후 저장 실패도 초안은 반환한다. unknown이면 같은 request_id로 조회하여 확인하고 무조건 새 요청을 만들지 않는다.

실행 상태는 running/completed/failed/interrupted다. 앱 재시작 시 소유 worker가 없는 실행은 interrupted로 바꾸고 기존 완료 버전과 messages 테이블은 유지한다. 실행기는 DB를 삭제하지 않는다. 부족한 정보·낮은 품질 자체는 기술 오류나 작성 거부 사유가 아니다.
