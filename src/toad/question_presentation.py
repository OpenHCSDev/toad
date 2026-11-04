"""A question mount owns its option view and timer for exactly that lifetime."""
from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.nominal.declared_family import DeclaredFamily


class QuestionMount(DeclaredFamily, affix="QuestionMount"):
    def attach(self, container, timer):
        self.close()
        return ActiveQuestionMount(container, timer)

    def detached(self):
        self.close()
        return DetachedQuestionMount()

    @abstractmethod
    def restyle(self) -> None:
        """The cursor, answer or caret phase changed; the options repaint their places."""

    @abstractmethod
    def focus(self, focused: bool) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class DetachedQuestionMount(QuestionMount):
    def restyle(self):
        pass

    def focus(self, focused: bool) -> None:
        pass

    def reset(self):
        pass

    def close(self):
        pass


@dataclass
class ActiveQuestionMount(QuestionMount):
    container: object
    timer: object

    def restyle(self):
        self.container.update_node_styles()

    def focus(self, focused: bool) -> None:
        if focused:
            self.timer.resume()
        else:
            self.timer.pause()

    def reset(self):
        self.timer.reset()

    def close(self):
        self.timer.stop()


class RetiredQuestionMount(DetachedQuestionMount):
    def attach(self, container, timer):
        timer.stop()
        return self

    def detached(self):
        return self


class QuestionPresentation:
    def __init__(self):
        self.mount: QuestionMount = DetachedQuestionMount()

    def attach(self, container, timer):
        self.mount = self.mount.attach(container, timer)

    def detach(self):
        self.mount = self.mount.detached()

    def retire(self):
        self.mount.close()
        self.mount = RetiredQuestionMount()

    def reopen(self):
        self.mount = DetachedQuestionMount()

    def start(self, question, container):
        def toggle_blink():
            question.caret_phase = question.caret_phase.toggled()

        self.attach(container, question.set_interval(0.5, toggle_blink, pause=True))
        self.mount.focus(question.has_focus)

    async def recompose(self, question, compose):
        self.detach()
        await compose()
        self.start(question, question._option_view)
