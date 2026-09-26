"""Provider-free cursor boundary tests; no native process or wire mutations."""

import json
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from toad.private_native_cursor import LABELS, TOOLTIP, CursorReducer, parse_cursor

FIXTURE_PATH = Path(__file__).parent / "fixtures/private_native_cursor_v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text())


class CursorParserTests(unittest.TestCase):
    def test_frozen_backend_fixture(self):
        self.assertEqual(
            sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
            "321b777a59b4d84cec32aea05fe81def4a5d2942df7a5d8444d8924d1f48a593",
        )
        values = [
            FIXTURE["trustedLoad"]["cursor"],
            FIXTURE["nextTrustedLoad"]["cursor"],
            FIXTURE["coverageOnlyExample"],
            *(
                update["cursor"]
                for update in FIXTURE["updates"] + FIXTURE["afterNextLoad"]
            ),
        ]
        for value in values:
            with self.subTest(status=value["status"], revision=value["revision"]):
                parsed = parse_cursor(value)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed.status, value["status"])
                self.assertNotIn("recipient-opaque", repr(parsed))
                self.assertNotIn("native-session-opaque", repr(parsed))
                self.assertNotIn("bbbbbbbb", repr(parsed))

    def test_malformed_envelopes(self):
        base = FIXTURE["trustedLoad"]["cursor"]
        for key, invalid in [
            ("version", True),
            ("version", 2),
            ("revision", False),
            ("revision", 0),
            ("revision", -1),
            ("revision", 1.0),
            ("revision", 2**64),
            ("status", "accepted"),
            ("status", []),
            ("scope", None),
            ("scope", []),
            ("input_id", None),
            ("wire_root_id", "x" * 32),
            ("owner_admission_epoch", True),
            ("owner_admission_epoch", 4),
            ("owner_generation", False),
            ("covered_seq", 0),
            ("injected_seq", 0),
            ("injected_seq", True),
            ("request_generation", False),
            ("claim_id", ""),
            ("recipient_lookup", "x" * 20_000),
        ]:
            with self.subTest(key=key, invalid=invalid):
                self.assertIsNone(parse_cursor({**base, key: invalid}))
        for key, invalid in [
            ("ownerEpoch", True),
            ("ownerEpoch", 0),
            ("ownerPid", False),
            ("ownerPid", -1),
            ("ownerCreatedAt", True),
            ("ownerCreatedAt", float("nan")),
            ("ownerCreatedAt", float("inf")),
            ("ownerCreatedAt", 10**1000),
            ("sessionId", ""),
            ("wireRootId", "z" * 32),
            ("ownerThread", []),
        ]:
            with self.subTest(scope_key=key):
                value = deepcopy(base)
                value["scope"][key] = invalid
                self.assertIsNone(parse_cursor(value))
        for value in [None, {}, [], "", {"version": 1}]:
            self.assertIsNone(parse_cursor(value))
        for key in base:
            value = deepcopy(base)
            del value[key]
            with self.subTest(missing=key):
                self.assertIsNone(parse_cursor(value))

    def test_coverage_is_not_injection(self):
        base = FIXTURE["coverageOnlyExample"]
        self.assertIsNotNone(parse_cursor(base))
        for key, value in [
            ("injected_seq", 1),
            ("input_id", "a" * 32),
            ("claim_id", "claim"),
            ("session_id", "native"),
        ]:
            self.assertIsNone(parse_cursor({**base, key: value}))

    def test_null_scope_never_proof(self):
        for status in LABELS:
            parsed = parse_cursor(
                {"version": 1, "scope": None, "revision": 1, "status": status}
            )
            self.assertEqual(parsed is not None, status == "unavailable")

    def test_presentation_is_constant(self):
        self.assertEqual(
            LABELS["proven"], "Native history: selected source proof available"
        )
        self.assertIn("no injected input", LABELS["coverage_only"])
        self.assertIn("not input acceptance, consumption, completion or ACK", TOOLTIP)


