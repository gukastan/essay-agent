export class ApiError extends Error {
  constructor(status, payload) {
    super(payload?.message || "요청을 완료하지 못했습니다. 입력과 이전 결과는 유지됩니다.");
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export class EventDecoder {
  constructor() {
    this.decoder = new TextDecoder("utf-8", { fatal: true });
    this.buffer = "";
    this.data = [];
  }
  push(bytes, final = false) {
    this.buffer += this.decoder.decode(bytes, { stream: !final });
    if (this.buffer.length > 8_000_000) throw new Error("응답이 너무 커서 연결을 중단했습니다.");
    const events = [];
    while (true) {
      const separator = this.buffer.search(/[\r\n]/);
      if (separator < 0 || (!final && separator === this.buffer.length - 1 && this.buffer[separator] === "\r")) break;
      const line = this.buffer.slice(0, separator);
      const size = this.buffer.slice(separator, separator + 2) === "\r\n" ? 2 : 1;
      this.buffer = this.buffer.slice(separator + size);
      if (line === "") {
        if (this.data.length) events.push(this.data.join("\n"));
        this.data = [];
      } else if (line.startsWith("data:")) {
        this.data.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (final && (this.buffer || this.data.length)) throw new Error("응답 연결이 끝나기 전에 끊겼습니다. 저장 결과를 조회해 주세요.");
    return events;
  }
}

export function parseResult(value) {
  const strings = ["document_id", "request_id", "version_id", "subtitle", "body", "copy_text", "generation_status"];
  if (!value || strings.some(key => typeof value[key] !== "string") || !Number.isInteger(value.character_count)
      || !Array.isArray(value.structure) || !Array.isArray(value.suggestions) || !Array.isArray(value.source_summary)
      || !value.quality_report?.length_check || !value.length_policy) {
    throw new Error("결과 형식을 확인하지 못했습니다. 저장 결과를 조회해 주세요.");
  }
  return value;
}

async function checked(response) {
  if (!response.ok) {
    let payload;
    try { payload = (await response.json()).error; } catch { payload = null; }
    throw new ApiError(response.status, payload);
  }
  return response;
}

export async function getJson(path) {
  const response = await checked(await fetch(path, { signal: AbortSignal.timeout(15000) }));
  return response.json();
}

export async function streamEssay(request, onEvent) {
  const response = await checked(await fetch("/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request), signal: AbortSignal.timeout(600000),
  }));
  if (!response.headers.get("content-type")?.includes("text/event-stream") || !response.body) {
    throw new Error("진행 응답을 읽을 수 없습니다. 저장 결과를 조회해 주세요.");
  }
  const reader = response.body.getReader();
  const decoder = new EventDecoder();
  let terminal = null;
  let ended = false;
  try {
    while (!ended) {
      const { value, done } = await reader.read();
      for (const data of decoder.push(value, done)) {
        if (data === "[DONE]") {
          if (!terminal) throw new Error("결과 없이 진행 응답이 종료되었습니다. 저장 결과를 조회해 주세요.");
          ended = true;
          continue;
        }
        if (ended || terminal) throw new Error("결과 뒤에 중복 응답이 도착했습니다.");
        const event = JSON.parse(data);
        switch (event.event) {
          case "StageStarted":
          case "StageCompleted":
            if (event.request_id !== request.request_id || !Number.isInteger(event.stage) || event.stage < 1 || event.stage > 6) {
              throw new Error("진행 응답의 요청 또는 단계를 확인하지 못했습니다.");
            }
            break;
          case "FinalResult":
            parseResult(event.result);
            if (event.result.request_id !== request.request_id) throw new Error("다른 요청의 결과가 도착했습니다.");
            terminal = event;
            break;
          case "RunError":
            if (event.error?.request_id !== request.request_id) throw new Error("오류 응답의 요청을 확인하지 못했습니다.");
            terminal = event;
            break;
          default: throw new Error("알 수 없는 진행 응답입니다.");
        }
        await onEvent(event);
      }
      if (done && !ended) throw new Error("연결이 끊겼습니다. 새로 작성하기 전에 저장 결과를 조회해 주세요.");
    }
    return terminal;
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
