#!/usr/bin/env python3
"""Build letter unigram/bigram statistics for Ventriloquist's spelling mode.

Spelling mode splits the alphabet into groups by probability, so the engine
needs letter counts for each supported language. This script downloads a small
set of public-domain texts, normalises them, counts letters and writes:

    backend/app/engine/data/letters_en.json
    backend/app/engine/data/letters_id.json

Sources
-------
English (Project Gutenberg plain-text editions):
  * #1342 Pride and Prejudice, Jane Austen (1813; this edition carries the
    1894 preface by George Saintsbury).
    https://www.gutenberg.org/cache/epub/1342/pg1342.txt
  * #11 Alice's Adventures in Wonderland, Lewis Carroll (1865).
    https://www.gutenberg.org/cache/epub/11/pg11.txt

Indonesian (statutory text from JDIH BPK, the Audit Board's official legal
documentation network, peraturan.bpk.go.id):
  * UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi (personal data protection).
  * UU No. 17 Tahun 2023 tentang Kesehatan (health law; adds clinical vocabulary
    such as PASIEN, RUMAH SAKIT, DOKTER, PERAWAT).
  * UUD 1945 dalam satu naskah (the constitution with all four amendments, as
    published by the MPR secretariat; the only born-digital PDF of the three).

Licence reasoning
-----------------
* Gutenberg texts: both authors died more than a century ago (Austen 1817,
  Carroll 1898, Saintsbury 1933), so the works are public domain in the US and
  in life+70 countries. Project Gutenberg's licence only governs redistribution
  under the "Project Gutenberg" trademark; we strip the Gutenberg header and
  footer, never commit the text, and publish only aggregate letter counts.
* Indonesian statutes: Law No. 28 of 2014 on Copyright, Article 42, states that
  there is no copyright in "peraturan perundang-undangan" (letter b), among other
  official works. UUD 1945 heads the statutory hierarchy (Law No. 12 of 2011, Art. 7),
  so the same exclusion applies. The PDFs come from an official .go.id host.

Downloaded files go to data/corpora/ (gitignored, never committed). They are
cached: a file that already exists is reused, and a SHA-256 mismatch against
the hash recorded below prints a warning (the publisher may have re-issued the
file) but does not stop the build.

Normalisation
-------------
1. Source-specific cleaning:
   * Gutenberg: keep only the text between the "*** START OF ..." and
     "*** END OF ..." markers, and drop "[Illustration ...]" blocks (captions and
     the title-page publisher imprint).
   * Statutes (extracted with poppler's `pdftotext -layout`): drop page furniture
     (the "PRESIDEN / REPUBLIK INDONESIA" running header including OCR misreads,
     "SK No ..." stamps, page numbers), the UUD amendment legend, the elucidation
     filler "Cukup jelas." ("self-explanatory") and bare structural labels such
     as "Pasal 5", "Ayat (1)", "Huruf a".
2. Unicode NFKD, combining marks removed (so an accented E counts as E).
3. Uppercase.
4. Apostrophes between two letters are deleted (DON'T -> DONT, JUM'AT -> JUMAT)
   because patients spell without punctuation.
5. Every other run of characters that are not A-Z collapses to one space
   (so hyphenated reduplication ANAK-ANAK becomes the two words ANAK ANAK).

Counts
------
unigram     every letter occurrence
word_start  first letter of each word
word_end    last letter of each word (a one-letter word counts as start and end)
bigram      letter -> next letter, only inside a word
mean_word_length = letters / words; n_words = number of words.
All 26 letters appear as keys (zero when unseen), so the engine can rely on a
complete table; any smoothing is the engine's job.

Limitations
-----------
The two newer statutes are scanned PDFs with an OCR text layer. OCR slips
(e.g. "je1as", "ditqjukan") add a little noise, and legal register
over-represents words such as DAN, YANG, PASAL and PERATURAN. Treat the
Indonesian table as a reasonable prior, not a conversational frequency list.

Usage
-----
    backend/.venv/bin/python scripts/build_letter_stats.py            # both languages
    backend/.venv/bin/python scripts/build_letter_stats.py --lang id  # one language
    backend/.venv/bin/python scripts/build_letter_stats.py --refresh  # re-download

Requires httpx (a backend dependency) and `pdftotext` from poppler-utils
(`apt install poppler-utils` / `brew install poppler`). The committed JSON was
built with pdftotext 24.02.0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "data" / "corpora"
OUT_DIR = REPO_ROOT / "backend" / "app" / "engine" / "data"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
USER_AGENT = "ventriloquist-letter-stats/1.0 (+public-domain corpus build)"

GUTENBERG_LICENSE = (
    "public domain (Project Gutenberg eBook; author died over 100 years ago; "
    "Gutenberg header/footer stripped, only letter counts published)"
)
ID_STATUTE_LICENSE = (
    "public domain (no copyright in statutory text: UU No. 28 Tahun 2014 "
    "tentang Hak Cipta, Pasal 42 huruf b)"
)


@dataclass(frozen=True)
class Source:
    language: str
    title: str
    url: str
    filename: str
    kind: str  # "gutenberg" or "statute_pdf"
    license: str
    sha256: str


SOURCES: tuple[Source, ...] = (
    Source(
        language="en",
        title="Pride and Prejudice, Jane Austen (Project Gutenberg #1342)",
        url="https://www.gutenberg.org/cache/epub/1342/pg1342.txt",
        filename="pg1342.txt",
        kind="gutenberg",
        license=GUTENBERG_LICENSE,
        sha256="3f6bb9d6f78e0293b56acd4714dd68cb7d6d1d293402031ce9d5a216bcaf9d75",
    ),
    Source(
        language="en",
        title="Alice's Adventures in Wonderland, Lewis Carroll (Project Gutenberg #11)",
        url="https://www.gutenberg.org/cache/epub/11/pg11.txt",
        filename="pg11.txt",
        kind="gutenberg",
        license=GUTENBERG_LICENSE,
        sha256="01b38ea4c710a84bc18d0bd41271a5a1a92b94e97b2812f4dece97d4a694725e",
    ),
    Source(
        language="id",
        title="UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi (JDIH BPK)",
        url="https://peraturan.bpk.go.id/Download/224884/UU%20Nomor%2027%20Tahun%202022.pdf",
        filename="uu_27_2022_pdp.pdf",
        kind="statute_pdf",
        license=ID_STATUTE_LICENSE,
        sha256="ed952dea04b87d14ecf037f9f324a65d50b396ddd34fc28ddf9ff014391971f6",
    ),
    Source(
        language="id",
        title="UU No. 17 Tahun 2023 tentang Kesehatan (JDIH BPK)",
        url="https://peraturan.bpk.go.id/Download/314883/UU%20Nomor%2017%20Tahun%202023.pdf",
        filename="uu_17_2023_kesehatan.pdf",
        kind="statute_pdf",
        license=ID_STATUTE_LICENSE,
        sha256="612400d634aff1eca403cbbf3d1e7746d73ffb71b43aeb1775c6a494f509ca1a",
    ),
    Source(
        language="id",
        title="Undang-Undang Dasar Negara Republik Indonesia Tahun 1945, dalam satu naskah (JDIH BPK)",
        url="https://peraturan.bpk.go.id/Download/92288/UUD45_SatuNaskah.pdf",
        filename="uud_1945_satu_naskah.pdf",
        kind="statute_pdf",
        license=ID_STATUTE_LICENSE,
        sha256="6d629da7bdbec439629899c30ffea9df0aba842bf2406fad8ff6cc393edd3854",
    ),
)

# --------------------------------------------------------------------------- download


def fetch(source: Source, refresh: bool) -> Path:
    """Download a source into data/corpora/ unless it is already cached."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    path = CORPUS_DIR / source.filename
    if refresh or not path.exists():
        print(f"  downloading {source.url}", file=sys.stderr)
        with httpx.Client(
            follow_redirects=True, timeout=180, headers={"User-Agent": USER_AGENT}
        ) as client:
            resp = client.get(source.url)
            resp.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source.sha256:
        print(
            f"  WARNING: {source.filename} sha256 {digest} differs from the recorded "
            f"{source.sha256}; counts may differ from the committed JSON.",
            file=sys.stderr,
        )
    return path


