"""Compositional generator for entity-extraction-hard.

The 40 seed examples in ``build_hard_dataset.py`` are hand-written. Scaling to
200 by hand would mean 200 chances to mislabel something, so the rest are built
from templates: the gold answer comes from the *construction*, not from an
annotator reading the sentence back. Every rule in
``docs/datasets/entity-extraction-hard.md`` gets its own template family.

Deterministic: a fixed seed means the same dataset every time.
"""

from __future__ import annotations

import random

Row = tuple[list[str], str, list[str], list[str]]  # tags, text, people, places

GIVEN = [
    "Mara",
    "Orin",
    "Sera",
    "Pell",
    "Idris",
    "Alba",
    "Nadia",
    "Tomas",
    "Elara",
    "Bram",
    "Yuki",
    "Reza",
    "Noor",
    "Anya",
    "Cato",
    "Fen",
    "Hale",
    "Juno",
    "Mira",
    "Dag",
    "Isolde",
    "Rafe",
    "Suri",
    "Otto",
    "Lise",
    "Marek",
]
SURNAMES = ["Varga", "Ilic", "Renn", "Halloway", "Okonkwo", "Sandoval", "Petrov", "Aalto"]
TITLES = [
    "Captain",
    "Doctor",
    "Queen",
    "Brother",
    "Sister",
    "Sergeant",
    "Colonel",
    "Professor",
    "Father",
    "Lady",
    "Admiral",
    "Major",
]
PLACES = [
    "Veyr",
    "Kesh",
    "Ashfall",
    "Lorne",
    "Trieste",
    "Marseille",
    "Saint-Loup",
    "Kaldvik",
    "Norrland",
    "Ljubljana",
    "Highmoor",
    "Stonefall",
    "Ferrow",
    "Duraz",
    "Ostmark",
    "Calder",
]
MULTIWORD_PLACES = ["Glass Citadel", "Port Lorne", "Wray Point", "Bright Harbour", "Iron Gate"]
COMMON_PLACES = [
    "the abbey",
    "the harbour",
    "the river",
    "the valley",
    "the market",
    "the bridge",
    "the quarry",
    "the chapel",
    "the lighthouse",
    "the old town",
]
ROLES = [
    "The innkeeper",
    "The harbourmaster",
    "Her brother",
    "A courier",
    "The blacksmith",
    "The physician",
    "His cousin",
    "The magistrate",
    "The ferryman",
    "The night watchman",
]
ROLES_LOWER = [role[0].lower() + role[1:] for role in ROLES]
ORGS = [
    "the Verity Consortium",
    "the Norrland Bank",
    "the Lorne Shipping Line",
    "the Ferrow Salt Company",
    "the Highmoor Trust",
    "the Calder Mining Guild",
]
#: Organisation names that embed a place name — the place must NOT be extracted.
ORGS_WITH_PLACE = [
    ("the Kesh Mining Guild", "Kesh"),
    ("the Ashfall Company", "Ashfall"),
    ("the Trieste Maritime Board", "Trieste"),
    ("the Veyr Salt Works", "Veyr"),
    ("the Lorne Shipping Line", "Lorne"),
]
DEMONYMS = [
    ("Veyrish", "Veyr"),
    ("Triestine", "Trieste"),
    ("Kesh-born", "Kesh"),
    ("Lornish", "Lorne"),
    ("Ashfall-bound", "Ashfall"),
    ("Norrland-trained", "Norrland"),
]
BEINGS = ["The Hollow King", "the Drowned Man", "the Pale Sister", "the Weeping Boy", "Saint Alba"]


def _titled(rng: random.Random) -> str:
    return f"{rng.choice(TITLES)} {rng.choice(GIVEN)}"


def _full_name(rng: random.Random) -> str:
    return f"{rng.choice(GIVEN)} {rng.choice(SURNAMES)}"


def _place(rng: random.Random) -> str:
    return rng.choice(PLACES + MULTIWORD_PLACES)


def _sentence_case(text: str) -> str:
    """Uppercase only the first character.

    str.capitalize() lowercases the rest, which turns "the Ashfall Company"
    into "The ashfall company" — destroying the proper noun the example exists
    to test.
    """
    return text[:1].upper() + text[1:]


# --------------------------------------------------------------------------- #
# one builder per rule
# --------------------------------------------------------------------------- #


