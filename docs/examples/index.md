---
outline: deep
---

<CopyMarkdownButton />

# Examples

The repository ships six runnable scripts in
[`examples/`](https://github.com/agentsightio/agentsightio/tree/main/examples).
Each one exercises one part of the SDK and writes the spans it produced to disk
as **the exact JSON body the API would have received** — built by
the same function the HTTP transport uses, so what you read afterwards is what
the server would have got.

Nothing needs an API key, an account or a network.

```bash
git clone https://github.com/agentsightio/agentsightio
cd agentsightio
pip install agentsight
python examples/01_plain.py
```

The scripts run against the checkout, so they always match the code they sit
next to. Installing `agentsight` brings the dependencies; the provider and
framework examples additionally need the package they demonstrate (`openai`,
`anthropic`, `llama-index-core`, `langchain-core`) and say so when it is
missing.

| Script | What it shows |
|---|---|
| [`01_plain.py`](./plain) | The explicit surface on its own: visits, conversation metadata, turns, message bursts, `@tool`/`@task`, buttons, attachments, an abandoned turn and a turn that raised. |
| [`02_openai.py`](./openai) | The OpenAI patch: chat, streaming with and without usage, embeddings, a failed call, and spend outside any turn. |
| [`03_anthropic.py`](./anthropic) | The Anthropic patch: messages, the `stream()` manager, cache tokens. |
| [`04_llama_index.py`](./llamaindex) | The LlamaIndex handler: tool spans no provider patch can see. |
| [`05_langchain.py`](./langchain) | The LangChain handler: tools and LLM calls inside a chain, attached without `callbacks=[...]`. |
| [`06_streaming.py`](./streaming) | `wrap()` — the one place a naive integration silently records wrong data. Shows the wrong version next to the right one. |

Read `01_plain.py` first. Every other script adds spans on top of exactly that
shape rather than replacing it.

In the snippets on these pages, `ags` is the module — `import agentsight as
ags`, exactly as in the scripts. It is not the
[API client instance](/api/) that the API Client pages call `ags`.

## Offline and live

`02`–`05` call the real provider when the matching key is set, and fall back to
a stub otherwise. The stub is not a mock of the SDK: it is a real provider
client over a fake transport (`httpx.MockTransport`), or the framework's own
fake model. Every line of the instrumentation still runs — only the socket is
replaced, and a failed call fails identically in both modes.

**Importing `agentsight` runs `load_dotenv()`** when `python-dotenv` is
installed, so a provider key sitting in a `.env` file counts as present even
though nobody typed it. Real calls are billed; each script prints which mode it
chose before doing anything. To force the stub:

```bash
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/02_openai.py
```

## Reading the output

Each run empties its own directory under `examples/traces/` first, so what you
read afterwards is that run and not a pile of earlier ones. The terminal
summary — the span tree, token counts, incomplete-turn markers — is a
convenience; the files are the artefact:

```bash
ls examples/traces/01_plain/
jq '.conversations[].spans[] | {kind, name, attributes}' examples/traces/01_plain/*.json
```

One file per export batch, named so a directory listing is in export order. A
payload carries one block per conversation: the conversation's own fields plus
every span, whole — attributes, message events, and the `otel` sub-object.
[What the SDK sends](/getting-started/what-the-sdk-sends) documents every
field.

Point the whole tree somewhere else with `AGENTSIGHT_FILE_EXPORTER=/somewhere`;
the per-script subdirectory is still added.

## Sending to a real backend

To watch a script land in the dashboard instead, skip the file exporter and let
`init()` read the usual configuration:

```bash
AGENTSIGHT_EXAMPLES_HTTP=1 AGENTSIGHT_API_KEY=ags_... python examples/01_plain.py
```

With `AGENTSIGHT_API_ENDPOINT` set as well, the spans go to that endpoint —
useful against a staging deployment.

## What these do not show

The scripts stop at the payload. What the server does with it — which spans
become transcript rows, how token counts are priced into spend, what an
incomplete turn is allowed to write — is the other side of the contract, and
the dashboard and [API client](/api/) are where you see its results.
