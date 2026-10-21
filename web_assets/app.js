import { components } from "./components.js";
import { ResultView } from "./result-view.js";
import { ApiError, getJson, parseResult, streamEssay } from "./api.js";
import { blankForm, formRequest, newSource, readIds, restoreForm, saveIds, sourceGroups, updateQuestion } from "./form.js";

const { createApp, ref, computed, nextTick, onMounted } = window.Vue;

createApp({
  components: { ...components, ResultView },
  setup() {
    const form = ref(blankForm());
    const health = ref(null);
    const result = ref(null);
    const resultInput = ref(null);
    const restoredInput = ref(null);
    const persistence = ref("unknown");
    const busy = ref(false);
    const loading = ref(false);
    const rendered = ref(false);
    const editing = ref(false);
    const activeStep = ref(0);
    const completed = ref([]);
    const repairs = ref(0);
    const message = ref("");
    const error = ref("");
    const storageWarning = ref("");
    const copyStatus = ref("");
    const copyFallback = ref(false);
    const versions = ref([]);
    const selectedRequest = ref("");
    const lookupId = ref("");
    const selectedQuestion = ref(null);
    const responseKind = ref("answer");
    const answer = ref("");
    const threadId = ref(crypto.randomUUID());
    let pendingRequest = null;
    const canRetry = ref(false);
    const locked = computed(() => busy.value || loading.value);
    const backendLabel = computed(() => health.value ? (health.value.llm_backend === "fake" ? "테스트 모드 · 예시 결과" : "OpenAI 연결") : "서버 연결 미확인");

    function remember(request) {
      try { saveIds(localStorage, request); }
      catch { storageWarning.value = "브라우저 저장소를 사용할 수 없어 새로고침 후 자동 조회가 제한됩니다."; }
    }
    function showError(cause) {
      error.value = cause instanceof ApiError ? `요청 오류 ${cause.status} · ${cause.message}` : cause instanceof Error ? cause.message : "요청을 완료하지 못했습니다. 이전 결과는 유지됩니다.";
    }
    async function showResult(value, status, input) {
      const parsed = parseResult(value);
      rendered.value = false;
      result.value = parsed;
      resultInput.value = input;
      persistence.value = status;
      selectedRequest.value = parsed.request_id;
      copyStatus.value = "";
      copyFallback.value = false;
      editing.value = false;
      selectedQuestion.value = null;
      await nextTick();
      rendered.value = true;
    }
    async function refreshVersions(documentId) {
      const response = await getJson(`/documents/${encodeURIComponent(documentId)}/versions`);
      versions.value = response.versions;
    }
    async function lookup(requestId = lookupId.value, restore = true) {
      if (!requestId) return;
      loading.value = true;
      try {
        const run = await getJson(`/runs/${encodeURIComponent(requestId)}`);
        lookupId.value = requestId;
        if (run.input) {
          threadId.value = run.input.thread_id;
          remember(run.input);
          if (restore) { form.value = restoreForm(run.input); restoredInput.value = run.input; }
        }
        if (run.result) {
          await showResult(run.result, run.persistence_status, run.input);
          await refreshVersions(run.result.document_id);
          canRetry.value = false;
        }
        switch (run.status) {
          case "running": message.value = "서버에서 작성 중입니다. 잠시 후 저장 결과를 다시 조회해 주세요."; break;
          case "completed": message.value = "저장된 결과를 불러왔습니다."; break;
          case "failed":
          case "interrupted": error.value = run.error?.message || "작성이 중단되었습니다. 원문을 확인하고 새 요청으로 작성해 주세요."; canRetry.value = false; break;
          default: throw new Error("저장된 실행 상태를 확인하지 못했습니다.");
        }
      } finally { loading.value = false; }
    }
    async function lookupSafely(requestId) {
      error.value = "";
      try { await lookup(requestId); } catch (cause) { showError(cause); }
    }
    async function receive(event) {
      switch (event.event) {
        case "StageStarted": activeStep.value = event.stage; repairs.value = event.repair_count; break;
        case "StageCompleted": completed.value = [...new Set([...completed.value, event.stage])]; repairs.value = event.repair_count; break;
        case "FinalResult":
          await showResult(event.result, event.persistence_status, pendingRequest);
          message.value = "결과를 받아 화면에 표시했습니다.";
          canRetry.value = false;
          break;
        case "RunError":
          error.value = event.error.message;
          if (!result.value && event.error.last_result) await showResult(event.error.last_result, "unknown", null);
          canRetry.value = false;
          break;
        default: throw new Error("알 수 없는 진행 응답입니다.");
      }
    }
    async function run(request) {
      busy.value = true;
      error.value = "";
      message.value = "작성을 시작했습니다. 검토한 결과가 준비되면 표시합니다.";
      activeStep.value = 0;
      completed.value = [];
      repairs.value = 0;
      lookupId.value = request.request_id;
      pendingRequest = request;
      remember(request);
      canRetry.value = true;
      try {
        await streamEssay(request, receive);
        if (result.value?.request_id === request.request_id && persistence.value === "stored") {
          await lookup(request.request_id);
        }
        if (result.value?.request_id === request.request_id) {
          await nextTick();
          document.getElementById("result-view")?.focus({ preventScroll: true });
          document.getElementById("result-view")?.scrollIntoView({ block: "start" });
        }
      } catch (cause) {
        showError(cause);
        message.value = "입력과 이전 결과는 유지됩니다. 새로 작성하기 전에 저장 결과를 조회해 주세요.";
      } finally { busy.value = false; activeStep.value = 0; }
    }
    async function submit() {
      if (locked.value) return;
      try {
        if (selectedQuestion.value) updateQuestion(form.value, {
          question_key: selectedQuestion.value.question_key, response_kind: responseKind.value, text: answer.value,
        });
        const storedParent = result.value && persistence.value === "stored";
        const request = formRequest(form.value, { thread_id: threadId.value,
          document_id: storedParent ? result.value.document_id : crypto.randomUUID(),
          parent_version_id: storedParent ? result.value.version_id : null });
        await run(request);
      } catch (cause) { showError(cause); }
    }
    async function retryPending() {
      if (!locked.value && pendingRequest) await run(pendingRequest);
    }
    async function supplement(item = null) {
      editing.value = true;
      selectedQuestion.value = item?.question_key && !["unavailable", "not_needed"].includes(item.question_status) ? item : null;
      const existing = form.value.question_updates.find(update => update.question_key === item?.question_key);
      responseKind.value = existing?.response_kind || "answer";
      answer.value = existing?.text || "";
      message.value = "원문을 확인하고 보완한 뒤 ‘새 버전 작성’을 눌러 주세요. 선택만으로는 작성하지 않습니다.";
      await nextTick();
      document.getElementById(selectedQuestion.value ? "question-answer" : "revision-note")?.focus();
    }
    async function copy() {
      copyStatus.value = "";
      try {
        await navigator.clipboard.writeText(result.value.copy_text);
        copyStatus.value = "복사됨 · 제출용 텍스트를 클립보드에 복사했습니다.";
        copyFallback.value = false;
      } catch {
        copyFallback.value = true;
        copyStatus.value = "자동 복사가 허용되지 않았습니다. 아래 선택된 제출용 텍스트를 직접 복사해 주세요.";
        await nextTick();
        const target = document.getElementById("manual-copy");
        target?.focus();
        target?.select();
      }
    }
    function newDocument() {
      form.value = blankForm(); result.value = null; restoredInput.value = null; resultInput.value = null;
      versions.value = []; lookupId.value = ""; selectedQuestion.value = null; pendingRequest = null;
      canRetry.value = false; editing.value = false; error.value = ""; message.value = "새 문서를 작성합니다.";
      completed.value = []; activeStep.value = 0; rendered.value = false; repairs.value = 0;
      copyStatus.value = ""; copyFallback.value = false;
      try { localStorage.removeItem("essay.lookup.ids"); } catch { storageWarning.value = "브라우저 저장소 초기화가 제한됩니다."; }
    }
    onMounted(async () => {
      try { health.value = await getJson("/health"); } catch { message.value = "서버에 연결하지 못했습니다. 입력은 계속할 수 있습니다."; }
      try {
        const ids = readIds(localStorage);
        if (ids) { threadId.value = ids.thread_id; lookupId.value = ids.request_id; await lookup(ids.request_id); }
      } catch (cause) { showError(cause); }
    });
    return { form, health, result, resultInput, restoredInput, persistence, busy, loading, rendered, editing,
      activeStep, completed, repairs, message, error, storageWarning, copyStatus, copyFallback, versions,
      selectedRequest, lookupId, selectedQuestion, responseKind, answer, canRetry, locked, backendLabel,
      sourceGroups, newSource, submit, retryPending, supplement, copy, lookupSafely, newDocument };
  },
}).mount("#app");
