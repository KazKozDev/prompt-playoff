"""The business catalogue: fifty paid-for jobs, and the set that measures each.

A number on its own does not say what will break. "0.71 on summarization"
is a fact about a corpus; "0.71 on transcript-to-minutes, the job Ocado Retail
runs on this" is a fact about work. This module reads data/business_cases.yaml
and hands the API a shape the library screen can render without knowing how the
mapping was made.

What it adds to the file on disk is the one thing the file cannot know: which
of the named sets this server actually has. A catalogue that lists rows the
server cannot read is a brochure, so `available` is answered per set, and the
counts on each group are counted from sets that are really there.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from prompt_playoff.registry import default_data_root

MATCHES = ("direct", "partial", "none")


class CatalogError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _load(root: str | None = None) -> dict[str, Any]:
    path = (Path(root) if root else default_data_root()) / "business_cases.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"Cannot read the business catalogue at {path}: {exc}") from exc
    if not isinstance(payload, dict) or "groups" not in payload or "sets" not in payload:
        raise CatalogError(f"{path} is not a business catalogue: it needs `groups` and `sets`.")
    _check(payload, path)
    return payload


def _check(payload: dict[str, Any], path: Path) -> None:
    """Catch a mapping that points at nothing, at load time rather than in the UI.

    A case citing a set that no longer exists renders as a case with no
    evidence, which looks exactly like a case that never had any.
    """
    known = {item["name"] for item in payload["sets"]}
    referenced = {item["id"] for item in payload.get("references", [])}
    for group in payload["groups"]:
        # A category is a tile before it is a list, and a tile is a picture, a
        # line of large type and a line of small type. A group missing one of
        # those renders as a hole in the shelf, so it fails here instead.
        for field in ("name", "headline", "summary", "art"):
            if not str(group.get(field, "")).strip():
                raise CatalogError(f"{path}: group {group['id']} has no {field}")
        for case in group["cases"]:
            if case["match"] not in MATCHES:
                raise CatalogError(f"{path}: case {case['number']} has match {case['match']!r}")
            if not case.get("story"):
                raise CatalogError(f"{path}: case {case['number']} has no story")
            # A figure with nothing under it is a number floating on a card. The
            # two fields are one fact and travel together or not at all.
            if bool(case.get("claim")) != bool(case.get("claim_of")):
                raise CatalogError(f"{path}: case {case['number']} has half a claim")
            for name in case.get("sets", []):
                if name not in known:
                    raise CatalogError(f"{path}: case {case['number']} cites unknown set {name}")
            for ref in case.get("references", []):
                if ref not in referenced:
                    raise CatalogError(f"{path}: case {case['number']} cites unknown ref {ref}")


def catalog(available: dict[str, int], root: str | None = None) -> dict[str, Any]:
    """The catalogue, told what this server holds.

    `available` maps dataset name -> example count, as /v1/datasets reports it.
    """
    payload = _load(root)
    homes = _homes(payload)
    sets = [
        {
            **spec,
            "group": homes.get(spec["name"]),
            "available": spec["name"] in available,
            "examples": available.get(spec["name"]),
        }
        for spec in payload["sets"]
    ]
    by_name = {spec["name"]: spec for spec in sets}

    groups = []
    for group in payload["groups"]:
        cases = [
            {
                **case,
                "story": " ".join(case["story"].split()),
                "sets": list(case.get("sets", [])),
                "references": list(case.get("references", [])),
                # A case is measurable when at least one of its sets is here —
                # the mapping's verdict does not survive a missing file.
                "measurable": any(by_name[name]["available"] for name in case.get("sets", [])),
            }
            for case in group["cases"]
        ]
        groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "headline": " ".join(group["headline"].split()),
                "summary": " ".join(group["summary"].split()),
                "art": group["art"],
                "cases": cases,
                "counts": {
                    "cases": len(cases),
                    "measurable": sum(1 for case in cases if case["measurable"]),
                    **{
                        match: sum(1 for case in cases if case["match"] == match)
                        for match in MATCHES
                    },
                },
                "sets": sorted({name for case in cases for name in case["sets"]}),
            }
        )

    return {
        "version": payload.get("version", 1),
        "groups": groups,
        "sets": sets,
        "references": payload.get("references", []),
        "counts": {
            "cases": sum(group["counts"]["cases"] for group in groups),
            "measurable": sum(group["counts"]["measurable"] for group in groups),
            "sets": len(sets),
            "available": sum(1 for spec in sets if spec["available"]),
        },
    }


def _homes(payload: dict[str, Any]) -> dict[str, str]:
    """The one group each set belongs under, when several cite it.

    A support corpus is cited by a meetings case too — summarizing a customer's
    history is the same rows read for a different reason. Listing the set under
    whichever group happens to come first would file it under the borrower, so
    the group that leans on it hardest keeps it, and the file's own order breaks
    a tie.
    """
    tally: dict[str, dict[str, int]] = {}
    order = {group["name"]: index for index, group in enumerate(payload["groups"])}
    for group in payload["groups"]:
        for case in group["cases"]:
            for name in case.get("sets", []):
                tally.setdefault(name, {})[group["name"]] = (
                    tally.setdefault(name, {}).get(group["name"], 0) + 1
                )
    return {
        name: max(groups, key=lambda title: (groups[title], -order[title]))
        for name, groups in tally.items()
    }


def group_of(name: str, root: str | None = None) -> str | None:
    """Which business group a set belongs to, for a screen showing one set."""
    return _homes(_load(root)).get(name)
