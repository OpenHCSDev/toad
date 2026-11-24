"""Unified interactive dialog model, boundary parsers, and state machine.

One toolkit-neutral declaration owns structured user prompts — single-choice questions,
multi-select checklists, confirmations, text/number inputs, ACP `elicitation/create`
schemas, and multi-question agent payloads (`ask_question` / `AskUserQuestion`) — so
both Textual's `PromptDialog` and Qt's `QtInteractiveDialog` render and validate the
same family without parallel toolkit copies.
"""

from __future__ import annotations

import json
import re
from abc import abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from acp import schema
from agent_comms.nominal.declared_family import DeclaredFamily
from agent_comms.nominal.field_codec import boundary_decoder
from metaclass_registry.mro_dispatch import MroDispatch, handles

from toad.answer import Ask


@dataclass(frozen=True)
class DialogOption:
    """One selectable choice inside a single-select or multi-select field."""

    label: str
    value: str
    description: str = ""

    @classmethod
    @boundary_decoder
    def from_raw(cls, raw: object) -> DialogOption:
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, schema.EnumOption):
            return cls(
                label=raw.title,
                value=raw.const,
                description=raw.description or "",
            )
        if isinstance(raw, str):
            return cls(label=raw, value=raw)
        if isinstance(raw, Mapping):
            label = str(
                raw.get("label")
                or raw.get("title")
                or raw.get("text")
                or raw.get("value")
                or raw.get("const")
                or ""
            )
            value = str(
                raw.get("value")
                if raw.get("value") is not None
                else raw.get("const")
                if raw.get("const") is not None
                else raw.get("id")
                if raw.get("id") is not None
                else label
            )
            description = str(raw.get("description") or "")
            return cls(label=label, value=value, description=description)
        text = str(raw)
        return cls(label=text, value=text)


@dataclass(frozen=True, kw_only=True)
class DialogField(DeclaredFamily, affix="DialogField"):
    """One interactive question or input inside a dialog."""

    name: str
    title: str
    description: str = ""
    required: bool = True

    @property
    def is_quick_choice(self) -> bool:
        """Whether a lone field of this kind commits directly on a single option pick."""
        return False

    @abstractmethod
    def initial_value(self) -> object:
        """Starting value before the user edits this field."""

    @abstractmethod
    def coerce(self, value: object) -> object:
        """Convert the UI's held value into its canonical Python value."""

    @abstractmethod
    def validate(self, value: object) -> str | None:
        """Return a plain-English validation message, or None when the value is valid."""

    def to_elicitation_value(self, value: object) -> str | int | float | bool | list[str] | None:
        coerced = self.coerce(value)
        return coerced  # type: ignore[return-value]


@dataclass(frozen=True, kw_only=True)
class SingleSelectDialogField(DialogField):
    """Pick one option from a declared list (optionally allowing custom 'Other' text)."""

    options: tuple[DialogOption, ...]
    default: str | None = None
    allow_other: bool = False

    @property
    def is_quick_choice(self) -> bool:
        return not self.allow_other and bool(self.options)

    def initial_value(self) -> str | None:
        if self.default is not None:
            return self.default
        return self.options[0].value if self.options else None

    def coerce(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def validate(self, value: object) -> str | None:
        selected = self.coerce(value)
        if selected is None:
            return "Choose an option." if self.required else None
        allowed = {option.value for option in self.options}
        if not self.allow_other and allowed and selected not in allowed:
            return f"{selected!r} is not one of the offered choices."
        return None


@dataclass(frozen=True, kw_only=True)
class MultiSelectDialogField(DialogField):
    """Pick zero or more options from a declared list."""

    options: tuple[DialogOption, ...]
    default: tuple[str, ...] = ()
    min_items: int | None = None
    max_items: int | None = None
    allow_other: bool = False

    def initial_value(self) -> tuple[str, ...]:
        return self.default

    def coerce(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple, set, frozenset)):
            seen: dict[str, None] = {}
            for item in value:
                text = str(item).strip()
                if text:
                    seen[text] = None
            return list(seen)
        return [str(value)]

    def validate(self, value: object) -> str | None:
        chosen = self.coerce(value)
        minimum = self.min_items if self.min_items is not None else (1 if self.required else 0)
        if len(chosen) < minimum:
            return f"Select at least {minimum} option{'s' if minimum != 1 else ''}."
        if self.max_items is not None and len(chosen) > self.max_items:
            return f"Select at most {self.max_items} option{'s' if self.max_items != 1 else ''}."
        allowed = {option.value for option in self.options}
        if not self.allow_other and allowed:
            unknown = [item for item in chosen if item not in allowed]
            if unknown:
                return f"Unknown selection: {', '.join(unknown)}."
        return None


