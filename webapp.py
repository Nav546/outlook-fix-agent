#!/usr/bin/env python3
"""Live web GUI for the Outlook fix assistant.

Run:  python webapp.py          (opens http://127.0.0.1:8765 in your browser)

Left   - a Teams-style chat. The agent asks the user questions.
Centre - a SIMULATED Windows PC where you watch each fix step happen.
Right  - "how the agent decided": the notes it retrieved and why it chose one.

It reuses the same notes, retriever and scoring as agent.py. Everything on the
PC screen is a simulation: nothing touches a real computer.
"""
import argparse
import json
import re
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agent
import retriever as rt

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 20_000
MAX_SESSIONS = 200

YES = {"y", "yes", "yeah", "yep", "yup", "correct", "true"}
NO = {"n", "no", "nope", "nah", "false"}
SKIP = {"skip", "unsure", "idk", "maybe", "unknown"}
NEXT = {"done", "next", "ok", "okay", "continue", "go", "finished", "y", "yes", "yep", "yeah"}
STOP = {"stop", "quit", "q", "cancel", "abort"}
RESTART = {"restart", "reset"}


def first_word(text):
    words = re.findall(r"[a-z']+", text.lower())
    return words[0] if words else ""


def parse_answer(text):
    """Turn free text into 'yes', 'no', 'skip' or None (not understood)."""
    low = text.lower().strip()
    if any(p in low for p in ("not sure", "don't know", "dont know", "no idea")):
        return "skip"
    word = first_word(text)
    if word in YES:
        return "yes"
    if word in NO:
        return "no"
    if word in SKIP or low == "?":
        return "skip"
    return None


def second_person(text):
    """The notes are written for the technician; the chat talks to the user."""
    text = re.sub(r"\b[Ii]s the user\b", lambda m: "Are you" if m.group(0)[0] == "I" else "are you", text)
    text = re.sub(r"\b([Dd])oes the user\b", lambda m: m.group(1) + "o you", text)
    text = re.sub(r"\bthe user's\b", "your", text)
    text = re.sub(r"\bthe user\b", "you", text)
    text = text.replace("you knows", "you know")
    return text


def msg(text, kind="text", **extra):
    out = {"text": text, "kind": kind}
    out.update(extra)
    return out


class Session:
    """One chat. A small state machine: problem -> asking -> confirm -> fixing -> done."""

    def __init__(self, notes, search):
        self.notes = notes
        self.search = search
        self.reset()

    # ----- helpers -------------------------------------------------------
    def reset(self):
        self.state = "problem"
        self.query = ""
        self.cands = []
        self.cidx = 0
        self.qidx = 0
        self.decided = None
        self.step = -1
        self.tried = []
        return self._reply([msg("Hi! I'm the IT helpdesk assistant. Tell me what's going on with your PC "
                                "and I'll work out how to fix it.")])

    def _brain(self):
        return {
            "query": self.query,
            "mode": self.search.name,
            "decided": self.decided["file"] if self.decided else None,
            "active": self.cidx if self.state == "asking" else None,
            "candidates": [
                {
                    "file": c["note"]["file"],
                    "title": c["note"]["title"],
                    "score": round(c["base"], 3),
                    "adjusted": None if c["adjusted"] is None else round(c["adjusted"], 3),
                    "questions": [
                        {"text": second_person(q), "answer": a}
                        for q, a in zip(c["note"]["questions"], c["answers"])
                    ],
                }
                for c in self.cands
            ],
        }

    def _scene(self):
        if self.decided:
            file = self.decided["file"]
        elif self.cands:
            file = self.cands[0]["note"]["file"]
        else:
            return None
        step = self.step if self.state in ("fixing", "done", "closed") else -1
        return {"file": file, "step": step}

    def _reply(self, messages, quick=()):
        return {
            "messages": messages,
            "quick": list(quick),
            "state": self.state,
            "brain": self._brain(),
            "scene": self._scene(),
        }

    def _question(self):
        c = self.cands[self.cidx]
        text = second_person(c["note"]["questions"][self.qidx])
        return msg(text, kind="question")

    ASK_QUICK = ("Yes", "No", "Not sure")

    # ----- main entry ----------------------------------------------------
    def handle(self, text):
        text = (text or "").strip()
        if not text:
            return self._reply([])
        if first_word(text) in RESTART or text.lower() in ("start over", "new problem"):
            return self.reset()
        if self.state == "closed":
            self.reset()
        handler = getattr(self, "_on_" + self.state)
        return handler(text)

    def _on_problem(self, text):
        found = agent.retrieve(self.notes, text, retriever=self.search)
        if not found:
            return self._reply([msg("Hmm, I couldn't match that to anything I know how to fix. Could you describe "
                                    "what you see on screen, for example an error message or what Outlook is doing?")])
        self.query = text
        self.cands = [{"note": n, "base": s, "answers": [None] * len(n["questions"]), "adjusted": None}
                      for s, n in found]
        self.cidx, self.qidx, self.state = 0, 0, "asking"
        count = len(self.cands)
        intro = ("Thanks, that helps. I searched my notes and found "
                 f"{'a likely match' if count == 1 else str(count) + ' likely matches'}. "
                 "Let me ask a few quick questions to be sure.")
        return self._reply([msg(intro), self._question()], self.ASK_QUICK)

    def _on_asking(self, text):
        answer = parse_answer(text)
        if answer is None:
            return self._reply([msg("Sorry, I need a yes, no or not sure for that one.", kind="note"),
                                self._question()], self.ASK_QUICK)
        c = self.cands[self.cidx]
        c["answers"][self.qidx] = answer
        self.qidx += 1
        if self.qidx < len(c["note"]["questions"]):
            return self._reply([self._question()], self.ASK_QUICK)
        yes = c["answers"].count("yes")
        no = c["answers"].count("no")
        c["adjusted"] = c["base"] + agent.YES_BONUS * yes - agent.NO_PENALTY * no
        all_yes = yes == len(c["answers"])
        if (self.cidx == 0 and all_yes) or self.cidx + 1 >= len(self.cands):
            return self._decide()
        self.cidx += 1
        self.qidx = 0
        return self._reply([msg("Okay, that isn't a clear match. Let me check another possibility."),
                            self._question()], self.ASK_QUICK)

    def _decide(self, intro=None):
        pool = [c for c in self.cands if c["note"]["file"] not in self.tried]
        if not pool:
            self.state = "closed"
            return self._reply([msg("I've tried everything in my notes without success. I'm escalating this to "
                                    "second-line support with the details so far.", kind="resolved-no")],
                               ["Start over"])
        best = max(pool, key=lambda c: c["base"] if c["adjusted"] is None else c["adjusted"])
        note = best["note"]
        self.decided = note
        self.tried.append(note["file"])
        self.step = -1
        self.state = "confirm"
        messages = [msg(intro or "Based on your answers, the most likely cause is:"),
                    msg(note["title"], kind="decision")]
        if note["warnings"]:
            messages.append(msg("\n".join(second_person(w) for w in note["warnings"]), kind="warning"))
        messages.append(msg("Ready? I'll walk you through the fix one step at a time, and you can watch it "
                            "happen on the simulated PC."))
        return self._reply(messages, ["Show me the fix"])

    def _on_confirm(self, text):
        if first_word(text) in NO | STOP:
            self.state = "problem"
            return self._reply([msg("No problem. Tell me if you'd like to try describing it differently.")])
        self.state = "fixing"
        self.step = 0
        return self._reply([self._step_message()], ["Done, next step"])

    def _step_message(self):
        steps = self.decided["steps"]
        return msg(second_person(steps[self.step]), kind="step", step=self.step + 1, total=len(steps))

    def _on_fixing(self, text):
        word = first_word(text)
        if word in STOP:
            self.state = "problem"
            self.step = -1
            return self._reply([msg("Okay, stopped. Nothing was changed. Tell me if you want to try again.")])
        if word not in NEXT and not text.lower().startswith("done"):
            return self._reply([msg("Tell me 'done' when you've finished that step and I'll show the next one.",
                                    kind="note")], ["Done, next step"])
        steps = self.decided["steps"]
        if self.step + 1 < len(steps):
            self.step += 1
            return self._reply([self._step_message()], ["Done, next step"])
        self.state = "done"
        return self._reply([msg("That's every step. Can you confirm Outlook works now?")],
                           ["Yes, it works", "Still broken"])

    def _on_done(self, text):
        answer = parse_answer(text)
        if answer == "yes" or text.lower().startswith("it works"):
            self.state = "closed"
            return self._reply([msg("Brilliant, glad that's sorted. I've marked the ticket as resolved.",
                                    kind="resolved")], ["Start over"])
        if answer == "no" or "broken" in text.lower():
            self.state = "asking"
            self.step = -1
            return self._decide(intro="Thanks for letting me know. Let's try the next most likely cause:")
        return self._reply([msg("Did that fix it? Yes or no?", kind="note")], ["Yes, it works", "Still broken"])

    def _on_closed(self, text):  # pragma: no cover - handle() resets first
        return self.reset()


