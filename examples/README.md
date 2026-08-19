# Examples — seeing what the SDK actually emits

Each script runs on its own and exercises one integration, writing the spans it
produced to disk as **the exact JSON body the ingest endpoint would have
received** — the same `build_payload()` the HTTP transport uses, so what you
read here is what the backend will get.

Nothing needs an API key, an account or a network.

```bash
python examples/01_plain.py
```

Each run empties its own output directory first, so what you read afterwards is
that run and not a pile of earlier ones. Point the whole tree somewhere else
with `AGENTSIGHT_FILE_EXPORTER=/somewhere`; the per-script subdirectory is still
added.

| Script | What it shows |
|---|---|
| `01_plain.py` | The floor: no provider, no framework, no auto-instrumentation. Visit phase, conversation metadata, turns, message bursts, `@tool`/`@task`, buttons, attachments, an abandoned turn and a turn that raised. |
| `02_openai.py` | The OpenAI patch: chat, streaming with and without usage, embeddings, a failed call, and spend outside any turn. |
| `03_anthropic.py` | The Anthropic patch: messages, the `stream()` manager, cache tokens. Reports and exits if `anthropic` is not installed. |
| `04_llama_index.py` | The LlamaIndex dispatcher handler: tool spans no provider patch can see. |
| `05_langchain.py` | The LangChain callback handler: tools and LLM calls inside a chain, attached without `callbacks=[...]`. |
| `06_streaming.py` | `wrap()` — the one place a naive integration silently records wrong data. Shows the wrong version next to the right one. |

## Real provider calls

`02`–`05` call the real provider when the matching key is set, and fall back to
a stub otherwise. The stub is not a mock of our code: it is a real provider
client over a fake transport (`httpx.MockTransport`), or the framework's own
`MockLLM` / fake chat model. Every line of our instrumentation still runs — only
the socket is replaced.

**Importing `agentsight` runs `load_dotenv()`,** so a key sitting in this
repository's `.env` counts as present even though nobody typed it this morning.
Each script prints which mode it chose before doing anything. To force the stub:

```bash
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/02_openai.py
```

## Reading the output

The terminal summary is a convenience. The files are the artefact:

```bash
ls examples/traces/04_llama_index/
jq '.conversations[].spans[] | {kind, name, attributes}' examples/traces/04_llama_index/*.json
```

One file per export batch, named so a directory listing is in export order —
within a run and across runs. A payload contains one block per conversation,
each block carrying the conversation's own fields plus every span, whole:
attributes, message events, and the `otel` sub-object with resource, scope,
links and dropped-record counts.

Nothing is ever summarised away on the way out. That is deliberate — a metric
invented next year has to be computable from history rather than from the day
somebody thought of it.

## What these are not

They do not prove the *projection* rules — which spans become rows, how token
spend is booked, what an incomplete turn is and is not allowed to write. Those
are the API's side of the contract and are tested there. These scripts stop at
the payload.
