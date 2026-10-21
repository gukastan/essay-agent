from typing import Literal

from agent import contracts as c
from agent.stage_review_models import ReviewPayload

Scenario = Literal[
    "control",
    "lost_learning",
    "fabricated",
    "unsafe_swap",
    "no_positive",
    "source_title",
    "title_only",
    "review_error",
    "repair_error",
    "title_budget",
    "omitted",
    "missing",
    "all_unsafe",
    "unavailable",
    "resolved",
    "stale_best",
    "stale_all",
]


def issue(
    name: str,
    code: Literal[
        "style", "length", "subtitle", "missing_information", "prompt_coverage", "unsupported_claim"
    ],
    sentence: c.Sentence | None = None,
    *,
    fixable: bool = True,
) -> c.ReviewIssue:
    subtitle = code == "subtitle"
    return c.ReviewIssue(
        issue_id=c.IssueId(name),
        code=code,
        area="subtitle" if subtitle else "body",
        sentence_ids=(sentence.sentence_id,) if sentence else (),
        section_ids=sentence.section_ids if sentence else (),
        requirement_ids=()
        if subtitle
        else (c.RequirementId("req-result"),)
        if code in ("missing_information", "prompt_coverage")
        else (),
        fact_ids=sentence.fact_ids if sentence else (),
        gap_ids=(),
        excerpt=sentence.text if sentence else None,
        reason="Injected current-input finding.",
        action="replace_title" if subtitle else "suggest" if not fixable else "rewrite",
        verification="Check current original evidence and retained body answer.",
        fixable_without_new_info=fixable,
        status="open",
    )


def title(payload: ReviewPayload, scenario: Scenario) -> c.TitleReview:
    claims: tuple[c.TitleClaim, ...] = ()
    text = payload.candidate_bundle.subtitle or "Notes on the work"
    if scenario in ("source_title", "title_only"):
        text = "A lesson in agreement"
        claims = (
            c.TitleClaim(
                meaning="The applicant learned to agree on a method.",
                body_sentence_ids=(),
                fact_ids=(c.FactId("fact-learning"),),
            ),
        )
    return c.TitleReview(
        condition="allowed",
        condition_refs=(),
        placement="answer",
        reason="No restrictive title condition.",
        focus_summary="The supplied work.",
        candidates=(
            c.TitleCandidate(
                id="chosen",
                text=text,
                kind="generated" if claims else "generic",
                claims=claims,
                checks=(c.TitleCheck(name="support", status="met", reason="Injected assessment."),),
                decision="selected",
                reason="Injected title candidate.",
            ),
        ),
        selected_candidate_id="chosen",
    )
