"""Re-timing imported lines against the words heard in their audio."""

from limitful.importer import import_limitless
from limitful.store import Store, locate_lines

from test_importer import T0, make_zip, quiet


def heard(*phrases):
    """Words with times: each phrase is (second it starts, text), three words a second."""
    return [(start + i / 3, word) for start, text in phrases for i, word in enumerate(text.split())]


def test_lines_are_found_by_their_words():
    words = heard((2.0, "it helps with bone density and mood"), (9.2, "does it take a long time"),
                  (30.0, "it helps with bone density and mood"))
    lines = [(3.0, "It helps with bone density, and mood."),   # claimed a second late
             (10.0, "Does it take a long time?"),
             (11.0, "Mhm."),                                    # too short to place
             (50.0, "Something that was never said at all")]
    assert locate_lines(lines, words) == [2.0, 9.2, None, None]
    # The same words half a minute later are outside the window, so not confused with these.
    assert locate_lines([(31.0, "it helps with bone density and mood")], words) == [30.0]
    assert locate_lines([(3.0, "anything long enough to try")], []) == [None]


def test_a_repeated_phrase_is_placed_at_the_nearest_occurrence():
    # "yeah I think so too" is said three times; the line claims 21 s, so it is the
    # one at 20 s (lines run about a second late), not the first one heard.
    words = heard((14.0, "yeah I think so too"), (20.0, "yeah I think so too"), (26.0, "yeah I think so too"))
    assert locate_lines([(21.0, "Yeah, I think so too.")], words) == [20.0]
    assert locate_lines([(26.8, "Yeah, I think so too.")], words) == [26.0]


def test_retime_moves_lines_headings_and_the_conversation(tmp_path):
    store = Store(tmp_path / "data")
    import_limitless(store, make_zip(tmp_path / "export.zip"), log=quiet)
    (path, file_start, _d), = [r for r in store.pending_retime() if "13h55m50s" in r[0]]
    before = store.db.execute("SELECT text, start_ms FROM utterances ORDER BY start_ms").fetchall()
    assert [t - file_start for _x, t in before] == [8000, 18000, 68000]

    # In the audio the first line starts 1.2 s earlier than claimed, the third 0.5 s earlier.
    words = heard((6.8, "it helps with bone density"), (67.5, "does it take a long time"))
    assert store.retime_recording(path, words) == (2, 3)
    after = store.db.execute(
        "SELECT text, start_ms - ?, orig_start_ms - ?, end_ms - start_ms FROM utterances ORDER BY start_ms",
        (file_start, file_start)).fetchall()
    assert after == [
        ("It helps with bone density.", 6800, 8000, 10000),
        ("Mhm.", 16800, 18000, 1),                       # moved with its neighbour, 1.2 s earlier
        ("Does it take [a long] time?", 67500, 68000, 4000)]

    (talk,) = store.conversations(T0 - 60_000, T0 + 60_000)
    assert talk["start"] == file_start + 6800 and talk["lines"] == 3
    assert [s["start"] - file_start for s in talk["sections"]] == [6800, 67500, 67500]
    assert path not in [r[0] for r in store.pending_retime()]

    # Running it again starts from the original timestamps, so nothing drifts.
    store.db.execute("UPDATE segments SET retimed = NULL")
    assert store.retime_recording(path, words) == (2, 3)
    assert store.db.execute("SELECT start_ms - ? FROM utterances ORDER BY start_ms", (file_start,)).fetchall() == [
        (6800,), (16800,), (67500,)]

    # Undo puts lines, headings and the conversation back where the import had them.
    assert store.undo_retime() == 3
    assert [t - file_start for (t,) in store.db.execute("SELECT start_ms FROM utterances ORDER BY start_ms")] == [
        8000, 18000, 68000]
    assert store.db.execute("SELECT COUNT(*) FROM utterances WHERE orig_start_ms IS NOT NULL").fetchone() == (0,)
    (talk,) = store.conversations(T0 - 60_000, T0 + 60_000)
    assert talk["start"] == file_start + 8000
    assert [s["start"] - file_start for s in talk["sections"]] == [8000, 68000, 68000]
    assert len(store.pending_retime()) == 1 and store.undo_retime() == 0
    store.close()
