# Executor

Executor decorator record the executor action events, such as invoke, respond, and failed. Each time execute function has been called, the decorate will save the events to the event store. Also it will create tracer and push the tracer to the platform such as phoenix or Arize.
