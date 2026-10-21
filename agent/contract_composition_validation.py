"""Public contract_composition_validation boundary contracts."""

from .contract_base import require
from .contract_context import ContractContext
from .contract_drafts import DraftBundle, Sentence
from .contract_references import references, unique


def bundle_sentences(bundle: DraftBundle) -> tuple[Sentence, ...]:
    """Enforce bundle sentences boundary semantics."""
    return tuple(s for p in bundle.paragraphs for s in p.sentences)


def validate_sentences(
    sentences: tuple[Sentence, ...], ctx: ContractContext, fallback: set[str]
) -> None:
    """Enforce validate sentences boundary semantics."""
    _ = unique((s.sentence_id for s in sentences), "sentences")
    sections = (
        {section.section_id: section for section in ctx.outline.sections} if ctx.outline else {}
    )
    facts = {fact.fact_id: fact for fact in ctx.facts}
    for sentence in sentences:
        references(sentence.fact_ids, facts, "sentence facts")
        references(sentence.section_ids, sections, "sentence sections")
        allowed_facts = {fid for sid in sentence.section_ids for fid in sections[sid].fact_ids}
        references(sentence.fact_ids, allowed_facts, "sentence outside mapped section evidence")
        require(
            sentence.claim_kind in ("general_statement", "connective")
            or any(sections[sid].write_mode == "grounded" for sid in sentence.section_ids),
            "general_claim",
            "Personal claims need a grounded mapped section",
        )
        require(
            bool(sentence.section_ids) or sentence.sentence_id in fallback,
            "unmapped_sentence",
            "Only explicit fallback sentences can have no sections",
        )
        if sentence.sentence_id in fallback:
            require(
                not sentence.section_ids
                and not sentence.fact_ids
                and sentence.claim_kind == "general_statement",
                "fallback_claim",
                "Fallback cannot carry personal claims or section mapping",
            )
        for sid in sentence.section_ids:
            section = sections[sid]
            require(
                section.write_mode != "omit",
                "omit_sentence",
                "Omitted sections cannot generate sentences",
            )
        if sentence.claim_kind in ("personal_event", "stated_view"):
            require(
                all(facts[fid].source_kind == "applicant" for fid in sentence.fact_ids),
                "personal_source",
                "Personal sentences require applicant evidence",
            )


def validate_composition(ctx: ContractContext) -> None:
    """Enforce validate composition boundary semantics."""
    report = ctx.writing_report
    fallback: set[str] = {s.sentence_id for s in report.fallback_sentences} if report else set()
    draft_sentences = tuple(
        s
        for draft in ctx.section_drafts
        for allocation in draft.allocations
        for s in allocation.sentences
    )
    if ctx.section_drafts:
        require(ctx.outline is not None, "missing_context", "Section drafts require outline")
        if ctx.outline is not None:
            sections = {section.section_id: section for section in ctx.outline.sections}
            _ = unique((draft.section_id for draft in ctx.section_drafts), "section drafts")
            require(
                {draft.section_id for draft in ctx.section_drafts} == set(sections),
                "section_drafts",
                "Every section must appear exactly once",
            )
            for draft in ctx.section_drafts:
                require(
                    sections[draft.section_id].write_mode != "omit" or not draft.allocations,
                    "omit_allocation",
                    "Omitted section has no allocations",
                )
                for allocation in draft.allocations:
                    references(
                        (allocation.planned_paragraph_id,),
                        (
                            p.paragraph_id
                            for p in ctx.outline.paragraphs
                            if any(a.section_id == draft.section_id for a in p.allocations)
                        ),
                        "draft paragraph allocation",
                    )
                    require(
                        all(draft.section_id in s.section_ids for s in allocation.sentences),
                        "draft_section",
                        "Draft sentences retain their section",
                    )
        validate_sentences(draft_sentences, ctx, set())
    if report is not None:
        require(
            report.evidence_version == ctx.evidence_version, "evidence_version", "writing report"
        )
        require(
            not fallback or not draft_sentences,
            "fallback_nonempty",
            "Fallback is only for an empty draft",
        )
        validate_sentences(report.fallback_sentences, ctx, fallback)
        for check in report.section_checks:
            references(
                check.sentence_ids,
                (s.sentence_id for s in draft_sentences),
                "section check current sentences",
            )
    if ctx.bundle is not None:
        bundle = ctx.bundle
        if ctx.integration_report is not None and bundle_sentences(
            ctx.integration_report.baseline_bundle
        ):
            fallback.update(
                sid
                for edit in ctx.integration_report.edits
                if edit.operation == "add_fallback"
                for sid in edit.after_sentence_ids
            )
        require(bundle.evidence_version == ctx.evidence_version, "evidence_version", "bundle")
        _ = unique((p.paragraph_id for p in bundle.paragraphs), "bundle paragraphs")
        validate_sentences(bundle_sentences(bundle), ctx, fallback)
        references(bundle.subtitle_fact_ids, (fact.fact_id for fact in ctx.facts), "subtitle facts")
        applicant_facts = {f.fact_id for f in ctx.facts if f.source_kind == "applicant"}
        has_personal_evidence = any(
            s.claim_kind in ("personal_event", "stated_view", "interpretation")
            and applicant_facts.intersection(s.fact_ids)
            for s in bundle_sentences(bundle)
        )
        require(
            has_personal_evidence or bundle.personalization == "non_personalized",
            "personalization",
            "A bundle without applicant-grounded claims is non-personalized",
        )
