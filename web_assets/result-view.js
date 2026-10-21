import { components } from "./components.js";

export const ResultView = {
  components,
  props: { result: { type: Object, required: true }, context: Object, persistence: String, busy: Boolean, copyStatus: String },
  emits: ["copy", "supplement"],
  computed: {
    quality() { return this.result.quality_report; },
    length() { return this.quality.length_check; },
    status() { return ({ reviewed_draft: "검토한 초안", needs_attention: "확인할 내용이 있는 초안", review_incomplete: "검토가 일부 남은 초안" })[this.quality.display_status]; },
    requiredCount() { return this.result.suggestions.filter(item => item.category !== "optional").length; },
  },
  methods: {
    coverage(value) { return ({ supported: "근거를 반영함", general: "일반적인 내용", not_expressed: "아직 작성되지 않음", unassessed: "확인하지 못함" })[value]; },
    check(value) { return ({ met: "충족", partial: "일부 충족", unmet: "보완 필요", unassessed: "미검증", not_applicable: "해당 없음" })[value]; },
    category(value) { return ({ required_edit: "필수 수정", required_info: "필수 확인", optional: "선택 개선" })[value]; },
    questionState(value) { return ({ proposed: "선택하면 답변을 적을 수 있어요", asked: "답변 대기", resolved: "답변 반영", unavailable: "확인 불가로 처리됨", not_needed: "답변하지 않음으로 처리됨" })[value]; },
  },
  template: `<div class="ui-stack ui-result" id="result-view" tabindex="-1">
    <ui-panel id="draft" :title="status">
      <div class="ui-stack">
        <p class="ui-muted">{{ context?.company_name || '기업 미입력' }} · {{ context?.job_title || '직무 미입력' }}</p>
        <p class="ui-prose ui-field-hint">{{ context?.question || '문항 미입력' }}</p>
        <ui-notice v-if="quality.key_guidance.length" title="초안과 함께 확인해 주세요" tone="warning">
          <ul class="ui-list"><li v-for="line in quality.key_guidance" :key="line">{{ line }}</li></ul>
        </ui-notice>
        <ui-notice v-if="result.generation_status === 'completed_with_fallback'" title="일부 대체 처리된 결과" tone="warning">작성 과정의 일부 오류로 대체 결과가 포함되었습니다. 초안은 그대로 읽고 복사할 수 있습니다.</ui-notice>
        <div class="ui-stack ui-draft-copy">
          <p class="ui-field-hint">{{ result.subtitle_placement === 'display_only' ? '참고 소제목 · 제출용 복사에서 제외' : '소제목' }}</p>
          <h2>{{ result.subtitle }}</h2>
          <p class="ui-prose">{{ result.body }}</p>
        </div>
        <div class="ui-cluster"><ui-button icon="copy" tone="primary" @click="$emit('copy')">제출용 복사</ui-button><span class="ui-field-hint">{{ result.subtitle_placement === 'display_only' ? '본문만 복사합니다.' : '소제목과 본문을 복사합니다.' }}</span></div>
        <ui-notice v-if="copyStatus" title="복사 상태" live>{{ copyStatus }}</ui-notice>
        <p class="ui-field-hint">{{ persistence === 'stored' ? '저장됨 · 이전 버전에서 다시 열 수 있습니다.' : '저장되지 않았거나 저장 여부가 불명확합니다. 새로고침 전에 복사해 주세요.' }}</p>
      </div>
    </ui-panel>
    <ui-panel id="length" title="분량과 제출 조건">
      <div class="ui-stack">
        <p><strong>{{ result.character_count }}자</strong> <span class="ui-muted">{{ length.max_chars === null ? '최대 분량 미지정' : '/ 최대 ' + length.max_chars + '자' }}</span></p>
        <p class="ui-field-hint">서버 실측 · 공백 {{ result.length_policy.include_spaces ? '포함' : '제외' }} · 줄바꿈 {{ result.length_policy.include_newlines ? '포함' : '제외' }} · 소제목 {{ length.includes_subtitle ? '포함' : '제외' }}</p>
        <p class="ui-field-hint">본문 {{ length.body_chars }}자 · 소제목 {{ length.subtitle_chars }}자 · 구분자 {{ length.separator_chars }}자 · 조건 {{ check(length.condition_status) }}</p>
        <p v-if="length.status === 'over'">최대 분량을 넘었습니다. 제출 전 분량을 조정해 주세요.</p>
        <p class="ui-prose ui-field-hint">{{ quality.subtitle_reason }}</p>
        <ul v-if="length.notes.length" class="ui-list ui-field-hint"><li v-for="note in length.notes" :key="note">{{ note }}</li></ul>
        <ui-notice v-if="quality.unverified_conditions.length || quality.technical_limits.length" title="아직 확인하지 못한 조건" tone="warning"><ul class="ui-list"><li v-for="note in [...quality.unverified_conditions, ...quality.technical_limits]" :key="note">{{ note }}</li></ul></ui-notice>
        <ui-disclosure title="사용한 근거 확인"><ul class="ui-list ui-field-hint"><li v-for="source in result.source_summary" :key="source.source_kind">{{ ({ applicant: '경험·생각', company: '기업 자료', job_posting: '채용 공고' })[source.source_kind] }} · 제공 원문 {{ source.provided_source_count }}개 / 실제 사용한 근거 {{ source.used_fact_count }}개</li></ul></ui-disclosure>
      </div>
    </ui-panel>
    <ui-panel id="structure" title="글이 이렇게 구성되었어요" description="작성 의도와 최종 본문에 실제 반영된 문장을 구분합니다.">
      <div class="ui-stack">
        <article v-for="(entry, index) in result.structure" :key="entry.section_id" class="ui-section-entry ui-stack">
          <h3>{{ index + 1 }}. {{ entry.purpose }}</h3>
          <p class="ui-prose ui-muted">작성 의도 · {{ entry.intended_content }}</p>
          <p class="ui-field-hint">현재 반영 · {{ coverage(entry.coverage) }}</p>
          <div v-for="location in entry.locations" :key="location.paragraph_id" class="ui-excerpt"><p class="ui-field-hint">{{ location.paragraph_number }}번째 문단</p><p v-for="(excerpt, n) in location.excerpts" :key="n" class="ui-prose">{{ excerpt }}</p></div>
          <p v-if="!entry.locations.length" class="ui-muted">{{ entry.coverage === 'not_expressed' ? '이 부분은 아직 작성되지 않았습니다.' : '반영된 문장 위치를 확인하지 못했습니다.' }}</p>
          <p v-if="entry.requirement_statuses.length" class="ui-field-hint">문항 요구 · <span v-for="(requirement, n) in entry.requirement_statuses" :key="requirement.requirement_id">{{ n + 1 }}: {{ check(requirement.status) }} </span></p>
          <ul v-if="entry.missing_info.length" class="ui-list ui-muted"><li v-for="info in entry.missing_info" :key="info">남은 내용 · {{ info }}</li></ul>
        </article>
      </div>
    </ui-panel>
    <ui-panel id="suggestions" title="필요한 부분부터 보완하기" :description="'필수 보완 ' + requiredCount + '개 · 전체 ' + result.suggestions.length + '개. 지금 답하지 않아도 초안을 이용할 수 있습니다.'">
      <p v-if="!requiredCount" class="ui-muted">남은 필수 보완 없음</p>
      <div class="ui-stack">
        <article v-for="item in result.suggestions" :key="item.priority" class="ui-section-entry ui-stack">
          <h3>{{ item.priority }}. {{ category(item.category) }}</h3>
          <div v-for="location in item.locations" :key="location.paragraph_id" class="ui-excerpt"><p class="ui-field-hint">{{ location.paragraph_number }}번째 문단</p><p v-for="(excerpt, n) in location.excerpts" :key="n" class="ui-prose">{{ excerpt }}</p></div>
          <p v-if="!item.locations.length" class="ui-field-hint">{{ item.area === 'body' ? '미작성 부분 또는 위치를 확인하지 못한 내용' : '소제목 또는 답변 전체의 조건' }}</p>
          <p class="ui-prose">{{ item.missing_detail }}</p><p class="ui-prose ui-muted">{{ item.why_it_helps }}</p><p class="ui-prose">{{ item.next_action }}</p>
          <p v-if="item.example_question && !['unavailable', 'not_needed'].includes(item.question_status)" class="ui-prose ui-muted">{{ item.example_question }}</p>
          <p class="ui-field-hint">{{ questionState(item.question_status) }}</p>
          <div><ui-button :disabled="busy" @click="$emit('supplement', item)">{{ ['unavailable', 'not_needed'].includes(item.question_status) ? '새 정보가 있으면 원문 보완' : '이 부분 보완하기' }}</ui-button></div>
        </article>
        <p v-if="!result.suggestions.length" class="ui-muted">추가로 제안된 보완 항목이 없습니다.</p>
      </div>
    </ui-panel>
  </div>`,
};
