# Release notes

## Unreleased

`InMemTopicEventQueue.fetch(consumer_id)` now waits indefinitely for new events.
Previously, direct calls used a one-second default timeout. Pass `timeout=1.0`
to preserve that behavior, or `timeout=0` for an immediate read. Calls through
`TopicBase.consume()` already defaulted to an indefinite wait.

Cancelled queue reads now propagate cancellation and must leave the read cursor
unchanged. Queue implementations must finish cancellation cleanup promptly;
workflow shutdown waits for all readers to finish.

Each `TopicBase.publish_data()` call now creates a fresh destination publication
ID. Fan-out to different topics produces distinct IDs, with `emission_id`
recording the immediate source event's ID. Matched routes to the same topic are
deduplicated before delivery. Recording the same publication remains idempotent;
calling `publish_data()` again creates another publication. Older event records
without `emission_id` still decode with a value of `None`.

Parallel execution now stores every streaming publication and consumption record
with its actual offset. Output consumption is committed and recorded only for
publications already confirmed persisted. If a producer fails, stops or is
cancelled mid-stream, its unpersisted preview chunks remain unacknowledged and
may be delivered again when the input is retried. Stored stream history therefore
contains more raw records. Use `get_async_output_events()` explicitly for a
derived text display; its projections must not be persisted as recovery records.

Recovery restores publications in per-topic offset order, then consumer cursors,
before determining readiness. Missing or conflicting publication offsets and
consumption beyond surviving publications raise `WorkflowError` instead of
silently renumbering history or skipping records. Historical publications lost
through ID collisions or stream aggregation cannot be reconstructed automatically.
This does not make legacy acknowledgment and publication writes atomic.

Ready nodes restored in sequential mode now run in node-definition order,
rather than the history's publication order.

In-flight requests, including paused HITL requests from older parallel runs,
may fail to resume if stream aggregation or input fan-out ID collisions removed
required publications. Backward-compatible event decoding does not repair those
histories; requests with complete history can still resume.

The current parallel engine still exposes internal-topic publications before
their producer finishes and persists them. With fan-in, a failed producer can
leave a missing earlier offset while another producer or a downstream node has
already persisted later publications or consumption. Recovery reports this gap
with `WorkflowError`. Output acknowledgment filtering does not repair that case;
atomic step commits in the planned journal work are needed to close it.
