# OpenTelemetry Tracing Guide

Graphite traces every invocation with OpenTelemetry. Each run of an assistant,
workflow, node or tool is a span, nested as they call one another, with its
attributes named as [OpenInference](https://github.com/Arize-ai/openinference)
names them. Any OTLP backend can receive these spans (the OpenTelemetry
Collector, Jaeger, Tempo or a vendor), and OpenInference-aware ones, such as
Arize Phoenix, also show each span's kind, input and output. Installed
OpenInference instrumentors trace the calls of LLM clients, and those spans
are nested inside the tool spans.

## Exporting spans

```python
from grafi.common.instrumentations.tracing import setup_tracing

setup_tracing(project_name="my-agent")
```

That is all the setup there is. Call it once at startup, before invoking
assistants. `setup_tracing` sets OpenTelemetry's global tracer provider, which
Graphite's components trace through (it is the default tracer of
`ExecutionServices`). It exports their spans in batches to an OTLP collector
over gRPC. An argument not given follows OpenTelemetry's standard environment:

| Argument | From the environment | Default |
|----------|----------------------|---------|
| `project_name`, the spans' `service.name` and Phoenix project | `OTEL_SERVICE_NAME` | `grafi` |
| `endpoint` | `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` |
| `headers`, such as an API key | `OTEL_EXPORTER_OTLP_HEADERS` | none |

Give the endpoint's scheme: `http://` for a plain connection, `https://` for
TLS. In production, the environment alone can configure tracing:

```bash
export OTEL_SERVICE_NAME="my-agent"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://otel.example.com:4317"
export OTEL_EXPORTER_OTLP_HEADERS="api_key=..."
```

With `auto_instrument` (the default), every installed OpenInference
instrumentor traces its client too:
- `openinference-instrumentation-openai` comes with Graphite. It also covers
  DeepSeek and OpenRouter, which use the OpenAI client.
- To trace other clients, install their instrumentor. For example,
  `openinference-instrumentation-anthropic` traces Claude.

`setup_tracing` returns the provider, which you can flush (`force_flush()`),
shut down or add span processors to. Spans not yet exported are flushed when
the process exits. OpenTelemetry allows one global provider: if one is already
set, by an earlier call or by your application, `setup_tracing` keeps it and
returns it.

An application that sets up OpenTelemetry itself needs nothing from Graphite:
its global tracer provider traces Graphite's components too (its LLM clients
need instrumenting, as above). To trace a
runtime to a provider of its own, such as one exporting to memory in a test,
pass its tracer: `ExecutionServices(tracer=provider.get_tracer("grafi"))`.

### Running a backend locally

[Arize Phoenix](https://github.com/Arize-ai/phoenix) receives OTLP on port 4317
and shows the spans at <http://localhost:6006>:

```bash
docker run -p 6006:6006 -p 4317:4317 arizephoenix/phoenix
```

## Spans

| Span | `openinference.span.kind` |
|------|---------------------------|
| `{assistant}.run` | `AGENT` |
| `{workflow}.invoke` | `AGENT` |
| `{node}.invoke` | `CHAIN` |
| `{tool}.invoke` | `TOOL`, or `LLM` for an LLM tool |

| Attributes | Content |
|------------|---------|
| `id`, `name`, `type` | The component. An assistant adds `model`, and a node adds `subscribed_topics` and `publish_to_topics`. |
| `session.id`, `conversation_id`, `invoke_id`, `assistant_request_id`, `user_id` | The invoke context. `session.id` holds the conversation; backends group a session's traces by it. |
| `input.value`, `output.value`, with their `mime_type` | The input and the output, as JSON; as plain text when cut short or when JSON cannot hold them. |
| `error.type`, `error_id`, `error.details` | A failure. The span's status is then `ERROR`, and an `exception` event holds the traceback. `error_id` is the id in the failure's log line and in its failed events. |

## Settings

| Variable | Effect |
|----------|--------|
| `OPENINFERENCE_HIDE_INPUTS`, `OPENINFERENCE_HIDE_OUTPUTS` | When `true`, inputs or outputs are redacted on every span: Graphite's and the LLM clients' alike. A failure's message still shows in its span's status, exception event and `error.details`. OpenInference's other `OPENINFERENCE_HIDE_*` settings refine what LLM spans show. |
| `GRAFI_SPAN_MAX_PAYLOAD_CHARS` | A payload longer than this many characters is cut short (default 10,000; `0` means no limit). |
| `GRAFI_SPAN_DISABLE_PAYLOADS` | The older setting. When true, Graphite's spans carry no `input.value`, `output.value` or `error.details`. It does not cover LLM spans. |

## Troubleshooting

- **No spans arrive.** Check the collector's address, scheme included: the
  exporter logs a warning each time it cannot reach it. Also check that
  `setup_tracing` runs before the first invocation. If it logged that a tracer
  provider was already set, spans go wherever that provider sends them.
- **LLM calls are missing.** The client's OpenInference instrumentor must be
  installed: `setup_tracing` logs the ones it instrumented.
- **Spans are in the wrong project.** Pass `project_name`, or set
  `OTEL_SERVICE_NAME`.

## Resources

- [OpenTelemetry Python](https://opentelemetry-python.readthedocs.io/)
- [OpenTelemetry environment variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)
- [OpenInference](https://github.com/Arize-ai/openinference)
