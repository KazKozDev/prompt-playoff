"""Every number the documentation states out loud, checked against the code.

Prose drifts silently. The guides said the catalogue held "50 jobs grouped into
ten categories" long after the shelf held twelve categories and fifty-nine
tasks, and the README advertised thirty-two techniques over a registry of
sixty-one — undercounting by half. Neither is caught by a test of behaviour,
because both files render perfectly while lying.

So the counts are not proofread, they are asserted: the claim is located by the
sentence around it, and the numeral in it — digits, English words or Russian
words — is compared to what the registry and the catalogue actually hold.
"""

import re
from pathlib import Path

import pytest
import yaml

from prompt_playoff.registry import Registry

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src/prompt_playoff/data/static"
CATALOGUE = ROOT / "src/prompt_playoff/data/business_cases.yaml"

WORDS = {
    "eight": 8,
    "восьми": 8,
    "eleven": 11,
    "twelve": 12,
    "seventeen": 17,
    "twenty-three": 23,
    "twenty-eight": 28,
    "fifty": 50,
    "fifty-nine": 59,
    "sixty-one": 61,
    "одиннадцать": 11,
    "двенадцати": 12,
    "семнадцать": 17,
    "двадцать восемь": 28,
    "двадцать три": 23,
    "двенадцать": 12,
    "пятьдесят девять": 59,
    "шестидесяти одного": 61,
}


def _number(text: str) -> int:
    token = text.strip().lower()
    if token.isdigit():
        return int(token)
    if token in WORDS:
        return WORDS[token]
    raise AssertionError(f"{text!r} is not a numeral this test can read")


@pytest.fixture(scope="module")
def facts() -> dict[str, int]:
    registry = Registry.load()
    raw = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    business = {name for name in registry.datasets if name.startswith("business:")}
    return {
        "techniques": len(registry.techniques),
        "datasets": len(registry.datasets),
        "business_sets": len(business),
        "task_benchmarks": len(registry.datasets) - len(business),
        "categories": len(raw["taxonomy"]),
        "tasks": sum(len(item["tasks"]) for item in raw["taxonomy"]),
        "cases": sum(len(group["cases"]) for group in raw["groups"]),
    }


#: (file, pattern, the fact each capture group must equal). The pattern is
#: anchored on the words around the number so a rewrite that drops the claim
#: fails loudly rather than passing by absence.
CLAIMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("README.md", r"## (\S+) prompting techniques out of the box", ("techniques",)),
    ("README.md", r"schema-first extraction and (\d+) more", ("techniques_minus_four",)),
    ("help.html", r"catalogue of ([a-z-]+) techniques it was written from", ("techniques",)),
    (
        "help.html",
        r"shelf of ([a-z-]+) categories of business work, ([a-z-]+) tasks between them",
        ("categories", "tasks"),
    ),
    (
        "help.html",
        r"([A-Za-z-]+) sets ship with the app: ([a-z-]+) task benchmarks, "
        r"and ([a-z-]+) covering",
        ("datasets", "task_benchmarks", "business_sets"),
    ),
    ("evaluation.html", r"(\d+) categories holding (\d+) tasks", ("categories", "tasks")),
    ("evaluation.html", r"recorded cases underneath: (\d+) jobs", ("cases",)),
    (
        "evaluation.html",
        r"([A-Za-z-]+) of the ([a-z-]+) cases have a public dataset",
        ("direct_matches", "cases"),
    ),
    ("help.ru.html", r"каталог из ([а-яё ]+?) метода", ("techniques",)),
    (
        "help.ru.html",
        r"полкой из ([а-яё ]+?) категорий бизнес-работы, ([а-яё ]+?) задач",
        ("categories", "tasks"),
    ),
    (
        "help.ru.html",
        r"идут ([а-яё ]+?) набор(?:а|ов): ([а-яё ]+?) задачных бенчмарков и ([а-яё ]+?) по работе",
        ("datasets", "task_benchmarks", "business_sets"),
    ),
    ("evaluation.ru.html", r"(\d+) категорий и (\d+) задач", ("categories", "tasks")),
    ("evaluation.ru.html", r"кейсы: (\d+) работ", ("cases",)),
]


def _text(name: str) -> str:
    path = ROOT / name if name == "README.md" else STATIC / name
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name,pattern,keys", CLAIMS, ids=[f"{c[0]}:{c[2][0]}" for c in CLAIMS])
def test_the_documentation_states_the_counts_the_code_actually_holds(
    name: str, pattern: str, keys: tuple[str, ...], facts: dict[str, int]
) -> None:
    match = re.search(pattern, _text(name))
    assert match, f"{name} no longer states this count — the claim was reworded or dropped"
    for index, key in enumerate(keys, start=1):
        stated = _number(match.group(index))
        if key == "techniques_minus_four":
            # The README names four techniques, then counts the rest.
            assert stated == facts["techniques"] - 4, name
        elif key == "direct_matches":
            # Not derivable from a count: it is a claim about the mapping, and
            # only its consistency with the case total is checkable here.
            assert 0 < stated <= facts["cases"], name
        else:
            assert stated == facts[key], f"{name} says {stated} {key}, the code holds {facts[key]}"


#: The ladder guide states how many rungs it has, in four places across two
#: languages and the navigation. The number it should state is the number of
#: rows in its own table, so it is counted rather than proofread — the same
#: rule the rest of this file applies to the registry.
LADDER_CLAIMS = [
    ("llm-or-not.html", r"which of ([a-z]+) solution classes"),
    ("llm-or-not.html", r'content="([A-Z][a-z]+) solution classes'),
    ("llm-or-not.ru.html", r"какой из ([а-яё]+) классов решения"),
    ("navigation.js", r"'Do you need an LLM\?', '([A-Z][a-z]+) solution classes"),
]


def _rungs(name: str) -> int:
    body = re.search(r"<tbody>(.*?)</tbody>", _text(name), re.S)
    assert body, f"{name} no longer opens with the ladder table"
    return len(re.findall(r"<tr>", body.group(1)))


def test_both_ladder_guides_list_the_same_rungs() -> None:
    assert _rungs("llm-or-not.html") == _rungs("llm-or-not.ru.html")


@pytest.mark.parametrize("name,pattern", LADDER_CLAIMS, ids=[f"{c[0]}" for c in LADDER_CLAIMS])
def test_the_ladder_guide_states_as_many_classes_as_it_lists(name: str, pattern: str) -> None:
    match = re.search(pattern, _text(name))
    assert match, f"{name} no longer states how many solution classes there are"
    assert _number(match.group(1)) == _rungs("llm-or-not.html")
