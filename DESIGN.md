# 자기소개서 작성 도우미 · Design system

This is the approved extraction of the original `web_chat.html` dark/purple interface. Vue 3 remains a CDN runtime with no build step. Root accepted the foundation and connected frontend/proxy through Computer Use on2026-10-22; Task7 API acceptance is complete. The shared implementation lives in `web_assets/`; `showcase.html` remains an isolated state harness. UI acceptance is recorded in [task-8-browser.md](../.omo/evidence/essay-agent/task-8-browser.md). Live model semantic quality remains a separate COVER-11 integration issue and is not established by fake-backend UI tests.

## 1. Atmosphere & identity

A focused writing workspace with a deep blue-purple background, quiet tonal panels and a solid violet primary action. The recognizable identity is the original `#1e1e2e` page, `#262638` chrome and `#5b5bd6` action color. The reading area receives more space than supporting controls. Korean labels describe the next action directly. Sparse information and incomplete review never become a refusal to show a draft.

The user explicitly chose extraction of the existing look and reusable components. No new brand, hero, gradients, glass, decorative stripes, emoji icons, light theme or framework migration is part of this direction. The approved dark appearance also applies when the operating system prefers light mode.

References: existing page CSS is the visual source; the [StyleGallery scroll-body-shell](https://github.com/changeroa/StyleGallery/blob/main/patterns/viewport-shell/scroll-body-shell.md) contributes scroll ownership only; [beui action-swap](https://beui.dev/r/action-swap/raw) contributes stable control identity and semantic outcome feedback only. Neither external component code nor palette is copied.

## 2. Color

All color values below already exist in the source interface; its named `white` becomes `#ffffff`. `tokens.css :root` is their single CSS definition site. Components use semantic variables.

| Token | Value | Usage |
| --- | --- | --- |
| `--surface-page` | `#1e1e2e` | Page and input fill |
| `--surface-chrome` | `#262638` | Header, secondary action |
| `--surface-panel` | `#2e2e42` | Grouped content |
| `--surface-inset` | `#17171f` | Read-only excerpt and example text |
| `--text-primary` | `#e2e2f0` | Headings, body and input values |
| `--text-muted` | `#9a9ac0` | Supporting labels and hints |
| `--text-accent-muted` | `#8b8bd8` | Page/header eyebrow only; never small text on panel |
| `--text-on-accent` | `#ffffff` | Primary action text |
| `--accent-primary` | `#5b5bd6` | Primary action fill |
| `--border-default` | `#3a3a52` | Neutral panel separators |
| `--border-control` | `var(--text-muted)` | Identifiable editable control boundary |
| `--control-disabled` | `#3a3a52` | Disabled action fill, with primary text retained |
| `--scroll-thumb` | `#3a3a52` | Scrollbar |
| `--scroll-thumb-hover` | `#4a4a68` | Scrollbar hover |
| `--status-success` | `#7ee787` | Completed state text/icon |
| `--focus-ring` | `var(--text-primary)` | Keyboard focus-visible outline |

Warning and error states use explicit Korean labels and SVG symbols with primary text, rather than introducing red or amber. They remain distinguishable without color. A panel never gets a colored one-sided border. Focus-visible outlines and form control boundaries are functional boundaries.

Source contrast calculation: primary/page 12.79:1; primary/panel 10.32:1; muted/panel 4.89:1; white/accent 5.37:1; success/panel 8.62:1. Accent-muted/panel is only 4.28:1, so it is excluded from small panel text; accent-muted/page is 5.30:1. These mathematical checks complement root's recorded browser focus/state/layout review; they do not establish complete accessibility conformance.

The original `#11111a` and `#c3c3e0` belonged to raw prompt inspection. They are deliberately unused because that feature does not belong in the essay UI. No unrelated color has replaced them.

## 3. Typography

Font: `-apple-system, "Apple SD Gothic Neo", sans-serif`. No remote font or new font family. Source values: header15px/600, supporting13px, controls/body14px, captions12px, bubble line-height1.5. The foundation keeps these as named roles and adds a readable prose/title hierarchy for a multi-field writing interface.

| Token | Value | Role |
| --- | --- | --- |
| `--font-caption` | `0.75rem` | Compact numbered stage metadata |
| `--font-small` | `0.8125rem` | Hints and status descriptors |
| `--font-control` | `0.875rem` | Actions, labels and stage names |
| `--font-chrome` | `0.9375rem` | Header identity |
| `--font-body` | `1rem` | Form text and Korean reading copy; prevents mobile input zoom |
| `--font-section` | `1.125rem` | Panel headings |
| `--font-title` | `1.75rem` | Workspace heading |
| `--line-control` | `1.5` | Labels and controls |
| `--line-prose` | `1.8` | Korean prose, examples and explanations |
| `--weight-medium` | `600` | Section and control emphasis |

The root font remains the browser default; relative units respect zoom and user settings. Primary reading text is never the legacy12px caption. A `--measure-prose: 68ch` limiter prevents wide lines. Plain text uses `white-space: pre-wrap` and `overflow-wrap: anywhere`; display wrapping never changes copied content. No letter-by-letter or streaming draft animation.

## 4. Spacing & layout

The original CSS mixes3/6/7/8/10/11/12/14/20px gaps and padding. Foundation consolidates layout rhythm to4px steps while retaining the existing10px control and14px panel radii. This is an explicit accessibility/readability adaptation, not a claim that the old page already followed a grid.

| Token | Value | Role |
| --- | --- | --- |
| `--space-1` | `0.25rem` | Close label/detail |
| `--space-2` | `0.5rem` | Icon and action gap |
| `--space-3` | `0.75rem` | Field stack |
| `--space-4` | `1rem` | Mobile gutters and panel internals |
| `--space-5` | `1.25rem` | Original header/log spacing |
| `--space-6` | `1.5rem` | Panel padding and group gaps |
| `--space-8` | `2rem` | Section separation |
| `--space-10` | `2.5rem` | Workspace heading separation |
| `--space-12` | `3rem` | Large reading separation |
| `--control-min` | `2.75rem` | 44px minimum interactive target |
| `--content-max` | `70rem` | Wide workspace measure |
| `--measure-prose` | `68ch` | Long-form text measure |
| `--icon-size` | `1.125rem` | Consistent SVG geometry |

`UiShell` has a100dvh bounded grid with header and `minmax(0,1fr)` main. `main.ui-scroll` is the ONE application vertical scroll owner; body is fixed and does not independently scroll. The header stays fixed in the shell. Every flexible/grid ancestor has `min-block-size:0` and `min-inline-size:0` where necessary. Form/source/result content belongs inside main. Native textarea scrolling is only for editing that one field.

Use stack and wrapping action-cluster primitives. `ui-field-grid` uses intrinsic tracks that can shrink below their preferred width; no minimum width may force overflow. At the48rem wide-layout threshold the showcase can place explanatory support next to primitive examples; below it DOM order becomes a single column. Progress is six columns when roomy and two columns in narrow space. Main padding decreases from24px to16px. Header text wraps, controls remain reachable, and no sticky footer consumes mobile reading space. Primary content has no horizontal scrollbar.

## 5. Components

The browser module exports the following actual Vue definitions. They are presentation components with props/emits/slots and no fetch, storage, provider or persistence behavior. The showcase imports the same definitions that the future product page will use.

| Primitive | Structure / use | States and accessibility |
| --- | --- | --- |
| `UiShell` | Header slot + single named main/scroll slot | Skip link, header/main landmarks; long/empty states; source and focus order agree |
| `UiPanel` | Section, labelled heading, description and default slot | Tonal panel, heading hierarchy; no own scrollbar |
| `UiIcon` | Fixed SVG viewBox/path vocabulary | Decorative `aria-hidden`; meaningful label belongs to adjacent text |
| `UiButton` | Native button, optional icon, text slot | primary/secondary/quiet; default/hover/pressed/focus-visible/disabled/busy;44px target; busy communicates aria-busy and text |
| `UiField` | Native label + input/textarea + hint/error | Optional by default; empty/value/read-only/disabled/error/focus; label and description IDs; error says how to proceed |
| `UiCheck` | Native checkbox and wrapping label | Checked/unchecked/disabled/focus;44px whole label hit area; no switch semantics for a checkbox |
| `UiNotice` | Inline SVG + title/body | info/success/warning/error; explicit text; optional polite live region, never alert every static example |
| `UiDisclosure` | Native details/summary with text + chevron | Open/closed/keyboard focus;44px summary; plain text slot; no nested scroll |
| `UiSteps` | Ordered list of six fixed stages | Waiting/active/completed; optional current repair count; no percentages, no seventh repair stage |
| `UiEmpty` | Small heading and useful explanation | Empty source/result state; permits next action rather than requiring missing personal facts |
| `ResultView` | Composes shared primitives for the selected server result | Status/draft/copy, measured length, structure, then suggestions; display-only subtitle distinction; exact server text bindings |

Showcase groups: action states; editable/read-only/invalid/disabled fields; checkboxes; outcome notices; six-stage progress; empty/long text/disclosure states. It includes an editable literal HTML string to verify Vue escaping. Its local buttons only change demonstration state; clear copy labels say these are examples and no model/server request occurs. Neither fake generation nor actual clipboard success is claimed by a demo state switch.

Root accepted the foundation at1440×900,390×844 and820×1180, including focus, disclosure, long text, scroll end, reduced motion and light OS preference. Connected-product Computer Use then verified desktop/mobile layout, empty submission, source restoration, saved revisions, reference subtitles, exact clipboard text, stream recovery and retention of the prior draft during backend errors.

Product controllers keep transport and form state separate from presentation: `api.js` owns POST fetch, streaming UTF8 decoding and event boundaries; `form.js` preserves all raw source IDs/text/category and question keys; `app.js` owns request, lookup, copy and rendering state. Selecting a supplement only opens an editor. Retrying a pending request reuses its original ID/body; explicit new revisions carry the full editable source snapshot. Local storage contains only request/document/thread UUIDs. Source arrays are never collapsed into one field. Server-only previous drafts and registry history are never editable.

## 6. Motion & interaction

The original UI had no transitions. Add only feedback that preserves object identity and serves interaction: `--motion-feedback:120ms` ease-out opacity/transform for pressed/action feedback; `--motion-indicator:1s` linear rotation on the busy SVG only. Stable action labels and min-height avoid moving surrounding content. No animated layout properties, blur, spring library, forced autoscroll or background animation.

Under `prefers-reduced-motion:reduce`, the busy icon stays still with its textual `처리 중` status, pressed scale is removed, and the remaining short opacity change is20ms (`--motion-reduced`). State is always conveyed in Korean text and, when dynamic, a polite live region. Checkbox and details keep native keyboard behavior. A disabled button is visibly distinct but its label retains readable contrast. Focus-visible is a2px primary-text ring with3px offset; no focus ring is hidden without a replacement.

One event gets one response at the control or adjacent notice. The real product must await clipboard resolution before `복사됨`, show a selection fallback on failure, and send no request when selecting a suggestion. The foundation only demonstrates these presentation states.

## 7. Depth & surface

Strategy: existing tonal surfaces plus neutral1px hairlines. No shadows, glass or gradients. Header uses chrome; body uses page; panels use panel; read-only excerpts use inset. Functional input borders use the existing muted foreground to satisfy boundary contrast. Avoid nested panels when spacing or a neutral separator suffices.

| Token | Value | Role |
| --- | --- | --- |
| `--radius-control` | `0.625rem` | Existing10px inputs/buttons |
| `--radius-panel` | `0.875rem` | Existing14px grouped surfaces |
| `--radius-small` | `0.375rem` | Existing6px scrollbar/small marks |
| `--radius-full` | `999px` | Numbered stage marker only |
| `--border-width` | `1px` | Neutral hairline/control boundary |
| `--focus-width` | `2px` | Keyboard ring |
| `--focus-offset` | `3px` | Space around keyboard ring |

Hover changes foreground opacity only on quiet/secondary controls or overlays a subtle opacity change on the primary control; it does not create a new palette value or a decorative card hover. A selection can use an existing tonal surface plus a check, never a colored card edge.

## 8. Accessibility constraints & accepted debt

Target: WCAG2.2 AA task accessibility; normal text4.5:1, essential boundaries/focus3:1,44px interactive targets, keyboard access, labelled controls, meaningful headings and reduced motion. Korean typography must survive200% zoom, long unbroken content and mobile viewport changes. The working persona is an applicant editing uncertain personal information on a phone or keyboard; they must find the draft and next action without interpreting internal IDs or debugging details.

Privacy is architectural: only `web_assets/` is eligible for a temporary static preview. Never serve the project root (it can contain .env). Future product proxy assets require an explicit public allowlist; add sentinel-only tests for /.env, encoded traversal, .gitignore and source paths without ever fetching a real secret. Browser captures are limited to the application UI; only backend mode/model names may be visible, never configuration values.

Accepted UI debt: none. Root accepted Task8 frontend/proxy after connected-product Computer Use; no Lighthouse100, screen-reader or complete accessibility pass is claimed. The inherited external Vue CDN remains the existing delivery architecture. Separate COVER-11 work must resolve and replay live-model personalization and Korean-guidance quality before whole-service completion; frontend acceptance does not close that issue.

Execution references read: frontend design README, design-system architecture, layout, StyleGallery, interaction and perfection; designpowers README/routing/orchestration/lane-b-execution/lane-c-review. Root uses `mcp__cua_repl` for final UI verification per explicit user choice. This overrides the skill's default browser-engine preference; the implementation worker does not start a browser session.
