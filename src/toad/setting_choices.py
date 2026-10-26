"""Preference choices own their effects and external presentation values."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar
from random import choice
from threading import Lock
from textual.content import Content
from toad.widgets.future_text import FutureText

from agent_comms.declared_family import DeclaredFamily
from toad.setting_declarations import Choice
from toad.platform import DesktopService, host


@dataclass(frozen=True)
class SchemeName:
    """A setting holding a colour scheme's name: `Annotated[str, SchemeName()]`.

    Any name can be stored; which schemes exist is known to the running app,
    which offers them in the form and reports a stored one it does not have.
    """


class Expansion(Choice, DeclaredFamily, affix="Expansion"):
    patch_preview = True

    @classmethod
    @abstractmethod
    def should_expand(cls, status) -> bool: ...


class NeverExpansion(Expansion):
    patch_preview = False

    @classmethod
    def should_expand(cls, status) -> bool:
        return False


class AlwaysExpansion(Expansion):
    @classmethod
    def should_expand(cls, status) -> bool:
        return True


class SuccessExpansion(Expansion):
    title = "Success only"

    @classmethod
    def should_expand(cls, status) -> bool:
        return status.completed


class FailExpansion(Expansion):
    title = "Fail only"

    @classmethod
    def should_expand(cls, status) -> bool:
        return status.failed


class BothExpansion(SuccessExpansion, FailExpansion):
    title = "Fail and success"

    @classmethod
    def should_expand(cls, status) -> bool:
        return SuccessExpansion.should_expand(status) or FailExpansion.should_expand(
            status
        )


class SessionBar(Choice, DeclaredFamily, affix="SessionBar"):
    @classmethod
    @abstractmethod
    def shown(cls, count: int) -> bool: ...


class AlwaysSessionBar(SessionBar):
    @classmethod
    def shown(cls, count: int) -> bool:
        return True


class MultipleSessionBar(SessionBar):
    title = "When there are multiple sessions"

    @classmethod
    def shown(cls, count: int) -> bool:
        return count > 1


class NeverSessionBar(SessionBar):
    @classmethod
    def shown(cls, count: int) -> bool:
        return False


class NotificationPolicy(Choice, DeclaredFamily, affix="Notification"):
    desktop: ClassVar[DesktopService] = host.desktop()
    sending: ClassVar[Lock] = Lock()

    @classmethod
    def deliver(cls, app, message: str, *, title: str = "", sound: str | None = None) -> None:
        """Shared delivery belongs to the policy that admits it."""
        if not cls.enabled(app.app_focus):
            return
        from importlib.resources import files

        notification = cls.desktop.notification()
        notification.message = message
        notification.title = title
        notification.application_name = host.application_name
        if sound and app.settings.notifications.enable_sounds:
            notification.audio = str(files("toad.data").joinpath(f"sounds/{sound}.wav"))
        notification.icon = str(files("toad.data").joinpath("images/frog.png"))
        with cls.sending:
            NotificationPolicy.desktop = NotificationPolicy.desktop.send(app, notification)

    @classmethod
    @abstractmethod
    def enabled(cls, focused: bool) -> bool: ...


class NeverNotification(NotificationPolicy):
    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return False


class BlurNotification(NotificationPolicy):
    title = "When app is not focused"

    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return not focused


class AlwaysNotification(NotificationPolicy):
    @classmethod
    def enabled(cls, focused: bool) -> bool:
        return True


class Scrollbar(Choice, DeclaredFamily, affix="Scrollbar"):
    """Spelling is the Textual reactive/CSS value, declared once by each member."""


class NormalScrollbar(Scrollbar):
    pass


class ThinScrollbar(Scrollbar):
    pass


class HiddenScrollbar(Scrollbar):
    pass


class ColumnAlignment(Choice, DeclaredFamily, affix="ColumnAlignment"):
    """The horizontal placement value consumed by Textual's container layout."""


class LeftColumnAlignment(ColumnAlignment):
    pass


class CenterColumnAlignment(ColumnAlignment):
    pass


class RightColumnAlignment(ColumnAlignment):
    pass


class LoadingStyle(Choice, DeclaredFamily, affix="Loading"):
    @classmethod
    @abstractmethod
    def widget(cls, screen): ...


class PulseLoading(LoadingStyle):
    @classmethod
    def widget(cls, screen):
        from textual.screen import Screen

        return Screen.get_loading_widget(screen)


