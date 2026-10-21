import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { ApiError, EventDecoder, parseResult, streamEssay } from "../web_assets/api.js";
import { blankForm, formRequest, readIds, restoreForm, saveIds, updateQuestion } from "../web_assets/form.js";
import { components } from "../web_assets/components.js";
import { ResultView } from "../web_assets/result-view.js";

const fixture = JSON.parse(await readFile(new URL("./fixtures/complete.json", import.meta.url), "utf8"));
const result = fixture.result;
const encoder = new TextEncoder();
const final = { event: "FinalResult", result, persistence_status: "stored" };
const frames = `: keepalive\r\ndata: ${JSON.stringify(final)}\r\n\r\ndata: [DONE]\r\n\r\n`;

test("UTF8 and CRLF events survive every byte split", () => {
  const bytes = encoder.encode(frames);
  for (let split = 0; split <= bytes.length; split++) {
    const decoder = new EventDecoder();
    const events = [...decoder.push(bytes.slice(0, split)), ...decoder.push(bytes.slice(split)), ...decoder.push(undefined, true)];
    assert.deepEqual(JSON.parse(events[0]), final);
    assert.equal(events[1], "[DONE]");
    assert.equal(events.length, 2);
  }
});

test("single-byte chunks and multiline data preserve Korean and astral characters", () => {
  const decoder = new EventDecoder();
  const bytes = encoder.encode('data: {"text":\ndata: "한글𠮷"}\n\n');
  const events = [];
  for (const byte of bytes) events.push(...decoder.push(Uint8Array.of(byte)));
  events.push(...decoder.push(undefined, true));
  assert.deepEqual(JSON.parse(events[0]), { text: "한글𠮷" });
});

test("truncated event and malformed UTF8 fail instead of reporting completion", () => {
  const decoder = new EventDecoder();
  decoder.push(encoder.encode('data: {"text":"한글"}'));
  assert.throws(() => decoder.push(undefined, true));
  assert.throws(() => new EventDecoder().push(Uint8Array.of(0xff), true));
});

function streamingResponse(text) {
  const bytes = encoder.encode(text);
  let position = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (position >= bytes.length) controller.close();
      else { controller.enqueue(bytes.slice(position, position + 7)); position += 7; }
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

test("POST reader emits one final only after complete event bytes", async context => {
  const seen = [];
  context.mock.method(globalThis, "fetch", async (path, options) => {
    assert.equal(path, "/chat/stream");
    assert.equal(options.method, "POST");
    assert.equal(JSON.parse(options.body).request_id, result.request_id);
    return streamingResponse(frames);
  });
  const terminal = await streamEssay({ request_id: result.request_id }, event => { seen.push(event); });
  assert.deepEqual(terminal, final);
  assert.deepEqual(seen, [final]);
  assert.equal(terminal.result.copy_text, result.copy_text);
});

test("DONE and stage completion never become a generated result", async context => {
  context.mock.method(globalThis, "fetch", async () => streamingResponse('data: [DONE]\n\n'));
  const seen = [];
  await assert.rejects(streamEssay({ request_id: result.request_id }, event => seen.push(event)));
  assert.deepEqual(seen, []);
});

test("HTTP 409 and error envelope survive the browser transport", async context => {
  context.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ error: { code: "request_conflict", message: "conflict" } }), { status: 409 }));
  await assert.rejects(streamEssay({ request_id: result.request_id }, () => {}), error => error instanceof ApiError && error.status === 409 && error.payload.code === "request_conflict");
});

test("stream errors are returned as the terminal error envelope", async context => {
  const event = { event: "RunError", error: { request_id: result.request_id, message: "failed", last_result: null } };
  context.mock.method(globalThis, "fetch", async () => streamingResponse(`data: ${JSON.stringify(event)}\n\ndata: [DONE]\n\n`));
  const observed = await streamEssay({ request_id: result.request_id }, received => { assert.equal(received.event, "RunError"); });
  assert.deepEqual(observed, event);
});

test("duplicate terminal and mismatched request are rejected", async context => {
  context.mock.method(globalThis, "fetch", async () => streamingResponse(`data: ${JSON.stringify(final)}\n\ndata: ${JSON.stringify(final)}\n\n`));
  await assert.rejects(streamEssay({ request_id: result.request_id }, () => {}));
  await assert.rejects(streamEssay({ request_id: crypto.randomUUID() }, () => {}));
});

test("malformed result does not pass the render boundary", () => {
  assert.throws(() => parseResult({ body: "partial" }));
  assert.equal(parseResult(result), result);
});

test("empty form produces a valid empty source snapshot without a content gate", () => {
  const request = formRequest(blankForm(), { thread_id: crypto.randomUUID(), document_id: crypto.randomUUID(), parent_version_id: null });
  assert.equal(request.question, null);
  assert.equal(request.length_policy.max_chars, null);
  assert.deepEqual(request.experiences, []);
  assert.deepEqual(request.user_views, []);
  assert.deepEqual(request.company_sources, []);
});