def build_title(rng: random.Random) -> Row:
    person, place = _titled(rng), _place(rng)
    text = rng.choice(
        [
            f"{person} refused to sail past {place}.",
            f"{person} was last seen leaving {place}.",
            f"Everyone in {place} remembered {person}.",
            f"{person} sent no word from {place} that winter.",
            f"They waited for {person} at {place} until dusk.",
        ]
    )
    return ["title"], text, [person], [place]


def build_title_multi(rng: random.Random) -> Row:
    one, two, place = _titled(rng), _full_name(rng), _place(rng)
    text = rng.choice(
        [
            f"{one} met {two} in {place}.",
            f"{one} and {two} argued the whole way to {place}.",
            f"{two} reported to {one} outside {place}.",
        ]
    )
    return ["title", "multi"], text, [one, two], [place]


def build_role_only(rng: random.Random) -> Row:
    role, place = rng.choice(ROLES), _place(rng)
    text = rng.choice(
        [
            f"{role} refused to serve them in {place}.",
            f"{role} had already left for {place}.",
            f"{role} waited at {place} without explanation.",
            f"{role} knew every road out of {place}.",
        ]
    )
    return ["role-only"], text, [], [place]


def build_common_noun_place(rng: random.Random) -> Row:
    person, common, place = rng.choice(GIVEN), rng.choice(COMMON_PLACES), _place(rng)
    text = rng.choice(
        [
            f"{person} slept in {common}, then rode to {place}.",
            f"{person} crossed {common} before reaching {place}.",
            f"{person} waited at {common} in {place}.",
        ]
    )
    return ["common-noun-place"], text, [person], [place]


def build_common_noun_only(rng: random.Random) -> Row:
    common, place = rng.choice(COMMON_PLACES), _place(rng)
    text = rng.choice(
        [
            f"They crossed {common} before reaching {place}.",
            f"{_sentence_case(common)} above {place} stood empty that season.",
            f"Nobody used {common} on the road to {place} any more.",
        ]
    )
    return ["common-noun-place"], text, [], [place]


def build_organisation(rng: random.Random) -> Row:
    org, place = rng.choice(ORGS), _place(rng)
    text = rng.choice(
        [
            f"{_sentence_case(org)} opened an office in {place}.",
            f"{_sentence_case(org)} withdrew from {place} in the spring.",
        ]
    )
    return ["organisation"], text, [], [place]


def build_organisation_embedding_place(rng: random.Random) -> Row:
    """The hard case: a place name inside an organisation is not a mention."""
    org, _hidden = rng.choice(ORGS_WITH_PLACE)
    person = rng.choice(GIVEN)
    text = rng.choice(
        [
            f"{person} left {org} and never spoke of it again.",
            f"{_sentence_case(org)} filed its accounts late.",
            f"{person} had worked for {org} since childhood.",
        ]
    )
    return ["organisation", "same-token"], text, ([person] if person in text else []), []


def build_organisation_and_bare_place(rng: random.Random) -> Row:
    """Same token twice: once inside an organisation, once as a real place."""
    org, hidden = rng.choice(ORGS_WITH_PLACE)
    person = rng.choice(GIVEN)
    text = f"{person} signed with {org} before ever seeing {hidden}."
    return ["organisation", "same-token"], text, [person], [hidden]


def build_demonym(rng: random.Random) -> Row:
    demonym, _place = rng.choice(DEMONYMS)
    person = rng.choice(GIVEN)
    text = rng.choice(
        [
            f"The {demonym} delegation arrived without {person}.",
            f"{person} spoke with a {demonym} accent.",
            f"{demonym} traders avoided the coast that year.",
        ]
    )
    return ["demonym"], text, ([person] if person in text else []), []


def build_demonym_with_place(rng: random.Random) -> Row:
    demonym, _hidden = rng.choice(DEMONYMS)
    place = rng.choice(PLACES)
    text = f"{demonym} traders avoided {place} that year."
    return ["demonym"], text, [], [place]


def build_fictional(rng: random.Random) -> Row:
    being, place = rng.choice(BEINGS), _place(rng)
    opener = _sentence_case(being)
    # Sentence-initial position changes the surface form, and the gold has to be
    # the form that actually appears — it must be copyable verbatim.
    text, mention = rng.choice(
        [
            (f"{opener} was a story children told in {place}.", opener),
            (f"Sailors in {place} swore {being} walked the pier.", being),
            (f"They still leave bread for {being} in {place}.", being),
        ]
    )
    return ["fictional"], text, [mention], [place]