@dataclass(frozen=True, kw_only=True)
class ConfirmDialogField(DialogField):
    """Yes/no boolean confirmation."""

    default: bool = False

    def initial_value(self) -> bool:
        return self.default

    def coerce(self, value: object) -> bool:
        return bool(value)

    def validate(self, value: object) -> str | None:
        return None


@dataclass(frozen=True, kw_only=True)
class TextDialogField(DialogField):
    """Free-text input, single-line or multi-line."""

    default: str = ""
    placeholder: str = ""
    multiline: bool = False
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None

    def initial_value(self) -> str:
        return self.default

    def coerce(self, value: object) -> str:
        return "" if value is None else str(value)

    def validate(self, value: object) -> str | None:
        text = self.coerce(value)
        if self.required and not text.strip():
            return "Enter a value."
        if self.min_length is not None and len(text) < self.min_length:
            return f"Must be at least {self.min_length} characters."
        if self.max_length is not None and len(text) > self.max_length:
            return f"Must be at most {self.max_length} characters."
        if self.pattern and text and re.search(self.pattern, text) is None:
            return f"Must match pattern {self.pattern}."
        return None


@dataclass(frozen=True, kw_only=True)
class NumberDialogField(DialogField):
    """Integer or floating-point numeric input."""

    default: int | float | None = None
    integer: bool = False
    minimum: float | None = None
    maximum: float | None = None

    def initial_value(self) -> str:
        return "" if self.default is None else str(self.default)

    def coerce(self, value: object) -> int | float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if self.integer else float(value)
        if isinstance(value, float):
            return int(value) if self.integer and value.is_integer() else value
        text = str(value).strip()
        if not text:
            return None
        return int(text) if self.integer else float(text)

    def validate(self, value: object) -> str | None:
        try:
            parsed = self.coerce(value)
        except ValueError:
            return "Enter a whole number." if self.integer else "Enter a number."
        if parsed is None:
            return "Enter a number." if self.required else None
        if self.minimum is not None and parsed < self.minimum:
            return f"Must be at least {self.minimum}."
        if self.maximum is not None and parsed > self.maximum:
            return f"Must be at most {self.maximum}."
        return None


class DialogOutcome(DeclaredFamily, affix="DialogOutcome"):
    """What the user chose for an interactive dialog."""

    accepted: ClassVar[bool] = False

    @abstractmethod
    def to_elicitation_response(self) -> schema.CreateElicitationResponse:
        """Encode this outcome for ACP `elicitation/create`."""


@dataclass(frozen=True)
class DialogAccepted(DialogOutcome):
    values: dict[str, object]
    accepted: ClassVar[bool] = True

    def to_elicitation_response(self) -> schema.AcceptElicitationResponse:
        content = {key: value for key, value in self.values.items() if value is not None}
        return schema.AcceptElicitationResponse(action="accept", content=content)


@dataclass(frozen=True)
class DialogDeclined(DialogOutcome):
    def to_elicitation_response(self) -> schema.DeclineElicitationResponse:
        return schema.DeclineElicitationResponse(action="decline")


@dataclass(frozen=True)
class DialogCancelled(DialogOutcome):
    def to_elicitation_response(self) -> schema.CancelElicitationResponse:
        return schema.CancelElicitationResponse(action="cancel")


