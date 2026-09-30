"""Original wire identity is the join for both DM and IRC feedback."""

from agent_comms.message_reference import MessageReference


class WireMessageHandling:
    show_header: bool

    @property
    def message_reference(self) -> MessageReference | None:
        raise NotImplementedError

    @property
    def handling_references(self) -> tuple[MessageReference, ...]:
        if not self.show_header:
            return ()
        reference = self.message_reference
        return (reference,) if reference is not None else ()

    def on_mount(self) -> None:
        from toad.widgets.conversation import Conversation

        if self.handling_references:
            self.query_ancestor(Conversation).transcript.request_handling()

    def show_notifications(self, results) -> None:
        from toad.widgets.message_notifications import MessageNotifications

        feedback = self.query_one_optional(MessageNotifications)
        if feedback is not None:
            notifications = tuple(item for reference in self.handling_references
                                  for item in results.get((reference.seq, reference.message_id), ()))
            feedback.show_result(notifications)
