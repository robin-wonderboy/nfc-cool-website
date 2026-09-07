#!/usr/bin/env python3
"""
Deterministic lint for the Russian (`ru`) locale.

`swift run Site i18n-check` gates what is checkable for every locale at once:
missing siblings, leftover ⟦TODO⟧ markers, em dashes, per-locale quote styles.
This script covers the tells that are specific to Russian and that a reader
notices before they have finished a sentence:

  errors
    - a `вы` form of any kind. This locale is `ты`-only (see the style guide),
      so `вы / вас / вам / ваш` and the вы-imperatives (`поднесите`, `нажмите`)
      are register leaks, not style drift.
    - mixed Cyrillic and Latin inside one word. `с o e a p x y k B M H T` exist
      in both alphabets, so `сканер` with a Latin `c` looks perfect and breaks
      search, spellcheck and screen readers. Invisible to proofreading; trivial
      for a regex.
    - em / en dashes, banned house-wide - AND ` - ` standing in for one, which
      is the substitution a translator reaches for next and reads worse than
      either. Russian restructures instead; see the style guide §4.
    - `-тся` where the infinitive `-ться` belongs, after a modal. The classic
      Russian literacy tell.
    - a fixed list of words that must carry `ё` (`ещё`, `её`, `счётчик`,
      `надёжный`, `объём`, `нашёл`). The list is deliberately narrow: `все` and
      `всё` are BOTH correct spellings of different words, so they are not here.
    - glossary violations: `NFC-тег` (it is `NFC-метка`; `тег` is reserved for
      the blog's own tag chips), `тэг`, `бэкап`, `гайд`, `фича`, `аппликация`,
      and `тапнуть` for an NFC tap.
    - `является`, the bureaucratic copula Russian marketing prose never needs.
    - English curly quotes and English thousands separators (`73,500`).
    - ASCII `"` in a YAML value or in markdown frontmatter. i18n-check's quote
      rule covers markdown BODY prose only, so this closes that gap - the
      structural quotes YAML puts around a scalar are stripped first.

  warnings (advisory - style drift, not a hard gate)
    - `можешь` density: English leans on "you can"; Russian prefers the bare
      imperative.
    - explicit `ты / твой`: the person is already carried by the verb ending,
      so writing the pronoun out is emphatic and should be rare.
    - officialese density (`осуществлять`, `данный`, `посредством`, `в целях`).

Prose only. Identifier frontmatter, fenced and inline code, HTML tags and
attributes, and URLs are stripped before matching - but prose-bearing
frontmatter (`title`, `summary`, `imageAlt`, `metaDescription`, …) is KEPT,
because that is what a card and a search result actually show.

The register, glossary and calque traps this cannot check are in
`Scripts/russian-style-guide.md`.

Usage:
    python3 Scripts/lint-russian.py               # every *.ru.md / *.ru.yaml
    python3 Scripts/lint-russian.py <path>...     # only these files
    python3 Scripts/lint-russian.py --quiet       # errors only, no warnings
    python3 Scripts/lint-russian.py --selftest    # check the rules themselves

Exit code is non-zero when any error is found; warnings never fail the run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# вы-forms. Every one of these is a register leak in a ты-only locale.
VY_PRONOUNS = r"вы|вас|вам|вами|ваш(?:а|е|и|его|ей|ем|ему|им|ими|их|у|ую)?"

# вы-imperatives and 2pl indicatives that would leak in from a вы draft.
# Listed explicitly rather than matched by ending: Russian nouns in the
# prepositional case end in -те too (`на сайте`, `в документе`, `в комплекте`),
# so an ending-based rule would flag ordinary correct nouns.
VY_VERBS = [
    "поднесите", "нажмите", "откройте", "закройте", "выберите", "запишите",
    "считайте", "прочитайте", "скачайте", "установите", "попробуйте",
    "посмотрите", "проверьте", "убедитесь", "отправьте", "введите",
    "добавьте", "создайте", "сохраните", "включите", "выключите",
    "коснитесь", "держите", "используйте", "начните", "перейдите",
    "можете", "хотите", "знаете", "получите", "увидите", "сможете",
    "найдёте", "найдете", "сделайте", "напишите", "укажите", "настройте",
]

# Modals that force an infinitive, so a following `-тся` must be `-ться`.
# Adverbs (`легко`, `просто`) are deliberately absent: `легко читается` is
# correct third-person Russian and an adverb-based rule would flag it.
MODALS = [
    "можно", "может", "можешь", "могу", "могут", "нужно", "надо", "пора",
    "должен", "должна", "должно", "должны", "хочешь", "хочет", "хотят",
    "будет", "будут", "стоит", "готов", "готова", "начать", "перестать",
]

# Words that must carry `ё`. Narrow by design - every entry here has exactly
# one correct spelling. `все`/`всё` and `легко` (the adverb IS `легко`; only
# the adjective is `лёгкий`) are excluded because both forms are real words.
# The `-ен` entries are spelled out narrowly, and the shape is load-bearing:
# only TWO forms of these participles carry ё, and both are matched here.
#   `включён`      - masculine short form           -> stem + word boundary
#   `включённый`   - full form, note the double н   -> stem + н + ending
# Everything else on the same stem is correctly spelled with е and must NOT be
# flagged: the verbal noun (`включение`, `подключение`, `определение`) and the
# other short forms, which are stressed on the ending (`включена`, `включено`,
# `включены`, `защищена`). Both `включена` and `подключение` reached this list
# as false positives before it was written this way.
YO_WORDS = [
    r"еще", r"ее", r"счетчик\w*", r"объем\w*", r"надежн\w*", r"четк\w*",
    r"нашел", r"пришел", r"ушел", r"пошел", r"прочел", r"счел",
    r"сохранен(?:н\w*)?\b", r"включен(?:н\w*)?\b", r"подключен(?:н\w*)?\b",
    r"защищен(?:н\w*)?\b", r"определен(?:н\w*)?\b", r"разрешен(?:н\w*)?\b",
    r"нанесен(?:н\w*)?\b", r"перенесен(?:н\w*)?\b",
    r"съемк\w*", r"съемн\w*", r"звездочк\w*", r"трех\w*", r"четырех\w*",
    r"темн(?:ый|ая|ое|ые|ого|ой|ому|ым|ом|ых|ыми|ую)",
    r"легк(?:ий|ая|ое|ие|ого|ой|ому|им|ом|их|ими|ую)",
    r"приемник\w*", r"приема\b", r"приемом\b",
]

# Fixed glossary violations - the word is simply wrong for this site.
GLOSSARY = [
    (r"NFC[-\s]?тег\w*|тег\w*\s+NFC", "NFC hardware is a `метка`, never a `тег`"),
    (r"\bтэг\w*", "misspelling: the Russian word is `тег` (and NFC needs `метка`)"),
    (r"\bбэкап\w*", "`резервная копия`, not `бэкап`"),
    (r"\bгайд\w*", "`руководство` / `инструкция`, not `гайд`"),
    (r"\bфич[аиеу]\w*", "`функция` / `возможность`, not `фича`"),
    (r"\bаппликаци\w*|\bапп\b|\bсофт\b", "`приложение`"),
    (r"\bтапн\w*|\bтапа(?:ть|ет)\b", "NFC: `поднести`. A UI tap is `нажать` / `коснуться`"),
    (r"\bклонирован\w*\s+Amiibo|Amiibo[- ]клон\w*",
     "Amiibo: `резервное копирование и восстановление`, never `клонирование`"),
]

# Phrases where a rule hit is legitimate. Keep short and specific - it is an
# escape hatch, not a policy.
ALLOWED_PHRASES = [
    "теги блога",       # the blog's own tag chips, which ARE `теги`
    "Все теги",
    "тегам",
    # A product name that contains a spaced hyphen. It is the App Store title,
    # allowlisted in i18n.yaml too, so it cannot be restructured away.
    "1st Class - Flight Tracker",
]

# (name, pattern, explanation, regex flags)
ERROR_RULES: list[tuple[str, str, str, int]] = [
    (
        "vy-register",
        r"\b(?:" + VY_PRONOUNS + r")\b",
        "this locale is `ты`-only - a `вы` form is a register leak",
        re.I,
    ),
    (
        "vy-verb",
        r"\b(?:" + "|".join(VY_VERBS) + r")\b",
        "вы-form verb - use the `ты` imperative (`поднеси`, `нажми`, `выбери`)",
        re.I,
    ),
    (
        "mixed-script",
        r"[A-Za-zА-Яа-яЁё]*(?:[A-Za-z][А-Яа-яЁё]|[А-Яа-яЁё][A-Za-z])[A-Za-zА-Яа-яЁё]*",
        "Latin and Cyrillic mixed inside one word - `с o e a p x y k` look "
        "identical but break search, spellcheck and screen readers",
        0,
    ),
    ("dash", r"[—–]", "em/en dash - restructure the sentence (style guide §4)", 0),
    (
        "hyphen-as-dash",
        r"(?<=\S) - (?=\S)",
        "a hyphen standing in for a dash reads worse than either - restructure "
        "with a verb, `и` / `а`, a colon, or parentheses (style guide §4)",
        0,
    ),
    (
        "tsya-infinitive",
        r"\b(?:" + "|".join(MODALS) + r")\s+(?:не\s+)?\w+тся\b",
        "after a modal the verb is an infinitive: `-ться`, not `-тся`",
        re.I,
    ),
    (
        "tsya-third-person",
        r"\b(?:он|она|оно|они|это)\s+(?:не\s+)?\w+ться\b",
        "third person takes `-тся`, not `-ться` (что делает?)",
        re.I,
    ),
    (
        "missing-yo",
        r"\b(?:" + "|".join(YO_WORDS) + r")\b",
        "this word is written with `ё` (ещё, её, счётчик, надёжный, объём)",
        re.I,  # safe here: Cyrillic has no case-folding collision, and the
               # list must catch a sentence-initial `Ещё` / `Счётчик` too
    ),
    (
        "officialese-copula",
        r"\bявля(?:ется|ются|ясь)\b",
        "`является` is bureaucratic - Russian has no present-tense copula, "
        "so use a verb (`работает`, `хранит`) or restructure",
        re.I,
    ),
    (
        "curly-quote",
        r"[“”]",
        "English curly quotes - Russian prose uses «…» (nested: „…“)",
        0,
    ),
    (
        "number-format",
        r"\b\d{1,3},\d{3}\b",
        "English thousands separator - Russian groups with a non-breaking "
        "space (73 500) and uses the comma as a DECIMAL point (4,7)",
        0,
    ),
    (
        "ascii-quote",
        r"\"",
        "straight ASCII quote in a value i18n-check does not reach "
        "(YAML scalar or markdown frontmatter) - use «…»",
        0,
    ),
]

# Deliberately NOT linted: the copula `X это Y`. This locale bans the dash, so
# `NFC.cool — это приложение` cannot be written and `NFC.cool это приложение` is
# ungrammatical; the fix is always to restructure (style guide §4.1). But the
# defect cannot be separated from correct Russian mechanically: `это` is also a
# subject pronoun (`Для NFC это значение записи NDEF`), an object (`Счётчик
# касаний это использует`) and a determiner (`всё это`), and telling those apart
# needs to know whether the word before it is a nominative noun. A stop-list
# version of this rule scored 11 real defects against 12 false positives on this
# locale, so it stays a manual pass instead. Review it with:
#   grep -o '\S\+ это \S\+' Content/**/*.ru.{md,yaml}
# and check each hit for `noun + это + noun`, which is the shape to rewrite.
#
# Also deliberately NOT linted: comma placement before `что` / `чтобы` / `который`.
# Russian subordinate clauses take a comma, and a missing one is a real defect,
# but the same words also head non-clausal phrases (`что-то`, `не что иное`,
# `который час`), and `что` after a preposition or inside a fixed expression
# takes none. Every pattern tried here fired on correct prose more often than on
# a real omission, so the rule lives in the style guide, where judgment applies.
WARNING_RULES: list[tuple[str, str, float, str]] = [
    (
        "mozhesh-density",
        r"\bможешь\b",
        1.0,
        "\"you can\" fatigue - prefer the bare imperative (`запиши`, not "
        "`ты можешь записать`)",
    ),
    (
        "pronoun-density",
        r"\b(?:ты|тебя|тебе|тобой|тво(?:й|я|ё|е|и|его|ей|ему|им|их))\b",
        1.2,
        "the person is already carried by the verb ending - writing `ты / твой` "
        "out is emphatic and should be rare",
    ),
    (
        "officialese-density",
        r"\bосуществл\w*|\bпосредством\b|\bв целях\b|\bпри помощи\b|"
        r"\bданн(?:ый|ое|ая|ого|ому|ым|ом|ой|ую)\b|\bявляющ\w*",
        0.5,
        "officialese - marketing prose uses plain verbs "
        "(`записать`, not `осуществить запись`)",
    ),
]

SELFTEST: list[tuple[str, str | None]] = [
    # (prose fragment, expected rule name or None when it must stay clean)
    # -- correct Russian that must NOT trip anything --------------------------
    ("Поднеси iPhone к метке, и ссылка откроется сама", None),
    ("NFC-метка работает без батарейки", None),
    ("Приложение считывает метку и показывает содержимое", None),
    ("Wi-Fi, AirDrop и NameDrop работают на iPhone", None),
    ("3D-сканирование объектов и сканирование помещения", None),
    ("Метка легко читается, и счётчик растёт", None),
    ("Ссылка может открыться в браузере", None),
    ("Это приемлемый вариант, и всё работает", None),
    ("Выбор большой: выход есть всегда", None),
    ("Оценка 4,7 и 73 500 отзывов", None),
    ("Подключение к сети, сохранение файла, определение чипа", None),
    ("Разрешение экрана и нанесение краски", None),
    ("Функция включена, данные защищены, метка сохранена", None),
    ("Сканирование определено и разрешено", None),
    ("включенный режим", "missing-yo"),
    ("Темнота наступила, но идти было легко", None),
    ("Секрет сохранен на метке", "missing-yo"),
    ("Режим включен", "missing-yo"),
    ("трехмерная модель", "missing-yo"),
    ("- пункт списка", None),
    ("  - пункт списка", None),
    ("из-за плохого сигнала, по-своему удобно", None),
    ("Android читает метки, а камерные сканеры только на iOS", None),
    ("Теги блога помогают найти статью", None),
    # -- defects that MUST be caught -----------------------------------------
    ("Поднесите телефон к метке", "vy-verb"),
    ("Вы можете записать ссылку", "vy-register"),
    ("Это ваша метка", "vy-register"),
    ("сkанер документов", "mixed-script"),          # Latin k
    ("мeтка на столе", "mixed-script"),             # Latin e
    ("NFC-метка - это чип", "hyphen-as-dash"),
    ("NFC-метка — это чип", "dash"),
    ("Ссылка может открытся сама", "tsya-infinitive"),
    ("Она открываеться быстро", "tsya-third-person"),
    ("Еще одна метка", "missing-yo"),
    ("Счетчик касаний", "missing-yo"),
    ("Надежный чип", "missing-yo"),
    ("NFC-метка является чипом", "officialese-copula"),
    ("Запиши на NFC-тег ссылку", "glossary"),
    ("Сделай бэкап Amiibo", "glossary"),
    ("Просто тапни по метке", "glossary"),
    ("Он сказал “привет”", "curly-quote"),
    ("73,500 отзывов", "number-format"),
    ('title: "Возможности"', "ascii-quote"),
]


def compiled_error_rules() -> list[tuple[str, re.Pattern, str]]:
    rules = [(name, re.compile(pat, flags), why) for name, pat, why, flags in ERROR_RULES]
    rules += [(f"glossary", re.compile(pat, re.I), why) for pat, why in GLOSSARY]
    return rules


def selftest() -> int:
    failures = 0
    rules = compiled_error_rules()
    for prose, expected in SELFTEST:
        hits = {name for name, pattern, _ in rules if pattern.search(prose)}
        if expected is None and hits:
            print(f"  [SELFTEST] false positive on correct Russian: "
                  f"{prose!r} -> {sorted(hits)}")
            failures += 1
        elif expected is not None and expected not in hits:
            print(f"  [SELFTEST] missed {expected} on {prose!r} -> {sorted(hits) or 'nothing'}")
            failures += 1
    print(f"lint-russian selftest: {len(SELFTEST)} case(s), {failures} failure(s)")
    return 1 if failures else 0


FENCED = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.S | re.I)
# HTML code blocks are code, so their CONTENTS are blanked, not just the tags.
# The feature pages embed a sample JSON webhook body in <pre><code>…</code></pre>,
# and its escaped `\"` would otherwise read as ASCII quotes in Russian prose.
PRE_CODE = re.compile(r"<(pre|code)\b[^>]*>.*?</\1\s*>", re.S | re.I)
HTML_TAG = re.compile(r"<[^>\n]+>")
URL = re.compile(r"https?://\S+|\b[\w.-]+\.(?:com|org|net|io|cool|dev|pt|de|tr|ru)\b\S*")
MD_LINK_TARGET = re.compile(r"\]\([^)\n]*\)")
PATH_LIKE = re.compile(r"/[A-Za-z0-9._~%-]+(?:/[A-Za-z0-9._~%-]*)+")
YAML_COMMENT = re.compile(r"^\s*#.*$", re.M)

# Frontmatter / YAML keys whose value is an identifier, a path or a literal
# sentinel rather than prose. Everything NOT listed here stays linted, so a
# `title:` or `summary:` is checked - that is what a card and a search result
# show.
ID_KEYS = (
    r"slug|id|date|author|tags|url|image|ogImage|platforms|values|columns|"
    r"[A-Za-z]*[Pp]ath|[A-Za-z]*URL|[A-Za-z]*[Ii]con|badge|rating|count|"
    r"width|height|order|layout|type|theme|color"
)
ID_VALUE = re.compile(rf"^\s*-?\s*(?:{ID_KEYS})\s*:.*$", re.M)
# A quoted YAML/frontmatter scalar: the wrapping quotes are structural, not prose.
QUOTED_SCALAR = re.compile(r'^(\s*(?:-\s*)?(?:[\w.]+\s*:\s*)?)"(.*)"(\s*)$', re.M)


def blank(match: re.Match) -> str:
    """Replace a span with same-length whitespace so offsets stay put."""
    return re.sub(r"\S", " ", match.group(0))


def unquote_scalars(text: str) -> str:
    """Blank the structural quotes around a YAML scalar, keeping its prose."""
    return QUOTED_SCALAR.sub(lambda m: f"{m.group(1)} {m.group(2)} {m.group(3)}", text)


def strip_structure(text: str, path: Path) -> str:
    """Blank identifier values and structural quoting, keeping line numbers
    stable so reported positions still point at the real line."""
    if path.suffix == ".yaml":
        return unquote_scalars(ID_VALUE.sub(blank, YAML_COMMENT.sub(blank, text)))
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    head = unquote_scalars(ID_VALUE.sub(blank, text[: end + 1]))
    return head + text[end + 1 :]


def prose_of(path: Path) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8")
    body = strip_structure(text, path)
    for pattern in (SCRIPT_STYLE, PRE_CODE, FENCED, INLINE_CODE, HTML_TAG, URL, MD_LINK_TARGET, PATH_LIKE):
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
        for m in re.finditer(re.escape(phrase), prose, re.I)
    ]

    for name, pattern, explanation in compiled_error_rules():
        for m in pattern.finditer(prose):
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
    return sorted(ROOT.glob("Content/**/*.ru.md")) + sorted(ROOT.glob("Content/**/*.ru.yaml"))


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    quiet = "--quiet" in sys.argv
    files = targets(sys.argv[1:])
    if not files:
        print("lint-russian: no .ru files found")
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
        f"\nlint-russian: {len(files)} file(s), "
        f"{len(all_errors)} error(s), {len(all_warnings)} warning(s)"
    )
    if all_errors:
        return 1
    print("✓ Russian lint clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
