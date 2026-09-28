"""A question mount owns its option view and timer for exactly that lifetime."""
from abc import abstractmethod
from dataclasses import dataclass
from agent_comms.declared_family import DeclaredFamily


class QuestionMount(DeclaredFamily, affix="QuestionMount"):
    def attach(self, container, timer):
        self.close()
        return ActiveQuestionMount(container, timer)

    def detached(self):
        self.close()
        return DetachedQuestionMount()

    @abstractmethod
    def select(self, index: int) -> None: ...

    @abstractmethod
    def blink(self, value: bool) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class DetachedQuestionMount(QuestionMount):
    def select(self, index):
        pass

    def blink(self, value):
        pass

    def reset(self):
        pass

    def close(self):
        pass


@dataclass
class ActiveQuestionMount(QuestionMount):
    container: object
    timer: object

    def select(self, index):
        self.container.query(".-active").remove_class("-active")
        if index >= 0:
            self.container.children[index].add_class("-active")

    def blink(self, value):
        self.container.set_class(value, "-blink")

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
            question.blink = not question.blink if question.has_focus else False

        self.attach(container, question.set_interval(0.5, toggle_blink))
