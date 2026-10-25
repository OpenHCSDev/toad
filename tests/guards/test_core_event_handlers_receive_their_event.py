"""A Core-event handler receives the event it declares; the carrier stays in the dispatcher."""

import importlib
import inspect
import types
import typing
from pathlib import Path

import toad
from toad.core.events import CoreEvent
from toad.core_event_carrier import CoreEventMessage, CoreEventReceiver

PACKAGE = Path(toad.__file__).parent


def receivers() -> set[type[CoreEventReceiver]]:
    # screens/ and widgets/ are namespace packages, which pkgutil skips.
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.stem != "__main__":
            parts = path.relative_to(PACKAGE).with_suffix("").parts
            importlib.import_module(".".join(("toad", *parts)).removesuffix(".__init__"))
    found, pending = set(), [CoreEventReceiver]
    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass not in found:
                found.add(subclass)
                pending.append(subclass)
    return found


def accepted(annotation: object) -> tuple[type, ...]:
    if isinstance(annotation, types.UnionType):
        return typing.get_args(annotation)
    return (annotation,)


def handler_defects(receiver: type[CoreEventReceiver]) -> typing.Iterator[str]:
    # Core's dispatcher reads exactly these declarations (MroDispatch.__init_subclass__).
    for name, cases in receiver._handler_declarations:
        events = tuple(case for case in cases if issubclass(case, CoreEvent))
        if not events:
            continue
        handler = inspect.unwrap(getattr(receiver, name))
        where = f"{receiver.__qualname__}.{name} ({inspect.getsourcefile(handler)}:{inspect.getsourcelines(handler)[1]})"
        parameters = list(inspect.signature(handler).parameters)[1:]
        hints = typing.get_type_hints(handler)
        if parameters:
            declared = accepted(hints.get(parameters[0]))
            for event in events:
                if not any(isinstance(kind, type) and issubclass(event, kind) for kind in declared):
                    yield f"{where}: first parameter {hints.get(parameters[0])} does not accept {event.__name__}"
        if len(parameters) > 1 and hints.get(parameters[1]) is not CoreEventMessage:
            yield f"{where}: second parameter must be CoreEventMessage, not {hints.get(parameters[1])}"
        if len(parameters) > 2:
            yield f"{where}: Core delivers an event and its carrier, not {len(parameters)} values"


def test_every_core_event_handler_declares_the_event_it_receives():
    found = receivers()
    assert len(found) > 20
    defects = [defect for receiver in found for defect in handler_defects(receiver)]
    assert not defects, "\n".join(sorted(set(defects)))