class MultiSelectItemsDecoder(MroDispatch):
    """Decode ACP multi-select items into `DialogOption` tuples by schema class."""

    @handles(schema.TitledMultiSelectItems)
    def titled(self, items: schema.TitledMultiSelectItems) -> tuple[DialogOption, ...]:
        return tuple(DialogOption.from_raw(option) for option in items.any_of)

    @handles(schema.StringMultiSelectItems)
    def untitled(self, items: schema.StringMultiSelectItems) -> tuple[DialogOption, ...]:
        return tuple(DialogOption(label=value, value=value) for value in items.enum)

    @handles(schema.OtherMultiSelectItems)
    def other(self, items: schema.OtherMultiSelectItems) -> tuple[DialogOption, ...]:
        return ()


class ElicitationFieldDecoder(MroDispatch):
    """Decode ACP `ElicitationSchema` property schemas into `DialogField` members."""

    items_decoder: ClassVar[MultiSelectItemsDecoder] = MultiSelectItemsDecoder()

    @handles(schema.ElicitationStringPropertySchema)
    def string_field(
        self, prop: schema.ElicitationStringPropertySchema, name: str, required: bool,
    ) -> DialogField:
        title = prop.title or name
        description = prop.description or ""
        if prop.one_of:
            options = tuple(DialogOption.from_raw(option) for option in prop.one_of)
            return SingleSelectDialogField(
                name=name, title=title, description=description, required=required,
                options=options, default=prop.default,
            )
        if prop.enum:
            options = tuple(DialogOption(label=value, value=value) for value in prop.enum)
            return SingleSelectDialogField(
                name=name, title=title, description=description, required=required,
                options=options, default=prop.default,
            )
        return TextDialogField(
            name=name, title=title, description=description, required=required,
            default=prop.default or "",
            min_length=prop.min_length, max_length=prop.max_length, pattern=prop.pattern,
        )

    @handles(schema.ElicitationMultiSelectPropertySchema)
    def multiselect_field(
        self, prop: schema.ElicitationMultiSelectPropertySchema, name: str, required: bool,
    ) -> DialogField:
        options = next(self.items_decoder.handlers_for(prop.items))(prop.items)
        return MultiSelectDialogField(
            name=name,
            title=prop.title or name,
            description=prop.description or "",
            required=required,
            options=options,
            default=tuple(prop.default or ()),
            min_items=prop.min_items,
            max_items=prop.max_items,
        )

    @handles(schema.ElicitationBooleanPropertySchema)
    def boolean_field(
        self, prop: schema.ElicitationBooleanPropertySchema, name: str, required: bool,
    ) -> DialogField:
        return ConfirmDialogField(
            name=name,
            title=prop.title or name,
            description=prop.description or "",
            required=required,
            default=bool(prop.default) if prop.default is not None else False,
        )

    @handles(schema.ElicitationIntegerPropertySchema)
    def integer_field(
        self, prop: schema.ElicitationIntegerPropertySchema, name: str, required: bool,
    ) -> DialogField:
        return NumberDialogField(
            name=name,
            title=prop.title or name,
            description=prop.description or "",
            required=required,
            default=prop.default,
            integer=True,
            minimum=float(prop.minimum) if prop.minimum is not None else None,
            maximum=float(prop.maximum) if prop.maximum is not None else None,
        )

    @handles(schema.ElicitationNumberPropertySchema)
    def number_field(
        self, prop: schema.ElicitationNumberPropertySchema, name: str, required: bool,
    ) -> DialogField:
        return NumberDialogField(
            name=name,
            title=prop.title or name,
            description=prop.description or "",
            required=required,
            default=prop.default,
            integer=False,
            minimum=prop.minimum,
            maximum=prop.maximum,
        )

    @handles(schema.ElicitationOtherPropertySchema)
    def other_field(
        self, prop: schema.ElicitationOtherPropertySchema, name: str, required: bool,
    ) -> DialogField:
        return TextDialogField(name=name, title=name, required=required)


_ELICITATION_DECODER = ElicitationFieldDecoder()


