#!/usr/bin/env python3
"""
Deterministic lint for the Italian (`it`) locale.

`swift run Site i18n-check` gates what is checkable for every locale at once:
missing siblings, leftover ⟦TODO⟧ markers, em dashes, per-locale quote styles.
This script covers the tells that are specific to Italian and that a reader
notices before they have read a full sentence:

  errors
    - English plurals on invariable loanwords (`i tags`, `le apps`) - the single
      most common machine-translation artefact in Italian tech prose
    - orthography: `perchè` (must be `perché`), `qual'è`, `pò`, `E'` for `È`
    - em / en dashes, which the house style bans in every locale

  warnings (advisory - style drift, not a hard gate)
    - possessive density: English repeats "your", Italian drops it when the
      owner is obvious. A high `il tuo / la tua` rate reads as translated.
    - "puoi" density: English leans on "you can"; Italian prefers the bare
      imperative.

Prose only. Frontmatter, fenced and inline code, HTML tags and attributes, and
URLs are stripped before matching, so `apps.apple.com`, `<div class="page-cards">`
and `tags: [nfc-tags]` never trip the loanword rule.

Usage:
    python3 Scripts/lint-italian.py               # every *.it.md / *.it.yaml
    python3 Scripts/lint-italian.py <path>...     # only these files
    python3 Scripts/lint-italian.py --quiet       # errors only, no warnings

Exit code is non-zero when any error is found; warnings never fail the run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Loanwords Italian takes as invariable: the plural is carried by the article
# ("i tag", "le app"), never by an English -s.
INVARIABLE_LOANWORDS = [
    "tags", "apps", "links", "backups", "widgets", "webhooks",
    "smartphones", "tablets", "screenshots", "podcasts",
]

# Proper nouns that legitimately carry an English plural: UI labels and
# third-party product names. A rule hit inside one of these is suppressed.
# Keep this list short and specific - it is an escape hatch, not a policy.
ALLOWED_PHRASES = [
    "NFC Apps",         # NFC.cool's own in-app section label
    "modulo Webhooks",  # Make's module, named that in its UI
    "servizio Webhooks",  # IFTTT's service, likewise
]

# (name, pattern, explanation, regex flags)
ERROR_RULES: list[tuple[str, str, str, int]] = [
    (
        "loanword-plural",
        r"\b(" + "|".join(INVARIABLE_LOANWORDS) + r")\b",
        "English plural on an invariable loanword - Italian uses the singular form "
        "(i tag, le app, i link, i backup, i webhook)",
        re.I,
    ),
    (
        # Also catches the unaccented `perche`, so there is no separate rule for it.
        "accent-perche",
        r"\b(?:per|poi|ben|affin|sic|anzi)ch[èe]\b",
        "must end in -ché with an acute accent (perché, poiché, benché, affinché)",
        re.I,
    ),
    ("accent-quale", r"\bqual'\s*[eèé]\b", "`qual è` never takes an apostrophe", re.I),
    (
        "accent-po",
        r"\bpò\b|\bpo\b(?!')",
        "the truncation of `poco` is `po'`, not `pò`",
        re.I,
    ),
    # Case-sensitive on purpose: `E'` opening a sentence is the real defect, and
    # lowercasing the rule would fire on unrelated apostrophes.
    ("accent-e-maiuscola", r"(?:^|(?<=[\s\"(]))E'(?=\s)", "use the character `È`, not `E'`", 0),
    ("dash", r"[—–]", "em/en dash - house style is a plain hyphen ` - `", 0),
]

WARNING_RULES: list[tuple[str, str, float, str]] = [
    (
        "possessive-density",
        r"\b(?:il tuo|lo tuo|la tua|i tuoi|le tue|del tuo|della tua|dei tuoi|delle tue)\b",
        1.2,
        "possessive overuse - English repeats \"your\"; Italian drops it when the owner "
        "is obvious (`avvicina l'iPhone`, not `avvicina il tuo iPhone`)",
    ),
    (
        "puoi-density",
        r"\bpuoi\b",
        1.0,
        "\"you can\" fatigue - prefer the bare imperative or an impersonal `si può`",
    ),
]

FENCED = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HTML_TAG = re.compile(r"<[^>\n]+>")
URL = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|org|net|io|cool|dev|pt|de)\b\S*")
# Markdown link targets: `](/affiliate-links/)` is a route, not prose.
MD_LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
# Any site-relative route or asset path, wherever it appears.
PATH_LIKE = re.compile(r"/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]*)+")
# YAML values that are identifiers or paths rather than prose.
YAML_ID_VALUE = re.compile(
    r"^\s*-?\s*(?:slug|id|url|image|ogImage|[A-Za-z]*[Pp]ath|[A-Za-z]*URL)\s*:.*$", re.M
)
YAML_COMMENT = re.compile(r"^\s*#.*$", re.M)


def blank(match: re.Match) -> str:
    """Replace a span with same-length whitespace so offsets stay put."""
    return re.sub(r"\S", " ", match.group(0))


def strip_frontmatter(text: str, path: Path) -> str:
    """Blank out YAML frontmatter (markdown) or structural keys (yaml), keeping
    line numbers stable so reported positions still point at the real line."""
    if path.suffix == ".yaml":
        return YAML_ID_VALUE.sub(blank, YAML_COMMENT.sub(blank, text))
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    head = text[: end + 5]
    return "\n" * head.count("\n") + text[end + 5 :]


def prose_of(path: Path) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8")
    body = strip_frontmatter(text, path)
    for pattern in (FENCED, INLINE_CODE, HTML_TAG, URL, MD_LINK_TARGET, PATH_LIKE):
        body = pattern.sub(blank, body)
    return body, len(body.split())


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check(path: Path, quiet: bool) -> tuple[list[str], list[str]]:
    prose, words = prose_of(path)
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    errors, warnings = [], []

    allowed = [
        (m.start(), m.end())
        for phrase in ALLOWED_PHRASES
        for m in re.finditer(re.escape(phrase), prose)
    ]

    for name, pattern, explanation, flags in ERROR_RULES:
        for m in re.finditer(pattern, prose, flags):
            if any(start <= m.start() and m.end() <= end for start, end in allowed):
                continue
            errors.append(
                f"  [ERROR] {rel}:{line_of(prose, m.start())} [{name}] "
                f"\"{m.group(0).strip()}\" - {explanation}"
            )

    if not quiet and words >= 150:
        for name, pattern, per_hundred, explanation in WARNING_RULES:
            hits = len(re.findall(pattern, prose, re.I))
            rate = hits * 100 / words
            if rate > per_hundred:
                warnings.append(
                    f"  [WARN ] {rel} [{name}] {hits} hits in {words} words "
                    f"({rate:.1f} per 100, threshold {per_hundred}) - {explanation}"
                )
    return errors, warnings


def targets(argv: list[str]) -> list[Path]:
    paths = [Path(a) for a in argv if not a.startswith("-")]
    if paths:
        return [p if p.is_absolute() else ROOT / p for p in paths]
    found = sorted(ROOT.glob("Content/**/*.it.md")) + sorted(ROOT.glob("Content/**/*.it.yaml"))
    return found


def main() -> int:
    quiet = "--quiet" in sys.argv
    files = targets(sys.argv[1:])
    if not files:
        print("lint-italian: no .it files found")
        return 0

    all_errors, all_warnings = [], []
    for path in files:
        if not path.exists():
            print(f"  [ERROR] {path}: no such file")
            all_errors.append(str(path))
            continue
        errors, warnings = check(path, quiet)
        all_errors += errors
        all_warnings += warnings

    for line in all_errors:
        print(line)
    for line in all_warnings:
        print(line)

    print(
        f"\nlint-italian: {len(files)} file(s), "
        f"{len(all_errors)} error(s), {len(all_warnings)} warning(s)"
    )
    if all_errors:
        return 1
    print("✓ Italian lint clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
