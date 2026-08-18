"""Semantic conventions for AgentSight spans.

Two namespaces, deliberately:

* ``agentsight.*`` for domain concepts that only exist in this product.
* ``gen_ai.*`` — the OpenTelemetry GenAI standard — for LLM facts.

The second is future-proofing, not pedantry: because LLM usage is recorded
under the standard names, spans produced by any GenAI-instrumented library
already carry the attributes our ingest projectors read.
"""

from typing import Any, Mapping, Optional


def string_attribute(attributes: Mapping[str, Any], key: str) -> Optional[str]:
    """An identity attribute the SDK wrote as a string, read back as one.

    OTel types attribute values as a wide union, but every attribute named in
    this module that gets used as a key — conversation id, turn id — is only
    ever written as a string. Anything else reads as absent, which downstream
    treats the same as the attribute not being there. Shared by the exporter
    and the buffering processor so the two reads cannot drift.
    """
    value = attributes.get(key)
    return value if isinstance(value, str) else None


class SpanKind:
    """Value of ``agentsight.span.kind``.

    Kinds the backend does not recognise are archived rather than rejected, so
    a newer SDK against an older backend degrades instead of failing.
    """

    TURN = "turn"
    TOOL = "tool"
    TASK = "task"
    LLM = "llm"
    BUTTON = "button"
    ATTACHMENT = "attachment"
    #: The visit phase — the conversation exists but nobody has engaged yet.
    #: Ingest upserts the row *without* marking it used; any other span kind
    #: in the conversation implies engagement and flips it. Carries the same
    #: semantics the old side-channel ``is_used=False`` payload did, but as a
    #: span, so it needs nothing from the transport but span delivery.
    CONVERSATION = "conversation"


class ConversationAttributes:
    """Carried on every span, inherited from the active conversation scope."""

    ID = "agentsight.conversation.id"
    CUSTOMER_ID = "agentsight.conversation.customer_id"
    CUSTOMER_IP = "agentsight.conversation.customer_ip"
    DEVICE = "agentsight.conversation.device"
    SOURCE = "agentsight.conversation.source"
    LANGUAGE = "agentsight.conversation.language"
    NAME = "agentsight.conversation.name"
    ENVIRONMENT = "agentsight.conversation.environment"
    METADATA = "agentsight.conversation.metadata"

    #: Public ``conversation()`` keyword -> attribute name. Ingest reverses
    #: this to rebuild the Conversation row, so both sides stay in step by
    #: construction rather than by two lists that drift.
    BY_KWARG = {
        "customer_id": CUSTOMER_ID,
        "customer_ip_address": CUSTOMER_IP,
        "device": DEVICE,
        "source": SOURCE,
        "language": LANGUAGE,
        "name": NAME,
        "environment": ENVIRONMENT,
    }


class SpanAttributes:
    """Classification and payload common to all AgentSight spans."""

    KIND = "agentsight.span.kind"
    ENTITY_NAME = "agentsight.entity.name"
    ENTITY_INPUT = "agentsight.entity.input"
    ENTITY_OUTPUT = "agentsight.entity.output"
    METADATA = "agentsight.metadata"


class TurnAttributes:
    """One exchange.

    ``COMPLETE`` is the projection switch: every turn is exported, but a turn
    abandoned mid-stream, or one that raised, is archived and never projected
    into the transcript. The half-exchange guarantee is enforced at ingest,
    not by withholding the data — the token spend on a failed turn was real,
    and dropping the span would make it unrecoverable.

    ``INCOMPLETE_REASON`` says *why*, because an unhandled exception and a
    user closing the tab are different product signals. Set only when
    ``COMPLETE`` is false, from the closed ``REASON_*`` set below.

    ``ID`` tags every span produced inside a turn so TurnBufferingProcessor
    can group them without walking a parent chain it cannot see — a
    ReadableSpan exposes only its immediate parent.

    Latency is deliberately absent: it is the span's own duration. Recording
    it twice is how the two drift apart.
    """

    ID = "agentsight.turn.id"
    COMPLETE = "agentsight.turn.complete"
    INCOMPLETE_REASON = "agentsight.turn.incomplete_reason"

    #: The turn raised — an unhandled exception, a wrapped iterator or
    #: awaitable that blew up, a future that errored.
    REASON_ERROR = "error"
    #: The consumer walked away — client disconnect mid-stream, an explicit
    #: ``abandon_turn()``, a cancelled task.
    REASON_ABANDONED = "abandoned"
    #: Nothing ever ended the turn and the watchdog closed it at
    #: ``turn_timeout_ms``. Something wrapped by ``turn.wrap()`` was held
    #: but never drained.
    REASON_DEADLINE = "deadline"
    #: The process exited while the turn was still open; it was closed on the
    #: way out so the work done up to that point is not lost.
    REASON_SHUTDOWN = "shutdown"


