"""Provider-free exact-ID queue projection tests, separate from cursor verdicts."""

import json
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from toad.queue_view import QueueReducer, parse_event, parse_scope

PATH = Path(__file__).parent / "fixtures/acp_exact_id_queue_v1.json"
F = json.loads(PATH.read_text())


def load(reducer, value=None):
    value = value or F["trustedLoad"]
    session = value["queueBinding"]["sessionId"]
    return reducer.bind(
        value["queueBinding"], value["queueState"], session, reducer.begin(session)
    )


class QueueViewTests(unittest.TestCase):
    def test_fixture_hash_and_sequence(self):
        self.assertEqual(
            sha256(PATH.read_bytes()).hexdigest(),
            "cffc19837f6f013fba561e7a77197a8aab944b6fc2e617522dcb1bfe19c8f2de",
        )
        reducer = QueueReducer()
        self.assertEqual(load(reducer)[0], "bind")
        self.assertEqual(len(reducer.projection.items), 2)
        echoes = []
        for event in F["updates"]:
            decision, started = reducer.callback(event["kind"], event["value"], "beta")
            self.assertEqual(decision, event["decision"])
            echoes.extend(started)
        self.assertEqual(len(echoes), 1)
        self.assertEqual(echoes[0].input_id, "a" * 32)
        self.assertEqual(reducer.revision, 5)
        self.assertEqual(reducer.projection.items, ())
        self.assertEqual(
            [row.input_id for row in reducer.projection.restored], ["b" * 32]
        )
        load(reducer, F["nextTrustedLoad"])
        self.assertEqual(
            reducer.callback("queueState", F["lateOldUpdate"]["value"], "beta")[0],
            "reject_stale_scope",
        )
        self.assertEqual(reducer.projection.items + reducer.projection.restored, ())

    def test_prebind_floor_survives_superseded_uncertainty(self):
        for initially_bound in (False, True):
            for poison in ("none", "malformed", "overflow"):
                with self.subTest(initially_bound=initially_bound, poison=poison):
                    reducer = QueueReducer()
                    if initially_bound:
                        load(reducer)
                    pending = reducer.begin("beta")
                    reducer.callback(
                        "queueState",
                        F["prebindRace"]["callbackBeforeTrustedResult"],
                        "beta",
                    )
                    if poison == "malformed":
                        reducer.callback("queueState", {}, "beta")
                    if poison == "overflow":
                        for _ in range(32):
                            reducer.callback(
                                "queueState", F["trustedLoad"]["queueState"], "beta"
                            )
                    load(reducer, F["prebindRace"]["delayedTrustedLoad"])
                    self.assertEqual(reducer.projection.status, "unavailable")
                    self.assertEqual(
                        reducer.bind(
                            F["trustedLoad"]["queueBinding"],
                            F["trustedLoad"]["queueState"],
                            "beta",
                            pending,
                        )[0],
                        "reject_old_request",
                    )
                    load(reducer, F["prebindRace"]["subsequentTrustedLoad"])
                    self.assertEqual(reducer.projection.status, "available")
                    self.assertEqual(reducer.scope.owner_epoch, 4)

    def test_null_poison_is_not_empty_and_requires_subsequent_request(self):
        reducer = QueueReducer()
        pending = reducer.begin("beta")
        reducer.callback("queueState", None, "beta")
        reducer.bind(
            F["trustedLoad"]["queueBinding"],
            F["trustedLoad"]["queueState"],
            "beta",
            pending,
        )
        self.assertEqual(reducer.projection.status, "unavailable")
        self.assertIsNone(reducer.scope)
        load(reducer)
        self.assertEqual(len(reducer.projection.items), 2)
        self.assertEqual(reducer.projection.status, "available")
        reducer.callback("queueState", None, "beta")
        reducer.callback("queueState", F["trustedLoad"]["queueState"], "beta")
        self.assertEqual(reducer.projection.status, "unavailable")
        load(reducer)
        self.assertEqual(reducer.projection.status, "available")

    def test_exact_start_dedup_and_snapshot_resurrection(self):
        reducer = QueueReducer()
        load(reducer)
        started = F["updates"][0]["value"]
        self.assertEqual(len(reducer.callback("inputStarted", started, "beta")[1]), 1)
        self.assertEqual([row.input_id for row in reducer.projection.items], ["b" * 32])
        self.assertFalse(reducer.callback("inputStarted", started, "beta")[1])
        self.assertFalse(
            reducer.callback("inputStarted", {**started, "revision": 4}, "beta")[1]
        )
        # Same-owner reconnect cannot forget its exact-ID tombstone.
        rebinding = deepcopy(F["trustedLoad"])
        rebinding["queueState"]["revision"] = 8
        self.assertEqual(load(reducer, rebinding)[0], "reject_resurrection")
        self.assertEqual(reducer.projection.status, "unavailable")
        rebinding["queueState"]["items"] = [rebinding["queueState"]["items"][1]]
        self.assertEqual(load(reducer, rebinding)[0], "bind")
        self.assertFalse(
            reducer.callback("inputStarted", {**started, "revision": 9}, "beta")[1]
        )

    def test_equal_revision_conflict_and_foreign_scope(self):
        reducer = QueueReducer()
        load(reducer)
        original = reducer.projection
        state = deepcopy(F["trustedLoad"]["queueState"])
        state["items"] = []
        self.assertEqual(
            reducer.callback("queueState", state, "beta")[0],
            "reject_equal_revision_conflict",
        )
        self.assertEqual(reducer.projection, original)
        state["scope"]["ownerThread"] = "foreign"
        state["revision"] = 20
        self.assertEqual(
            reducer.callback("queueState", state, "beta")[0], "reject_foreign_scope"
        )
        self.assertEqual(
            reducer.callback("queueState", None, "foreign")[0], "reject_foreign_session"
        )
        self.assertEqual(reducer.projection, original)

    def test_newer_owner_quarantine_then_rebase(self):
        reducer = QueueReducer()
        load(reducer)
        newer = F["prebindRace"]["callbackBeforeTrustedResult"]
        self.assertEqual(
            reducer.callback("queueState", newer, "beta")[0], "quarantine_scope"
        )
        self.assertEqual(reducer.scope.owner_epoch, 2)
        old = {**F["trustedLoad"]["queueState"], "revision": 100}
        self.assertEqual(
            reducer.callback("queueState", old, "beta")[0], "reject_quarantined"
        )
        load(reducer)
        self.assertEqual(reducer.projection.status, "unavailable")
        load(reducer, F["nextTrustedLoad"])
        self.assertEqual(reducer.projection.status, "available")
        self.assertEqual(
            reducer.callback("inputStarted", F["updates"][0]["value"], "beta")[0],
            "reject_stale_scope",
        )

    def test_ambiguity_and_retired_request(self):
        reducer = QueueReducer()
        load(reducer)
        for key in ("ownerCreatedAt", "admissionGeneration"):
            event = deepcopy(F["trustedLoad"]["queueState"])
            event["scope"][key] += 1
            reducer.callback("queueState", event, "beta")
            self.assertEqual(reducer.projection.status, "unavailable")
            load(reducer)
            self.assertEqual(reducer.projection.status, "available")
        token = reducer.begin("beta")
        reducer.invalidate()
        self.assertEqual(
            reducer.bind(
                F["trustedLoad"]["queueBinding"],
                F["trustedLoad"]["queueState"],
                "beta",
                token,
            )[0],
            "reject_old_request",
        )
        self.assertEqual(reducer.projection.status, "unavailable")

    def test_unknown_new_attachment_never_applies_foreign_buffered_content(self):
        for kind in ("queueState", "inputStarted"):
            reducer = QueueReducer()
            token = reducer.begin(None)
            value = deepcopy(
                F["trustedLoad"]["queueState"]
                if kind == "queueState"
                else F["updates"][0]["value"]
            )
            value["scope"]["sessionId"] = "unrelated-attachment"
            value["revision"] = 20
            self.assertEqual(
                reducer.callback(kind, value, "unrelated-attachment")[0], "buffer"
            )
            decision, echoes = reducer.bind(
                F["trustedLoad"]["queueBinding"],
                F["trustedLoad"]["queueState"],
                "beta",
                token,
            )
            self.assertEqual(decision, "bind")
            self.assertFalse(echoes)
            self.assertEqual(reducer.revision, 2)
            self.assertEqual(
                [row.input_id for row in reducer.projection.items], ["a" * 32, "b" * 32]
            )
        # Negative evidence still crosses attachment aliases of this owner.
        reducer = QueueReducer()
        token = reducer.begin(None)
        value = deepcopy(F["nextTrustedLoad"]["queueState"])
        value["scope"]["sessionId"] = "unrelated-attachment"
        reducer.callback("queueState", value, "unrelated-attachment")
        self.assertEqual(
            reducer.bind(
                F["trustedLoad"]["queueBinding"],
                F["trustedLoad"]["queueState"],
                "beta",
                token,
            )[0],
            "reject_binding_floor",
        )
        self.assertEqual(reducer.projection.status, "unavailable")

    def test_prebind_starts_in_revision_order_once(self):
        reducer = QueueReducer()
        token = reducer.begin("beta")
        for index in (1, 0):
            event = F["updates"][index]
            reducer.callback(event["kind"], event["value"], "beta")
        _, echoes = reducer.bind(
            F["trustedLoad"]["queueBinding"],
            F["trustedLoad"]["queueState"],
            "beta",
            token,
        )
        self.assertEqual(len(echoes), 1)
        self.assertEqual(reducer.revision, 4)
        self.assertEqual(len(reducer.projection.items), 1)

    def test_distinct_floor_saturation_stays_unavailable(self):
        reducer = QueueReducer()
        reducer.begin("beta")
        for index in range(33):
            state = deepcopy(F["trustedLoad"]["queueState"])
            state["scope"]["ownerThread"] = f"owner-{index}"
            reducer.callback("queueState", state, "beta")
        self.assertEqual(len(reducer._floors), 32)
        self.assertEqual(load(reducer)[0], "reject_evidence_lost")
        self.assertEqual(reducer.projection.status, "unavailable")

    def test_alias_cannot_erase_epoch_or_snapshot_revision_fences(self):
        for case in ("epoch", "revision"):
            with self.subTest(case=case):
                reducer = QueueReducer()
                load(reducer)
                event = (
                    F["nextTrustedLoad"]["queueState"]
                    if case == "epoch"
                    else F["updates"][1]["value"]
                )
                reducer.callback("queueState", event, "beta")
                alias = deepcopy(F["trustedLoad"])
                alias["queueBinding"]["sessionId"] = "alias"
                alias["queueState"]["scope"]["sessionId"] = "alias"
                self.assertEqual(
                    load(reducer, alias)[0],
                    (
                        "reject_binding_floor"
                        if case == "epoch"
                        else "reject_stale_binding"
                    ),
                )
                self.assertEqual(reducer.projection.status, "unavailable")
                # A fresh, equal semantic snapshot may reattach via an alias;
                # the transport session field alone is not a contradiction.
                alias["queueState"] = deepcopy(event)
                alias["queueState"]["scope"]["sessionId"] = "alias"
                alias["queueBinding"] = {"version": 1, **alias["queueState"]["scope"]}
                self.assertEqual(load(reducer, alias)[0], "bind")
                self.assertEqual(reducer.revision, event["revision"])
                self.assertEqual(
                    [row.input_id for row in reducer.projection.items],
                    [] if case == "epoch" else ["b" * 32],
                )
                self.assertEqual(
                    reducer.callback("queueState", event, "beta")[0],
                    "reject_foreign_session",
                )
                # Equal revision with different membership is still rejected.
                alias["queueState"]["items"] = deepcopy(
                    F["trustedLoad"]["queueState"]["items"]
                )
                self.assertEqual(load(reducer, alias)[0], "reject_stale_binding")

    def test_alias_load_preserves_owner_ids_and_tombstones(self):
        reducer = QueueReducer()
        load(reducer)
        reducer.callback("inputStarted", F["updates"][0]["value"], "beta")
        alias = deepcopy(F["trustedLoad"])
        alias["queueBinding"]["sessionId"] = "alias"
        alias["queueState"]["scope"]["sessionId"] = "alias"
        alias["queueState"]["revision"] = 4
        alias["queueState"]["items"] = alias["queueState"]["items"][1:]
        token = reducer.begin("alias")
        self.assertEqual(
            reducer.bind(alias["queueBinding"], alias["queueState"], "alias", token)[0],
            "bind",
        )
        self.assertEqual(reducer.scope.owner_thread, "beta")
        self.assertEqual(reducer.projection.items[0].input_id, "b" * 32)
        started = deepcopy(F["updates"][0]["value"])
        started["scope"]["sessionId"] = "alias"
        started["revision"] = 5
        self.assertEqual(
            reducer.callback("inputStarted", started, "alias")[0],
            "reject_duplicate_start",
        )
        self.assertEqual(
            reducer.callback("queueState", F["trustedLoad"]["queueState"], "beta")[0],
            "reject_foreign_session",
        )

    def test_quarantined_callbacks_still_raise_the_epoch_floor(self):
        reducer = QueueReducer()
        load(reducer)
        reducer.callback("queueState", F["nextTrustedLoad"]["queueState"], "beta")
        latest = deepcopy(F["nextTrustedLoad"])
        for scope in (latest["queueBinding"], latest["queueState"]["scope"]):
            scope["ownerEpoch"] = scope["admissionGeneration"] = 6
        latest["queueState"]["revision"] = 8
        reducer.callback("queueState", latest["queueState"], "beta")
        self.assertEqual(load(reducer, F["nextTrustedLoad"])[0], "reject_binding_floor")
        self.assertEqual(load(reducer, latest)[0], "bind")
        self.assertEqual(reducer.scope.owner_epoch, 6)

    def test_parser_retains_only_bounded_immutable_semantics(self):
        state = deepcopy(F["trustedLoad"]["queueState"])
        circular = []
        circular.append(circular)
        state["extra"] = circular
        event = parse_event("queueState", state)
        self.assertIsNotNone(event)
        state["items"][0]["text"] = "changed after admission"
        self.assertEqual(event.items[0].text, "same text")
        self.assertEqual(
            event.digest,
            parse_event("queueState", F["trustedLoad"]["queueState"]).digest,
        )

    def test_tombstone_exhaustion_requires_a_fresh_attachment(self):
        from toad.queue_view import MAX_TOMBSTONES

        reducer = QueueReducer()
        load(reducer)
        for index in range(MAX_TOMBSTONES + 1):
            event = {
                **F["updates"][0]["value"],
                "inputId": str(index),
                "revision": index + 3,
                "text": None,
            }
            decision, echoes = reducer.callback("inputStarted", event, "beta")
            self.assertFalse(echoes)
        self.assertEqual(decision, "reject_tombstone_bound")
        self.assertEqual(len(reducer._retired), MAX_TOMBSTONES)
        self.assertEqual(load(reducer, F["nextTrustedLoad"])[0], "reject_evidence_lost")
        self.assertEqual(reducer.projection.status, "unavailable")
        fresh = QueueReducer()
        self.assertEqual(load(fresh, F["nextTrustedLoad"])[0], "bind")

    def test_utf8_bounds_duplicate_ids_and_malformed(self):
        original = F["trustedLoad"]["queueState"]
        for text in ("\ud800", "x" * 4097, "🐸" * 1025):
            state = deepcopy(original)
            state["items"][0]["text"] = text
            self.assertIsNone(parse_event("queueState", state))
        state = deepcopy(original)
        state["items"] = [
            {"inputId": str(index), "text": "🐸" * 1024} for index in range(16)
        ]
        self.assertIsNotNone(parse_event("queueState", state))
        state["items"].append({"inputId": "last", "text": "x"})
        self.assertIsNone(parse_event("queueState", state))
        for bad in (
            None,
            {},
            {**original, "revision": True},
            {**original, "version": True},
            {**original, "items": original["items"] * 17},
            {**original, "restored": original["items"]},
        ):
            self.assertIsNone(parse_event("queueState", bad))
        for field, value in (
            ("ownerEpoch", True),
            ("admissionGeneration", 0),
            ("ownerCreatedAt", float("nan")),
            ("ownerThread", ""),
        ):
            scope = {**original["scope"], field: value}
            self.assertIsNone(parse_scope(scope))


if __name__ == "__main__":
    unittest.main()
