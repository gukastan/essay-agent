from dataclasses import dataclass, field
from typing import Literal, assert_never

from agent import contracts as c
from agent.essay_llm import ErrorKind, GenerationError, GenerationUsage, Output, Stage, TokenUsage
from agent.stage_writing_models import WritingOutput, WritingPayload
from tests.composition_adversarial_support import prepared_context
from tests.fixtures.cases import ContractCase

Scenario = Literal[
    "partial_timeout",
    "retry_collision",
    "retry_prior_only",
    "all_invalid",
    "all_removed",
    "omitted",
    "missing",
    "targeted",
    "merged",
    "merged_wrong_owner",
    "bad_section",
    "bad_requirement",
    "bad_gap",
    "bad_sentence",
]


def context_for(scenario: Scenario) -> c.ContractContext:
    context = prepared_context()
    if scenario == "merged":
        context = (
            ContractCase.load("composition_adversarial.json")
            .replace(("outline", "sections", 0, "fact_ids"), ["fact-library", "fact-garden"])
            .replace(
                ("outline", "sections", 0, "experience_ids"), ["event-library", "event-garden"]
            )
            .replace(
                ("outline", "sections", 0, "allowed_content"),
                "Library sorting and garden watering.",
            )
            .replace(
                ("outline", "paragraphs", 0, "allocations", 0, "fact_ids"),
                ["fact-library", "fact-garden"],
            )
            .parse()
        )
        c.validate_contract(context)
    if scenario != "missing":
        return context
    missing = (
        ContractCase.load("merged-sections.json")
        .replace(("request", "question"), "Describe your actions and what you learned.")
        .replace(("analysis", "requirements", 1, "description"), "Explain what you learned.")
        .replace(("analysis", "evidence_links", 1, "reason"), "No learning is supplied.")
        .replace(("analysis", "gaps", 0, "missing_detail"), "The applicant's learning is unknown.")
        .replace(("analysis", "gaps", 0, "why_it_matters"), "The prompt asks for learning.")
        .replace(("analysis", "gaps", 0, "question"), "What did you learn?")
        .replace(("outline", "sections", 2, "role"), "learning")
        .replace(("outline", "sections", 2, "purpose"), "Preserve the unanswered learning.")
        .replace(("outline", "sections", 2, "intended_content"), "Learning remains unanswered.")
        .replace(("outline", "sections", 2, "missing_info"), ["Learning is unknown"])
        .parse()
    )
    assert missing.analysis is not None
    assert context.analysis is not None
    analysis = missing.analysis.model_copy(
        update={
            "evidence_links": (context.analysis.evidence_links[0], *missing.analysis.evidence_links)
        }
    )
    current = missing.model_copy(
        update={
            "analysis": analysis,
            "section_drafts": (
                *context.section_drafts[:2],
                c.SectionDraft(section_id=c.SectionId("section-result"), allocations=()),
            ),
            "writing_report": None,
            "bundle": None,
            "integration_report": None,
            "review": None,
            "result": None,
        }
    )
    c.validate_contract(current)
    return current


def unsafe_note(sentence: c.Sentence) -> c.WritingNote:
    return c.WritingNote(
        code="unsupported_claim",
        section_ids=sentence.section_ids,
        requirement_ids=(),
        sentence_ids=(sentence.sentence_id,),
        gap_ids=(),
        handling="omitted",
        message="Explicit injected semantic finding.",
        proposed_question=None,
    )