class MessageAttributes:
    """A message is a span *event*, not an attribute.

    Attributes give a fixed number of slots; events are ordered, individually
    timestamped and unbounded — which is what lets a turn carry any number of
    messages from either sender in any order.
    """

    EVENT_NAME = "agentsight.message"

    SENDER = "agentsight.message.sender"
    CONTENT = "agentsight.message.content"
    METADATA = "agentsight.message.metadata"

    SENDER_USER = "end_user"
    SENDER_AGENT = "agent"


class ToolAttributes:
    """Projected onto ActionLog, plus its required synthetic Message."""

    NAME = "agentsight.tool.name"
    ARGUMENTS = "agentsight.tool.arguments"
    RESPONSE = "agentsight.tool.response"
    ERROR = "agentsight.tool.error"


class ButtonAttributes:
    """Projected onto Button.

    A click is its own kind rather than a message, because writing it as one
    would put "Button clicked: Yes" into a transcript a customer reads. The
    click is real data; the sentence describing it is not something anybody
    said.
    """

    EVENT = "agentsight.button.event"
    LABEL = "agentsight.button.label"
    VALUE = "agentsight.button.value"


class AttachmentAttributes:
    """Projected onto Attachment.

    The bytes never travel in a span — a span pipeline is the wrong shape for
    megabytes, and the batch queue is sized in spans, not bytes. What the span
    carries is the record that an upload happened, when, by whom, and enough
    per-file detail to reconcile it with the blobs.
    """

    SENDER = "agentsight.attachment.sender"
    MODE = "agentsight.attachment.mode"
    COUNT = "agentsight.attachment.count"
    #: JSON list of {name, size, mime} — descriptors only, never content.
    FILES = "agentsight.attachment.files"


