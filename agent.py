#!/usr/bin/env python3
"""Outlook fix assistant: a small, offline, guided troubleshooting agent.

How it works (the "agent loop"):
  1. RETRIEVE  - score every note in notes/ against the user's description.
  2. ASK       - ask the top candidate's diagnostic questions (yes/no).
                 "Yes" answers raise that note's score, "no" lowers it.
  3. DECIDE    - pick the best-scoring note.
  4. SUGGEST   - show warnings, then walk through the steps one at a time.

Safety: this agent NEVER runs anything. It only tells the human what to do
and waits for confirmation. No network, no AI model, no real user data.
"""
import argparse
import re
import sys
from pathlib import Path

import retriever as rt

NOTES_DIR = Path(__file__).parent / "notes"
TOP_CANDIDATES = 2
# Similarity scores run from 0 to 1, so the yes/no nudges are small too.
YES_BONUS = 0.10
NO_PENALTY = 0.08

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "and", "or", "of", "in", "on", "it",
    "can", "cant", "can't", "not", "user", "my", "his", "her", "with", "for",
    "has", "have", "does", "do", "i", "me", "they", "their", "after", "when",
}


def tokenize(text):
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def parse_note(path):
    """Parse one markdown note into a dict."""
    note = {"file": path.name, "title": "", "keywords": [], "questions": [],
            "warnings": [], "steps": []}
    section = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            note["title"] = line[2:].strip()
        elif line.lower().startswith("keywords:"):
            note["keywords"] = [k.strip().lower() for k in line.split(":", 1)[1].split(",") if k.strip()]
        elif line.startswith("## "):
            section = line[3:].strip().lower()
        elif section == "questions" and line.startswith("- "):
            q = line[2:].strip()
            q = re.sub(r"\s*\[yes\]\s*$", "", q)
            note["questions"].append(q)
        elif section == "warnings" and line.startswith("- "):
            note["warnings"].append(line[2:].strip())
        elif section == "steps" and re.match(r"\d+\.", line):
            note["steps"].append(re.sub(r"^\d+\.\s*", "", line))
    return note


def load_notes(notes_dir=NOTES_DIR):
    return [parse_note(p) for p in sorted(Path(notes_dir).glob("*.md"))]


def score_note(note, description):
    """Keyword overlap score. Multi-word keywords count as phrases."""
    text = description.lower()
    tokens = set(tokenize(description))
    score = 0
    for kw in note["keywords"]:
        if " " in kw:
            if kw in text:
                score += 3
        elif kw in tokens:
            score += 2
    title_tokens = set(tokenize(note["title"]))
    score += len(tokens & title_tokens)
    return score


def keyword_retrieve(notes, description, top_n=TOP_CANDIDATES):
    """The original keyword matcher. Kept so you can compare it with vector search."""
    ranked = sorted(((score_note(n, description), n) for n in notes),
                    key=lambda pair: pair[0], reverse=True)
    return [(s, n) for s, n in ranked[:top_n] if s > 0]


def retrieve(notes, description, top_n=TOP_CANDIDATES, retriever=None):
    """Vector search: find the notes closest in meaning to the description."""
    retriever = retriever or rt.TfidfRetriever(notes)
    return retriever.search(description, top_n)


def ask_yes_no(question, input_fn=input):
    while True:
        answer = input_fn(f"  {question} (y/n/skip): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        if answer in ("s", "skip", ""):
            return None
        print("  Please type y, n, or skip.")


def diagnose(candidates, input_fn=input, output_fn=print):
    """Ask each candidate's questions and adjust its score. Returns best note."""
    adjusted = []
    for base_score, note in candidates:
        output_fn(f"\nChecking: {note['title']}")
        score = base_score
        yes_count = 0
        for q in note["questions"]:
            answer = ask_yes_no(q, input_fn)
            if answer is True:
                score += YES_BONUS
                yes_count += 1
            elif answer is False:
                score -= NO_PENALTY
        adjusted.append((score, note))
        # Stop early if the first candidate got a "yes" to every question.
        if len(adjusted) == 1 and yes_count == len(note["questions"]):
            break
    adjusted.sort(key=lambda pair: pair[0], reverse=True)
    return adjusted[0][1]


def walk_through(note, input_fn=input, output_fn=print):
    """Show warnings, then each step. The human does the work."""
    output_fn(f"\n=== Suggested fix: {note['title']} ===")
    if note["warnings"]:
        output_fn("\nBefore you start:")
        for w in note["warnings"]:
            output_fn(f"  ! {w}")
    output_fn("\nI will not change anything myself. Do each step, then tell me.")
    for i, step in enumerate(note["steps"], 1):
        output_fn(f"\nStep {i}/{len(note['steps'])}: {step}")
        while True:
            reply = input_fn("  Done? (y = next, q = quit): ").strip().lower()
            if reply in ("y", "yes"):
                break
            if reply in ("q", "quit"):
                output_fn("Stopped. Nothing was changed by me.")
                return False
    output_fn("\nAll steps shown. Ask the user to confirm Outlook now opens.")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Outlook fix assistant (suggest-only).")
    parser.add_argument("--mode", choices=["auto", "tfidf", "embeddings"], default="tfidf",
                        help="how to search the notes (default: tfidf, fully offline)")
    args = parser.parse_args(argv)

    notes = load_notes()
    if not notes:
        print(f"No notes found in {NOTES_DIR}")
        return 1
    try:
        search = rt.build_retriever(notes, args.mode)
    except Exception as err:
        print(f"Could not start '{args.mode}' search: {type(err).__name__}: {err}")
        print("For embeddings, run:  pip install sentence-transformers")
        print("(The first run downloads a ~90 MB model. Or use --mode tfidf.)")
        return 1
    print(f"Outlook fix assistant (suggest-only, search: {search.name}).")
    try:
        description = input("Describe the user's issue: ").strip()
        candidates = retrieve(notes, description, retriever=search)
        if not candidates:
            print("\nI could not match that to any note. Try other words, or add a new note to notes/.")
            return 0
        best = diagnose(candidates)
        walk_through(best)
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Nothing was changed by me.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
