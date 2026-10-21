import { components } from "./components.js";

const { createApp, computed, reactive, ref } = window.Vue;

createApp({
  components,
  setup() {
    const form = reactive({
      company: "",
      role: "",
      question: "",
      experience: '<img src="example" onerror="alert(1)">\n이 문장은 HTML로 실행하지 않고 원문 그대로 표시합니다.',
      limit: "오백",
      includeSpaces: true,
      subtitle: true,
    });
    const activeStep = ref(3);
    const completedSteps = computed(() => Array.from({ length: activeStep.value - 1 }, (_, index) => index + 1));
    const actionMessage = ref("");
    const longText = "가상의 작성 예시입니다. 동료와 함께 자료를 정리하던 중, 같은 정보를 찾는 데 시간이 반복해서 쓰인다는 점을 발견했습니다. 먼저 자주 묻는 질문을 모으고, 필요한 내용을 어떤 순서로 찾는지 살펴보았습니다.\n\n내용을 나누어 읽을 수 있도록 제목을 붙이고, 서로 다른 표현으로 적힌 항목을 하나의 기준으로 정리했습니다. 결과를 설명할 때는 실제로 확인한 사실과 아직 확인하지 못한 부분을 구분했습니다. 이 문장은 긴 한국어 본문의 줄바꿈과 읽기 폭을 확인하기 위한 예시입니다.\n\n긴문자열도화면밖으로넘치지않고읽을수있어야합니다긴문자열도화면밖으로넘치지않고읽을수있어야합니다긴문자열도화면밖으로넘치지않고읽을수있어야합니다긴문자열도화면밖으로넘치지않고읽을수있어야합니다.";
    const sourceText = "읽기 전용 원문 예시\n가상의 메모: 자료를 정리하고, 동료가 필요한 내용을 찾는 과정을 관찰했습니다.\n사용자 경험이나 실제 기업 자료가 아닙니다.";
    const displayBody = "가상의 본문 예시입니다. 반복되는 질문을 관찰하고 필요한 정보를 정리하는 과정에서, 문제를 구체적으로 정의하는 일의 중요성을 배웠습니다.";
    function showAction() {
      actionMessage.value = "버튼의 응답 상태를 확인했습니다. 서버 요청, 저장 또는 클립보드 복사는 실행하지 않았습니다.";
    }
    function nextStep() {
      activeStep.value = activeStep.value === 6 ? 1 : activeStep.value + 1;
    }
    function resetStep() {
      activeStep.value = 1;
    }
    return { form, activeStep, completedSteps, actionMessage, longText, sourceText, displayBody, showAction, nextStep, resetStep };
  },
}).mount("#app");
