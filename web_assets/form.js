export const sourceGroups = Object.freeze([
  { key: "experiences", title: "경험", hint: "했던 일과 직접 확인한 결과를 자유롭게 적어 주세요." },
  { key: "user_views", title: "생각과 가치관", hint: "일하는 방식이나 중요하게 생각하는 점을 적어 주세요." },
  { key: "company_sources", title: "기업 자료", hint: "참고할 기업 자료의 원문을 붙여 넣어 주세요." },
]);

export function newSource() {
  return { source_id: `user-${crypto.randomUUID()}`, text: "" };
}

export function blankForm() {
  return {
    company_name: "", job_title: "", question: "", experiences: [newSource()], user_views: [newSource()],
    company_sources: [newSource()], job_posting_text: "", tone: "담백한 존댓말", max_chars: "",
    include_spaces: true, include_newlines: true, include_subtitle: false,
    revision_instruction: "", question_updates: [],
  };
}

export function restoreForm(input) {
  const form = blankForm();
  for (const field of ["company_name", "job_title", "question", "job_posting_text", "tone", "revision_instruction"]) form[field] = input[field] ?? "";
  for (const { key } of sourceGroups) form[key] = input[key]?.length ? input[key].map(source => ({ source_id: source.source_id, text: source.text })) : [newSource()];
  for (const field of ["include_spaces", "include_newlines", "include_subtitle"]) form[field] = input.length_policy[field];
  form.max_chars = input.length_policy.max_chars === null ? "" : String(input.length_policy.max_chars);
  form.question_updates = (input.question_updates ?? []).map(update => ({ ...update }));
  return form;
}

export function formRequest(form, lineage) {
  const max = form.max_chars.trim();
  if (max && (!/^[0-9]+$/.test(max) || !Number.isSafeInteger(Number(max)) || Number(max) < 1)) {
    throw new Error("최대 글자 수는 양의 정수로 입력하거나 비워 주세요.");
  }
  const request = {
    request_id: crypto.randomUUID(), thread_id: lineage.thread_id,
    document_id: lineage.document_id, parent_version_id: lineage.parent_version_id,
    length_policy: { max_chars: max ? Number(max) : null, include_spaces: form.include_spaces,
      include_newlines: form.include_newlines, include_subtitle: form.include_subtitle },
    question_updates: form.question_updates.map(update => ({ ...update })),
  };
  for (const field of ["company_name", "job_title", "question", "job_posting_text", "revision_instruction"]) request[field] = form[field] || null;
  request.tone = form.tone;
  for (const { key } of sourceGroups) request[key] = form[key].filter(source => source.text.trim()).map(source => ({ source_id: source.source_id, text: source.text }));
  return request;
}

export function updateQuestion(form, response) {
  if (response.response_kind === "answer" && !response.text?.trim()) throw new Error("답변을 적거나 ‘확인 불가’ 또는 ‘답변하지 않음’을 선택해 주세요.");
  const value = { question_key: response.question_key, response_kind: response.response_kind,
    text: response.response_kind === "answer" ? response.text : null };
  form.question_updates = [...form.question_updates.filter(item => item.question_key !== value.question_key), value];
}

export function readIds(storage) {
  const value = JSON.parse(storage.getItem("essay.lookup.ids") || "null");
  if (!value) return null;
  const keys = ["thread_id", "document_id", "request_id"];
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (keys.some(key => !uuid.test(value[key]))) return null;
  return Object.fromEntries(keys.map(key => [key, value[key]]));
}

export function saveIds(storage, request) {
  storage.setItem("essay.lookup.ids", JSON.stringify({ thread_id: request.thread_id, document_id: request.document_id, request_id: request.request_id }));
}
