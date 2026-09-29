"""Local process outcomes, never approval receipts."""

from agent_comms.declared_family import DeclaredFamily


class DecisionOutcome(DeclaredFamily, affix="Outcome"):
    message: str


class ExitedZeroOutcome(DecisionOutcome):
    message = "CLI exited zero; inspect its visible applied receipt. Changes apply next Pi turn."


class ExitedErrorOutcome(DecisionOutcome):
    message = "CLI exited nonzero; outcome may be uncertain after a package write. Refresh inventory."


class StaleSnapshotOutcome(DecisionOutcome):
    message = "Inventory changed or became unavailable. Action refused before launch; refresh it."


class OutputLimitOutcome(DecisionOutcome):
    message = "CLI output limit; child stopped. Package outcome may be uncertain; refresh inventory."


class TimeoutOutcome(DecisionOutcome):
    message = "Local decision timed out; child stopped. Package outcome may be uncertain; refresh inventory."


class UnsupportedOutcome(DecisionOutcome):
    message = "This action is unsupported or on safety hold."


class UnavailableOutcome(DecisionOutcome):
    message = "Local PTY/package unavailable. No action launched."


class ControllerLostOutcome(DecisionOutcome):
    message = "Controller disappeared; child stopped. Package outcome may be uncertain."


class UnknownOutcome(DecisionOutcome):
    message = "CLI failed after spawn; package outcome may be uncertain. Refresh inventory."
