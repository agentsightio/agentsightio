"""The explicit calls — things no decorator can observe.

Each one has a one-sentence justification, and they are short:

* messages     — the text a human typed is not derivable from the call stack,
                 and guessing puts the wrong text in a client-facing transcript
* buttons      — a click happens in the browser
* attachments  — blobs cannot ride in spans
* open_conversation — a decorator only fires once someone has engaged, so it
                 cannot express "the widget loaded but nobody typed"
"""

from typing import Any, Dict, List, Optional

from agentsight.sdk import context as ags_context
from agentsight.sdk.core import logger
from agentsight.sdk.scopes import ConversationScope, TurnScope
from agentsight.sdk.semconv import (
    AttachmentAttributes,
    ButtonAttributes,
    MessageAttributes,
    SpanAttributes,
    SpanKind,
    TurnAttributes,
)
from agentsight.sdk.serialization import to_json


def _emit_message(sender: str, text: Any, metadata: Optional[Dict[str, Any]]) -> None:
    """Attach a message event to the active turn.

    Outside a turn — a proactive nudge, say — a one-off turn is opened and
    closed around the single message, so it still has somewhere to live.
    """
    from agentsight.sdk.core import is_enabled

    if not is_enabled() or not ags_context.tracking_enabled():
        return

    turn = ags_context.current_turn()
    if turn is not None and turn.span is not None:
        turn.add_message(sender, text, metadata)
        return

    standalone = TurnScope("message").start()
    try:
        standalone.add_message(sender, text, metadata)
    finally:
        standalone.finish(complete=True)


