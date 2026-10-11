# Release notes

## Unreleased

`InMemTopicEventQueue.fetch(consumer_id)` now waits indefinitely for new events.
Previously, direct calls used a one-second default timeout. Pass `timeout=1.0`
to preserve that behavior, or `timeout=0` for an immediate read. Calls through
`TopicBase.consume()` already defaulted to an indefinite wait.

Cancelled queue reads now propagate cancellation and must leave the read cursor
unchanged. Queue implementations must finish cancellation cleanup promptly;
workflow shutdown waits for all readers to finish.