# --------------------------------------------------------------------------- cleaning

_PG_START = re.compile(r"^\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)
_PG_END = re.compile(r"^\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*$", re.M)
_PG_ILLUSTRATION = re.compile(r"\[Illustration[^\]]{0,600}\]", re.S)


def clean_gutenberg(raw: str) -> str:
    start = _PG_START.search(raw)
    end = _PG_END.search(raw)
    if not start or not end or end.start() <= start.end():
        raise ValueError("Project Gutenberg START/END markers not found")
    body = raw[start.end() : end.start()]
    return _PG_ILLUSTRATION.sub(" ", body)


_STATUTE_DROP = [
    re.compile(p, re.I)
    for p in (
        r"^SK\s*No\b.*$",  # page stamp on every page of the State Secretariat copy
        r"^[^A-Za-z]*$",  # page numbers such as "-2-", stray punctuation
        r"^salinan$",
        r"^cukup\s*je[l1i|]as\s*\.?$",  # elucidation filler, hundreds of repeats
        r"^(?:pasal|ayat|huruf|angka)\s*\S{0,6}$",  # bare structural labels
        r"^\*+\)\s*:?\s*perubahan\b.*$",  # UUD amendment legend repeated per page
    )
]
_RUNNING_HEADERS = ("PRESIDEN", "REPUBLIKINDONESIA", "PRESIDENREPUBLIKINDONESIA")


def _is_running_header(line: str) -> bool:
    letters = re.sub(r"[^A-Z]", "", line.upper())
    if not letters or len(letters) > 30:
        return False
    return any(SequenceMatcher(None, letters, h).ratio() >= 0.8 for h in _RUNNING_HEADERS)


def pdf_to_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if exe is None:
        sys.exit("pdftotext not found: install poppler-utils (apt) or poppler (brew).")
    result = subprocess.run(
        [exe, "-layout", "-enc", "UTF-8", str(path), "-"],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def clean_statute(raw: str) -> str:
    kept = []
    for line in raw.splitlines():
        s = line.strip()
        if any(p.match(s) for p in _STATUTE_DROP) or _is_running_header(s):
            continue
        kept.append(s)
    return "\n".join(kept)


def load_text(source: Source, refresh: bool) -> str:
    path = fetch(source, refresh)
    if source.kind == "gutenberg":
        return clean_gutenberg(path.read_bytes().decode("utf-8-sig"))
    if source.kind == "statute_pdf":
        return clean_statute(pdf_to_text(path))
    raise ValueError(f"unknown source kind {source.kind!r}")


# --------------------------------------------------------------------------- counting

_INNER_APOSTROPHE = re.compile(r"(?<=[A-Z])['’ʼ](?=[A-Z])")
_NON_LETTERS = re.compile(r"[^A-Z]+")


def normalise(text: str) -> str:
    """Uppercase A-Z words separated by single spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).upper()
    text = _INNER_APOSTROPHE.sub("", text)
    return _NON_LETTERS.sub(" ", text).strip()


def letter_stats(words: Iterable[str]) -> dict:
    unigram: Counter[str] = Counter()
    word_start: Counter[str] = Counter()
    word_end: Counter[str] = Counter()
    bigram: dict[str, Counter[str]] = {a: Counter() for a in ALPHABET}
    n_words = 0
    for w in words:
        n_words += 1
        unigram.update(w)
        word_start[w[0]] += 1
        word_end[w[-1]] += 1
        for a, b in zip(w, w[1:], strict=False):
            bigram[a][b] += 1
    n_letters = sum(unigram.values())
    return {
        "unigram": {a: unigram[a] for a in ALPHABET},
        "word_start": {a: word_start[a] for a in ALPHABET},
        "bigram": {a: {b: bigram[a][b] for b in ALPHABET} for a in ALPHABET},
        "word_end": {a: word_end[a] for a in ALPHABET},
        "mean_word_length": round(n_letters / n_words, 4) if n_words else 0.0,
        "n_words": n_words,
    }


def build(language: str, refresh: bool) -> Path:
    sources = [s for s in SOURCES if s.language == language]
    words: list[str] = []
    for s in sources:
        w = normalise(load_text(s, refresh)).split()
        print(f"  {s.filename}: {len(w)} words", file=sys.stderr)
        words.extend(w)
    stats = letter_stats(words)
    doc = {
        "language": language,
        "sources": [{"title": s.title, "url": s.url, "license": s.license} for s in sources],
        "alphabet": ALPHABET,
        **stats,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"letters_{language}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(stats["unigram"].values())
    top = sorted(stats["unigram"].items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    print(
        f"{language}: {stats['n_words']} words, mean length {stats['mean_word_length']}, "
        f"top letters {' '.join(f'{k}={v / total:.3f}' for k, v in top)} -> {out}",
        file=sys.stderr,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", choices=["en", "id", "all"], default="all")
    parser.add_argument("--refresh", action="store_true", help="re-download cached sources")
    args = parser.parse_args(argv)
    for language in ("en", "id") if args.lang == "all" else (args.lang,):
        print(f"[{language}]", file=sys.stderr)
        build(language, args.refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
