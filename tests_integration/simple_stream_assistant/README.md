# simple_stream_assistant

Integration tests for token-by-token streaming OpenAI assistants — a single-node streamer and a function-call-capable streamer — plus a subprocess runner that executes the example scripts.

## Assistants

### `simple_stream_assistant.py` — `SimpleStreamAssistant`

A one-node assistant wrapping a streaming `OpenAITool` (`is_streaming=True`, default `gpt-4o-mini`) that streams the model response token-by-token from input to output.

Topology:

```
(agent_input_topic) [input]
        |
        v
[LLMStreamNode: OpenAITool]   (is_streaming=True)
        |
        v
(agent_output_topic) [output]
```

### `simple_stream_function_call_assistant.py` — `SimpleStreamFunctionCallAssistant`

A three-node assistant that routes user input through a tool-calling LLM: if the model requests a tool call it runs a `FunctionCallTool` and summarizes the result, otherwise it answers directly, with the final `OpenAITool` node streaming the response to output.

Topology:

```
                    (agent_input_topic) [input]
                              |
                              v
                   [OpenAIInputNode: OpenAITool]
                    /                          \
      --when=has_tool_call-->          --when=has_no_tool_call-->
                  |                                |
                  v                                |
        (function_call_topic)                      |
                  |                                |
                  v                                |
   [FunctionCallNode: FunctionCallTool]            |
                  |                                |
                  v                                v
       (function_result_topic)             (summary_topic)
                   \                          /
                    \                        /   (LLMStreamNode subscribes to
                     v                      v     function_result_topic OR summary_topic)
                   [LLMStreamNode: OpenAITool]
                              |
                              v
                   (agent_output_topic) [output]
```

## Examples

- `simple_stream_assistant_example.py` — Streams `SimpleStreamAssistant` for a greeting ("Hello, my name is Grafi..."), printing each streamed chunk with a `_` separator to show token-by-token delivery; asserts every message has `role == "assistant"`, that "Grafi" appears in the accumulated content, and that exactly 12 events were persisted.
- `simple_stream_function_call_assistant_example.py` — Streaming *with* a function call: asks `SimpleStreamFunctionCallAssistant` for the weather in postcode 12345, exercising the `has_tool_call` route through the mock `WeatherMock` tool; asserts "bad" and "12345" appear in the streamed content.
- `simple_stream_function_call_assistant_no_function_call_example.py` — Streaming *without* a function call: asks `SimpleStreamFunctionCallAssistant` "what's AWS EC2?", exercising the `has_no_tool_call` (summary) route that bypasses the tool; asserts "EC2" appears in the streamed content.

## Runner

- `run_simple_stream_assistant.py` — Discovers and runs every `*_example.py` script in this directory as a subprocess (skipping any with `ollama`/`_local` in the name unless `--no-pass-local` is passed), then prints a pass/fail summary and exits non-zero on any failure.
