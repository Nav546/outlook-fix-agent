"""Retrievers: turn text into vectors and find the notes closest to a question.

This is the "R" in RAG (Retrieval). Every note and the user's question become
vectors (lists of numbers). Notes whose vector points the same way as the
question's vector are the best matches (cosine similarity).

Two ways to make vectors:
  * TfidfRetriever      - pure Python, offline, no installs. Counts words, with
                          rare words weighted higher. Good default.
  * EmbeddingRetriever  - uses a neural model (sentence-transformers) so it
                          understands MEANING, e.g. "stuck on loading screen"
                          is close to "hangs on Loading profile".
"""
import math
import re
from collections import Counter

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "and", "or", "of", "in", "on", "it",
    "can", "cant", "can't", "not", "user", "my", "his", "her", "with", "for",
    "has", "have", "does", "do", "i", "me", "they", "their", "after", "when",
    "this", "that", "then", "so", "be", "was", "were", "at", "by", "from",
    "up", "if", "as", "but", "no", "yes", "again", "still", "all", "any",
    "keep", "keeps", "says", "say", "whenever", "get", "gets", "got",
}


def stem(word):
    """Very small stemmer so crashes/crashing/crashed all match 'crash'."""
    for suffix, min_len in (("ing", 6), ("ed", 5), ("es", 5), ("s", 4)):
        if word.endswith(suffix) and len(word) >= min_len and not word.endswith("ss"):
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def tokenize(text):
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def note_text(note):
    """The text we index for a note: title + keywords + questions + steps."""
    parts = [note["title"], " ".join(note["keywords"]), " ".join(note["questions"]), " ".join(note["steps"])]
    return ". ".join(p for p in parts if p)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class TfidfRetriever:
    name = "tfidf"
    min_score = 0.08  # below this, treat as "no match"

    def __init__(self, notes):
        self.notes = notes
        docs = [Counter(tokenize(note_text(n))) for n in notes]
        df = Counter(term for d in docs for term in d)
        n_docs = len(docs)
        self.vocab = sorted(df)
        self.index = {t: i for i, t in enumerate(self.vocab)}
        # Smoothed inverse document frequency: rare words weigh more.
        self.idf = {t: math.log((1 + n_docs) / (1 + df[t])) + 1 for t in self.vocab}
        self.doc_vectors = [self._vector(d) for d in docs]

    def _vector(self, counts):
        vec = [0.0] * len(self.vocab)
        for term, count in counts.items():
            if term in self.index:
                vec[self.index[term]] = (1 + math.log(count)) * self.idf[term]
        return vec

    def search(self, query, top_n=2):
        qvec = self._vector(Counter(tokenize(query)))
        scored = [(cosine(qvec, dv), n) for dv, n in zip(self.doc_vectors, self.notes)]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(s, n) for s, n in scored[:top_n] if s >= self.min_score]


class EmbeddingRetriever:
    name = "embeddings"
    min_score = 0.30

    def __init__(self, notes, encode):
        """`encode` takes a list of strings and returns a list of vectors."""
        self.notes = notes
        self.encode = encode
        self.doc_vectors = encode([note_text(n) for n in notes])

    def search(self, query, top_n=2):
        qvec = self.encode([query])[0]
        scored = [(cosine(qvec, dv), n) for dv, n in zip(self.doc_vectors, self.notes)]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(s, n) for s, n in scored[:top_n] if s >= self.min_score]


def sentence_transformer_encoder(model_name="all-MiniLM-L6-v2"):
    """Return an encode function, or raise ImportError if not installed.

    Install with: pip install sentence-transformers
    The first run downloads the model (about 90 MB). After that it is offline.
    """
    from sentence_transformers import SentenceTransformer  # noqa: WPS433

    model = SentenceTransformer(model_name)

    def encode(texts):
        return [list(map(float, v)) for v in model.encode(texts)]

    return encode


def build_retriever(notes, mode="auto", encode=None):
    """mode: 'tfidf', 'embeddings', or 'auto' (embeddings if available)."""
    if mode == "tfidf":
        return TfidfRetriever(notes)
    if mode in ("embeddings", "auto"):
        try:
            return EmbeddingRetriever(notes, encode or sentence_transformer_encoder())
        except Exception as err:  # not installed, or model could not load
            if mode == "embeddings":
                raise
            print(f"(Embeddings not available: {type(err).__name__}. Using TF-IDF instead.)")
            return TfidfRetriever(notes)
    raise ValueError(f"unknown mode: {mode}")
