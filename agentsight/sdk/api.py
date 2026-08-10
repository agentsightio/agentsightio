"""The explicit calls — things no decorator can observe.

Each one has a one-sentence justification, and they are short:

* messages     — the text a human typed is not derivable from the call stack,
                 and guessing puts the wrong text in a client-facing transcript
* buttons      — a click happens in the browser
* attachments  — blobs cannot ride in spans
* open_conversation — a decorator only fires once someone has engaged, so it
                 cannot express "the widget loaded but nobody typed"
"""

from typing import Any, Dict, Iterable, List, Optional

from agentsight import _metadata
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
    """The visit phase — records that the conversation exists before any
    interaction does. The first turn is what marks it engaged, which is what
    separates "widget loaded" from "user engaged" for Unique Interaction.

    An ordinary span of kind ``conversation``, so it rides the same pipeline
    as everything else and needs nothing from the transport but span
    delivery. (It used to bypass the pipeline and POST a hand-built payload
    straight through the exporter — a coupling to one concrete transport
    that made every alternative exporter impossible.) The cost of the move
    is immediacy: it now arrives within an export interval rather than
    instantly, which for a widget-loaded event changes nothing.
    """
    from agentsight.sdk.core import get_tracer, is_enabled

    if not is_enabled():
        return
    tracer = get_tracer()
    if tracer is None:
        return

    scope = ConversationScope(conversation_id, **kwargs)
    attributes = dict(scope.attributes)
    attributes[SpanAttributes.KIND] = SpanKind.CONVERSATION
    attributes[SpanAttributes.ENTITY_NAME] = "conversation_opened"

    try:
        span = tracer.start_span("conversation_opened", attributes=attributes)
        span.end()
    except Exception as exc:  # pragma: no cover
        logger.debug("open_conversation failed: %s", exc)


def update_metadata(
    metadata: Optional[Dict[str, Any]] = None,
    *,
    remove: Optional[Iterable[str]] = None,
) -> None:
    """Add to or change the active conversation's metadata, keeping the rest.

    ``agentsight.conversation(...)`` takes metadata once, at the top of a
    handler, which is before most of what is worth recording has happened. This
    is the same field afterwards::

        agentsight.update_metadata({"plan": "enterprise", "escalated": False})
        agentsight.update_metadata(remove=["awaiting_reply"])

    Merging is shallow — a nested dict is replaced whole, not merged key by
    key — and **no value is filtered**: ``None``, ``False``, ``0`` and ``""``
    are stored as given. ``remove`` is the only thing that deletes a key, and
    naming a key that is not there is a no-op.

    The merge is against what this process knows, which is what the scope was
    opened with plus any earlier calls. Keys written by another process are not
    visible here, so they are not preserved — use
    ``AgentSight().conversations.update_metadata(...)`` when the previous state
    lives on the server rather than in this scope.

    Needs an active ``agentsight.conversation(...)`` scope; outside one there is
    nothing to update and the call is dropped with a debug line.
    """
    try:
        from agentsight.sdk.core import is_enabled

        if not is_enabled() or not ags_context.tracking_enabled():
            logger.debug(
                "update_metadata not recorded: no active conversation scope. "
                "Call it inside `with agentsight.conversation(...)`."
            )
            return

        scope = ags_context.current_conversation()
        if scope is None:  # pragma: no cover — tracking_enabled() implies one
            return

        _metadata.check(metadata, remove)
        scope.set_metadata(_metadata.merge(scope.metadata, metadata, remove))

        # Emitted, not merely stored, because the merged document only reaches
        # the backend on a span — and the most natural moment to call this is
        # as a conversation closes, when there may be no further span to ride.
        # `conversation` is the right kind for a second reason: ingest reads
        # any other kind as "someone engaged", and recording metadata is not
        # engagement.
        _emit_span(SpanKind.CONVERSATION, "metadata_updated", {})
    except Exception as exc:
        logger.debug("update_metadata failed: %s", exc)


def _emit_span(kind: str, name: str, attributes: Dict[str, Any]) -> None:
    """A point-in-time span for something that has no duration to measure."""
    from agentsight.sdk.core import get_tracer, is_enabled

    if not is_enabled():
        return
    if not ags_context.tracking_enabled():
        # No conversation scope, so there is nothing to file this under and it
        # is dropped. Said out loud at debug because from the caller's side a
        # silent no-op and a successful record look identical.
        logger.debug(
            "%s not recorded: no active conversation scope. Call it inside "
            "`with agentsight.conversation(...)`.",
            kind,
        )
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
    """Record a button click. Explicit because a click happens in the browser.

    Needs an active ``agentsight.conversation(...)`` scope; outside one there
    is nothing to attach the click to and it is dropped with a debug line.

    **Recorded, not yet surfaced.** The click is archived verbatim — event,
    label, value, metadata and the conversation it belongs to — but no read
    API or dashboard currently displays it, so there is nothing to query it
    back with today. Keep calling this if you want the record: the archive is
    complete enough to reconstruct button analytics exactly, whenever
    something is built to consume them. What you should not do is build a
    feature that depends on reading these back this week.
    """
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


def record_attachments(
    files: List[Any],
    sender: str = MessageAttributes.SENDER_USER,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record that files exist, for bytes you moved yourself.

    **This moves no bytes and does not put the files in the dashboard.** Use
    :func:`agentsight.upload_attachments` for that — it is the call that
    uploads, and it records this span for you afterwards. Reach for this one
    only when the bytes already went somewhere else (your own storage, a CDN)
    and you want AgentSight's archive to know the files were part of the
    conversation.

    Blobs cannot ride in spans: a pipeline sized in spans is the wrong place
    to push megabytes through, and losing a batch under backpressure would
    mean losing a customer's file rather than a metric. So this carries a
    descriptor per file — name, size, type — and nothing else.
    """
    _attachment_span(files, sender=sender, metadata=metadata)


def _attachment_span(
    files: List[Any],
    sender: str = MessageAttributes.SENDER_USER,
    mode: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """The span itself. ``mode`` is how the bytes travelled, when they did —
    set by ``upload_attachments``, absent for a record-only call, and never a
    user-facing choice (that was removed in 0.1.0)."""
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
