import json
import threading
import unittest
import urllib.request
from pathlib import Path

import agent
import retriever as rt
import webapp

ROOT = Path(__file__).parent
NOTES = agent.load_notes(ROOT / "notes")
SEARCH = rt.TfidfRetriever(NOTES)
SCENES = json.loads((ROOT / "web" / "scenes.json").read_text(encoding="utf-8"))


def new_session():
    return webapp.Session(NOTES, SEARCH)


def run_to_decision(session, problem, answer="yes"):
    reply = session.handle(problem)
    guard = 0
    while session.state == "asking" and guard < 20:
        reply = session.handle(answer)
        guard += 1
    return reply


class TestHelpers(unittest.TestCase):
    def test_parse_answer(self):
        self.assertEqual(webapp.parse_answer("Yes"), "yes")
        self.assertEqual(webapp.parse_answer("yeah it does"), "yes")
        self.assertEqual(webapp.parse_answer("No, it doesn't"), "no")
        self.assertEqual(webapp.parse_answer("Not sure"), "skip")
        self.assertEqual(webapp.parse_answer("I don't know"), "skip")
        self.assertEqual(webapp.parse_answer("banana"), None)

    def test_second_person(self):
        sp = webapp.second_person
        self.assertEqual(sp("Was the user's mailbox recently moved?"), "Was your mailbox recently moved?")
        self.assertEqual(sp("Does the user have internet?"), "Do you have internet?")
        self.assertEqual(sp("Is the user using the cached copy?"), "Are you using the cached copy?")
        self.assertEqual(sp("Can the user sign in?"), "Can you sign in?")
        self.assertEqual(sp("mail the user knows exists"), "mail you know exists")


class TestScenesInSync(unittest.TestCase):
    def test_every_note_has_a_scene_with_matching_step_count(self):
        for note in NOTES:
            with self.subTest(note=note["file"]):
                scene = SCENES.get(note["file"])
                self.assertIsNotNone(scene, "add a scene for this note in web/scenes.json")
                self.assertEqual(len(scene["steps"]), len(note["steps"]))
                self.assertIn("outlook", scene["initial"])

    def test_scene_states_are_known(self):
        known = {"closed", "broken", "loading", "ok", "safe", "freezing", "password",
                 "disconnected", "connecting", "nosearch", "search_ok"}
        for name, scene in SCENES.items():
            if name.startswith("_"):
                continue
            states = [scene["initial"]["outlook"]]
            for st in scene["steps"]:
                states += [st.get("outlook"), st.get("outlook_after")]
            for s in states:
                if s is not None:
                    self.assertIn(s, known, f"{name}: {s}")


