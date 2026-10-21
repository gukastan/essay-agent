"""Selected-result references and exact excerpts."""

from .contract_base import require
from .contract_composition_validation import bundle_sentences
from .contract_context import ContractContext
from .contract_references import references
from .contract_rendering import count_characters, counted_text, render_body, render_copy_text
from .contract_review import Location


def validate_locations(locations: tuple[Location, ...], ctx: ContractContext) -> None:
    """Enforce validate locations boundary semantics."""
    require(ctx.bundle is not None, "missing_context", "Locations require bundle")
    if ctx.bundle is None:
        return
    paragraphs = {p.paragraph_id: (index, p) for index, p in enumerate(ctx.bundle.paragraphs, 1)}
    for location in locations:
        references((location.paragraph_id,), paragraphs, "location paragraph")
        index, paragraph = paragraphs[location.paragraph_id]
        sentences = {s.sentence_id: s for s in paragraph.sentences}
        references(location.sentence_ids, sentences, "location sentences")
        require(
            location.paragraph_number == index
            and location.excerpts == tuple(sentences[sid].text for sid in location.sentence_ids),
            "result_excerpt",
            "Locations contain exact selected sentence excerpts",
        )


def validate_result(ctx: ContractContext) -> None:
    """Enforce validate result boundary semantics."""
    result = ctx.result
    if result is None:
        return
    require(ctx.bundle is not None, "missing_context", "Result requires selected bundle")
    if ctx.bundle is None:
        return
    bundle = ctx.bundle
    require(
        result.version_id == bundle.version_id and result.evidence_version == ctx.evidence_version,
        "result_version",
        "Result identifies selected version",
    )
    require(
        result.body == render_body(bundle) and result.copy_text == render_copy_text(bundle),
        "result_rendering",
        "Body and copy text derive from selected sentences",
    )
    require(
        result.subtitle == bundle.subtitle
        and result.subtitle_placement == bundle.subtitle_placement,
        "result_title",
        "Result title derives from selected title",
    )
    require(
        result.character_count
        == count_characters(counted_text(bundle, result.length_policy), result.length_policy),
        "result_count",
        "Result count uses shared renderer",
    )
    require(
        all(entry.outcome != "pending_review" for entry in ctx.repair_log),
        "pending_repair",
        "Result cannot contain pending repair",
    )
    if ctx.request is not None:
        require(
            result.document_id == ctx.request.document_id
            and result.request_id == ctx.request.request_id,
            "result_request",
            "Result belongs to current request",
        )
    sentences = {s.sentence_id: s for s in bundle_sentences(bundle)}
    sections = {s.section_id: s for s in ctx.outline.sections} if ctx.outline else {}
    checks = {c.sentence_id: c for c in ctx.review.sentence_checks} if ctx.review else {}
    for entry in result.structure:
        references((entry.section_id,), sections, "structure section")
        references(entry.actual_sentence_ids, sentences, "structure sentences")
        require(
            all(
                entry.section_id in sentences[sid].section_ids for sid in entry.actual_sentence_ids
            ),
            "structure_mapping",
            "Structure maps actual section sentences",
        )
        validate_locations(entry.locations, ctx)
        require(
            {sid for location in entry.locations for sid in location.sentence_ids}
            == set(entry.actual_sentence_ids),
            "structure_locations",
            "Structure locations must describe exactly its current sentences",
        )
        requirement_checks = (
            {c.requirement_id: c.status for c in ctx.review.requirement_checks}
            if ctx.review
            else {}
        )
        for status in entry.requirement_statuses:
            require(
                status.requirement_id in entry.requirement_ids
                and requirement_checks.get(status.requirement_id) == status.status,
                "result_requirement_status",
                "Result status must match current review",
            )
        if entry.coverage == "supported":
            require(
                bool(entry.actual_sentence_ids)
                and all(
                    sid in checks and checks[sid].status in ("source_supported", "general_valid")
                    for sid in entry.actual_sentence_ids
                )
                and any(
                    checks[sid].status == "source_supported" for sid in entry.actual_sentence_ids
                ),
                "coverage_evidence",
                "Supported coverage needs current positive sentence checks",
            )
    for suggestion in result.suggestions:
        references(suggestion.sentence_ids, sentences, "suggestion sentences")
        references(
            suggestion.issue_ids,
            (i.issue_id for i in ctx.review.issues) if ctx.review else (),
            "suggestion issues",
        )
        references(
            suggestion.gap_ids,
            (g.gap_id for g in ctx.analysis.gaps) if ctx.analysis else (),
            "suggestion gaps",
        )
        require(
            bool(suggestion.issue_ids or suggestion.gap_ids or suggestion.requirement_ids),
            "suggestion_origin",
            "Suggestions need current origins",
        )
        require(
            suggestion.example_question is None or suggestion.question_key is not None,
            "question_key",
            "Answerable questions require stable keys",
        )
        require(
            suggestion.question_status not in ("unavailable", "not_needed")
            or suggestion.example_question is None,
            "question_repeat",
            "Closed unavailable questions cannot be asked again",
        )
        validate_locations(suggestion.locations, ctx)
    if ctx.analysis is not None and any(
        r.resolution == "unparsed" for r in ctx.analysis.requirements
    ):
        require(
            result.quality_report.display_status == "review_incomplete",
            "display_status",
            "Unparsed requirements keep review incomplete",
        )
