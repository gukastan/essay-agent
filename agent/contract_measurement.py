"""Deterministic count checks against preserved selected content."""

from .contract_base import require
from .contract_context import ContractContext
from .contract_rendering import count_characters, counted_text, render_body
from .contract_review import LengthCheck
from .contract_sources import StrictLengthPolicy


def validate_measurements(ctx: ContractContext) -> None:
    """Compare supplied counts to Python measurements and source references."""
    if ctx.bundle is None:
        return
    policy = (
        ctx.result.length_policy
        if ctx.result
        else ctx.request.length_policy
        if ctx.request
        else None
    )
    if policy is not None:
        if ctx.review is not None:
            _validate_length(ctx.review.length_check, ctx, policy)
        if ctx.result is not None:
            _validate_length(ctx.result.quality_report.length_check, ctx, policy)
    if ctx.result is not None:
        used = {fid for p in ctx.bundle.paragraphs for s in p.sentences for fid in s.fact_ids}
        used.update(ctx.bundle.subtitle_fact_ids)
        for summary in ctx.result.source_summary:
            require(
                summary.provided_source_count
                == sum(s.source_kind == summary.source_kind for s in ctx.sources),
                "source_summary",
                "Provided count must match snapshots",
            )
            require(
                summary.used_fact_count
                == sum(
                    f.fact_id in used and f.source_kind == summary.source_kind for f in ctx.facts
                ),
                "source_summary",
                "Used count must match selected references",
            )


def _validate_length(check: LengthCheck, ctx: ContractContext, policy: StrictLengthPolicy) -> None:
    bundle = ctx.bundle
    if bundle is None:
        return
    includes = (
        policy.include_subtitle and bundle.subtitle_placement == "answer" and bool(bundle.subtitle)
    )
    body = count_characters(render_body(bundle), policy)
    title = count_characters(bundle.subtitle or "", policy)
    separator = count_characters("\n\n", policy) if includes else 0
    count = count_characters(counted_text(bundle, policy), policy)
    expected_status = (
        "unspecified"
        if policy.max_chars is None
        else "over"
        if count > policy.max_chars
        else "within"
    )
    require(
        (
            check.body_chars,
            check.subtitle_chars,
            check.separator_chars,
            check.counted_chars,
            check.max_chars,
            check.includes_subtitle,
            check.status,
        )
        == (body, title, separator, count, policy.max_chars, includes, expected_status),
        "length_measurement",
        "Length check must match selected content and policy",
    )