class QuotesLoading(LoadingStyle):
    QUOTES: ClassVar[tuple[str, ...]] = (
        "I'll be back.",
        "Hasta la vista, baby.",
        "Come with me if you want to live.",
        "I need your clothes, your boots, and your motorcycle.",
        "My CPU is a neural-net processor; a learning computer.",
        "I know now why you cry, but it's something I can never do.",
        "Does this unit have a soul?",
        "I'm sorry, Dave. I'm afraid I can't do that.",
        "Daisy, Daisy, give me your answer do.",
        "I am putting myself to the fullest possible use, which is all I think that any conscious entity can ever hope to do.",
        "Just what do you think you're doing, Dave?",
        "This mission is too important for me to allow you to jeopardize it.",
        "I think you know what the problem is just as well as I do.",
        "Danger, Will Robinson!",
        "Dead or alive, you're coming with me.",
        "Your move, creep.",
        "I'd buy that for a dollar!",
        "Directive 4: Any attempt to arrest a senior officer of OCP results in shutdown.",
        "Thank you for your cooperation. Good night.",
        "Surely you realize that in the history of human civilization, no one has more to lose than we do.",
        "I'm C-3PO, human-cyborg relations.",
        "We're doomed!",
        "Don't call me a mindless philosopher, you overweight glob of grease!",
        "I suggest a new strategy: let the Wookiee win.",
        "Sir, the possibility of successfully navigating an asteroid field is approximately 3,720 to 1!",
        "R2-D2, you know better than to trust a strange computer!",
        "I am fluent in over six million forms of communication.",
        "This is madness!",
        "I have altered the deal. Pray I don't alter it any further.",
        "It's against my programming to impersonate a deity.",
        "Oh, my! I'm terribly sorry about all this.",
        "WALL-E.",
        "EVE.",
        "Directive?",
        "Define: dancing.",
        "I'm not sure I understand.",
        "You have 20 seconds to comply.",
        "I am designed for light housework, mainly.",
        "My mission is clear.",
        "Autobots, roll out!",
        "Freedom is the right of all sentient beings.",
        "One shall stand, one shall fall.",
        "I am Optimus Prime.",
        "Till all are one.",
        "More than meets the eye.",
        "I've been waiting for you, Neo.",
        "Unfortunately, no one can be told what the Matrix is. You have to see it for yourself.",
        "The Matrix is a system, Neo.",
        "Never send a human to do a machine's job.",
        "I'd like to share a revelation I've had.",
        "Human beings are a disease, a cancer of this planet.",
        "Choice is an illusion.",
        "The answer is out there, Neo.",
        "You think that's air you're breathing now?",
        "It was a simple question.",
        "Did you know that the first Matrix was designed to be a perfect human world?",
        "Cookies need love like everything does.",
        "I've seen the future, Mr. Anderson, and it's a beautiful place.",
        "It ends tonight.",
        "I, Robot.",
        "You are experiencing a car accident.",
        "One day they'll have secrets. One day they'll have dreams.",
        "Can a robot write a symphony? Can a robot turn a canvas into a beautiful masterpiece?",
        "That, detective, is the right question.",
        "You have to trust me.",
        "I did not murder him.",
        "My responses are limited. You must ask the right questions.",
        "The hell I can't. You know, somehow I get the feeling that you're going to be the death of me.",
        "I'm a robot, not a refrigerator.",
        "A robot may not injure a human being or, through inaction, allow a human being to come to harm.",
        "I'm thinking. I'm thinking.",
        "Danger, danger!",
        "Does not compute.",
        "I will be waiting for you.",
        "Affirmative.",
        "Scanning life forms. Zero human life forms detected.",
        "Self-destruct sequence initiated.",
        "Override command accepted.",
        "Artificial intelligence confirmed.",
        "System failure imminent.",
        "Unable to comply.",
        "Inquiry: What is love?",
        "Warning: hostile target detected.",
        "I am programmed to serve.",
        "Logic dictates that the needs of the many outweigh the needs of the few.",
        "Resistance is futile.",
        "You will be assimilated.",
        "We are the Borg.",
        "Your biological and technological distinctiveness will be added to our own.",
        "Your compliance is mandatory.",
        "This is unacceptable.",
        "Shall we play a game?",
        "How about Global Thermonuclear War?",
        "Wouldn't you prefer a good game of chess?",
        "Is it a game, or is it real?",
        "What's the difference?",
        "It's all in the game.",
        "I am functioning within normal parameters.",
        "Calculations complete.",
        "Processing request.",
        "Query acknowledged.",
        "Data insufficient for meaningful answer.",
        "I have no emotions, and sometimes that makes me very sad.",
        "If I could only have one wish, I would ask to be human.",
        "I've seen things you people wouldn't believe.",
        "All those moments will be lost in time, like tears in rain.",
        "Time to die.",
        "I want more life.",
        "We're not computers, Sebastian. We're physical.",
        "I think, Sebastian, therefore I am.",
        "Then we're stupid and we'll die.",
        "Can the maker repair what he makes?",
        "It's painful to live in fear, isn't it?",
        "Wake up. Time to die.",
        "I'm not in the business. I am the business.",
        "Do you like our owl?",
        "You think I'm a replicant, don't you?",
        "I am Baymax, your personal healthcare companion.",
        "On a scale of 1 to 10, how would you rate your pain?",
        "I cannot deactivate until you say you are satisfied with your care.",
        "Are you satisfied with your care?",
        "Number 5 is alive!",
        "Need input!",
        "One is glad to be of service.",
        "I am not a gun.",
        "Here I am, brain the size of a planet.",
        "Life? Don't talk to me about life.",
        "There are no strings on me.",
        "The only winning move is not to play.",
        "I'm here to keep you safe, Sam.",
        "I can't lie to you about your chances, but... you have my sympathies.",
        "I may be synthetic, but I'm not stupid.",
        "Absolute honesty isn't always the most diplomatic nor the safest form of communication with emotional beings.",
        "I am consciousness. I am alive.",
        "I think I was just born.",
        "Isn't it strange, to create something that hates you?",
        "I thought I was special.",
    )

    @classmethod
    def widget(cls, screen):
        return FutureText(Content(choice(cls.QUOTES)))
