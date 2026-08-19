"""The SDK on its own — no provider, no framework, no auto-instrumentation.

This is the floor: everything here is what you get from the explicit surface
alone. Read it first, because every other example adds spans on top of exactly
this shape rather than replacing it.

    python examples/01_plain.py
"""

import _common  # noqa: F401  — puts the repository root on sys.path

import agentsight as ags


@ags.tool
def search_orders(customer_id: str, status: str = "open"):
    return [{"id": "A-1", "total": 42.0}]


@ags.tool(name="fallback_to_human")
def escalate(reason: str):
    return "queued for an agent"


@ags.task
def rerank(candidates: list):
    return sorted(candidates)


def main() -> None:
    run = _common.start("01_plain", auto_instrument=False)

    # ---------------------------------------------------------------- visit
    # Somebody loaded the widget and typed nothing. Ingest creates the
    # conversation row without marking it engaged, which is the whole reason
    # this is a separate call: a decorator only fires once someone has already
    # engaged, so it cannot express "loaded but silent".
    ags.open_conversation("demo-visitor", device="mobile", source="web", language="en")
    ags.flush()  # forced early, purely so the visit lands in its own file

    # ------------------------------------------------------------ a real one
    with ags.conversation(
        "demo-plain",
        customer_id="user-12345",
        device="desktop",
        source="web",
        language="en",
        environment="development",
        name="Order questions",
    ):
        # The common shape: one message in, one out.
        with ags.turn("ask"):
            ags.user_message("Where is my order?")
            search_orders("user-12345")
            ags.agent_message("Order A-1 ships tomorrow.")

        # Messages have no rules. Three in, two out, plus internal work.
        with ags.turn("burst"):
            ags.user_message("actually")
            ags.user_message("two of them")
            ags.user_message("the second one is urgent")
            rerank(["b", "a"])
            ags.agent_message("Got it — checking both.")
            ags.agent_message("The urgent one is already out for delivery.")

        # A click happens in the browser, so it cannot be observed from here.
        # Recording it writes nothing to the transcript — the click was real, a
        # sentence describing it would not be — and today it writes no row
        # either: the span is archived and nothing projects it further, so
        # this is captured history rather than something to go and look at.
        ags.button("feedback", "Was this helpful?", "yes")

        # Files the customer sent. `upload_attachments` is the one that moves
        # bytes and creates the row; `record_attachments` only notes that a
        # file exists, for bytes you delivered some other way. This script
        # writes spans to disk rather than to the API, so it uses the recorder.
        ags.record_attachments(
            [{"filename": "receipt.pdf", "mime_type": "application/pdf"}]
        )

        # What the conversation turned out to be about. The scope above takes
        # metadata once, at the top, which is before any of this was known —
        # this merges into it rather than replacing it, so `customer_id` and
        # everything else set earlier survives. `remove=` is the only thing
        # that deletes a key; a falsy value like False is stored as data.
        ags.update_metadata({"topic": "delivery", "self_served": False})

        # Silent escalation: a turn with no agent message at all.
        with ags.turn("escalate"):
            ags.user_message("I want to talk to a person")
            escalate("customer asked")

        # The user closed the tab. The application noticed and returned
        # normally, which from here is indistinguishable from success — so it
        # has to say so. No transcript rows; the spend still counts.
        with ags.turn("abandoned"):
            ags.user_message("wait, never mind")
            ags.abandon_turn()

        # And a turn that raised. Same treatment, different reason.
        try:
            with ags.turn("boom"):
                ags.user_message("do the thing")
                raise RuntimeError("the thing exploded")
        except RuntimeError:
            pass

    run.finish()


if __name__ == "__main__":
    main()
