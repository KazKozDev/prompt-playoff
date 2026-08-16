"""Concrete, deterministic examples for the technique catalog.

The catalog must demonstrate methods, not reuse one generic task across many
cards.  Every registry technique therefore owns a distinct input here, while
the prompt text itself is still produced by :class:`PromptCompiler` from the
live recipe.  Drift is caught by tests that require exact registry coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompt_playoff.compiler import PromptCompiler
from prompt_playoff.domain import (
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
    "reasoning.least-to-most": TechniqueExample(
        TaskType.coding,
        "A depot ships 3 crates per pallet, 7 pallets per truck, and pays €12 per truck plus €0.40 "
        "per crate. Give the total cost of shipping 148 crates.",
        "The subproblems have a strict dependency order, so the second stage can only solve them "
        "in the order the first stage established.",
        domain="logistics",
    ),
    "reasoning.analogical": TechniqueExample(
        TaskType.coding,
        "Design a rate limiter that tolerates short bursts but caps sustained throughput, and say "
        "what it does when the clock jumps backwards.",
        "The model must recall its own comparable problems before solving, so the demonstrations "
        "are generated rather than supplied.",
        domain="distributed systems",
    ),
    "reasoning.chain-of-symbol": TechniqueExample(
        TaskType.agents,
        "Box A sits on the left shelf, B is directly above A, C is to the right of B, and D is "
        "below C. Give the order to remove them so nothing is lifted through another box.",
        "Spatial relations stated in prose are condensed to symbols before any planning happens.",
        domain="spatial planning",
    ),
    "reasoning.tabular-cot": TechniqueExample(
        TaskType.coding,
        "A meter reads 41,208 kWh on 1 March and 44,976 kWh on 1 June. At €0.28/kWh with a €9.50 "
        "monthly standing charge, compute the quarterly bill.",
        "Each arithmetic step lands in its own table row with the operation stated separately from "
        "its result.",
        domain="arithmetic",
    ),
    "summarization.chain-of-density": TechniqueExample(
        TaskType.summarization,
        "Summarize: ‘The 2024 pilot ran in Girona with 312 households. Uptake reached 68% by "
        "week six, against a 45% target. Costs came in at €214 per household, above the €180 "
        "forecast, driven mainly by installer scheduling. The council extended it to Figueres "
        "in January.’",
        "The first pass is deliberately sparse so the second can fold named entities in at the "
        "same length.",
        domain="program evaluation",
    ),
    "direct.role-prompting": TechniqueExample(
        TaskType.creative_writing,
        "Write the opening paragraph of a museum wall label for a 12th-century astrolabe, for "
        "visitors who have never seen one.",
        "The answer changes with the expertise assumed, which is exactly what the technique fixes.",
        domain="museum curation",
    ),
    "reasoning.progressive-hint": TechniqueExample(
        TaskType.coding,
        "A tank fills at 14 L/min and drains at 9 L/min. It starts at 120 L and holds 400 L. How "
        "long until it overflows if the drain fails after 20 minutes?",
        "The second pass sees the first answer as a hint and must either confirm or replace it.",
        domain="arithmetic",
    ),
    "coding.structured-cot": TechniqueExample(
        TaskType.coding,
        "Implement normalize_phone(text, country) returning E.164, handling local prefixes, "
        "extensions, and unparseable input.",
        "The plan is written as sequence, branch and loop structures before any code exists.",
        domain="Python",
    ),
    "reasoning.graph-of-thought": TechniqueExample(
        TaskType.research,
        "Assess whether a mid-size grocery chain should build its own delivery fleet or contract "
        "it out, given rural coverage obligations.",
        "Three framings are developed independently and the answer is merged from parts of each.",
        domain="operations strategy",
    ),
    "reasoning.code-prompting": TechniqueExample(
        TaskType.research,
        "A grant pays 60% of costs unless the applicant received support in the prior year, in "
        "which case it pays 30% — but never below €2,000 for rural applicants. A rural applicant "
        "with €9,000 costs took support last year. What is paid?",
        "Nested conditions with an exception are rewritten as pseudo-code and traced by hand.",
        domain="public policy",
    ),
    "coding.chain-of-code": TechniqueExample(
        TaskType.coding,
        "Given a list of customer complaints, count how many express frustration about delivery "
        "timing rather than product quality.",
        "The semantic test cannot be executed, so it is written as a call and its result marked "
        "simulated.",
        domain="Python",
    ),
    "reasoning.faithful-cot": TechniqueExample(
        TaskType.coding,
        "A cyclist rides 18 km at 24 km/h, rests 25 minutes, then rides 12 km at 16 km/h. Give "
        "the average speed over the whole journey including the rest.",
        "The symbolic chain is written first and the answer is derived from that chain alone.",
        domain="arithmetic",
    ),
    "context.thread-of-thought": TechniqueExample(
        TaskType.research,
        "From this thread — a standup, two off-topic links, a deploy notice, a customer complaint, "
        "and a rollback note — state whether the payment bug reached production.",
        "The context is disordered, so each part is judged relevant or not before answering.",
        domain="incident review",
    ),
    "reasoning.logic-of-thought": TechniqueExample(
        TaskType.research,
        "Every audited vendor is bonded. No bonded vendor is uninsured. Vendor K is uninsured. "
        "Can Vendor K have been audited?",
        "Contraposition is needed to reach the answer, which is what the expansion step recovers.",
        domain="formal logic",
    ),
    "reasoning.narrative-of-thought": TechniqueExample(
        TaskType.structured_extraction,
        "The alarm was already ringing when Petra arrived, though the technician had reset it "
        "after the outage that followed the storm. Order the events.",
        "The text narrates events out of order, so the story is retold before the ordering is read "
        "back out.",
        domain="event ordering",
    ),
    "reasoning.layer-of-thought": TechniqueExample(
        TaskType.research,
        "From these eight candidate venues, find the ones seating over 200, available on a "
        "Tuesday, within 3 km of the station, and with step-free access.",
        "Four constraints are applied as successive layers so every exclusion carries a reason.",
        domain="venue selection",
    ),
    "reasoning.cumulative": TechniqueExample(
        TaskType.research,
        "Given that the deploy preceded the error spike, the rollback did not clear it, and the "
        "database migration ran an hour earlier, determine what the evidence supports.",
        "Each proposition is verified against the accepted set before it enters the argument.",
        domain="incident analysis",
    ),
    "reasoning.maieutic": TechniqueExample(
        TaskType.classification,
        "Claim: ‘The outage was caused by the config change.’ Decide whether the evidence supports "
        "it, given that the change shipped at 14:02 and errors began at 13:40.",
        "Both sides are argued in good faith and the decision turns on which set holds together.",
        domain="incident analysis",
    ),
    "grounding.generated-knowledge": TechniqueExample(
        TaskType.research,
        "Explain why sourdough starters fail to rise in a cold kitchen and what actually fixes it.",
        "The facts the answer rests on are stated first, then cited as the answer is built.",
        domain="food science",
    ),
    "grounding.recitation": TechniqueExample(
        TaskType.research,
        "What does the Berne Convention say about the minimum term of copyright protection?",
        "The relevant passage is recited from memory before the question is answered from it.",
        domain="intellectual property",
    ),
    "grounding.chain-of-knowledge": TechniqueExample(
        TaskType.research,
        "May a tenant install a heat pump on a shared facade — considering the lease, the building "
        "regulations, and local noise limits?",
        "The question spans three separate bodies of knowledge that must be reconciled, not "
        "merged.",
        domain="property law",
    ),
    "verification.verify-and-edit": TechniqueExample(
        TaskType.research,
        "Explain why the Hanseatic League declined, then correct any step that does not hold.",
        "Uncertain steps become standalone questions, and only the contradicted steps are "
        "rewritten.",
        domain="economic history",
    ),
    "reasoning.simtom": TechniqueExample(
        TaskType.research,
        "Ines put the invoice in the blue folder and left. Bram moved it to the drawer. Where will "
        "Ines look for it, and where is it?",
        "The context is first reduced to what one participant observed, which separates belief "
        "from fact.",
        domain="theory of mind",
    ),
    "direct.emotional-stimuli": TechniqueExample(
        TaskType.creative_writing,
        "Write a 120-word note telling a long-standing supplier that their contract will not be "
        "renewed.",
        "The framing raises the care taken without altering what the task asks for.",
        domain="business writing",
    ),
    "reasoning.scratchpad": TechniqueExample(
        TaskType.coding,
        "Trace a stack machine through PUSH 4, PUSH 7, ADD, PUSH 3, MUL, DUP, SUB and report the "
        "final stack.",
        "The full machine state must be rewritten after every instruction rather than carried "
        "implicitly.",
        domain="virtual machines",
    ),
    "reasoning.instance-adaptive-cot": TechniqueExample(
        TaskType.classification,
        "Ticket: ‘Password reset email never arrives, but only for our @school.edu addresses.’",
        "The instance looks trivial and is not, so classifying its difficulty changes how much "
        "reasoning it gets.",
        domain="support triage",
    ),
    "direct.directional-stimulus": TechniqueExample(
        TaskType.summarization,
        "Condense this quarterly report into three sentences for the board: revenue €4.2M "
        "(up 11%), churn 3.1% (up from 2.4%), two enterprise logos lost, headcount flat.",
        "Keywords are extracted first so generation is conditioned on them instead of on an "
        "impression of the text.",
        domain="corporate reporting",
    ),
    "structured.chain-of-table": TechniqueExample(
        TaskType.structured_extraction,
        "From a table of 40 orders with columns region, channel, units, and unit_price, find which "
        "region had the highest revenue through the retail channel.",
        "The table is transformed by named operations and shown after each, so the answer is "
        "visible in it.",
        domain="sales analytics",
        response_schema=LABEL_SCHEMA,
    ),
    "verification.reflexion": TechniqueExample(
        TaskType.coding,
        "Write merge_intervals(intervals) that merges overlapping ranges, then critique and redo "
        "it.",
        "The first attempt is evaluated into an explicit lesson that the second attempt must "
        "follow.",
        domain="Python",
    ),
    "agents.meta-prompting": TechniqueExample(
        TaskType.research,
        "Should a 30-person company self-host its analytics stack? Weigh the engineering, legal, "
        "and cost sides.",
        "Each side is answered under its own brief in isolation, then the conductor resolves the "
        "conflicts.",
        domain="technology strategy",
    ),
    "reasoning.graph-flattening": TechniqueExample(
        TaskType.structured_extraction,
        "From a build graph where api depends on core and db, web depends on api, jobs depends on "
        "db and core, and core depends on nothing, give a valid build order.",
        "The graph is linearized into an ordered edge list before any reachability claim is made.",
        domain="build systems",
    ),
    "reasoning.buffer-of-thoughts": TechniqueExample(
        TaskType.coding,
        "Find the number of ways to make €2.35 from coins of 5, 10, 20, 50 and 100 cents.",
        "The reusable template for coin-change problems is distilled before it is filled in for "
        "this instance.",
        domain="combinatorics",
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