@dataclass(frozen=True)
class DialogSpec:
    """One structured interactive dialog rendered identically by Textual and Qt."""

    title: str
    message: str = ""
    fields: tuple[DialogField, ...] = ()
    submit_label: str = "Submit"
    decline_label: str = "Decline"
    cancel_label: str = "Cancel"

    @property
    def is_quick_choice(self) -> bool:
        return len(self.fields) == 1 and self.fields[0].is_quick_choice

    @classmethod
    def from_elicitation(
        cls,
        message: str,
        requested_schema: schema.ElicitationSchema,
    ) -> DialogSpec:
        required = set(requested_schema.required or ())
        fields = tuple(
            next(_ELICITATION_DECODER.handlers_for(prop))(prop, name, name in required)
            for name, prop in requested_schema.properties.items()
        )
        title = requested_schema.title or message or "Input requested"
        detail = requested_schema.description or (message if requested_schema.title else "")
        return cls(title=title, message=detail, fields=fields)

    @classmethod
    def from_questions(
        cls,
        questions: Sequence[Mapping[str, object]],
        *,
        title: str = "",
        message: str = "",
    ) -> DialogSpec:
        """Decode the common multi-question / single-or-multi-select prompt pattern
        (`ask_question`, `AskUserQuestion`, CLI prompt cards)."""
        fields: list[DialogField] = []
        for index, raw in enumerate(questions):
            prompt_text = str(raw.get("question") or raw.get("title") or f"Question {index + 1}")
            field_name = str(raw.get("name") or raw.get("id") or raw.get("header") or f"q{index + 1}")
            description = str(raw.get("description") or "")
            raw_options = raw.get("options") or raw.get("choices") or ()
            options = tuple(DialogOption.from_raw(item) for item in raw_options)  # type: ignore[union-attr]
            multi = bool(raw.get("is_multi_select") or raw.get("multiSelect") or raw.get("multi_select"))
            allow_other = bool(raw.get("allow_other", True)) if options else False
            required = bool(raw.get("required", True))
            if options and multi:
                fields.append(MultiSelectDialogField(
                    name=field_name, title=prompt_text, description=description,
                    required=required, options=options, allow_other=allow_other,
                ))
            elif options:
                fields.append(SingleSelectDialogField(
                    name=field_name, title=prompt_text, description=description,
                    required=required, options=options, allow_other=allow_other,
                ))
            elif raw.get("type") == "boolean":
                fields.append(ConfirmDialogField(
                    name=field_name, title=prompt_text, description=description,
                    required=required, default=bool(raw.get("default", False)),
                ))
            else:
                fields.append(TextDialogField(
                    name=field_name, title=prompt_text, description=description,
                    required=required,
                    default=str(raw.get("default") or ""),
                    placeholder=str(raw.get("placeholder") or ""),
                    multiline=bool(raw.get("multiline", False)),
                ))
        heading = title or (fields[0].title if len(fields) == 1 else "Questions")
        return cls(title=heading, message=message, fields=tuple(fields))

    @classmethod
    def from_ask(cls, ask: Ask) -> DialogSpec:
        """Lift an existing single-choice `Ask` into the unified dialog model."""
        options = tuple(DialogOption(label=answer.text, value=answer.id) for answer in ask.options)
        field = SingleSelectDialogField(
            name="answer",
            title=ask.question or "Choose an option",
            options=options,
            default=options[0].value if options else None,
            allow_other=False,
        )
        return cls(title=ask.question or "Choose an option", fields=(field,))

    @classmethod
    @boundary_decoder
    def parse(cls, source: object) -> DialogSpec:
        """Unified boundary decoder for any supported dialog payload."""
        if isinstance(source, cls):
            return source
        if isinstance(source, Ask):
            return cls.from_ask(source)
        if isinstance(source, schema.ElicitationSchema):
            return cls.from_elicitation(source.title or "", source)
        if isinstance(source, str):
            return cls.parse(json.loads(source))
        if isinstance(source, Mapping):
            if "requestedSchema" in source or "requested_schema" in source:
                raw_schema = source.get("requestedSchema") or source.get("requested_schema")
                elicitation = schema.ElicitationSchema.model_validate(raw_schema)
                return cls.from_elicitation(str(source.get("message") or ""), elicitation)
            if "properties" in source and isinstance(source["properties"], Mapping):
                elicitation = schema.ElicitationSchema.model_validate(source)
                return cls.from_elicitation(str(source.get("message") or ""), elicitation)
            if "questions" in source and isinstance(source["questions"], Sequence):
                return cls.from_questions(
                    source["questions"],
                    title=str(source.get("title") or ""),
                    message=str(source.get("message") or ""),
                )
            if "question" in source or "options" in source:
                return cls.from_questions(
                    [source],
                    title=str(source.get("title") or ""),
                    message=str(source.get("message") or ""),
                )
        raise ValueError(f"Unsupported interactive dialog payload: {type(source).__name__}")


