"""Which of the dealership's languages a customer wrote in.

Routing reads it the moment a new customer's first message lands — before any
model has read it — so it is decided here, from the text: Arabic script is
Arabic; Arabic in Latin letters ("3andkom hilux?") is Arabic too; otherwise
French or English by the words and accents they use. None when a message says
too little to tell ("OK", a price, a thumbs-up), and the next message decides.

ponytail: word lists for three languages. Upgrade trigger: a fourth language in
the routing rules, or customers routed to the wrong team in the pilot — then a
real language identifier.
"""

from __future__ import annotations

import re
from typing import Literal

from ..guards.script import script_of

Language = Literal["ar", "en", "fr"]

_WORDS = re.compile(r"[a-z0-9àâçéèêëîïôûùüÿœ']+")
#: A digit standing for an Arabic letter inside a word: ma3ak, a7la, 3andkom.
#: Not at the end of one, where it is a model: Q7, CX9, X3.
_ARABIZI = re.compile(r"^(?:[a-z]+[2379][a-z]+|[2379][a-z]{2,})$")
_ARABIZI_WORDS = frozenset(
    "salam marhaba ahlan hala shukran habibi yalla inshallah mashallah kifak kif "
    "shu sho shou mafi bkam wein wen tamam ana enta inta".split()
)
_FRENCH = frozenset(
    "bonjour bonsoir salut merci vous votre vos nous je j'ai est c'est les des une "
    "le la du au et pour avec oui non combien prix voiture disponible svp quel "
    "quelle".split()
)
_FRENCH_LETTERS = frozenset("àâçéèêëîïôûùüÿœ")
_ENGLISH = frozenset(
    "hi hello the is are you your have has do does what how much price please "
    "thanks thank available can i my it for with and any there".split()
)


def language_of(text: str) -> Language | None:
    script = script_of(text)
    if script == "arabic":
        return "ar"
    if script != "latin":
        return None
    words = _WORDS.findall(text.lower())
    scores: dict[Language, int] = {
        "ar": sum(1 for w in words if _ARABIZI.match(w) or w in _ARABIZI_WORDS),
        "fr": sum(1 for w in words if w in _FRENCH or _FRENCH_LETTERS & set(w)),
        "en": sum(1 for w in words if w in _ENGLISH),
    }
    best = max(scores.values())
    leaders = [language for language, score in scores.items() if score == best]
    return leaders[0] if best and len(leaders) == 1 else None