def user_message(text: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Record a message from the end user. Any number, any order."""
    try:
        _emit_message(MessageAttributes.SENDER_USER, text, metadata)
    except Exception as exc:  # pragma: no cover
        logger.debug("user_message failed: %s", exc)


def agent_message(text: Any, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Record a message from the agent. Any number, any order."""
    try:
        _emit_message(MessageAttributes.SENDER_AGENT, text, metadata)
    except Exception as exc:  # pragma: no cover
        logger.debug("agent_message failed: %s", exc)


def wrap(obj: Any) -> Any:
    """Bind the active turn's lifetime to ``obj`` rather than to a block.

    The answer to the one real problem with scoping by ``with``: a block ends
    when the function returns, and a unit of work often does not. A handler
    that returns a streaming response, a generator, a task or a future has not
    finished — the framework drains or awaits it afterwards, and everything
    interesting happens then.

    ::

        with agentsight.conversation(cid):
            with agentsight.turn():
                agentsight.user_message(text)
                return agentsight.wrap(StreamingResponse(body()))

    Returns ``obj`` unchanged when there is no turn to bind, so it is always
    safe to leave in place.
    """
    try:
        turn = ags_context.current_turn()
        if turn is None:
            return obj
        return turn.wrap(obj)
    except Exception as exc:  # pragma: no cover
        logger.debug("wrap failed: %s", exc)
        return obj


def end_turn(complete: bool = True) -> None:
    """End a turn whose lifetime you took over with ``keep_open()``.

    For work finished by a later callback — a websocket exchange, a queue
    reply — where there is no iterator or future to bind to.
    """
    try:
        turn = ags_context.current_turn()
        if turn is not None:
            turn.end(complete=complete)
    except Exception as exc:  # pragma: no cover
        logger.debug("end_turn failed: %s", exc)


def abandon_turn() -> None:
    """Mark the active turn unfinished, so it is archived but never projected.

    Needed because an application that detects its own client disconnect
    (``if await request.is_disconnected(): break``) then returns *normally* —
    from the SDK's side that is indistinguishable from success, so it has to
    be told.
    """
    try:
        turn = ags_context.current_turn()
        if turn is not None:
            turn.abandon()
    except Exception as exc:  # pragma: no cover
        logger.debug("abandon_turn failed: %s", exc)


def conversation(conversation_id: Optional[str] = None, **kwargs: Any) -> ConversationScope:
    """Open a conversation scope. Context manager or decorator.

    ``conversation_id`` is generated when omitted: losing the data would be
    worse than a synthetic id.
    """
    return ConversationScope(conversation_id, **kwargs)


def open_conversation(conversation_id: str, **kwargs: Any) -> None:
    """The visit phase — records the conversation with ``is_used=False``.

    Sent immediately rather than batched, because the point of this call is to
    exist before any interaction does. The first turn then upserts the same
    row to ``is_used=True``, which is what separates "widget loaded" from
    "user engaged" for the Unique Interaction metric.
    """
    from agentsight.sdk.core import get_exporter, is_enabled

    if not is_enabled():
        return

    exporter = get_exporter()
    if exporter is None:
        return

    scope = ConversationScope(conversation_id, **kwargs)
    block: Dict[str, Any] = {"conversation_id": scope.conversation_id, "spans": []}
    from agentsight.sdk.semconv import ConversationAttributes

    for kwarg, attribute in ConversationAttributes.BY_KWARG.items():
        if attribute in scope.attributes:
            block[kwarg] = scope.attributes[attribute]
    if ConversationAttributes.METADATA in scope.attributes:
        block["metadata"] = scope.attributes[ConversationAttributes.METADATA]
    block["is_used"] = False

    try:
        exporter._post({"sdk": {"name": "agentsight-python"}, "conversations": [block]})
    except Exception as exc:  # pragma: no cover
        logger.debug("open_conversation failed: %s", exc)


def _emit_span(kind: str, name: str, attributes: Dict[str, Any]) -> None:
    """A point-in-time span for something that has no duration to measure."""
    from agentsight.sdk.core import get_tracer, is_enabled

    if not is_enabled() or not ags_context.tracking_enabled():
        return
    tracer = get_tracer()
    if tracer is None:
        return

    full = dict(ags_context.conversation_attributes())
    full[SpanAttributes.KIND] = kind
    full[SpanAttributes.ENTITY_NAME] = name
    full.update({k: v for k, v in attributes.items() if v is not None})

    turn = ags_context.current_turn()
    if turn is not None and turn.turn_id:
        full[TurnAttributes.ID] = turn.turn_id

    span = tracer.start_span(name, attributes=full)
    span.end()


def button(
    button_event: str,
    label: str,
    value: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a button click. Explicit because a click happens in the browser."""
    try:
        _emit_span(
            SpanKind.BUTTON,
            label or button_event,
            {
                ButtonAttributes.EVENT: button_event,
                ButtonAttributes.LABEL: label,
                ButtonAttributes.VALUE: value,
                SpanAttributes.METADATA: to_json(metadata) if metadata else None,
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("button failed: %s", exc)


def attachments(
    files: List[Any],
    sender: str = MessageAttributes.SENDER_USER,
    mode: str = "base64",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record uploads. Explicit because blobs cannot ride in spans.

    The span records *that* an upload happened, with a descriptor per file. The
    bytes still go over the existing ``/api/attachments/`` route, unchanged
    from 0.0.x — a span pipeline sized in spans is the wrong place to push
    megabytes through, and losing a batch under backpressure would mean losing
    a customer's file rather than a metric.
    """
    try:
        _emit_span(
            SpanKind.ATTACHMENT,
            f"{len(files)} attachment(s)",
            {
                AttachmentAttributes.SENDER: sender,
                AttachmentAttributes.MODE: mode,
                AttachmentAttributes.COUNT: len(files),
                AttachmentAttributes.FILES: to_json(
                    [_describe_attachment(f) for f in files]
                ),
                SpanAttributes.METADATA: to_json(metadata) if metadata else None,
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("attachments failed: %s", exc)


def _describe_attachment(file: Any) -> Dict[str, Any]:
    """Name, size and type — whatever of those the object will admit to.

    Users pass paths, file objects, dicts and framework upload objects, and no
    single accessor covers them. Anything undiscoverable is simply absent
    rather than guessed.
    """
    if isinstance(file, dict):
        return {
            key: file[key]
            for key in ("name", "filename", "size", "mime_type", "content_type")
            if key in file and key != "content"
        }

    descriptor: Dict[str, Any] = {}
    for attribute, key in (
        ("filename", "name"),
        ("name", "name"),
        ("size", "size"),
        ("content_type", "mime_type"),
    ):
        value = getattr(file, attribute, None)
        if value is not None and key not in descriptor:
            descriptor[key] = value if isinstance(value, (str, int)) else str(value)
    if not descriptor and isinstance(file, str):
        descriptor["name"] = file
    return descriptor