test("restoration preserves every source ID, category and exact raw text", () => {
  const input = structuredClone(fixture.request);
  input.experiences = [{ source_id: "experience-a", text: "  원문\r\n한글 " }, { source_id: "answer:q-1", text: "보완 답변" }];
  input.user_views = [{ source_id: "view-a", text: "생각 하나" }, { source_id: "view-b", text: "생각 둘" }];
  input.company_sources = [{ source_id: "company-a", text: "자료 하나" }, { source_id: "company-b", text: "자료 둘" }];
  input.question_updates = [{ question_key: "raw:q-1", response_kind: "unavailable", text: null }];
  const restored = restoreForm(input);
  restored.revision_instruction = "간결하게";
  const revised = formRequest(restored, { thread_id: input.thread_id, document_id: input.document_id, parent_version_id: result.version_id });
  for (const key of ["experiences", "user_views", "company_sources", "question_updates"]) assert.deepEqual(revised[key], input[key]);
  assert.equal(revised.parent_version_id, result.version_id);
  assert.notEqual(revised.request_id, input.request_id);
  assert.ok(!("previous_draft" in revised));
  assert.ok(!("revision_context" in revised));
});

test("question response transitions preserve raw key and clear non-answer text", () => {
  const form = blankForm();
  updateQuestion(form, { question_key: "raw:q-2", response_kind: "answer", text: "  실제 답변  " });
  assert.equal(form.question_updates[0].text, "  실제 답변  ");
  updateQuestion(form, { question_key: "raw:q-2", response_kind: "unavailable", text: "discard" });
  assert.deepEqual(form.question_updates, [{ question_key: "raw:q-2", response_kind: "unavailable", text: null }]);
  updateQuestion(form, { question_key: "raw:q-2", response_kind: "not_needed", text: "discard" });
  assert.equal(form.question_updates[0].response_kind, "not_needed");
  assert.throws(() => updateQuestion(form, { question_key: "raw:q-2", response_kind: "answer", text: " " }));
});

test("browser storage holds only three UUIDs even from a full request", () => {
  const values = new Map();
  const storage = { setItem: (key, value) => values.set(key, value), getItem: key => values.get(key) };
  const request = formRequest(blankForm(), { thread_id: crypto.randomUUID(), document_id: crypto.randomUUID(), parent_version_id: null });
  saveIds(storage, request);
  const ids = readIds(storage);
  assert.deepEqual(Object.keys(ids).sort(), ["document_id", "request_id", "thread_id"]);
  assert.equal(values.size, 1);
  assert.ok(!values.get("essay.lookup.ids").includes("experiences"));
});

test("product and showcase HTML5 normalization preserves controls before Vue compile", async () => {
  const response = await fetch("https://unpkg.com/vue@3/dist/vue.global.prod.js");
  assert.ok(response.ok);
  const errors = [];
  const context = { console: { ...console, warn: (...items) => errors.push(items), error: (...items) => errors.push(items) } };
  runInNewContext(await response.text(), context);
  const parserResponse = await fetch("https://esm.sh/parse5@7.2.1/node/parse5.bundle.mjs");
  assert.ok(parserResponse.ok);
  const parser = await import(`data:text/javascript;base64,${Buffer.from(await parserResponse.text()).toString("base64")}`);
  const compileOptions = { decodeEntities: value => {
    const fragment = parser.parseFragment(`<textarea>${value.replaceAll("<", "&lt;")}</textarea>`);
    return fragment.childNodes[0].childNodes.map(node => node.value || "").join("");
  } };
  for (const component of [...Object.values(components), ResultView]) context.Vue.compile(component.template, compileOptions);
  for (const page of ["../web_chat.html", "../web_assets/showcase.html"]) {
    const html = await readFile(new URL(page, import.meta.url), "utf8");
    const parseErrors = [];
    const tree = parser.parse(html, { onParseError: error => parseErrors.push(error.code) });
    assert.ok(!parseErrors.includes("non-void-html-element-start-tag-with-trailing-solidus"), page);
    const nodes = [];
    function visit(node) {
      nodes.push(node);
      for (const child of node.childNodes || []) visit(child);
      if (node.content) visit(node.content);
    }
    visit(tree);
    const app = nodes.find(node => node.attrs?.some(attr => attr.name === "id" && attr.value === "app"));
    assert.ok(app);
    const leaves = nodes.filter(node => ["ui-field", "ui-steps", "result-view"].includes(node.tagName));
    assert.ok(leaves.length > 0);
    for (const node of leaves) assert.equal(node.childNodes.length, 0, `${node.tagName} swallowed sibling HTML`);
    assert.ok(nodes.some(node => node.tagName === "ui-button"));
    if (page === "../web_chat.html") assert.ok(nodes.some(node => node.tagName === "ui-button" && node.attrs.some(attr => attr.name === "type" && attr.value === "submit")));
    context.Vue.compile(parser.serialize(app), compileOptions);
    assert.deepEqual(errors, []);
    assert.ok(!html.includes("v-html"));
  }
});
