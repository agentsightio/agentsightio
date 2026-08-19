---
outline: deep
---

<CopyMarkdownButton />

# Attachments

Files shared in a conversation, with a deliberate split into two calls. The
difference between them is whether the file's **bytes** travel, and that is
always your explicit choice rather than a mode you configure.

| Call | What it does |
|---|---|
| `record_attachments()` | records *that* files exist. Moves no bytes. |
| `upload_attachments()` | uploads the files and stores them with the conversation. |

## Recording that a file exists

For files whose contents already live somewhere else — your own storage, a CDN,
a bucket the customer uploaded to directly:

```python
with agentsight.conversation("wa-3859"):
    agentsight.record_attachments([
        {"filename": "receipt.pdf", "mime_type": "application/pdf", "size": 20481},
    ])
```

This records the name, size and type, and **nothing else**. The bytes stay where
they are, and the files do not appear in the dashboard. It is the right call when
you want the conversation's history to know a file was part of it, and the wrong
call if you expected to be able to open it afterwards.

| Parameter | Type | Default |
|---|---|---|
| `files` | `list` | required |
| `sender` | `str` | `"end_user"` |
| `metadata` | `dict` | — |

`files` takes descriptors in whatever shape you already have them: dictionaries
like the one above, framework upload objects, or plain paths. Whatever can be
read off them — name, size, MIME type — is recorded, and anything that cannot is
left out rather than guessed at.

`sender` is `"end_user"` or `"agent"`, for who shared the file.

Like every other tracking call, it needs an active conversation scope, returns
nothing, and never raises.

## Uploading the files themselves

```python
with agentsight.conversation("wa-3859"):
    agentsight.upload_attachments("/tmp/receipt.pdf")
```

This uploads the bytes, attaches them to the conversation, and records the same
descriptor for you afterwards. One file or a list of them, and each may be:

- **a path** — `str` or `os.PathLike`;
- **an open file object** — read as bytes, named from its `.name`;
- **a dictionary** — `{"filename": ..., "data": ...}` where `data` is raw bytes,
  a file object, or an already-base64-encoded string. `mime_type` is optional and
  guessed from the filename when absent.

```python
agentsight.upload_attachments(
    [
        {"filename": "report.pdf", "data": pdf_bytes},
        open("screenshot.png", "rb"),
    ],
    metadata={"origin": "customer_upload"},
)
```

| Parameter | Type | Default |
|---|---|---|
| `files` | one attachment or a list | required |
| `conversation_id` | `str` | the active scope |
| `sender` | `str` | `"end_user"` |
| `metadata` | `dict` | — |
| `timeout` | `float` | `30` |

`conversation_id` defaults to the conversation you are inside, and may be passed
explicitly when you are not inside one. The conversation is created if it does
not exist yet, so uploading immediately after opening a scope is safe even though
tracking is delivered in the background.

It returns the backend's response, and it needs the HTTP transport — file bytes
always travel over the network, so a file exporter or a custom span exporter
cannot carry them.

## This one blocks, and this one raises

Every other call in the SDK returns immediately, records in the background, and
**never** raises into your code. `upload_attachments()` does the opposite on both
counts, deliberately: it moves a customer's data rather than telemetry, and
silently dropping a file somebody believes was delivered is worse than an
exception.

```python
try:
    agentsight.upload_attachments(uploaded_file)
except ValueError:
    ...      # something about the call was wrong
except agentsight.UploadError as exc:
    ...      # the upload was refused or could not be made
```

**`ValueError`** is a caller mistake, and the message says which: no filename,
no data, a string that is not valid base64, a path that does not exist, an empty
list, or no conversation to attach to.

**`UploadError`** is everything on the other side — the request was refused, the
network failed, or credentials are missing. It carries `status_code` and
`response` so you can tell those apart in code.

## Size limits

These are properties of the upload endpoint, so they apply however you pass the
file:

| Limit | Value |
|---|---|
| One file, decoded | 25 MB |
| Files per request | 10 |
| Whole request, on the wire | 40 MB |

The last two are separate numbers because base64 inflates by a third: a 25 MB
file arrives as roughly 33.4 MB of encoded text, so the request ceiling has to
sit above the file ceiling rather than match it. Ten files at the maximum size do
not fit in one request — split them.

Exceeding any of the three is refused with a **413** whose detail names the
limit it passed — and, for the per-file ceiling, the file — raised to you as
`UploadError` with that status. It is
not retryable by resending the same request, which is what makes it a 413 rather
than an ordinary error.

These are the figures the hosted service enforces. A self-hosted deployment
configures its own.

## Next

- [Conversations](./conversations.md) — the scope both calls record into
- [Turns & Messages](./turns-and-messages.md) — the exchange a shared file
  belongs to
- [What the SDK sends](/getting-started/what-the-sdk-sends) — everything that
  leaves your process, and the limits on the rest of it
