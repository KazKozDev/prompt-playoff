"""Build deterministic datasets for the four previously uncovered task types.

Each collection starts with hand-written seeds and then expands from controlled
templates. Gold values are consequences of construction, not model labels.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

TARGET = 120
SEED = 20260808
OUT = Path("src/prompt_playoff/data/datasets")


def _write(name: str, rows: list[dict[str, Any]]) -> None:
    assert len(rows) == TARGET, f"{name}: expected {TARGET} rows, got {len(rows)}"
    ids = [row["id"] for row in rows]
    inputs = [row["input"] for row in rows]
    assert len(set(ids)) == TARGET, f"{name}: duplicate ids"
    assert len(set(inputs)) == TARGET, f"{name}: duplicate inputs"
    path = OUT / f"{name}.jsonl"
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"wrote {len(rows)} examples to {path}")


TRANSLATION_SEEDS = [
    (
        "The audit trail records every workspace change.",
        "El registro de auditoría registra cada cambio del espacio de trabajo.",
        {"audit trail": "registro de auditoría", "workspace": "espacio de trabajo"},
    ),
    (
        "Enable dark mode before opening the dashboard.",
        "Activa el modo oscuro antes de abrir el panel de control.",
        {"dark mode": "modo oscuro", "dashboard": "panel de control"},
    ),
    (
        "The service agreement includes a recovery point objective.",
        "El acuerdo de servicio incluye un objetivo de punto de recuperación.",
        {
            "service agreement": "acuerdo de servicio",
            "recovery point objective": "objetivo de punto de recuperación",
        },
    ),
    (
        "Rotate the access token after the security review.",
        "Rota el token de acceso después de la revisión de seguridad.",
        {"access token": "token de acceso", "security review": "revisión de seguridad"},
    ),
]

SUBJECTS = [
    ("The support team", "El equipo de soporte"),
    ("The release manager", "El responsable de versiones"),
    ("The data steward", "El administrador de datos"),
    ("The platform owner", "El propietario de la plataforma"),
]
VERBS = [
    ("reviews", "revisa"),
    ("archives", "archiva"),
    ("updates", "actualiza"),
    ("checks", "comprueba"),
]
TERMS = [
    ("audit trail", "registro de auditoría"),
    ("feature flag", "indicador de función"),
    ("incident report", "informe de incidente"),
    ("deployment window", "ventana de despliegue"),
    ("retention policy", "política de retención"),
    ("service account", "cuenta de servicio"),
]
CADENCES = [
    ("every Monday", "cada lunes"),
    ("before each release", "antes de cada versión"),
    ("after every incident", "después de cada incidente"),
    ("once per quarter", "una vez por trimestre"),
]


def build_translation() -> list[dict[str, Any]]:
    triples = list(TRANSLATION_SEEDS)
    for subject_en, subject_es in SUBJECTS:
        for verb_en, verb_es in VERBS:
            for term_en, term_es in TERMS:
                for cadence_en, cadence_es in CADENCES:
                    source = f"{subject_en} {verb_en} the {term_en} {cadence_en}."
                    target = f"{subject_es} {verb_es} el {term_es} {cadence_es}."
                    triples.append((source, target, {term_en: term_es, cadence_en: cadence_es}))
    rows = []
    for index, (source, target, glossary) in enumerate(triples[:TARGET], 1):
        for source_term, target_term in glossary.items():
            assert source_term in source
            assert target_term in target
        rows.append(
            {
                "id": f"translation-{index:03d}",
                "input": (
                    "Translate the SOURCE from English to Spanish. Return only the translation.\n"
                    f"SOURCE: {source}"
                ),
                "expected": target,
                "graders": ["glossary_consistency", "omission_check"],
                "grader_options": {
                    "glossary": glossary,
                    "source": source,
                    "min_ratio": 0.55,
                    "max_ratio": 1.8,
                },
                "variables": {
                    "target_language": "Spanish",
                    "glossary": "; ".join(f"{a} = {b}" for a, b in glossary.items()),
                    "register": "neutral professional prose",
                },
                "tags": ["handwritten" if index <= len(TRANSLATION_SEEDS) else "generated"],
            }
        )
    return rows


SUMMARY_SEEDS = [
    (
        "Project Cedar launched in Porto on 14 March. It reduced queue time by 18%. "
        "The pilot involved 240 customers. No security incidents were reported.",
        ["Project Cedar", "Porto", "14 March", "18%", "240 customers"],
    ),
    (
        "Clinic North added weekend appointments in Leeds on 6 May. Waiting time fell 22%. "
        "The trial served 310 patients and cost £48,000.",
        ["Clinic North", "Leeds", "6 May", "22%", "310 patients"],
    ),
    (
        "Depot Seven opened in Brno on 9 September. Delivery errors dropped 11%. "
        "The first month covered 1,400 parcels and used 16 couriers.",
        ["Depot Seven", "Brno", "9 September", "11%", "1,400 parcels"],
    ),
]
PROJECTS = ["Project Alder", "Project Beacon", "Project Cobalt", "Project Delta", "Project Elm"]
CITIES = ["Bilbao", "Graz", "Lille", "Turin", "Utrecht"]
DATES = ["3 February", "17 April", "8 June", "21 August", "12 November"]


def build_summarization() -> list[dict[str, Any]]:
    records = list(SUMMARY_SEEDS)
    for project in PROJECTS:
        for city in CITIES:
            for date in DATES:
                index = len(records)
                percent = 7 + (index * 7) % 31
                people = 120 + (index * 37) % 780
                document = (
                    f"{project} began in {city} on {date}. The programme cut processing time by "
                    f"{percent}%. The evaluation covered {people} participants. "
                    f"The steering group met {(index % 8) + 2} times. "
                    "A follow-up review is planned for next year."
                )
                records.append(
                    (document, [project, city, date, f"{percent}%", f"{people} participants"])
                )
    rows = []
    for index, (document, required) in enumerate(records[:TARGET], 1):
        assert all(value in document for value in required)
        max_chars = 170
        rows.append(
            {
                "id": f"summarization-{index:03d}",
                "input": (
                    f"Summarize the DOCUMENT in at most {max_chars} characters. Preserve all "
                    "named entities, dates, quantities, and units; return only the summary.\n"
                    f"DOCUMENT: {document}"
                ),
                "expected": "; ".join(required),
                "graders": ["contains_all", "length_limit"],
                "grader_options": {"contains": required, "max_chars": max_chars},
                "tags": ["handwritten" if index <= len(SUMMARY_SEEDS) else "generated"],
            }
        )
    return rows


RESEARCH_SEEDS = [
    {
        "question": "What was the verified uptime of Atlas in Q2?",
        "sources": [
            "Source A: Atlas uptime was 99.91% in Q2.",
            "Source B: The Q2 Atlas report covers April through June.",
        ],
        "required": ["Atlas", "99.91%", "Q2"],
        "expected": "Atlas had 99.91% uptime in Q2.",
        "settled": True,
    },
    {
        "question": "How many active users did Boreal have in July?",
        "sources": [
            "Source A: Boreal had 18,400 active users in June.",
            "Source B: The July Boreal note reports revenue but no user count.",
        ],
        "required": ["INSUFFICIENT_EVIDENCE"],
        "expected": "INSUFFICIENT_EVIDENCE",
        "settled": False,
    },
]
SUBJECT_METRICS = [
    ("Atlas", "uptime", "%"),
    ("Boreal", "active users", "users"),
    ("Cygnus", "median latency", "ms"),
    ("Dorado", "renewal rate", "%"),
    ("Equinox", "energy use", "MWh"),
]
PERIODS = ["January", "Q1", "May", "Q2", "September", "Q3"]


def build_research() -> list[dict[str, Any]]:
    cases = list(RESEARCH_SEEDS)
    for subject, metric, unit in SUBJECT_METRICS:
        for period_index, period in enumerate(PERIODS):
            for variant in range(4):
                base = 40 + (period_index * 13 + variant * 17 + len(subject)) % 750
                value = f"{base}.{variant + 1}%" if unit == "%" else f"{base + variant} {unit}"
                previous = PERIODS[(period_index - 1) % len(PERIODS)]
                settled = variant != 3
                if settled:
                    sources = [
                        f"Source A: The verified {metric} for {subject} in {period} was {value}.",
                        f"Source B: {subject}'s reporting period labelled {period} is complete.",
                        (
                            f"Source C: The prior {previous} figure is not used for the "
                            f"{period} result."
                        ),
                    ]
                    required = [subject, value, period]
                    expected = f"{subject} reported {value} {metric} in {period}."
                else:
                    sources = [
                        (
                            f"Source A: The {subject} note gives {metric} for {previous}, "
                            f"not {period}."
                        ),
                        f"Source B: The {period} report for {subject} does not state {metric}.",
                        (
                            "Source C: When the requested period is absent, the evidence is "
                            "insufficient."
                        ),
                    ]
                    required = ["INSUFFICIENT_EVIDENCE"]
                    expected = "INSUFFICIENT_EVIDENCE"
                cases.append(
                    {
                        "question": f"What was {subject}'s verified {metric} in {period}?",
                        "sources": sources,
                        "required": required,
                        "expected": expected,
                        "settled": settled,
                    }
                )
    rows = []
    for index, case in enumerate(cases[:TARGET], 1):
        evidence = "\n".join(case["sources"])
        assert all(item in evidence for item in case["required"] if item != "INSUFFICIENT_EVIDENCE")
        policy = (
            "Answer the QUESTION using only the SOURCES. Include the subject, metric, reporting "
            "period, value, and unit. If the sources do not settle the requested period and "
            "metric, "
            "return exactly INSUFFICIENT_EVIDENCE.\n"
        )
        rows.append(
            {
                "id": f"research-{index:03d}",
                "input": f"{policy}QUESTION: {case['question']}\nSOURCES:\n{evidence}",
                "expected": case["expected"],
                "graders": ["grounding_overlap", "contains_all"],
                "grader_options": {
                    "evidence": f"{evidence}\nAllowed abstention: INSUFFICIENT_EVIDENCE",
                    "contains": case["required"],
                },
                "tags": [
                    "handwritten" if index <= len(RESEARCH_SEEDS) else "generated",
                    "settled" if case["settled"] else "unsettled",
                ],
            }
        )
    return rows


AGENT_SEEDS = [
    (
        "Use the calculator tool to evaluate (19 * 7) + 4. Return exactly the result value "
        "shown by the tool, and nothing else.",
        "137.0",
    ),
    (
        "Use the word_count tool on exactly this text: red fox crosses quiet field. "
        "Return only the integer count.",
        "5",
    ),
]
WORDS = ["amber", "birch", "calm", "delta", "ember", "forest", "glade", "harbor", "island"]


def build_agents() -> list[dict[str, Any]]:
    rng = random.Random(SEED)
    tasks = list(AGENT_SEEDS)
    seen = {task for task, _ in tasks}
    while len(tasks) < TARGET:
        if len(tasks) % 2 == 0:
            left = rng.randint(11, 97)
            right = rng.randint(3, 29)
            offset = rng.randint(-20, 40)
            expression = f"({left} * {right}) + ({offset})"
            task = (
                f"Use the calculator tool to evaluate {expression}. "
                "Return exactly the result value shown by the tool, and nothing else."
            )
            expected = str(float(left * right + offset))
        else:
            count = rng.randint(4, 9)
            selected = [rng.choice(WORDS) for _ in range(count)]
            text = " ".join(selected) + "."
            task = (
                f"Use the word_count tool on exactly this text: {text} "
                "Return only the integer count."
            )
            expected = str(count)
        if task in seen:
            continue
        seen.add(task)
        tasks.append((task, expected))
    return [
        {
            "id": f"agents-{index:03d}",
            "input": task,
            "expected": expected,
            "graders": ["tool_success", "exact_match"],
            "tags": [
                "handwritten" if index <= len(AGENT_SEEDS) else "generated",
                "word-count" if "word_count" in task else "calculator",
            ],
        }
        for index, (task, expected) in enumerate(tasks, 1)
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    _write("translation", build_translation())
    _write("summarization", build_summarization())
    _write("grounded-qa", build_research())
    _write("agents", build_agents())


if __name__ == "__main__":
    main()
