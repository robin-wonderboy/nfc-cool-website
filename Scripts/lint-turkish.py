#!/usr/bin/env python3
"""
Deterministic lint for the Turkish (`tr`) locale.

`swift run Site i18n-check` gates what is checkable for every locale at once:
missing siblings, leftover ⟦TODO⟧ markers, em dashes, per-locale quote styles.
This script covers the tells that are specific to Turkish and that a reader
notices before they have finished a sentence:

  errors
    - a missing apostrophe before a suffix on a proper noun or an abbreviation
      (`iPhone'un`, `Android'de`, `NFC'yi`, `App Store'dan`). Turkish common
      nouns never take one; brand names and initialisms always do, and getting
      it wrong is the loudest orthographic tell in the language.
    - `tag` inflected without an apostrophe, or with BACK vowel harmony. The
      loanword is read /teg/, so it takes front vowels: `tag'e`, `tag'i`,
      `tag'ler`, `tag'de` - never `taga`, `tagı`, `taglar`.
    - English plurals on loanwords Turkish inflects itself (`tags`, `apps`,
      `webhooks`) - the classic machine-translation artefact.
    - the fixed orthography traps every Turkish reader spots: `herşey`,
      `hiç bir`, `bir çok`, `yada`, `herkez`, `farketmez`, `şuan`, `-da ki`.
    - ASCII-folded Turkish (`icin`, `degil`, `ozellik`), which happens whenever
      text passes through a tool that drops ı/ş/ğ/ü/ö/ç.
    - em / en dashes, which the house style bans in every locale.

  warnings (advisory - style drift, not a hard gate)
    - `-ebilirsin` density: English leans on "you can"; Turkish prefers the
      bare imperative.
    - explicit `sen / senin`: the person is already carried by the suffix, so
      writing the pronoun out is emphatic and should be rare.

Prose only. Frontmatter, fenced and inline code, HTML tags and attributes, and
URLs are stripped before matching, so `apps.apple.com`, `<div class="page-card">`
and `tags: [nfc-tags]` never trip a rule.

The register, glossary and calque traps this cannot check are in
`Scripts/turkish-style-guide.md`.

Usage:
    python3 Scripts/lint-turkish.py               # every *.tr.md / *.tr.yaml
    python3 Scripts/lint-turkish.py <path>...     # only these files
    python3 Scripts/lint-turkish.py --quiet       # errors only, no warnings
    python3 Scripts/lint-turkish.py --selftest    # check the rules themselves

Exit code is non-zero when any error is found; warnings never fail the run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Turkish case/plural suffixes, as they appear directly after a proper noun.
# Anchored with \b on both sides at the use site, so `Mac` + `eralar` (inside
# "Maceralar") cannot match - only a complete suffix does.
# Alternation order does not matter: the trailing \b at the use site forces the
# engine to backtrack until an alternative ends exactly at a word boundary.
SUFFIX = (
    r"(?:"
    # plural, with the case endings that can follow it
    r"l[ae]r[ıiuü]m[ıiuü]z|l[ae]r[ıiuü]n[ıiuü]z|l[ae]r[ıiuü]n[ıiuü]n|"
    r"l[ae]r[ıiuü]nd[ae]n|l[ae]r[ıiuü]nd[ae]|l[ae]r[ıiuü]n[ıiuü]|l[ae]r[ıiuü]n[ae]|"
    r"l[ae]rd[ae]n|l[ae]rd[ae]|l[ae]r[ıiuü]n|l[ae]r[ıiuü]|l[ae]r[ae]|l[ae]r|"
    # 2nd-person possessive followed by a case ending (iPhone'unu, iPad'inde)
    r"[ıiuü]n[ıiuü]zd[ae]n|[ıiuü]n[ıiuü]zd[ae]|[ıiuü]n[ıiuü]z|[ıiuü]m[ıiuü]z|"
    r"[ıiuü]nd[ae]n|[ıiuü]nd[ae]|[ıiuü]n[ıiuü]n|[ıiuü]n[ıiuü]|[ıiuü]n[ae]|"
    r"[ıiuü]md[ae]n|[ıiuü]md[ae]|[ıiuü]m[ıiuü]|[ıiuü]m[ae]|[ıiuü]m|"
    # bare case endings
    r"n[ıiuü]n|[ıiuü]n|[ıiuü]z|d[ae]ki|t[ae]ki|d[ae]n|t[ae]n|d[ae]|t[ae]|"
    r"[ıiuü]yl[ae]|y[ae]|y[ıiuü]|n[ae]|n[ıiuü]|"
    r"[ıiuü]|[ae]|l[ae]|s[ıiuü]|d[ıi]r|t[ıi]r"
    r")"
)

# Proper nouns and initialisms that MUST take an apostrophe before a suffix.
# Multi-word entries are matched literally, so `App Store'dan` is covered.
# (`NFC.cool` is deliberately absent: the URL stripper blanks it first.)
PROPER_NOUNS = [
    "iPhone", "iPad", "iPod", "Mac", "macOS", "iOS", "iPadOS", "watchOS",
    "Android", "Amiibo", "Wi-Fi", "Bluetooth", "AirDrop", "NameDrop",
    "App Store", "Play Store", "Google Play", "Google", "Apple", "Nintendo",
    "App Clip", "Apple Wallet", "Apple Pay", "Safari", "Chrome", "Shortcuts",
    "NFC", "NDEF", "RFID", "UID", "URL", "PDF", "CSV", "OCR", "AES", "API",
    "JSON", "HTTP", "HTTPS", "QR", "GPS", "SDK", "iCloud", "Platinum",
    r"NTAG\s?\d{0,3}", "MIFARE", "ICODE SLIX", "OpenPrintTag",
]

# Loanwords Turkish inflects with its own suffixes - the English -s is always
# wrong (`webhook'lar`, `widget'lar`, `uygulamalar`).
ENGLISH_PLURALS = [
    "tags", "apps", "links", "backups", "widgets", "webhooks",
    "smartphones", "tablets", "screenshots", "scanners", "readers",
]

# Proper nouns that legitimately carry an English plural: UI labels and
# third-party product names. A rule hit inside one of these is suppressed.
# Keep this list short and specific - it is an escape hatch, not a policy.
ALLOWED_PHRASES = [
    "NFC Apps",              # NFC.cool's own in-app section label
    "Webhooks modülü",       # Make's module, named that in its UI
    "Webhooks servisi",      # IFTTT's service, likewise
    "Webhooks by Zapier",
]

# ASCII-folded Turkish. Split into whole words (short, would over-match as a
# prefix) and stems (long enough that a prefix match is unambiguous).
FOLDED_WORDS = [
    "icin", "degil", "cok", "tum", "tumu", "sey", "seyler", "acik", "nasil",
    "hizli", "dogru", "buyuk", "kucuk", "kisi", "kisiler", "sayac", "kagit",
    "gec", "ogren", "ornek", "onemli", "birsey", "hicbir",
]
FOLDED_STEMS = [
    "ucretsiz", "ozellik", "baglanti", "sifrele", "calis", "guncelle",
    "gorun", "dusun", "secenek", "yukle", "yaklastir", "tarayici",
    "yazilim", "guvenli", "acikla", "degistir", "gonder",
]

# (name, pattern, explanation, regex flags)
ERROR_RULES: list[tuple[str, str, str, int]] = [
    (
        "missing-apostrophe",
        r"\b(?:" + "|".join(PROPER_NOUNS) + r")" + SUFFIX + r"\b",
        "a suffix on a proper noun or an initialism needs an apostrophe "
        "(iPhone'un, Android'de, NFC'yi, App Store'dan)",
        0,
    ),
    (
        "tag-missing-apostrophe",
        r"\b[Tt]ag" + SUFFIX + r"\b",
        "`tag` is a loanword: suffixes attach with an apostrophe "
        "(tag'e, tag'i, tag'ler, tag'de)",
        0,
    ),
    (
        "tag-vowel-harmony",
        r"\b[Tt]ag'(?:l?[aıu]\w*|[ıu]\w*)",
        "`tag` is read /teg/, so it takes FRONT vowels: tag'e, tag'i, tag'in, "
        "tag'de, tag'den, tag'ler - never tag'a, tag'ı, tag'lar",
        0,  # NOT re.I: Python folds `ı` onto `i`, which would flag correct forms
    ),
    (
        "english-plural",
        r"\b(?:" + "|".join(ENGLISH_PLURALS) + r")\b",
        "English plural on a loanword - Turkish supplies its own "
        "(webhook'lar, widget'lar, uygulamalar, bağlantılar)",
        0,
    ),
    (
        "orthography-bitisik",
        r"\bhiç bir\b|\bbir çok\b(?!\s*yönlü)|\bbir kaç\b|\bher hangi\b|\bbir birin",
        "written as one word in Turkish: hiçbir, birçok, birkaç, herhangi, birbirine",
        re.I,
    ),
    (
        "orthography-ayri",
        r"\bherşey|\bbirşey|\bhoşgeldin|\bşuan\b|\bfarket|\bhiçbirşey",
        "written as two words in Turkish: her şey, bir şey, hoş geldin, "
        "şu an, fark etmez",
        re.I,
    ),
    (
        "orthography-yanlis",
        r"\byada\b|\bherkez\b|\byanlız\b|\byalnış\b|\bdahi̇\b",
        "misspelling: ya da, herkes, yalnız, yanlış",
        re.I,
    ),
    (
        # `-ki` after a locative suffix is joined: `cebindeki tag`, not
        # `cebinde ki tag`. The conjunction `ki` never follows a locative.
        "orthography-daki",
        r"(?<=[a-zçğıöşü])(?:d[ae]|t[ae])\s+ki\b",
        "the suffix `-ki` joins the locative: `cebindeki`, not `cebinde ki`",
        re.I,
    ),
    (
        "ascii-folded",
        r"\b(?:" + "|".join(FOLDED_WORDS) + r")\b"
        r"|\b(?:" + "|".join(FOLDED_STEMS) + r")[a-z]*\b",
        "ASCII-folded Turkish - use the real characters (ı İ ş ğ ü ö ç)",
        0,  # NOT re.I: it would fold pattern `i` onto text `ı` and flag `nasıl`
    ),
    ("dash", r"[—–]", "em/en dash - house style is a plain hyphen ` - `", 0),
]

# Deliberately NOT linted: `bir` density. `bir` overuse IS the loudest tell in
# translated Turkish (see Scripts/turkish-style-guide.md §3.1), but it cannot be
# measured mechanically: Turkish REQUIRES `bir` before an indefinite noun that
# carries a relative clause ("fabrika anahtarlarında olan bir tag"), and that
# construction dominates explanatory prose. Measured over this locale's 53
# hand-written files, correct prose runs 0.5-5.3 per 100 words, and narrowing to
# two `bir` inside one clause still matched mostly valid coordination
# ("bir X ya da bir Y"). Any threshold either fires on correct Turkish or never
# fires at all, so the rule lives in the style guide, where judgment applies.
WARNING_RULES: list[tuple[str, str, float, str]] = [
    (
        "ebilirsin-density",
        r"\w+[ae]bilirsin(?:iz)?\b",
        1.2,
        "\"you can\" fatigue - prefer the bare imperative (`yaz`, not `yazabilirsin`)",
    ),
    (
        "pronoun-density",
        r"\b(?:sen|senin)\b",
        0.6,
        "the person is already carried by the suffix - writing `sen / senin` out "
        "is emphatic and should be rare",
    ),
]

# Python's case folding maps dotless `ı` and dotted `i` onto each other, so
# `re.I` on any rule that distinguishes them produces false positives on
# CORRECT Turkish. These cases pin that down - two rules were written with
# `re.I` and flagged `tag'i` and `nasıl` before this existed.
SELFTEST: list[tuple[str, str | None]] = [
    # (prose fragment, expected rule name or None when it must stay clean)
    ("iPhone'unu tag'e yaklaştır", None),
    ("iPhone'unda ve iPad'lerinde", None),
    ("Amiibo'yu yedekle, NTAG 216'ya yaz", None),
    ("nasıl hızlı açılır, kısa yanıt", None),
    ("tag'i oku, tag'in içeriğini gör, tag'ler hazır", None),
    ("Android'de ve iOS'ta çalışır", None),
    ("Maceralar ve Macaristan", None),
    ("MIFARE DESFire ve NTAG I²C türevleri", None),
    ("Apple Silicon Mac'lerde çalışır", None),
    ("bir çok yönlü araç", None),
    ("her şey cihazda kalır", None),
    ("iPhoneunu al", "missing-apostrophe"),
    ("iPadinde saklı", "missing-apostrophe"),
    ("Amiiboyu yedekle", "missing-apostrophe"),
    ("Androidde çalışır", "missing-apostrophe"),
    ("NFCyi aç", "missing-apostrophe"),
    ("App Storeda bulunur", "missing-apostrophe"),
    ("taglar hazır", "tag-missing-apostrophe"),
    ("tag'lar hazır", "tag-vowel-harmony"),
    ("tag'a yaklaştır", "tag-vowel-harmony"),
    ("webhooks kurulumu", "english-plural"),
    ("bir çok kişi", "orthography-bitisik"),
    ("herşey hazır", "orthography-ayri"),
    ("yada başka bir yol", "orthography-yanlis"),
    ("cebinde ki tag", "orthography-daki"),
    ("bunu senin icin yaptım", "ascii-folded"),
    ("ozellikleri ac", "ascii-folded"),
]


def selftest() -> int:
    failures = 0
    for prose, expected in SELFTEST:
        hits = {
            name
            for name, pattern, _, flags in ERROR_RULES
            if re.search(pattern, prose, flags)
        }
        if expected is None and hits:
            print(f"  [SELFTEST] false positive on correct Turkish: "
                  f"{prose!r} -> {sorted(hits)}")
            failures += 1
        elif expected is not None and expected not in hits:
            print(f"  [SELFTEST] missed {expected} on {prose!r} -> {sorted(hits) or 'nothing'}")
            failures += 1
    print(f"lint-turkish selftest: {len(SELFTEST)} case(s), {failures} failure(s)")
    return 1 if failures else 0


FENCED = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
HTML_TAG = re.compile(r"<[^>\n]+>")
URL = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|org|net|io|cool|dev|pt|de|tr)\b\S*")
# Markdown link targets: `](/affiliate-links/)` is a route, not prose.
MD_LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
# Any site-relative route or asset path, wherever it appears.
PATH_LIKE = re.compile(r"/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]*)+")
# YAML values that are identifiers or paths rather than prose.
YAML_ID_VALUE = re.compile(
    r"^\s*-?\s*(?:slug|id|url|image|ogImage|tags|author|[A-Za-z]*[Pp]ath|[A-Za-z]*URL)\s*:.*$",
    re.M,
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
    return sorted(ROOT.glob("Content/**/*.tr.md")) + sorted(ROOT.glob("Content/**/*.tr.yaml"))


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    quiet = "--quiet" in sys.argv
    files = targets(sys.argv[1:])
    if not files:
        print("lint-turkish: no .tr files found")
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
        f"\nlint-turkish: {len(files)} file(s), "
        f"{len(all_errors)} error(s), {len(all_warnings)} warning(s)"
    )
    if all_errors:
        return 1
    print("✓ Turkish lint clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
