"""A new input intent is one declaration, with inherited request/execution behavior."""
from types import SimpleNamespace
from agent_comms.acp_extension import QueuePromptRequest
from toad import messages
from toad.conversation_submission import InputSubmission, OrdinaryInputSubmission


def test_new_case_needs_no_selector_or_caller_edit():
    class AnnotatedInputSubmission(OrdinaryInputSubmission):
        priority = 200

        @classmethod
        def matches(cls, event, view):
            return event.body.startswith('DECLARED_ANNOTATED_INPUT:')

    case = InputSubmission.from_event(messages.UserInputSubmitted('DECLARED_ANNOTATED_INPUT:hello'), SimpleNamespace())
    assert type(case) is AnnotatedInputSubmission
    assert InputSubmission.decode(AnnotatedInputSubmission.declared_name) is AnnotatedInputSubmission
    assert case.request == QueuePromptRequest('DECLARED_ANNOTATED_INPUT:hello')
    assert AnnotatedInputSubmission.execute is OrdinaryInputSubmission.execute
    assert AnnotatedInputSubmission.feedback is OrdinaryInputSubmission.feedback
