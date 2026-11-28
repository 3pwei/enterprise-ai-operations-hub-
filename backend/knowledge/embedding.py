"""Deterministic offline embeddings for the simulated bilingual document set."""

import hashlib
import math
import re
import unicodedata

from backend.knowledge.models import DIMENSIONS

TERMS = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+")


def normalize(text: str) -> str:
    return " ".join(TERMS.findall(unicodedata.normalize("NFKC", text).casefold()))


def embed(text: str) -> list[float]:
    values = [0.0] * DIMENSIONS
    for term in set(TERMS.findall(normalize(text))):
        if term.isascii():
            features = [term] + [term[i:i + 3] for i in range(len(term) - 2)]
        else:
            features = list(term) + [term[i:i + 2] for i in range(len(term) - 1)]
        for feature in features:
            key = hashlib.blake2b(feature.encode(), digest_size=4).digest()
            bucket = int.from_bytes(key, "big") % DIMENSIONS
            values[bucket] += 1 if key[0] & 1 else -1
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values
