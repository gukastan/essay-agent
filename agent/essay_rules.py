"""Deterministic paragraph budgeting shared by normal and fallback planning."""

from typing import Final

from .contract_base import require
from .contracts import Budget, Outline, ParagraphPlan, StrictLengthPolicy, count_characters

TOTAL_WEIGHT: Final = 100


def budget_outline(outline: Outline, policy: StrictLengthPolicy) -> Outline:
    """Replace proposed counts with Python's largest-remainder apportionment."""
    paragraphs = tuple(sorted(outline.paragraphs, key=lambda paragraph: paragraph.order))
    require(bool(paragraphs), "paragraphs", "Plan at least one writable paragraph")
    require(all(p.weight > 0 for p in paragraphs), "paragraph_weight", "Weights are positive")
    require(
        sum(p.weight for p in paragraphs) == TOTAL_WEIGHT, "paragraph_weight", "Weights sum to100"
    )
    separators = count_characters("\n\n" * (len(paragraphs) - 1), policy)
    if policy.max_chars is None:
        budget = Budget(
            max_chars=None,
            subtitle_reserved_chars=None,
            separator_chars=separators,
            usable_body_chars=None,
            constraint_notes=outline.budget.constraint_notes,
        )
        updated = tuple(p.model_copy(update={"target_chars": None}) for p in paragraphs)
    else:
        reservation = outline.budget.subtitle_reserved_chars or 0
        if policy.include_subtitle:
            require(
                reservation > 0, "subtitle_budget", "Counted subtitles need a positive reservation"
            )
            separators += count_characters("\n\n", policy)
        else:
            reservation = 0
        available = max(0, policy.max_chars - reservation - separators)
        notes = outline.budget.constraint_notes
        if available < len(paragraphs):
            notes += ("constraint_conflict: 완결된 문장에 필요한 분량을 확보하지 못했습니다.",)
        budget = Budget(
            max_chars=policy.max_chars,
            subtitle_reserved_chars=reservation,
            separator_chars=separators,
            usable_body_chars=available,
            constraint_notes=notes,
        )
        updated = apportion(paragraphs, available)
    return outline.model_copy(update={"paragraphs": updated, "budget": budget})


def apportion(paragraphs: tuple[ParagraphPlan, ...], available: int) -> tuple[ParagraphPlan, ...]:
    """Integer remainders avoid floating-point ties and preserve paragraph order."""
    targets = [available * p.weight // TOTAL_WEIGHT for p in paragraphs]
    order = sorted(
        range(len(paragraphs)),
        key=lambda index: (-(available * paragraphs[index].weight % TOTAL_WEIGHT), index),
    )
    for index in order[: available - sum(targets)]:
        targets[index] += 1
    return tuple(
        p.model_copy(update={"target_chars": target})
        for p, target in zip(paragraphs, targets, strict=True)
    )