def build_negation(rng: random.Random) -> Row:
    person, place = rng.choice(GIVEN), _place(rng)
    text = rng.choice(
        [
            f"{person} never reached {place}.",
            f"No one had seen {person} since the fire at {place}.",
            f"{person} was not among those who fled {place}.",
            f"Nobody expected {person} to return to {place}.",
        ]
    )
    return ["negation"], text, [person], [place]


def build_negation_multi(rng: random.Random) -> Row:
    one, two, place = rng.sample(GIVEN, 2) + [_place(rng)]
    text = f"Neither {one} nor {two} returned to {place}."
    return ["negation", "multi"], text, [one, two], [place]


def build_duplicate(rng: random.Random) -> Row:
    person, place = rng.choice(GIVEN), _place(rng)
    text = rng.choice(
        [
            f"{person} left {place}, and {person} did not look back at {place}.",
            f"{person} wrote from {place}; {person} wrote again from {place}.",
            f"{place}, always {place} — {person} could not leave {place}.",
        ]
    )
    return ["duplicate"], text, [person], [place]


def build_same_token(rng: random.Random) -> Row:
    """One surface form, both a person and a place, decided by context."""
    shared = rng.choice(["Kesh", "Lorne", "Calder", "Alba", "Ferrow"])
    text = f"{shared}, the youngest of the three, had never seen {shared}."
    return ["same-token"], text, [shared], [shared]


def build_same_token_titled(rng: random.Random) -> Row:
    shared = rng.choice(["Lorne", "Calder", "Ferrow", "Wray"])
    title = rng.choice(TITLES)
    text = f"{title} {shared} refused to leave Port {shared}."
    return ["same-token", "title"], text, [f"{title} {shared}"], [f"Port {shared}"]


def build_empty(rng: random.Random) -> Row:
    text = rng.choice(
        [
            "Nothing happened that day.",
            "The roads were empty and the sea was grey.",
            "Rain, then more rain.",
            "It was too cold to argue.",
            "The season turned without ceremony.",
            "No one wrote anything down.",
        ]
    )
    return ["empty"], text, [], []


def build_mixed(rng: random.Random) -> Row:
    """Two rules colliding in one sentence, which is where prompts break."""
    person, role, common, place = (
        _titled(rng),
        rng.choice(ROLES_LOWER),
        rng.choice(COMMON_PLACES),
        _place(rng),
    )
    text = f"{person} asked {role} for directions at {common} outside {place}."
    return ["title", "role-only", "common-noun-place", "mixed"], text, [person], [place]


def build_mixed_negation_org(rng: random.Random) -> Row:
    org, hidden = rng.choice(ORGS_WITH_PLACE)
    person = rng.choice(GIVEN)
    text = f"{person} never worked for {org}, whatever they say in {hidden}."
    return ["negation", "organisation", "same-token", "mixed"], text, [person], [hidden]


BUILDERS = [
    (build_title, 18),
    (build_title_multi, 12),
    (build_role_only, 16),
    (build_common_noun_place, 12),
    (build_common_noun_only, 10),
    (build_organisation, 8),
    (build_organisation_embedding_place, 10),
    (build_organisation_and_bare_place, 10),
    (build_demonym, 12),
    (build_demonym_with_place, 8),
    (build_fictional, 10),
    (build_negation, 14),
    (build_negation_multi, 6),
    (build_duplicate, 10),
    (build_same_token, 6),
    (build_same_token_titled, 6),
    (build_empty, 6),
    (build_mixed, 10),
    (build_mixed_negation_org, 6),
]


def generate(count: int, seed: int = 20260807) -> list[Row]:
    """Draw rows until `count` distinct sentences exist, honouring the weights."""
    rng = random.Random(seed)
    weighted = [builder for builder, weight in BUILDERS for _ in range(weight)]
    rows: list[Row] = []
    seen: set[str] = set()
    attempts = 0
    while len(rows) < count and attempts < count * 200:
        attempts += 1
        tags, text, people, places = rng.choice(weighted)(rng)
        if text in seen:
            continue
        seen.add(text)
        rows.append((tags, text, sorted(set(people)), sorted(set(places))))
    if len(rows) < count:
        raise SystemExit(f"template bank exhausted at {len(rows)} of {count} distinct sentences")
    return rows
