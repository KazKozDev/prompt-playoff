#!/usr/bin/env python3
"""Fail-closed publication checks for documentation, evidence, data, and wheels."""

from __future__ import annotations

import argparse
import concurrent.futures
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "src/prompt_playoff/data/business_cases.yaml"
BUSINESS = ROOT / "src/prompt_playoff/data/datasets/business"
NOTICE = ROOT / "THIRD_PARTY_NOTICES.md"
EVIDENCE = {"verified_official", "qualified_official", "unverified"}
MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
HTML_LINK = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']")


class Audit:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part.startswith(".") or part in {"node_modules", "dist"} for part in path.parts)
    )


def heading_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip().lower()
        anchor = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE)
        anchor = re.sub(r"[\s-]+", "-", anchor).strip("-")
        anchors.add(anchor)
    return anchors


def split_target(raw: str) -> tuple[str, str | None]:
    target = raw.strip().strip("<>").split(maxsplit=1)[0]
    path, marker, anchor = target.partition("#")
    return path, anchor if marker else None


def audit_local_links(audit: Audit) -> set[str]:
    external: set[str] = set()
    for document in markdown_files():
        text = document.read_text(encoding="utf-8")
        targets = MARKDOWN_LINK.findall(text) + HTML_LINK.findall(text)
        for raw in targets:
            path_text, anchor = split_target(raw)
            if path_text.startswith(("http://", "https://")):
                external.add(path_text)
                continue
            if path_text.startswith(("mailto:", "data:")):
                continue
            target = document if not path_text else (document.parent / path_text).resolve()
            audit.require(
                target.exists(), f"{document.relative_to(ROOT)}: missing link target {raw}"
            )
            if target.exists() and anchor and target.suffix.lower() == ".md":
                audit.require(
                    anchor in heading_anchors(target),
                    f"{document.relative_to(ROOT)}: missing anchor #{anchor} in "
                    f"{target.relative_to(ROOT)}",
                )
    return external


def audit_catalogue(audit: Audit) -> tuple[dict, set[str]]:
    payload = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    urls: set[str] = set()
    sources = {source["id"]: source for source in payload.get("case_sources", [])}
    audit.require(bool(sources), "business catalogue has no case_sources")
    for source in sources.values():
        for field in ("title", "publisher", "url", "source_type", "accessed_at"):
            audit.require(bool(source.get(field)), f"case source {source['id']} has no {field}")
        audit.require("published_at" in source, f"case source {source['id']} omits published_at")
        if source.get("url"):
            urls.add(source["url"])

    cases = [case for group in payload.get("groups", []) for case in group.get("cases", [])]
    audit.require(
        [case.get("number") for case in cases] == list(range(1, 51)), "case numbers are not 1..50"
    )
    for case in cases:
        number = case.get("number")
        audit.require(case.get("source_ref") in sources, f"case {number} has no resolvable source")
        audit.require(
            case.get("evidence_status") in EVIDENCE, f"case {number} has invalid evidence status"
        )
        audit.require(
            bool(str(case.get("evidence_note", "")).strip()), f"case {number} has no evidence note"
        )

    notice = NOTICE.read_text(encoding="utf-8") if NOTICE.exists() else ""
    audit.require(bool(notice), "THIRD_PARTY_NOTICES.md is missing")
    for spec in payload.get("sets", []):
        name = spec.get("name", "unknown")
        for field in (
            "source",
            "url",
            "license",
            "license_status",
            "license_url",
            "redistribution",
            "source_revision",
        ):
            audit.require(bool(spec.get(field)), f"dataset {name} has no {field}")
        revision = str(spec.get("source_revision", ""))
        audit.require(
            bool(re.fullmatch(r"[0-9a-f]{40}", revision)),
            f"dataset {name} has an unpinned revision",
        )
        path = BUSINESS / f"{name.split(':', 1)[-1]}.jsonl"
        bundled = spec.get("bundled") is True
        audit.require(path.exists() is bundled, f"dataset {name}: bundled flag and file disagree")
        if bundled:
            audit.require(
                spec.get("license_status") == "verified_upstream",
                f"dataset {name} bundles an unresolved license",
            )
        else:
            audit.require(
                spec.get("redistribution") == "source_only",
                f"dataset {name} needs source_only status",
            )
        audit.require(
            spec.get("source", "") in notice, f"dataset {name} is absent from THIRD_PARTY_NOTICES"
        )
        audit.require(
            revision in notice, f"dataset {name} revision is absent from THIRD_PARTY_NOTICES"
        )
        urls.update(filter(None, (spec.get("url"), spec.get("license_url"))))
    for reference in payload.get("references", []):
        if reference.get("url"):
            urls.add(reference["url"])
    return payload, urls


def check_url(url: str) -> tuple[str, str, int | None]:
    headers = {"User-Agent": "prompt-playoff-publication-audit/1.0"}
    automated_access_blocked = {401, 403, 406, 429, 999}
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return url, "ok", response.status
        except urllib.error.HTTPError as exc:
            if exc.code in automated_access_blocked | {405} and method == "HEAD":
                continue
            if exc.code in automated_access_blocked:
                return url, "blocked", exc.code
            return url, "failed", exc.code
        except (urllib.error.URLError, TimeoutError, OSError):
            if method == "GET":
                return url, "failed", None
    return url, "failed", None


def audit_urls(audit: Audit, urls: Iterable[str]) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(check_url, sorted(set(urls))))
    for url, state, status in results:
        if state == "failed":
            audit.errors.append(f"external link unavailable ({status or 'network error'}): {url}")
        elif state == "blocked":
            audit.warn(f"external link blocks automated access ({status}): {url}")


def audit_wheel(audit: Audit, wheel: Path, payload: dict) -> None:
    audit.require(wheel.exists(), f"wheel does not exist: {wheel}")
    if not wheel.exists():
        return
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        audit.require(
            any(name.endswith("/licenses/LICENSE") for name in names), "wheel omits LICENSE"
        )
        audit.require(
            any(name.endswith("/licenses/THIRD_PARTY_NOTICES.md") for name in names),
            "wheel omits THIRD_PARTY_NOTICES.md",
        )
        for spec in payload["sets"]:
            suffix = f"data/datasets/business/{spec['name'].split(':', 1)[-1]}.jsonl"
            present = any(name.endswith(suffix) for name in names)
            audit.require(
                present is spec["bundled"], f"wheel distribution disagrees for {spec['name']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-links", action="store_true", help="make live requests to external links"
    )
    parser.add_argument("--artifact", type=Path, help="also inspect a built wheel")
    args = parser.parse_args()

    audit = Audit()
    external = audit_local_links(audit)
    payload, catalogue_urls = audit_catalogue(audit)
    if args.check_links:
        audit_urls(audit, external | catalogue_urls)
    if args.artifact:
        audit_wheel(audit, args.artifact, payload)

    for warning in audit.warnings:
        print(f"WARN {warning}")
    for error in audit.errors:
        print(f"FAIL {error}", file=sys.stderr)
    if audit.errors:
        print(
            f"Publication audit failed: {len(audit.errors)} error(s), "
            f"{len(audit.warnings)} warning(s).",
            file=sys.stderr,
        )
        return 1
    print(f"Publication audit passed: {len(audit.warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
