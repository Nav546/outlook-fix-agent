import contextlib
import io
import unittest
from pathlib import Path

import agent
import retriever as rt

NOTES = agent.load_notes(Path(__file__).parent / "notes")


def fake_input(answers):
    it = iter(answers)
    return lambda prompt="": next(it)


class TestNotes(unittest.TestCase):
    def test_all_notes_parse(self):
        self.assertEqual(len(NOTES), 5)
        for n in NOTES:
            self.assertTrue(n["title"], n["file"])
            self.assertTrue(n["keywords"], n["file"])
            self.assertTrue(n["questions"], n["file"])
            self.assertTrue(n["steps"], n["file"])


class TestRetrieval(unittest.TestCase):
    def best(self, text):
        return agent.retrieve(NOTES, text)[0][1]["file"]

    def test_migration_profile(self):
        self.assertTrue(self.best("user cannot open outlook after migration to the cloud").startswith("01"))

    def test_addin_crash(self):
        self.assertTrue(self.best("outlook keeps freezing and crashing, maybe an add-in").startswith("02"))

    def test_password_loop(self):
        self.assertTrue(self.best("outlook keeps asking for password").startswith("03"))

    def test_disconnected(self):
        self.assertTrue(self.best("outlook says disconnected and not syncing").startswith("04"))

    def test_search(self):
        self.assertTrue(self.best("search not working, cannot find email").startswith("05"))

    def test_no_match(self):
        self.assertEqual(agent.retrieve(NOTES, "printer is out of toner"), [])


class TestDiagnose(unittest.TestCase):
    def test_yes_answers_win(self):
        cands = agent.retrieve(NOTES, "outlook problem")
        out = []
        # Say yes to everything for the first candidate, no to the rest.
        first_q = len(cands[0][1]["questions"])
        answers = ["y"] * first_q + ["n"] * 20
        best = agent.diagnose(cands, fake_input(answers), out.append)
        self.assertEqual(best["file"], cands[0][1]["file"])


class TestEarlyStop(unittest.TestCase):
    def test_all_yes_skips_second_candidate(self):
        cands = agent.retrieve(NOTES, "outlook is stuck on the loading screen")
        self.assertEqual(len(cands), 2)
        n_first = len(cands[0][1]["questions"])
        # Only n_first answers exist: asking one more would raise StopIteration.
        best = agent.diagnose(cands, fake_input(["y"] * n_first), lambda *_: None)
        self.assertEqual(best["file"], cands[0][1]["file"])


class TestWalkThrough(unittest.TestCase):
    def test_walks_all_steps(self):
        out = []
        note = NOTES[0]
        done = agent.walk_through(note, fake_input(["y"] * len(note["steps"])), out.append)
        self.assertTrue(done)
        self.assertTrue(any("will not change anything" in line for line in out))

    def test_quit_stops(self):
        out = []
        done = agent.walk_through(NOTES[0], fake_input(["q"]), out.append)
        self.assertFalse(done)

    def test_profile_note_mentions_mail_32bit(self):
        text = " ".join(NOTES[0]["steps"])
        self.assertIn("32-bit", text)


class TestVectorSearch(unittest.TestCase):
    """Wordings the old keyword matcher missed or tied on."""

    def best(self, text):
        return agent.retrieve(NOTES, text)[0][1]["file"][:2]

    def test_paraphrases_find_the_right_note(self):
        cases = {
            "outlook is stuck on the loading screen": "01",
            "outlook keeps closing by itself": "02",
            "it asks for my password again and again": "03",
            "outlook says it is offline": "04",
            "my emails are missing when I look for them": "05",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.best(text), expected)

    def test_old_keyword_matcher_misses_what_vectors_find(self):
        text = "my emails are missing when I look for them"
        self.assertEqual(agent.keyword_retrieve(NOTES, text), [])
        self.assertTrue(self.best(text).startswith("05"))

    def test_unrelated_text_matches_nothing(self):
        for text in ("printer is out of toner", "I want a coffee", ""):
            with self.subTest(text=text):
                self.assertEqual(agent.retrieve(NOTES, text), [])


class TestRetrieverPieces(unittest.TestCase):
    def test_stemmer_groups_word_forms(self):
        self.assertEqual(rt.stem("crashes"), rt.stem("crashing"))
        self.assertEqual(rt.stem("closing"), rt.stem("close"))

    def test_cosine_basics(self):
        self.assertAlmostEqual(rt.cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(rt.cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(rt.cosine([0, 0], [1, 1]), 0.0)

    def test_embedding_retriever_plumbing_with_fake_encoder(self):
        # A fake "model": each text becomes a count of a few chosen words.
        words = ["profile", "password", "search", "disconnected", "add-in"]

        def fake_encode(texts):
            return [[t.lower().count(w) for w in words] for t in texts]

        r = rt.EmbeddingRetriever(NOTES, fake_encode)
        top = r.search("password password")[0][1]["file"]
        self.assertTrue(top.startswith("03"))

    def test_auto_mode_falls_back_to_tfidf(self):
        def broken_encoder():
            raise ImportError("sentence-transformers not installed")

        original = rt.sentence_transformer_encoder
        rt.sentence_transformer_encoder = broken_encoder
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                r = rt.build_retriever(NOTES, "auto")
        finally:
            rt.sentence_transformer_encoder = original
        self.assertEqual(r.name, "tfidf")

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            rt.build_retriever(NOTES, "magic")


if __name__ == "__main__":
    unittest.main()