class InteractiveDialogOwner:
    """Shared state machine for an inline interactive dialog, inherited by Textual and Qt.

    Plain mixin (no ABCMeta) so Textual's `Widget` metaclass and Qt's `PyQtWidgetMeta`
    both inherit it cleanly without metaclass conflict.
    """

    _dialog_spec: DialogSpec | None = None
    _dialog_callback: Callable[[DialogOutcome], None] | None = None

    def init_dialog_owner(self) -> None:
        self._dialog_spec = None
        self._dialog_callback = None
        self._dialog_values: dict[str, object] = {}
        self._dialog_errors: dict[str, str] = {}

    @property
    def dialog_spec(self) -> DialogSpec | None:
        return self._dialog_spec

    @property
    def dialog_values(self) -> dict[str, object]:
        return self._dialog_values

    @property
    def dialog_errors(self) -> dict[str, str]:
        return self._dialog_errors

    @property
    def dialog_open(self) -> bool:
        return self._dialog_spec is not None

    def open_dialog(
        self,
        spec: DialogSpec,
        callback: Callable[[DialogOutcome], None] | None = None,
    ) -> None:
        self._dialog_spec = spec
        self._dialog_callback = callback
        self._dialog_values = {field.name: field.initial_value() for field in spec.fields}
        self._dialog_errors = {}
        self.present_dialog(spec)

    def withdraw_dialog(self, spec: DialogSpec) -> None:
        if self._dialog_spec is spec:
            self.close_dialog()

    def close_dialog(self) -> None:
        self._dialog_spec = None
        self._dialog_callback = None
        self._dialog_values = {}
        self._dialog_errors = {}
        self.clear_dialog()

    def set_dialog_value(self, name: str, value: object) -> None:
        self._dialog_values[name] = value
        if name in self._dialog_errors:
            self._dialog_errors.pop(name, None)
            self.show_dialog_errors(dict(self._dialog_errors))

    def toggle_dialog_option(self, name: str, option_value: str, selected: bool) -> None:
        current = list(self._dialog_values.get(name) or ())
        if selected and option_value not in current:
            current.append(option_value)
        elif not selected and option_value in current:
            current.remove(option_value)
        self.set_dialog_value(name, current)

    def pick_quick_option(self, name: str, option_value: str) -> bool:
        self.set_dialog_value(name, option_value)
        return self.commit_dialog()

    def validate_dialog(self) -> dict[str, str]:
        spec = self._dialog_spec
        if spec is None:
            return {}
        errors: dict[str, str] = {}
        for field in spec.fields:
            error = field.validate(self._dialog_values.get(field.name))
            if error is not None:
                errors[field.name] = error
        return errors

    def commit_dialog(self) -> bool:
        spec = self._dialog_spec
        if spec is None:
            return False
        errors = self.validate_dialog()
        if errors:
            self._dialog_errors = errors
            self.show_dialog_errors(dict(errors))
            return False
        resolved = {
            field.name: field.to_elicitation_value(self._dialog_values.get(field.name))
            for field in spec.fields
        }
        self._finish_dialog(DialogAccepted(resolved))
        return True

    def decline_dialog(self) -> None:
        if self._dialog_spec is not None:
            self._finish_dialog(DialogDeclined())

    def cancel_dialog(self) -> None:
        if self._dialog_spec is not None:
            self._finish_dialog(DialogCancelled())

    def _finish_dialog(self, outcome: DialogOutcome) -> None:
        callback = self._dialog_callback
        self.close_dialog()
        if callback is not None:
            callback(outcome)

    @abstractmethod
    def present_dialog(self, spec: DialogSpec) -> None:
        """Render the dialog fields and make the panel visible."""

    @abstractmethod
    def clear_dialog(self) -> None:
        """Remove rendered controls and hide the panel."""

    @abstractmethod
    def show_dialog_errors(self, errors: dict[str, str]) -> None:
        """Display per-field validation messages."""
