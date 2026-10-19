"""An unchanged coordination log gives the same snapshot on every read, with every unread message counted."""

from agent_comms.comms import wire


def test_unread_count_is_stable_across_repeated_reads_of_a_long_log(tmp_path):
    comms = wire(tmp_path)
    for name in ("sender", "reader"):
        comms.registry.declare(comms.registry.new_thread(name, frozenset({"team"}), str(tmp_path)))
    count = 100
    for _ in range(count):
        comms.messaging.send("sender", "#team", "A historical coordination update. " * 10)
    first = comms.views.coordination_snapshot("reader")
    assert first.unread["#team"] == count
    for _ in range(100):
        assert comms.views.coordination_snapshot("reader") == first
