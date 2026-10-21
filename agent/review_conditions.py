"""Carry explicit title submission rules into normal and error paths."""

import re

from .contracts import TitleCandidate, TitleReview
from .stage_writing_models import CompositionPayload


def apply_known_conditions(payload: CompositionPayload, title: TitleReview) -> TitleReview:
    """Preserve explicit no-title and quoted fixed-title instructions on every path."""
    texts = tuple(
        dict.fromkeys(
            (
                payload.request.question or "",
                *(c.quote or c.description for c in payload.analysis.writing_conditions),
            )
        )
    )
    forbidden = next(
        (
            text
            for text in texts
            if re.search(r"(?:소?제목).{0,12}(?:금지|쓰지|작성하지|넣지)", text)
        ),
        None,
    )
    fixed: tuple[str, str] | None = None
    for text in texts:
        match = re.search(
            r"(?:고정\s*(?:소?제목)|소?제목은)\s*[:\uFF1A]?\s*[\"'\u2018\u201C]([^\"'\u2019\u201D]+)[\"'\u2019\u201D]",
            text,
        )
        if match is not None:
            fixed = (match.group(1), text)
            break
    if fixed is not None:
        candidate = TitleCandidate(
            id="fixed",
            text=fixed[0],
            kind="fixed",
            claims=(),
            checks=(),
            decision="selected",
            reason="명시된 제목 문구를 그대로 보존했습니다.",
        )
        title = title.model_copy(
            update={
                "condition": "fixed",
                "condition_refs": (fixed[1],),
                "candidates": (candidate,),
                "selected_candidate_id": candidate.id,
            }
        )
    if forbidden is not None:
        title = title.model_copy(
            update={
                "condition": "uncertain" if fixed is not None else "forbidden",
                "placement": "display_only",
                "condition_refs": tuple(dict.fromkeys((*title.condition_refs, forbidden))),
                "reason": "제출용 본문에서 제목을 제외하고 화면 참고용으로 제공합니다.",
            }
        )
    return title
