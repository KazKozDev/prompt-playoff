"""Concrete, deterministic examples for the technique catalog.

The catalog must demonstrate methods, not reuse one generic task across many
cards.  Every registry technique therefore owns a distinct input here, while
the prompt text itself is still produced by :class:`PromptCompiler` from the
live recipe.  Drift is caught by tests that require exact registry coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import (
    Capability,
    Constraints,
    Exemplar,
    ModelClass,
    ModelProfile,
    TaskProfile,
    TaskType,
    TechniqueSpec,
)


@dataclass(frozen=True)
class TechniqueExample:
    task_type: TaskType
    user_input: str
    why_this_example: str
    domain: str = "general"
    response_schema: dict[str, Any] | None = None
    exemplars: tuple[Exemplar, ...] = ()
    variables: dict[str, str] = field(default_factory=dict)


LABEL_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string"}},
    "required": ["label"],
    "additionalProperties": False,
}

ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["people", "places"],
    "additionalProperties": False,
}

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_id": {"type": "string"},
        "currency": {"type": "string"},
        "total": {"type": "number"},
    },
    "required": ["invoice_id", "currency", "total"],
    "additionalProperties": False,
}


EXAMPLES: dict[str, TechniqueExample] = {
    "verification.backward-check": TechniqueExample(
        TaskType.structured_extraction,
        "From the clause ‘Marta must deliver the keys in Valencia by 12 June’, extract "
        "the actor, obligation, place, and deadline. Do not infer missing terms.",
        "The second pass must trace every extracted field back to the clause.",
        domain="legal",
    ),
    "reasoning.chain-of-draft": TechniqueExample(
        TaskType.coding,
        "Design a Python chess-clock state machine with pause, increment, timeout, and turn "
        "switching, then provide the implementation.",
        "The planning stage is forced into five-word notes before the final code is written.",
        domain="software",
    ),
    "grounding.chain-of-note": TechniqueExample(
        TaskType.research,
        "Source A says the pilot started in 2023 with 40 users. Source B reports 61 users in "
        "2024. Explain what changed without combining the two reporting periods.",
        "The method records one evidence note per source before synthesizing an answer.",
        domain="program evaluation",
    ),
    "verification.chain-of-verification": TechniqueExample(
        TaskType.research,
        "Using the supplied policy memo, state the eligibility age, application deadline, and "
        "maximum award; explicitly mark anything the memo does not state.",
        "A draft is followed by independent verification questions and a corrected final answer.",
        domain="public policy",
    ),
    "classification.label-rules": TechniqueExample(
        TaskType.classification,
        "Ticket: ‘I was charged twice after upgrading, but the app itself works.’",
        "The ambiguity between billing and technical support exercises declared label boundaries.",
        response_schema=LABEL_SCHEMA,
        exemplars=(
            Exemplar(input="The export button crashes.", output='{"label":"technical"}'),
            Exemplar(input="Refund my duplicate payment.", output='{"label":"billing"}'),
        ),
        variables={
            "label_set": "billing | technical | account",
            "boundaries": (
                "Payment, invoice, refund → billing. Broken product behavior → technical. "
                "Login or identity changes → account."
            ),
        },
    ),
    "coding.tests-first": TechniqueExample(
        TaskType.coding,
        "Implement parse_duration(text) supporting 90s, 15m, and 2h; reject negatives, empty "
        "strings, decimals, and unknown units.",
        "Observable edge cases become tests before any implementation is produced.",
        domain="Python",
    ),
    "few-shot.contrastive-cot": TechniqueExample(
        TaskType.classification,
        "Classify ‘The password reset email never arrives’ as billing, technical, or account.",
        "Correct and incorrect demonstrations teach the decision boundary, not just the format.",
        response_schema=LABEL_SCHEMA,
        exemplars=(
            Exemplar(
                input="I cannot update my recovery email.",
                output='{"label":"account"}',
                note="Correct: identity settings are an account issue.",
            ),
            Exemplar(
                input="The invoice total is wrong.",
                output='{"label":"technical"}',
                note="Incorrect: this should be billing, not technical.",
            ),
        ),
    ),
    "creative.constraint-lattice": TechniqueExample(
        TaskType.creative_writing,
        "Write an 800-word opening in which a night-shift metro controller notices a train that "
        "does not exist on the timetable.",
        "Premise, audience, voice, and exclusions remain fixed as a visible constraint lattice.",
        domain="fiction",
        variables={
            "premise": "A nonexistent train appears on a live metro control map.",
            "audience": "adult readers of grounded psychological thrillers",
            "voice": "close third person, restrained and tense",
            "exclusions": "no supernatural explanation, dream reveal, or exposition dump",
        },
    ),
    "verification.critique-revise": TechniqueExample(
        TaskType.translation,
        "Translate ‘The tenant may terminate only after written notice’ into Spanish. Preserve "
        "the legal force of ‘may’ and ‘only’ and return only the translation.",
        "The draft is checked against explicit terminology and omission criteria, then revised.",
        domain="legal translation",
    ),
    "reasoning.decomposition": TechniqueExample(
        TaskType.research,
        "Evaluate whether a four-day workweek pilot is suitable for a 60-person support team: "
        "separate staffing, coverage, cost, quality, and measurement questions.",
        "Independent subproblems are listed first and solved before the result is merged.",
        domain="operations",
    ),
    "direct.explicit-constraints": TechniqueExample(
        TaskType.summarization,
        "Summarize the release note into exactly three bullets: user-visible change, migration "
        "action, and known limitation. Use only the supplied note.",
        "A single call follows explicit constraints without adding a reasoning workflow.",
        domain="product communication",
    ),
    "structured.few-shot-repair": TechniqueExample(
        TaskType.structured_extraction,
        "Invoice AC-204 states: total EUR 1,240.50, payable within 30 days.",
        "A demonstrated JSON shape is generated first, then a validator stage repairs it.",
        domain="invoices",
        response_schema=INVOICE_SCHEMA,
        exemplars=(
            Exemplar(
                input="Invoice B-7. Total USD 99.00.",
                output='{"invoice_id":"B-7","currency":"USD","total":99.0}',
            ),
        ),
    ),
    "context.map-reduce": TechniqueExample(
        TaskType.summarization,
        "Summarize a 120-page incident archive by month, then produce one chronology containing "
        "only causes supported by at least one monthly section.",
        "The long input is mapped chunk by chunk and reduced from partial summaries.",
        domain="incident response",
    ),
    "reasoning.metacognitive": TechniqueExample(
        TaskType.classification,
        "Decide whether ‘Cancel the subscription but keep my workspace data’ is a billing or "
        "account request, and return one label.",
        "The model states its interpretation and confidence before checking its own decision.",
        domain="support routing",
        response_schema=LABEL_SCHEMA,
    ),
    "reasoning.plan-execute": TechniqueExample(
        TaskType.coding,
        "Create a migration that adds immutable audit events to an existing SQLite application "
        "without breaking current reads.",
        "A bounded executable plan is produced in one stage and carried into implementation.",
        domain="database migration",
    ),
    "reasoning.program-of-thought": TechniqueExample(
        TaskType.research,
        "Given monthly users [120, 150, 135, 210], calculate month-over-month changes, mean users, "
        "and the largest absolute change.",
        "The model writes a small computation program and uses its result for the answer.",
        domain="analytics",
    ),
    "reasoning.re-reading": TechniqueExample(
        TaskType.structured_extraction,
        "Extract every date and responsible person from: ‘Ana approved on 3 May; Luis reviewed on "
        "5 May; final publication was 8 May.’",
        "The complete input is deliberately presented twice before extraction.",
        domain="document review",
        response_schema=ENTITY_SCHEMA,
    ),
    "agents.react": TechniqueExample(
        TaskType.agents,
        "Use the available calculator to determine which is cheaper: €24 per month for 18 months "
        "or a one-time €399 payment. Report the observed totals.",
        "The prompt enforces a tool call → observation → supported conclusion loop.",
        domain="cost comparison",
    ),
    "reasoning.rephrase-and-respond": TechniqueExample(
        TaskType.coding,
        "Make the upload safer and fast, but do not change what existing clients see.",
        "The ambiguous request is restated with an explicit success condition before solving it.",
        domain="software requirements",
    ),
    "grounding.evidence-first": TechniqueExample(
        TaskType.research,
        "Evidence: the 2024 report lists 18% adoption; the 2025 report lists 27%. State the change "
        "in percentage points and keep both reporting years visible.",
        "Claims must be paired with supplied evidence before synthesis is allowed.",
        domain="market research",
    ),
    "structured.schema-first": TechniqueExample(
        TaskType.structured_extraction,
        "Text: ‘Nora met Pavel in Zaragoza. Later Pavel travelled alone to Bilbao.’ Extract people "
        "and places; never infer relationships.",
        "The JSON schema is the primary contract and every value must be grounded in the input.",
        domain="entity extraction",
        response_schema=ENTITY_SCHEMA,
    ),
    "reasoning.self-ask": TechniqueExample(
        TaskType.research,
        "Explain whether a Spanish autónomo can apply for an EU Digital Europe grant, separating "
        "programme eligibility from call-specific eligibility.",
        "The model creates and answers prerequisite questions before the final conclusion.",
        domain="grants",
    ),
    "reasoning.self-consistency": TechniqueExample(
        TaskType.research,
        "A project has a 60% chance of €40k profit and a 40% chance of €15k loss. "
        "Calculate expected value and state whether it is positive.",
        "Several independently sampled solutions are aggregated instead of trusting one path.",
        domain="decision analysis",
    ),
    "reasoning.skeleton-of-thought": TechniqueExample(
        TaskType.summarization,
        "Turn the supplied climate adaptation report into a six-section executive briefing, with "
        "one claim and one action per section.",
        "A concise answer skeleton is created before each point is expanded.",
        domain="executive briefing",
    ),
    "reasoning.step-back": TechniqueExample(
        TaskType.coding,
        "Design retry behavior for a payment API that may time out after the charge succeeded.",
        "The model first identifies the governing principle—idempotency—then applies it.",
        domain="distributed systems",
    ),
    "reasoning.system2-attention": TechniqueExample(
        TaskType.classification,
        "The customer mentions being angry, using an iPhone, and travelling tomorrow, but asks "
        "only to correct a duplicated invoice. Route the request.",
        "Distracting details are removed before the cleaned task is answered.",
        domain="support routing",
        response_schema=LABEL_SCHEMA,
    ),
    "translation.glossary-context": TechniqueExample(
        TaskType.translation,
        "Translate into German: ‘The workspace owner can revoke a recovery key without deleting "
        "the tenant.’ Preserve the product terminology exactly.",
        "Binding glossary terms and register rules are inserted directly into the translation "
        "prompt.",
        domain="software localization",
        variables={
            "target_language": "German",
            "glossary": "workspace owner → Workspace-Inhaber; recovery key → "
            "Wiederherstellungsschlüssel; tenant → Mandant (never Mieter)",
            "register": "formal product documentation",
        },
        exemplars=(
            Exemplar(
                input="The workspace owner rotated the recovery key.",
                output="Der Workspace-Inhaber hat den Wiederherstellungsschlüssel rotiert.",
            ),
        ),
    ),
    "reasoning.tree-of-thought": TechniqueExample(
        TaskType.coding,
        "Choose an architecture for offline-first collaborative notes with conflict resolution, "
        "then justify the final design under mobile storage constraints.",
        "Several distinct branches are expanded, ranked, and continued before answering.",
        domain="system design",
    ),
    "reasoning.zero-shot-cot": TechniqueExample(
        TaskType.research,
        "A service costs €80 plus 21% VAT, then receives a 15% discount on the VAT-inclusive "
        "price. Calculate the final amount.",
        "A single prompt explicitly elicits stepwise reasoning before the final result.",
        domain="arithmetic",
    ),
}


def compiled_examples(
    compiler: PromptCompiler,
    techniques: dict[str, TechniqueSpec],
) -> list[dict[str, Any]]:
    """Compile every catalog example through the production compiler."""
    entries: list[dict[str, Any]] = []
    capabilities = set(Capability)
    for technique_id in sorted(techniques):
        technique = techniques[technique_id]
        example = EXAMPLES[technique_id]
        task = TaskProfile(
            task_type=example.task_type,
            domain=example.domain,
            output_contract="json_schema" if example.response_schema else "free_text",
            complexity="high",
            constraints=Constraints(
                max_calls=20,
                tools_allowed=technique.tools_required,
                strict_json=example.response_schema is not None,
                requires_validation=technique.validation_fit,
            ),
            model=ModelProfile(
                provider="catalog-example",
                model_id="capable-example-model",
                model_class=ModelClass.large,
                local=False,
                context_window=32768,
                capabilities=capabilities,
            ),
        )
        program = compiler.compile(
            task=task,
            technique=technique,
            user_input=example.user_input,
            response_schema=example.response_schema,
            variables=example.variables,
            exemplars=list(example.exemplars),
        )
        entries.append(
            {
                "technique_id": technique_id,
                "task_type": example.task_type.value,
                "user_input": example.user_input,
                "why_this_example": example.why_this_example,
                "program": program.model_dump(mode="json"),
            }
        )
    return entries
