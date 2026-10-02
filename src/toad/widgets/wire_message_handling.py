"""Original wire identity is the join for both DM and IRC feedback."""

from agent_comms.message_reference import MessageReference
from textual.message import Message


class WireMessageHandling:
    show_header: bool

    class Requested(Message):
        """Ask the mounted transcript source to publish original handling."""

    @property
    def message_reference(self) -> MessageReference:
        raise NotImplementedError

    @property
    def handling_references(self) -> tuple[MessageReference, ...]:
        return (self.message_reference,) if self.show_header else ()

    def on_mount(self) -> None:
        if self.handling_references:
            self.post_message(self.Requested())

    @classmethod
    def within(cls, contents):
        """The original mounted resources declare their handling capability."""
        return tuple(body for body in contents.walk_children()
                     if isinstance(body, cls) and body.handling_references)

    @classmethod
    def references_in(cls, bodies) -> tuple[MessageReference, ...]:
        return tuple(dict.fromkeys(reference for body in bodies
                                   for reference in body.handling_references))

    def show_notification_error(self, error: Exception) -> None:
        from toad.widgets.message_notifications import MessageNotifications

        feedback = self.query_one_optional(MessageNotifications)
        if feedback is not None:
            feedback.show_error(error)

    def show_notifications(self, results) -> None:
        from toad.widgets.message_notifications import MessageNotifications

        feedback = self.query_one_optional(MessageNotifications)
        if feedback is not None:
            notifications = tuple(item for reference in self.handling_references
                                  for item in results.get((reference.seq, reference.message_id), ()))
            feedback.show_result(notifications)