class CursorReducerTests(unittest.TestCase):
    def load(self, reducer, value):
        token = reducer.begin(value["scope"]["sessionId"])
        return reducer.bind(value, value["scope"]["sessionId"], token)

    def test_frozen_postbind_sequence(self):
        reducer = CursorReducer()
        self.assertEqual(self.load(reducer, FIXTURE["trustedLoad"]["cursor"]), "bind")
        for update in FIXTURE["updates"]:
            self.assertEqual(
                reducer.callback(update["cursor"], "beta"), update["decision"]
            )
        self.assertEqual(reducer.status, "unavailable")
        self.assertTrue(reducer.quarantined)
        self.assertEqual(reducer.current.scope.owner_epoch, 2)
        self.assertEqual(
            self.load(reducer, FIXTURE["nextTrustedLoad"]["cursor"]), "bind"
        )
        for update in FIXTURE["afterNextLoad"]:
            self.assertEqual(
                reducer.callback(update["cursor"], "beta"), update["decision"]
            )
        self.assertEqual(reducer.status, "unavailable")
        self.assertEqual(reducer.current.revision, 5)
        self.assertEqual(reducer.current.scope.owner_epoch, 4)

    def test_frozen_prebind_sequence_and_floor(self):
        race = FIXTURE["prebindRace"]
        reducer = CursorReducer()
        token = reducer.begin("beta")
        reducer.callback(race["callbackBeforeTrustedResult"], "beta")
        reducer.bind(race["delayedTrustedLoad"], "beta", token)
        self.assertEqual(reducer.status, "unavailable")
        self.assertTrue(reducer.quarantined)
        self.assertEqual(reducer.floor.owner_epoch, 4)
        # Even another explicit but obsolete trusted result cannot erase floor.
        self.load(reducer, race["delayedTrustedLoad"])
        self.assertTrue(reducer.quarantined)
        self.load(reducer, race["subsequentTrustedLoad"])
        self.assertFalse(reducer.quarantined)
        self.assertEqual(reducer.status, "none")
        self.assertEqual(reducer.current.revision, 4)

    def test_overflow_and_malformed_require_new_request(self):
        value = FIXTURE["trustedLoad"]["cursor"]
        for failure in ("overflow", "malformed", "ambiguity", "null"):
            with self.subTest(failure=failure):
                reducer = CursorReducer()
                token = reducer.begin("beta")
                if failure == "overflow":
                    for _ in range(33):
                        reducer.callback(value, "beta")
                    self.assertEqual(len(reducer._buffer), 32)
                elif failure == "ambiguity":
                    bad = deepcopy(value)
                    bad["scope"]["ownerCreatedAt"] += 1
                    reducer.callback(bad, "beta")
                elif failure == "null":
                    reducer.callback(
                        {
                            "version": 1,
                            "scope": None,
                            "revision": 3,
                            "status": "unavailable",
                        },
                        "beta",
                    )
                else:
                    reducer.callback({}, "beta")
                reducer.bind(value, "beta", token)
                self.assertTrue(reducer.quarantined)
                self.assertEqual(reducer.status, "unavailable")
                self.load(reducer, value)
                self.assertFalse(reducer.quarantined)
                self.assertEqual(reducer.status, "proven")

    def test_revisions_foreign_ambiguity_and_retired_requests(self):
        value = FIXTURE["trustedLoad"]["cursor"]
        reducer = CursorReducer()
        self.load(reducer, value)
        self.assertEqual(reducer.callback(value, "beta"), "duplicate")
        self.assertEqual(
            reducer.callback({**value, "status": "none"}, "beta"),
            "reject_equal_revision_conflict",
        )
        self.assertEqual(
            reducer.callback({**value, "revision": 1}, "beta"), "reject_stale_revision"
        )
        for key, foreign in (("wireRootId", "f" * 32), ("ownerThread", "other")):
            bad = deepcopy(FIXTURE["nextTrustedLoad"]["cursor"])
            bad["scope"][key] = foreign
            self.assertEqual(reducer.callback(bad, "beta"), "reject_foreign_scope")
        self.assertEqual(reducer.callback({}, "foreign"), "reject_foreign_session")
        self.assertEqual(reducer.status, "proven")
        for key in ("ownerCreatedAt", "ownerPid"):
            self.load(reducer, value)
            bad = deepcopy(value)
            bad["scope"][key] += 1
            self.assertEqual(reducer.callback(bad, "beta"), "quarantine_ambiguous")
            self.assertEqual(reducer.status, "unavailable")
        old = reducer.begin("beta")
        new = reducer.begin("beta")
        reducer.bind(FIXTURE["nextTrustedLoad"]["cursor"], "beta", new)
        self.assertEqual(reducer.bind(value, "beta", old), "reject_old_request")
        self.assertEqual(reducer.status, "none")
        reducer.invalidate()
        reducer.callback(value, "beta")
        self.assertEqual(reducer.status, "unavailable")

    def test_canonical_null_prebind(self):
        case = FIXTURE["nullScopePrebind"]
        reducer = CursorReducer()
        token = reducer.begin("beta")
        reducer.callback(case["callbackBeforeTrustedResult"], "beta")
        reducer.bind(case["delayedTrustedLoad"], "beta", token)
        self.assertTrue(reducer.quarantined)
        self.assertEqual(reducer.status, "unavailable")
        self.assertIsNone(reducer.current)
        self.load(reducer, case["subsequentExplicitLoadInitiatedAfterCallback"])
        self.assertEqual(reducer.status, "none")
        self.assertFalse(reducer.quarantined)

    def test_distinct_scope_floor_saturation_requires_fresh_attachment(self):
        reducer = CursorReducer()
        token = reducer.begin("beta")
        case = FIXTURE["distinctKeySaturation"]
        start, end = case["foreignWireRootIdRangeInclusive"]
        for index in range(start, end + 1):
            foreign = {
                "version": 1,
                "revision": 1,
                "status": "none",
                "scope": {**case["foreignScopeFields"], "wireRootId": f"{index:032x}"},
            }
            reducer.callback(foreign, "beta")
        newer = case["realOwnerCallback33"]
        self.assertEqual(reducer.callback(newer, "beta"), "quarantine_evidence_lost")
        self.assertEqual(len(reducer._prebind_floors), 32)
        self.assertEqual(len(reducer._buffer), 32)
        self.assertEqual(
            reducer.bind(FIXTURE["trustedLoad"]["cursor"], "beta", token),
            "reject_evidence_lost",
        )
        # The additive saturation example abbreviates proof fields. Supply
        # the canonical old proof too, so malformed input cannot mask this test.
        valid_old = {
            **FIXTURE["trustedLoad"]["cursor"],
            **case["subsequentTrustedOldLoad"],
        }
        self.assertIsNotNone(parse_cursor(valid_old))
        for value in (valid_old, FIXTURE["nextTrustedLoad"]["cursor"]):
            self.assertEqual(self.load(reducer, value), "reject_evidence_lost")
            self.assertEqual(reducer.status, "unavailable")
        fresh = CursorReducer()
        self.assertEqual(self.load(fresh, FIXTURE["nextTrustedLoad"]["cursor"]), "bind")
        self.assertEqual(fresh.status, "none")

    def test_superseding_uncertain_request_preserves_prebind_epoch_floor(self):
        old = FIXTURE["trustedLoad"]["cursor"]
        newer = FIXTURE["prebindRace"]["callbackBeforeTrustedResult"]
        for initially_bound in (False, True):
            for uncertainty in ("malformed", "overflow"):
                with self.subTest(bound=initially_bound, uncertainty=uncertainty):
                    reducer = CursorReducer()
                    if initially_bound:
                        self.load(reducer, old)
                    pending = reducer.begin("beta")
                    reducer.callback(newer, "beta")
                    if uncertainty == "malformed":
                        reducer.callback({}, "beta")
                    else:
                        for _ in range(32):
                            reducer.callback(old, "beta")
                    # Supersede BEFORE the previous result compares its buffer.
                    latest = reducer.begin("beta")
                    self.assertEqual(
                        reducer.bind(old, "beta", latest),
                        "reject_binding_floor_or_uncertainty",
                    )
                    self.assertEqual(reducer.status, "unavailable")
                    self.assertEqual(reducer.floor.owner_epoch, 4)
                    self.assertLessEqual(len(reducer._prebind_floors), 32)
                    self.assertEqual(
                        reducer.bind(old, "beta", pending), "reject_old_request"
                    )
                    self.load(reducer, FIXTURE["nextTrustedLoad"]["cursor"])
                    self.assertEqual(reducer.status, "none")
                    self.assertFalse(reducer.quarantined)

    def test_trusted_same_scope_cannot_regress_but_new_epoch_can_reset(self):
        value = FIXTURE["trustedLoad"]["cursor"]
        reducer = CursorReducer()
        self.load(reducer, {**value, "revision": 8})
        self.assertEqual(
            self.load(reducer, value), "reject_stale_or_conflicting_binding"
        )
        self.assertEqual(reducer.status, "unavailable")
        replacement = deepcopy(FIXTURE["nextTrustedLoad"]["cursor"])
        replacement["revision"] = 1
        replacement["scope"]["ownerPid"] += 1
        self.assertEqual(self.load(reducer, replacement), "bind")
        self.assertEqual(reducer.status, "none")
        self.assertEqual(reducer.current.revision, 1)

    def test_prebind_revision_order_no_callback_binding(self):
        value = FIXTURE["trustedLoad"]["cursor"]
        reducer = CursorReducer()
        token = reducer.begin("beta")
        for revision in (6, 4, 5):
            reducer.callback({**value, "revision": revision, "status": "none"}, "beta")
            self.assertIsNone(reducer.current)
        reducer.bind(value, "beta", token)
        self.assertEqual(reducer.current.revision, 6)
        self.assertEqual(reducer.status, "none")


if __name__ == "__main__":
    unittest.main()
