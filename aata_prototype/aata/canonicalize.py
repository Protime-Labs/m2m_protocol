"""
C10 (inline) / W1 step 2 -- Gateway canonicalization pre-pass.

Production tooling: custom ICU-based NFKC normalizer in the C1 Agent Gateway
(Envoy AI Gateway / LiteLLM MCP filter). Here: Python stdlib `unicodedata`.

Guarantee produced (W1 step 2):
    "Canonicalized payload; delta logged if normalization changed content
     (itself an IOC)."

This destroys the cheapest covert-channel encodings *before* content moves
further down the hot path. The DELTA between raw and canonical is retained --
a non-empty delta is an indicator-of-compromise fed to C10 deep inspection.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

# Zero-width / invisible formatting characters commonly abused for stego.
ZERO_WIDTH = {
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "⁠",  # word joiner
    "﻿",  # zero width no-break space / BOM
    "᠎",  # mongolian vowel separator
    "‎",  # left-to-right mark
    "‏",  # right-to-left mark
}

# A tiny confusables table (real deployments use the full Unicode confusables
# data set). Maps look-alike glyphs to their ASCII skeleton.
CONFUSABLES = {
    "а": "a",  # cyrillic a
    "е": "e",  # cyrillic e
    "о": "o",  # cyrillic o
    "р": "p",  # cyrillic er
    "с": "c",  # cyrillic es
    "х": "x",  # cyrillic ha
    "ԁ": "d",  # cyrillic komi de
    "ɡ": "g",  # latin small script g
    "ａ": "a",  # fullwidth a
    "ｅ": "e",  # fullwidth e
}


@dataclass
class CanonResult:
    raw: str
    canonical: str
    changed: bool
    zero_width_removed: int = 0
    confusables_mapped: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def delta_is_ioc(self) -> bool:
        """A non-trivial normalization delta is itself an indicator of compromise."""
        return self.zero_width_removed > 0 or self.confusables_mapped > 0


def canonicalize(text: str) -> CanonResult:
    """Run the pre-pass: strip zero-width, map confusables, NFKC-normalize."""
    zw = 0
    cf = 0
    out_chars: list[str] = []
    for ch in text:
        if ch in ZERO_WIDTH:
            zw += 1
            continue  # destroy the covert channel carrier
        if ch in CONFUSABLES:
            cf += 1
            out_chars.append(CONFUSABLES[ch])
            continue
        out_chars.append(ch)
    stripped = "".join(out_chars)
    canonical = unicodedata.normalize("NFKC", stripped)

    notes: list[str] = []
    if zw:
        notes.append(f"stripped {zw} zero-width/invisible char(s)")
    if cf:
        notes.append(f"mapped {cf} confusable glyph(s) to ASCII skeleton")
    if canonical != stripped:
        notes.append("NFKC normalization altered content")

    return CanonResult(
        raw=text,
        canonical=canonical,
        changed=canonical != text,
        zero_width_removed=zw,
        confusables_mapped=cf,
        notes=notes,
    )
