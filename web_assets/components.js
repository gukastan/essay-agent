export const UiIcon = {
  props: { name: { type: String, default: "arrow" }, busy: Boolean },
  computed: {
    path() {
      const paths = {
        arrow: "M5 12h14m-6-6 6 6-6 6",
        check: "m5 12 4 4L19 6",
        chevron: "m6 9 6 6 6-6",
        copy: "M9 9h11v11H9zM15 9V4H4v11h5",
        info: "M12 11v6m0-10v.1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
        warning: "M12 3 2 21h20L12 3Zm0 6v5m0 3v.1",
        error: "m8 8 8 8m0-8-8 8M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
        loader: "M21 12a9 9 0 1 1-9-9",
        edit: "m15 5 4 4M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15l-1 5Z",
      };
      return paths[this.name] ?? paths.info;
    },
  },
  template: `<svg class="ui-icon" :class="{ 'is-spinning': busy }" viewBox="0 0 24 24"
    fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
    stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="path" /></svg>`,
};

export const UiShell = {
  props: { title: String, subtitle: String },
  template: `<div class="ui-shell">
    <a class="ui-skip" href="#main-content">본문으로 이동</a>
    <header class="ui-header"><div class="ui-header-inner">
      <div class="ui-brand">{{ title }}<span v-if="subtitle">{{ subtitle }}</span></div>
      <slot name="header-actions" />
    </div></header>
    <main id="main-content" class="ui-scroll" tabindex="-1"><div class="ui-workspace"><slot /></div></main>
  </div>`,
};

export const UiPanel = {
  props: { id: { type: String, required: true }, title: String, description: String },
  template: `<section class="ui-panel" :aria-labelledby="id + '-title'">
    <div class="ui-panel-heading"><h2 :id="id + '-title'">{{ title }}</h2>
      <p v-if="description" class="ui-muted">{{ description }}</p></div><slot />
  </section>`,
};

export const UiButton = {
  components: { UiIcon },
  props: {
    tone: { type: String, default: "secondary", validator: value => ["primary", "secondary", "quiet"].includes(value) },
    type: { type: String, default: "button" },
    icon: String,
    busy: Boolean,
    disabled: Boolean,
    busyLabel: { type: String, default: "처리 중" },
  },
  emits: ["click"],
  template: `<button class="ui-button" :class="'ui-button--' + tone" :type="type"
    :disabled="disabled || busy" :aria-busy="busy || undefined" @click="$emit('click', $event)">
    <ui-icon v-if="icon || busy" :name="busy ? 'loader' : icon" :busy="busy" />
    <span v-if="busy">{{ busyLabel }}</span><span v-else><slot /></span>
  </button>`,
};

export const UiField = {
  props: {
    id: { type: String, required: true }, label: { type: String, required: true },
    modelValue: { type: String, default: "" }, hint: String, error: String,
    placeholder: String, multiline: Boolean, readonly: Boolean, disabled: Boolean,
    optional: { type: Boolean, default: true }, rows: { type: Number, default: 4 },
    type: { type: String, default: "text" },
  },
  emits: ["update:modelValue"],
  computed: {
    describedBy() {
      return [this.hint && this.id + "-hint", this.error && this.id + "-error"].filter(Boolean).join(" ") || undefined;
    },
  },
  methods: {
    update(event) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
        this.$emit("update:modelValue", event.target.value);
      }
    },
  },
  template: `<div class="ui-field">
    <label :for="id">{{ label }} <span v-if="optional" class="ui-field-optional">선택</span></label>
    <textarea v-if="multiline" :id="id" class="ui-input" :value="modelValue" :rows="rows"
      :placeholder="placeholder" :readonly="readonly" :disabled="disabled"
      :aria-invalid="error ? 'true' : undefined" :aria-describedby="describedBy" @input="update" />
    <input v-else :id="id" class="ui-input" :type="type" :value="modelValue"
      :placeholder="placeholder" :readonly="readonly" :disabled="disabled" autocomplete="off"
      :aria-invalid="error ? 'true' : undefined" :aria-describedby="describedBy" @input="update" />
    <p v-if="hint" :id="id + '-hint'" class="ui-field-hint">{{ hint }}</p>
    <p v-if="error" :id="id + '-error'" class="ui-field-error">{{ error }}</p>
  </div>`,
};

export const UiCheck = {
  props: { id: { type: String, required: true }, modelValue: Boolean, disabled: Boolean },
  emits: ["update:modelValue"],
  methods: {
    update(event) {
      if (event.target instanceof HTMLInputElement) this.$emit("update:modelValue", event.target.checked);
    },
  },
  template: `<label class="ui-check" :for="id">
    <input :id="id" type="checkbox" :checked="modelValue" :disabled="disabled" @change="update" />
    <span><slot /></span></label>`,
};

export const UiNotice = {
  components: { UiIcon },
  props: {
    tone: { type: String, default: "info", validator: value => ["info", "success", "warning", "error"].includes(value) },
    title: { type: String, required: true }, live: Boolean,
  },
  template: `<div class="ui-notice" :class="'ui-notice--' + tone"
    :role="live ? 'status' : undefined" :aria-live="live ? 'polite' : undefined" :aria-atomic="live || undefined">
    <ui-icon :name="tone === 'success' ? 'check' : tone" />
    <div><p class="ui-notice-title">{{ title }}</p><div class="ui-notice-body"><slot /></div></div>
  </div>`,
};

export const UiDisclosure = {
  components: { UiIcon },
  props: { title: { type: String, required: true }, open: Boolean },
  template: `<details class="ui-disclosure" :open="open">
    <summary><span>{{ title }}</span><ui-icon name="chevron" /></summary>
    <div class="ui-disclosure-body"><slot /></div></details>`,
};

export const UiSteps = {
  components: { UiIcon },
  props: {
    active: { type: Number, default: 0 },
    completed: { type: Array, default: () => [] },
    repairCount: { type: Number, default: 0 },
  },
  data() {
    return { labels: ["내용 분석", "구조 설계", "부분 작성", "초안 통합", "검토와 수정", "결과 정리"] };
  },
  methods: {
    state(index) {
      if (this.completed.includes(index + 1)) return "완료";
      return this.active === index + 1 ? "진행 중" : "대기";
    },
  },
  template: `<div class="ui-stage-group">
    <ol class="ui-steps" aria-label="자기소개서 작성 6단계">
      <li v-for="(label, index) in labels" :key="label" :class="{ 'is-current': active === index + 1, 'is-complete': completed.includes(index + 1) }"
        :aria-current="active === index + 1 ? 'step' : undefined">
        <span class="ui-step-number"><ui-icon v-if="completed.includes(index + 1)" name="check" /><span v-else>{{ index + 1 }}</span></span>
        <div><span class="ui-step-label">{{ label }}</span><span class="ui-step-state">{{ state(index) }}</span></div>
      </li></ol>
    <p v-if="repairCount" class="ui-field-hint">검토 단계에서 {{ repairCount }}회 수정 · 최대 2회</p>
  </div>`,
};

export const UiEmpty = {
  props: { title: { type: String, required: true } },
  template: `<div class="ui-empty"><h3>{{ title }}</h3><p><slot /></p></div>`,
};

export const components = Object.freeze({ UiIcon, UiShell, UiPanel, UiButton, UiField, UiCheck, UiNotice, UiDisclosure, UiSteps, UiEmpty });
