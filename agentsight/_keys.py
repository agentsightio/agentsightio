"""What makes a data entity key one the API refuses.

Both planes need the same answer. The tracking SDK drops such a key before it
can cost a whole batch, and the API client refuses it before anything is sent.
Neither package imports the other, so the rule lives at the top level next to
``_settings`` and ``_metadata``, and there is one definition of it.
"""

from typing import Optional


def refused_character(text: str) -> Optional[str]:
    """What the API refuses in ``text``, named for a message, or ``None``.

    Two things: a NUL, which the server cannot store, and an unpaired
    surrogate (U+D800 to U+DFFF), which is not valid text and cannot even be
    encoded into a request. A real astral character is never one of these: a
    Python ``str`` holds it as a single code point above the surrogate range.
    """
    for char in text:
        if char == "\x00":
            return "a NUL character"
        if "\ud800" <= char <= "\udfff":
            return "an unpaired surrogate character"
    return None