def proposed_output(context: c.ContractContext, scenario: Scenario) -> WritingOutput:
    drafts = context.section_drafts
    sentences = tuple(s for d in drafts for a in d.allocations for s in a.sentences)
    notes: tuple[c.WritingNote, ...] = ()
    match scenario:
        case "partial_timeout" | "retry_collision" | "retry_prior_only" | "all_invalid":
            drafts = tuple(
                d.model_copy(
                    update={
                        "allocations": tuple(
                            a.model_copy(
                                update={
                                    "sentences": tuple(
                                        s.model_copy(
                                            update={"fact_ids": (c.FactId("foreign-fact"),)}
                                        )
                                        if scenario == "all_invalid"
                                        or s.sentence_id == "sentence-two"
                                        else s
                                        for s in a.sentences
                                    )
                                }
                            )
                            for a in d.allocations
                        )
                    }
                )
                for d in drafts
            )
        case "all_removed":
            notes = tuple(unsafe_note(s) for s in sentences)
        case "targeted":
            notes = (unsafe_note(sentences[0]),)
        case "omitted":
            drafts = tuple(d for d in drafts if d.section_id != "section-result")
        case "missing":
            pass
        case "bad_section" | "bad_requirement" | "bad_gap" | "bad_sentence":
            field_name = {
                "bad_section": "section_ids",
                "bad_requirement": "requirement_ids",
                "bad_gap": "gap_ids",
                "bad_sentence": "sentence_ids",
            }[scenario]
            notes = (unsafe_note(sentences[0]).model_copy(update={field_name: ("foreign",)}),)
        case "merged" | "merged_wrong_owner":
            first, garden = sentences[0], sentences[2]
            merged = first.model_copy(
                update={
                    "sentence_id": c.SentenceId("writing-merged"),
                    "text": "At the library I sorted books; separately, I watered the garden.",
                    "section_ids": (*first.section_ids, *garden.section_ids),
                    "fact_ids": (*first.fact_ids, *garden.fact_ids),
                }
            )
            drafts = (
                drafts[0].model_copy(
                    update={
                        "allocations": (
                            drafts[0].allocations[0].model_copy(update={"sentences": (merged,)}),
                            drafts[0].allocations[1],
                        )
                    }
                ),
                drafts[1].model_copy(update={"allocations": ()}),
                drafts[2],
            )
        case _:
            assert_never(scenario)
    return WritingOutput(
        section_drafts=drafts, notes=notes, section_checks=(), personalization="partial"
    )


@dataclass(frozen=True, slots=True)
class ScriptedWriting:
    scenario: Scenario
    context: c.ContractContext
    calls: list[Stage] = field(default_factory=list)
    payloads: list[WritingPayload] = field(default_factory=list)
    outputs: list[WritingOutput] = field(default_factory=list)

    def __call__(
        self, stage: Stage, payload: c.ContractModel, output_model: type[Output]
    ) -> Output:
        assert stage == "write_sections"
        self.calls.append(stage)
        self.payloads.append(WritingPayload.model_validate(payload.model_dump()))
        if self.scenario == "partial_timeout" and len(self.calls) == 2:
            raise GenerationError(
                ErrorKind.TIMEOUT,
                GenerationUsage(
                    attempts=(
                        TokenUsage(
                            model="fake:timeout",
                            input_tokens=None,
                            output_tokens=None,
                            total_tokens=None,
                        ),
                    )
                ),
            )
        output = proposed_output(self.context, self.scenario)
        if self.scenario == "retry_prior_only" and len(self.calls) == 2:
            first = output.section_drafts[0]
            note = unsafe_note(first.allocations[0].sentences[0])
            output = output.model_copy(
                update={
                    "section_drafts": (
                        first.model_copy(update={"allocations": first.allocations[1:]}),
                        *output.section_drafts[1:],
                    ),
                    "notes": (note,),
                }
            )
        if self.scenario == "retry_collision" and len(self.calls) == 2:
            original = output.section_drafts[0].allocations[0].sentences[0]
            unsafe = original.model_copy(update={"text": "I led every library in the country."})
            first = output.section_drafts[0]
            first = first.model_copy(
                update={
                    "allocations": (
                        first.allocations[0].model_copy(update={"sentences": (unsafe,)}),
                        *first.allocations[1:],
                    )
                }
            )
            output = output.model_copy(
                update={
                    "section_drafts": (first, *output.section_drafts[1:]),
                    "notes": (unsafe_note(unsafe),),
                }
            )
        self.outputs.append(output)
        return output_model.model_validate(output.model_dump())
