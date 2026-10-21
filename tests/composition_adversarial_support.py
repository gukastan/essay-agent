from dataclasses import dataclass, field
from typing import Final, Literal, assert_never

from agent import contracts as c
from agent.essay_llm import Output, Stage
from agent.stage_integration_models import IntegrationOutput, IntegrationPayload
from tests.fixtures.cases import ContractCase

LEARNING: Final = "I learned to agree on a method before starting."
Scenario = Literal[
    "control",
    "loss",
    "unsupported_baseline",
    "unsupported_all",
    "metric",
    "causality",
    "merge_move",
]


def prepared_context() -> c.ContractContext:
    context = ContractCase.load("composition_adversarial.json").parse()
    c.validate_contract(context)
    return context


def report_issue(code: str, sentence: c.Sentence, *, baseline: bool) -> c.IntegrationIssue:
    return c.IntegrationIssue(
        code=code,
        scope="baseline" if baseline else "current",
        sentence_ids=(sentence.sentence_id,),
        section_ids=sentence.section_ids,
        requirement_ids=(c.RequirementId("req-result"),) if baseline else (),
        gap_ids=(),
        status="open",
        message="Injected semantic finding, not an automatic text classifier.",
        handling="Exclude unsupported content and preserve valid original statements.",
    )


@dataclass(frozen=True, slots=True)
class ScriptedIntegration:
    scenario: Scenario
    calls: list[Stage] = field(default_factory=list)
    payloads: list[IntegrationPayload] = field(default_factory=list)
    proposals: list[IntegrationOutput] = field(default_factory=list)

    def __call__(
        self, stage: Stage, payload: c.ContractModel, output_model: type[Output]
    ) -> Output:
        assert stage == "integrate_draft"
        current = IntegrationPayload.model_validate(payload.model_dump())
        self.calls.append(stage)
        self.payloads.append(current)
        output = proposal(current, self.scenario)
        self.proposals.append(output)
        return output_model.model_validate(output.model_dump())


def proposal(payload: IntegrationPayload, scenario: Scenario) -> IntegrationOutput:
    baseline = payload.baseline_bundle
    sentences = {s.sentence_id: s for p in baseline.paragraphs for s in p.sentences}
    learning = sentences[c.SentenceId("sentence-learning")]
    paragraphs = baseline.paragraphs
    edits = tuple(
        c.IntegrationEdit(
            operation="retain",
            before_sentence_ids=(s.sentence_id,),
            after_sentence_ids=(s.sentence_id,),
            section_ids=s.section_ids,
            fact_ids=s.fact_ids,
            reason="Keep the original statement.",
        )
        for s in sentences.values()
    )
    issues: tuple[c.IntegrationIssue, ...] = ()
    after_learning: tuple[c.SentenceId, ...] = (learning.sentence_id,)
    after_state: Literal["expressed", "not_expressed"] = "expressed"
    match scenario:
        case "unsupported_all":
            issues = tuple(
                report_issue("unsupported_claim", sentence, baseline=True)
                for sentence in sentences.values()
            )
        case "loss" | "unsupported_baseline":
            paragraphs = tuple(
                p.model_copy(
                    update={
                        "sentences": tuple(
                            s for s in p.sentences if s.sentence_id != learning.sentence_id
                        )
                    }
                )
                for p in paragraphs
            )
            edits = tuple(
                e.model_copy(update={"operation": "delete", "after_sentence_ids": ()})
                if e.before_sentence_ids == (learning.sentence_id,)
                else e
                for e in edits
            )
            after_learning, after_state = (), "not_expressed"
            issues = {
                "loss": (),
                "unsupported_baseline": (
                    report_issue("unsupported_claim", learning, baseline=True),
                ),
            }[scenario]
        case "metric" | "causality":
            original = sentences[c.SentenceId("sentence-one")]
            text = {
                "metric": "I increased sorting speed by 40 percent.",
                "causality": "My sorting caused every visitor to return.",
            }[scenario]
            changed = original.model_copy(
                update={"sentence_id": c.SentenceId("sentence-injected"), "text": text}
            )
            paragraphs = tuple(
                p.model_copy(
                    update={
                        "sentences": tuple(
                            changed if s.sentence_id == original.sentence_id else s
                            for s in p.sentences
                        )
                    }
                )
                for p in paragraphs
            )
            edits = tuple(
                e.model_copy(
                    update={"operation": "rewrite", "after_sentence_ids": (changed.sentence_id,)}
                )
                if e.before_sentence_ids == (original.sentence_id,)
                else e
                for e in edits
            )
            issues = (report_issue("unsupported_" + scenario, changed, baseline=False),)
        case "merge_move":
            first, second = (
                sentences[c.SentenceId("sentence-one")],
                sentences[c.SentenceId("sentence-two")],
            )
            merged = first.model_copy(
                update={
                    "sentence_id": c.SentenceId("sentence-merged"),
                    "text": "At the library I sorted books; separately, I watered the garden.",
                    "section_ids": (*first.section_ids, *second.section_ids),
                    "fact_ids": (*first.fact_ids, *second.fact_ids),
                }
            )
            paragraphs = (
                baseline.paragraphs[1],
                baseline.paragraphs[0].model_copy(update={"sentences": (merged,)}),
            )
            edits = (
                c.IntegrationEdit(
                    operation="merge",
                    before_sentence_ids=(first.sentence_id, second.sentence_id),
                    after_sentence_ids=(merged.sentence_id,),
                    section_ids=merged.section_ids,
                    fact_ids=merged.fact_ids,
                    reason="Keep both distinct events explicit.",
                ),
                *(
                    e.model_copy(update={"operation": "move"})
                    for e in edits
                    if e.before_sentence_ids not in ((first.sentence_id,), (second.sentence_id,))
                ),
            )
        case "control":
            pass
        case _:
            assert_never(scenario)
    reverse = tuple(
        c.ReverseOutline(
            scope="candidate",
            paragraph_id=p.paragraph_id,
            sentence_ids=tuple(s.sentence_id for s in p.sentences),
            section_ids=tuple(dict.fromkeys(sid for s in p.sentences for sid in s.section_ids)),
            fact_ids=tuple(dict.fromkeys(fid for s in p.sentences for fid in s.fact_ids)),
            gist="Injected candidate-specific summary",
            roles=("injected role",),
            requirement_ids=(),
            semantic_status="assessed",
            difference_from_plan="Injected edit",
        )
        for p in paragraphs
    )
    check = c.IntegrationRequirementCheck(
        requirement_id=c.RequirementId("req-result"),
        baseline_sentence_ids=(learning.sentence_id,),
        candidate_sentence_ids=after_learning,
        before_state="expressed",
        after_state=after_state,
        gap_ids=(),
        missing_detail=None,
        reason="Injected comparison of the sole learning statement.",
    )
    return IntegrationOutput(
        paragraphs=paragraphs,
        edits=edits,
        reverse_outline=reverse,
        requirement_checks=(check,),
        issues=issues,
    )
