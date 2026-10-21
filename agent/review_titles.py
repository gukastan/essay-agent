"""Apply title evidence and submission conditions without changing body prose."""

from typing import Final

from .contracts import (
    DraftBundle,
    LengthCheck,
    StrictLengthPolicy,
    TitleCandidate,
    TitleReview,
    count_characters,
    counted_text,
    render_body,
)

MAX_TITLE_CANDIDATES: Final = 3
GENERIC_TITLE: Final = "지원 내용을 정리한 초안"


def title_for_body(bundle: DraftBundle, proposed: TitleReview) -> tuple[DraftBundle, TitleReview]:
    """Preserve valid selected title evidence or use a nonpersonal generic title."""
    sentences = {s.sentence_id: s for p in bundle.paragraphs for s in p.sentences}
    selected = next(
        (c for c in proposed.candidates if c.id == proposed.selected_candidate_id), None
    )
    valid = (
        selected is not None
        and bool(selected.text.strip())
        and len(proposed.candidates) <= MAX_TITLE_CANDIDATES
    )
    if selected is not None:
        valid = (
            valid
            and selected.decision == "selected"
            and all(c.status in ("met", "not_applicable") for c in selected.checks)
        )
        for claim in selected.claims:
            valid = valid and set(claim.body_sentence_ids) <= set(sentences)
            body_facts = {
                fid
                for sid in claim.body_sentence_ids
                if sid in sentences
                for fid in sentences[sid].fact_ids
            }
            valid = valid and set(claim.fact_ids) <= body_facts
        if selected.kind == "generated":
            valid = (
                valid
                and bool(selected.claims)
                and all(claim.body_sentence_ids and claim.fact_ids for claim in selected.claims)
            )
        if selected.kind == "fixed":
            valid = (
                valid
                and bool(proposed.condition_refs)
                and any(selected.text in ref for ref in proposed.condition_refs)
            )
    placement = "display_only" if proposed.condition == "forbidden" else proposed.placement
    if not valid or selected is None:
        selected = TitleCandidate(
            id="generic",
            text=GENERIC_TITLE,
            kind="generic",
            claims=(),
            checks=(),
            decision="selected",
            reason="현재 본문에 없는 개인 주장을 추가하지 않는 참고 제목입니다.",
        )
        proposed = proposed.model_copy(
            update={
                "candidates": (selected,),
                "selected_candidate_id": selected.id,
                "focus_summary": None,
            }
        )
    title = proposed.model_copy(update={"placement": placement})
    return bundle.model_copy(
        update={
            "subtitle": selected.text,
            "subtitle_fact_ids": tuple(
                dict.fromkeys(fid for claim in selected.claims for fid in claim.fact_ids)
            ),
            "subtitle_placement": placement,
        }
    ), title


def generic_title(placement: str = "answer") -> TitleReview:
    """Build a title record that makes no personal fact claim."""
    return TitleReview.model_validate(
        {
            "condition": "allowed",
            "condition_refs": (),
            "placement": placement,
            "reason": "제공된 정보 범위의 일반 참고 제목입니다.",
            "focus_summary": None,
            "candidates": (
                TitleCandidate(
                    id="generic",
                    text=GENERIC_TITLE,
                    kind="generic",
                    claims=(),
                    checks=(),
                    decision="selected",
                    reason="개인 성과를 주장하지 않습니다.",
                ),
            ),
            "selected_candidate_id": "generic",
        }
    )


def measure_final(
    bundle: DraftBundle, policy: StrictLengthPolicy, *, uncertain: bool = False
) -> LengthCheck:
    """Count actual body/title/separator with the shared Unicode policy."""
    includes = bool(
        policy.include_subtitle and bundle.subtitle_placement == "answer" and bundle.subtitle
    )
    count = count_characters(counted_text(bundle, policy), policy)
    return LengthCheck(
        version_id=bundle.version_id,
        body_chars=count_characters(render_body(bundle), policy),
        subtitle_chars=count_characters(bundle.subtitle or "", policy),
        separator_chars=count_characters("\n\n", policy) if includes else 0,
        counted_chars=count,
        max_chars=policy.max_chars,
        includes_subtitle=includes,
        status="unspecified"
        if policy.max_chars is None
        else "over"
        if count > policy.max_chars
        else "within",
        condition_status="unassessed" if uncertain else "met",
        notes=("명시 조건과 계수 정책의 일치 여부를 확인해야 합니다.",) if uncertain else (),
    )