# ----- HTTP server ---------------------------------------------------------
class Store:
    def __init__(self, notes, search):
        self.notes, self.search = notes, search
        self.sessions = {}
        self.lock = threading.Lock()

    def get(self, sid):
        with self.lock:
            if sid not in self.sessions:
                if len(self.sessions) >= MAX_SESSIONS:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[sid] = Session(self.notes, self.search)
                created = True
            else:
                created = False
            return self.sessions[sid], created


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the console quiet
            pass

        def _send(self, status, body, ctype):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            routes = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/index.html": ("index.html", "text/html; charset=utf-8"),
                      "/scenes.json": ("scenes.json", "application/json; charset=utf-8")}
            route = routes.get(self.path.split("?")[0])
            if not route:
                return self._send(404, b"Not found", "text/plain")
            self._send(200, (WEB_DIR / route[0]).read_bytes(), route[1])

        def do_POST(self):
            if self.path not in ("/api/chat", "/api/reset"):
                return self._send(404, b"Not found", "text/plain")
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > MAX_BODY:
                    return self._json({"error": "too large"}, 413)
                data = json.loads(self.rfile.read(length) or b"{}")
                sid = str(data.get("sid") or uuid.uuid4())[:64]
            except (ValueError, TypeError):
                return self._json({"error": "bad request"}, 400)
            session, created = store.get(sid)
            if self.path == "/api/reset" or created and not str(data.get("text") or "").strip():
                return self._json(session.reset())
            return self._json(session.handle(str(data.get("text") or "")))

    return Handler


def make_server(host, port, notes, search):
    return ThreadingHTTPServer((host, port), make_handler(Store(notes, search)))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Live GUI for the Outlook fix assistant.")
    parser.add_argument("--mode", choices=["auto", "tfidf", "embeddings"], default="tfidf")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    notes = agent.load_notes()
    if not notes:
        print(f"No notes found in {agent.NOTES_DIR}")
        return 1
    try:
        search = rt.build_retriever(notes, args.mode)
    except Exception as err:
        print(f"Could not start '{args.mode}' search: {type(err).__name__}: {err}")
        print("For embeddings, run:  pip install sentence-transformers  (or use --mode tfidf)")
        return 1
    server = make_server("127.0.0.1", args.port, notes, search)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Outlook Fix Assistant GUI running at {url}  (search: {search.name})")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