class TestSessionFlow(unittest.TestCase):
    def test_greeting(self):
        reply = new_session().reset()
        self.assertEqual(reply["state"], "problem")
        self.assertIsNone(reply["scene"])
        self.assertEqual(reply["brain"]["candidates"], [])

    def test_unknown_problem_stays_in_problem_state(self):
        s = new_session()
        reply = s.handle("my printer is out of toner")
        self.assertEqual(reply["state"], "problem")
        self.assertIn("couldn't match", reply["messages"][0]["text"])

    def test_problem_leads_to_questions_in_second_person(self):
        s = new_session()
        reply = s.handle("A user can't open Outlook after the cloud migration")
        self.assertEqual(reply["state"], "asking")
        self.assertEqual(reply["quick"], ["Yes", "No", "Not sure"])
        question = reply["messages"][-1]
        self.assertEqual(question["kind"], "question")
        self.assertNotIn("the user", question["text"].lower())
        self.assertEqual(reply["scene"]["step"], -1)
        self.assertTrue(reply["scene"]["file"].startswith("01"))

    def test_bad_answer_repeats_question(self):
        s = new_session()
        s.handle("Outlook keeps freezing and crashing")
        reply = s.handle("banana")
        self.assertEqual(reply["state"], "asking")
        self.assertEqual(reply["messages"][0]["kind"], "note")

    def test_all_yes_decides_first_candidate_and_stops_early(self):
        s = new_session()
        run_to_decision(s, "A user can't open Outlook after the cloud migration")
        self.assertEqual(s.state, "confirm")
        self.assertTrue(s.decided["file"].startswith("01"))
        self.assertEqual(len(s.cands[0]["answers"]), 3)
        self.assertEqual(s.cands[1]["adjusted"], None)  # second candidate never asked

    def test_full_happy_path_for_every_note(self):
        problems = {
            "01": "A user can't open Outlook after the cloud migration",
            "02": "Outlook keeps freezing and crashing when it starts",
            "03": "Outlook keeps asking for my password",
            "04": "Outlook says disconnected and I'm not getting new mail",
            "05": "My emails are missing when I search",
        }
        for prefix, problem in problems.items():
            with self.subTest(note=prefix):
                s = new_session()
                run_to_decision(s, problem)
                self.assertTrue(s.decided["file"].startswith(prefix), s.decided["file"])
                reply = s.handle("Show me the fix")
                total = len(s.decided["steps"])
                self.assertEqual(reply["state"], "fixing")
                self.assertEqual(reply["scene"]["step"], 0)
                for i in range(1, total):
                    reply = s.handle("done")
                    self.assertEqual(reply["scene"]["step"], i)
                    self.assertEqual(reply["messages"][0]["step"], i + 1)
                reply = s.handle("done")
                self.assertEqual(reply["state"], "done")
                reply = s.handle("Yes, it works")
                self.assertEqual(reply["state"], "closed")
                self.assertEqual(reply["messages"][0]["kind"], "resolved")

    def test_warnings_are_shown_before_the_fix(self):
        s = new_session()
        reply = run_to_decision(s, "A user can't open Outlook after the cloud migration")
        kinds = [m["kind"] for m in reply["messages"]]
        self.assertIn("decision", kinds)
        self.assertIn("warning", kinds)

    def test_still_broken_tries_the_next_note_then_escalates(self):
        s = new_session()
        run_to_decision(s, "A user can't open Outlook after the cloud migration")
        first = s.decided["file"]
        s.handle("Show me the fix")
        for _ in s.decided["steps"]:
            s.handle("done")
        self.assertEqual(s.state, "done")
        reply = s.handle("Still broken")
        self.assertEqual(s.state, "confirm")
        self.assertNotEqual(s.decided["file"], first)
        s.handle("Show me the fix")
        for _ in s.decided["steps"]:
            s.handle("done")
        reply = s.handle("Still broken")
        self.assertEqual(reply["state"], "closed")
        self.assertIn("escalating", reply["messages"][0]["text"])

    def test_stop_during_fix_changes_nothing(self):
        s = new_session()
        run_to_decision(s, "A user can't open Outlook after the cloud migration")
        s.handle("Show me the fix")
        reply = s.handle("stop")
        self.assertEqual(reply["state"], "problem")
        self.assertIn("Nothing was changed", reply["messages"][0]["text"])

    def test_start_over_resets(self):
        s = new_session()
        run_to_decision(s, "Outlook keeps asking for my password")
        reply = s.handle("start over")
        self.assertEqual(reply["state"], "problem")
        self.assertEqual(reply["brain"]["candidates"], [])

    def test_no_answers_move_on_to_next_candidate(self):
        s = new_session()
        s.handle("Outlook keeps freezing and crashing when it starts")
        first = s.cands[0]["note"]["file"]
        for _ in s.cands[0]["note"]["questions"]:
            s.handle("no")
        self.assertEqual(s.cidx, 1)
        self.assertEqual(s.state, "asking")
        for _ in s.cands[1]["note"]["questions"]:
            s.handle("yes")
        self.assertEqual(s.state, "confirm")
        self.assertNotEqual(s.decided["file"], first)


class TestHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = webapp.make_server("127.0.0.1", 0, NOTES, SEARCH)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return r.status, r.read()

    def post(self, path, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", json.dumps(payload).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_serves_page_and_scenes(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Outlook Fix Assistant", body)
        status, body = self.get("/scenes.json")
        self.assertIn("01-profile-corrupt-after-migration.md", json.loads(body))

    def test_unknown_path_is_404_and_no_file_traversal(self):
        for path in ("/nope", "/../agent.py", "/notes/01-profile-corrupt-after-migration.md"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.get(path)
            self.assertEqual(ctx.exception.code, 404)

    def test_chat_round_trip_keeps_session_state(self):
        sid = "test-session-1"
        self.post("/api/reset", {"sid": sid})
        first = self.post("/api/chat", {"sid": sid, "text": "Outlook keeps asking for my password"})
        self.assertEqual(first["state"], "asking")
        second = self.post("/api/chat", {"sid": sid, "text": "yes"})
        self.assertEqual(second["brain"]["candidates"][0]["questions"][0]["answer"], "yes")

    def test_sessions_are_isolated(self):
        self.post("/api/chat", {"sid": "a", "text": ""})
        self.post("/api/chat", {"sid": "a", "text": "Outlook keeps asking for my password"})
        other = self.post("/api/chat", {"sid": "b", "text": "yes"})
        self.assertEqual(other["state"], "problem")


if __name__ == "__main__":
    unittest.main()