class LLMAttributes:
    """OTel GenAI standard names, plus AgentSight additions.

    ``gen_ai.usage.{input,output}_tokens`` are the two standard fields. Every
    other category below has no GenAI equivalent yet, so it lives under
    ``agentsight.llm.*`` — but the two standard names keep third-party
    instrumentation compatible out of the box.
    """

    SYSTEM = "gen_ai.system"
    #: The model the call actually ran on — the resolved id
    #: (``gpt-4o-mini-2024-07-18``) whenever the provider reports one, falling
    #: back to what was asked for. This is the field cost and usage are keyed
    #: on, so it holds the id that was billed, not the id that was typed.
    REQUEST_MODEL = "gen_ai.request.model"
    #: What the caller asked for, when that differs from what ran
    #: (``gpt-4o-mini`` against the dated snapshot above). Present only on the
    #: difference, so its absence means the two agreed. Without it the alias
    #: a caller actually uses is unrecoverable, and "which of my model
    #: aliases is expensive" cannot be answered.
    REQUESTED_MODEL = "agentsight.llm.requested_model"
    #: ``True`` when REQUEST_MODEL came from ``agentsight.model_hint(...)``
    #: rather than from the call or its response — an assertion, not a
    #: measurement, and the archive must keep the two distinguishable (the
    #: same reasoning as USAGE_REPORTED). Present only when the hint was
    #: consumed; a call that resolved its own model never carries it, however
    #: many hint blocks it ran inside.
    MODEL_DECLARED = "agentsight.llm.model_declared"
    #: GenAI standard: "chat", "text_completion", "embeddings". Distinguishes an
    #: embedding call from a chat call without having to infer it from which
    #: token fields happen to be set.
    OPERATION = "gen_ai.operation.name"
    #: Whether the response was streamed. Streaming and non-streaming calls
    #: report usage through completely different mechanisms, so when a token
    #: count looks wrong this is the first thing worth knowing.
    STREAMING = "agentsight.llm.streaming"

    #: The call failed. Mirrors ``agentsight.tool.error``. Present only on
    #: failure, which is what makes a failed call distinguishable from one
    #: that legitimately reported zero tokens — without it, an error-rate
    #: metric cannot exist and a raised call either vanishes or masquerades
    #: as success. Tokens billed before the failure ride along: a streamed
    #: call that died halfway still spent them.
    ERROR = "agentsight.llm.error"

    #: ``False`` when a streamed call closed without the provider ever
    #: reporting usage (caller passed ``include_usage: False``, or the server
    #: ignored the option). Present only in that case. The duration on such a
    #: span is real; the 0/0 token counts are *unknowns*, not zeros — ingest
    #: must not read them as "the model returned nothing", and no rollup may
    #: treat their absence of tokens as free.
    USAGE_REPORTED = "agentsight.llm.usage_reported"

    #: Billable input, *excluding* anything served from or written to cache.
    INPUT_TOKENS = "gen_ai.usage.input_tokens"
    #: Billable output. On both providers this **already includes** reasoning
    #: tokens — see REASONING_TOKENS.
    OUTPUT_TOKENS = "gen_ai.usage.output_tokens"

    # -- cache ---------------------------------------------------------------
    #: Served from cache. Cheap — ~0.1x input on Anthropic, ~0.5x on OpenAI.
    CACHE_READ_TOKENS = "agentsight.llm.cache_read_tokens"
    #: Written to cache. Costs MORE than plain input (1.25x at 5m TTL, 2x at
    #: 1h on Anthropic), which is why it cannot be folded into input_tokens.
    CACHE_WRITE_TOKENS = "agentsight.llm.cache_write_tokens"

    # -- reasoning -----------------------------------------------------------
    #: Thinking/reasoning tokens. **A subset of OUTPUT_TOKENS, not an
    #: addition** — adding it to a total double-counts. Recorded separately
    #: because "how much did we spend thinking" is its own question.
    #:
    #: OpenAI reports it as completion_tokens_details.reasoning_tokens.
    #: Anthropic does NOT expose a counter: extended thinking is billed inside
    #: output_tokens with no breakdown, so this stays 0 there regardless of
    #: the `display` setting.
    REASONING_TOKENS = "agentsight.llm.reasoning_tokens"

    # -- modality ------------------------------------------------------------
    #: Also subsets of input/output, for the same reason as reasoning.
    AUDIO_INPUT_TOKENS = "agentsight.llm.audio_input_tokens"
    AUDIO_OUTPUT_TOKENS = "agentsight.llm.audio_output_tokens"

    #: Separate models and separate prices — never a subset of anything.
    EMBEDDING_TOKENS = "agentsight.llm.embedding_tokens"

    # There is deliberately no cost attribute. Cost is a pure function of the
    # counts above, the model and the date, so the backend derives it on
    # arrival — one rate table for every customer, and a rate that turns out to
    # have been wrong can be restated instead of being frozen into whichever
    # release each caller pinned.

    #: Categories that are their own billable line. Summing these gives the
    #: true total; summing every attribute above would double-count.
    BILLABLE = (
        INPUT_TOKENS,
        OUTPUT_TOKENS,
        CACHE_READ_TOKENS,
        CACHE_WRITE_TOKENS,
        EMBEDDING_TOKENS,
    )

    #: Breakdowns of a billable category. Reported, never summed into a total.
    SUBSETS = (
        REASONING_TOKENS,
        AUDIO_INPUT_TOKENS,
        AUDIO_OUTPUT_TOKENS,
    )
