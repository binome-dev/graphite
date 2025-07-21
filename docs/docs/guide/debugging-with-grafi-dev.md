# Debugging and Development with Grafi-Dev: A Complete Guide

The Graphite AI framework is powerful, but like any complex system, debugging workflows and understanding execution flow can be challenging. Enter **grafi-dev** - a specialized development server designed to make debugging Graphite applications intuitive and efficient.

In this guide, we'll explore how to use grafi-dev to debug your Graphite workflows, inspect events in real-time, and streamline your development process.

## What is Grafi-Dev?

Grafi-dev is a development server that provides real-time debugging capabilities for Graphite applications. It offers:

- **Real-time event monitoring**: See events as they flow through your workflow
- **Interactive debugging**: Pause, inspect, and step through workflow execution  
- **Event inspection**: Deep dive into event payloads and transformations
- **Workflow visualization**: Understand how your events are being processed
- **Hot reload**: Make changes and see them reflected immediately

## Installation and Setup

### Prerequisites

Before installing grafi-dev, ensure you have:
- Node.js (version 16 or higher)
- A Graphite project to debug
- Basic familiarity with Graphite workflows

### Installing Grafi-Dev

Install grafi-dev globally using npm:

```bash
npm install -g @binome-dev/graphite-dev
```

Or if you prefer using it locally in your project:

```bash
npm install --save-dev @binome-dev/graphite-dev
```

### Verify Installation

Check that grafi-dev is installed correctly:

```bash
grafi-dev --version
```

## Getting Started: Your First Debug Session

Let's walk through setting up grafi-dev with a simple Graphite workflow.

### Step 1: Prepare Your Graphite Project

First, ensure your Graphite project has a proper structure. Here's a minimal example:

```python
# workflow.py
from graphite import Workflow, event_handler

class MyWorkflow(Workflow):
    @event_handler("user.message")
    async def handle_message(self, event):
        print(f"Received: {event.data['message']}")
        await self.emit("response.generated", {
            "reply": f"Echo: {event.data['message']}"
        })

    @event_handler("response.generated")
    async def handle_response(self, event):
        print(f"Sending: {event.data['reply']}")
```

### Step 2: Configure Grafi-Dev

Create a `grafi-dev.config.js` file in your project root:

```javascript
module.exports = {
  // Port for the development server
  port: 3001,
  
  // Path to your Graphite application
  appPath: './workflow.py',
  
  // Enable hot reload
  hotReload: true,
  
  // Event filtering (optional)
  eventFilters: [
    'user.*',
    'response.*'
  ],
  
  // Debug settings
  debug: {
    pauseOnError: true,
    showEventPayloads: true,
    logLevel: 'debug'
  }
};
```

### Step 3: Start the Debug Server

Launch grafi-dev from your project directory:

```bash
grafi-dev start
```

You should see output similar to:

```
🚀 Grafi-Dev Server starting...
📊 Dashboard available at: http://localhost:3001
🔧 Watching for changes in: ./workflow.py
✅ Connected to Graphite application
```

### Step 4: Open the Debug Dashboard

Navigate to `http://localhost:3001` in your browser. You'll see the grafi-dev dashboard with several panels:

- **Event Stream**: Real-time view of events flowing through your workflow
- **Workflow Graph**: Visual representation of your event handlers and their connections
- **Inspector**: Detailed view of selected events and their payloads
- **Console**: Logs and debug output from your application

## Key Features and How to Use Them

### Real-Time Event Monitoring

The Event Stream panel shows all events as they occur in your workflow. Each event displays:

- **Timestamp**: When the event was emitted
- **Event Type**: The event name (e.g., "user.message")
- **Source**: Which handler emitted the event
- **Payload Size**: Amount of data in the event
- **Processing Status**: Whether the event was handled successfully

Click on any event to inspect its full payload in the Inspector panel.

### Interactive Debugging

#### Setting Breakpoints

You can set breakpoints directly in the dashboard:

1. Navigate to the Workflow Graph panel
2. Click on any event handler node
3. Select "Add Breakpoint" from the context menu

When execution hits a breakpoint, the workflow pauses and you can:
- Inspect the current event data
- Step through the handler line by line
- Modify event payloads before continuing
- Skip to the next event handler

#### Stepping Through Execution

When paused at a breakpoint, use the debug controls:

```bash
# Continue execution
c or continue

# Step to next line
s or step

# Step over function calls
n or next

# Step into function calls
i or into
```

### Event Inspection and Modification

The Inspector panel allows you to:

#### View Event Details

```json
{
  "type": "user.message",
  "timestamp": "2025-07-20T10:30:45.123Z",
  "source": "web_interface",
  "data": {
    "message": "Hello, Graphite!",
    "user_id": "user_123",
    "session_id": "sess_456"
  },
  "metadata": {
    "correlation_id": "corr_789",
    "retry_count": 0
  }
}
```

#### Modify Event Data

Before an event is processed, you can modify its payload:

1. Click on an event in the Event Stream
2. Edit the JSON in the Inspector panel
3. Click "Apply Changes"
4. The modified event will be processed with your changes

This is incredibly useful for testing edge cases without modifying your code.

### Workflow Visualization

The Workflow Graph panel provides a visual representation of your event flow:

- **Nodes** represent event handlers
- **Edges** show event flow between handlers
- **Colors** indicate handler status (idle, processing, error)
- **Thickness** of edges shows event frequency

You can:
- Click nodes to see handler code
- Hover over edges to see recent events
- Filter the graph by event types
- Export the graph as an image

## Advanced Debugging Techniques

### Conditional Breakpoints

Set breakpoints that only trigger under specific conditions:

```javascript
// In grafi-dev.config.js
module.exports = {
  debug: {
    conditionalBreakpoints: [
      {
        handler: "handle_message",
        condition: "event.data.user_id === 'admin'"
      },
      {
        handler: "handle_response",
        condition: "event.data.reply.includes('error')"
      }
    ]
  }
};
```

### Event Replay

Grafi-dev automatically records all events. You can replay them for testing:

1. Go to the Event Stream panel
2. Select events you want to replay
3. Click "Replay Selected Events"
4. Watch as the events are re-processed through your workflow

This is perfect for:
- Testing fixes after identifying bugs
- Reproducing intermittent issues
- Performance testing with real event patterns

### Custom Event Injection

Inject custom events for testing:

```javascript
// Through the dashboard
{
  "type": "test.custom_event",
  "data": {
    "test_parameter": "test_value",
    "scenario": "edge_case_1"
  }
}
```

Or programmatically:

```bash
curl -X POST http://localhost:3001/api/inject \
  -H "Content-Type: application/json" \
  -d '{
    "type": "user.message",
    "data": {"message": "Test message"}
  }'
```

## Performance Profiling

### Event Processing Metrics

Grafi-dev tracks performance metrics for each handler:

- **Average Processing Time**: How long handlers take to process events
- **Throughput**: Events processed per second
- **Memory Usage**: Memory consumption during processing
- **Error Rate**: Percentage of events that cause errors

### Bottleneck Identification

The Performance panel highlights:
- Slow handlers (processing time > threshold)
- Memory leaks (increasing memory usage)
- High error rates
- Queue backups (events waiting to be processed)

### Optimization Suggestions

Based on the metrics, grafi-dev provides optimization suggestions:

```
⚠️  Handler 'process_large_data' is taking 2.3s on average
💡 Suggestion: Consider breaking this into smaller, parallel tasks

🔍 Memory usage increased 45% in the last 5 minutes
💡 Suggestion: Check for memory leaks in event handlers

📈 Queue depth is growing for 'user.message' events  
💡 Suggestion: Consider adding more worker processes
```

## Integration with Development Workflow

### CI/CD Integration

You can run grafi-dev in headless mode for continuous integration:

```bash
# Run tests with grafi-dev monitoring
grafi-dev test --headless --config ci-config.js

# Generate performance report
grafi-dev profile --duration 60s --output performance-report.json
```

### Team Collaboration

Share debugging sessions with your team:

```bash
# Start shared session
grafi-dev start --share

# Others can connect to the session
grafi-dev connect --session <session_id>
```

Team members can:
- See the same event stream
- Set breakpoints collaboratively  
- Share event inspections
- Review performance metrics together

## Best Practices

### 1. Use Descriptive Event Names

Instead of generic names like "event1", use descriptive names:

```python
# ❌ Poor naming
await self.emit("event1", data)

# ✅ Good naming  
await self.emit("user.authentication_failed", {
    "user_id": user_id,
    "failure_reason": "invalid_password"
})
```

### 2. Structure Event Payloads Consistently

Maintain consistent payload structure for easier debugging:

```python
# Standard event payload structure
{
    "type": "user.message_received",
    "data": {
        # Main event data
        "message": "Hello",
        "user_id": "123"
    },
    "metadata": {
        # Debugging/tracking information
        "correlation_id": "corr_456",
        "source": "web_interface",
        "timestamp": "2025-07-20T10:30:45.123Z"
    }
}
```

### 3. Add Contextual Information

Include debugging context in your events:

```python
await self.emit("data.processing_started", {
    "data_type": "user_upload",
    "file_size": file_size,
    "processing_id": processing_id,
    # Debugging context
    "debug_info": {
        "handler": "process_upload",
        "thread_id": threading.current_thread().ident,
        "memory_usage": psutil.Process().memory_info().rss
    }
})
```

### 4. Use Event Filters Strategically

Configure filters to focus on relevant events:

```javascript
// Focus on user interactions and errors
eventFilters: [
    'user.*',           // All user events
    '*.error',          // All error events  
    'system.critical.*' // Critical system events
]
```

### 5. Regular Performance Reviews

Schedule regular performance reviews using grafi-dev:

```bash
# Weekly performance snapshot
grafi-dev profile --duration 1h --schedule weekly --alert-on-degradation
```

## Troubleshooting Common Issues

### Connection Issues

If grafi-dev can't connect to your Graphite application:

1. **Check the app path**: Ensure `appPath` in your config points to the correct file
2. **Verify dependencies**: Make sure your Graphite app has all required dependencies
3. **Check ports**: Ensure no other services are using the grafi-dev port
4. **Firewall settings**: Verify firewall isn't blocking the connection

### Performance Issues

If grafi-dev itself is slowing down:

1. **Reduce event history**: Limit the number of events kept in memory
2. **Use event filters**: Focus on specific event types
3. **Disable heavy features**: Turn off workflow visualization for high-throughput scenarios

```javascript
// Performance-optimized config
module.exports = {
  performance: {
    maxEventHistory: 1000,      // Keep only recent events
    enableVisualization: false, // Disable heavy graph rendering
    samplingRate: 0.1          // Sample 10% of events
  }
};
```

### Memory Leaks

If you notice memory usage growing:

1. **Check event retention**: Events might not be garbage collected
2. **Review breakpoints**: Paused workflows can accumulate events
3. **Monitor handler memory**: Look for handlers that don't release resources

## Advanced Configuration

### Custom Plugins

Extend grafi-dev with custom plugins:

```javascript
// custom-plugin.js
module.exports = {
  name: 'custom-metrics',
  
  onEventProcessed(event, duration) {
    // Send metrics to external system
    metricsClient.timing('event.processed', duration, {
      event_type: event.type
    });
  },
  
  onError(error, event) {
    // Custom error handling
    errorTracker.captureException(error, {
      event_context: event
    });
  }
};

// In grafi-dev.config.js
module.exports = {
  plugins: [
    require('./custom-plugin')
  ]
};
```

### Multiple Environment Support

Configure different settings for different environments:

```javascript
module.exports = {
  development: {
    port: 3001,
    debug: { logLevel: 'debug' },
    hotReload: true
  },
  
  staging: {
    port: 3002,
    debug: { logLevel: 'info' },
    hotReload: false,
    performance: { samplingRate: 0.5 }
  },
  
  production: {
    port: 3003,
    debug: { logLevel: 'error' },
    hotReload: false,
    performance: { samplingRate: 0.1 }
  }
};
```

## Conclusion

Grafi-dev transforms the Graphite development experience by providing powerful debugging and monitoring capabilities. With real-time event streams, interactive debugging, and performance profiling, you can:

- **Debug faster**: Identify issues quickly with real-time event monitoring
- **Understand better**: Visualize your workflow to see how events flow
- **Optimize effectively**: Use performance metrics to identify bottlenecks
- **Collaborate seamlessly**: Share debugging sessions with your team

The key to getting the most out of grafi-dev is to integrate it early in your development process. Don't wait until you have problems - use it from day one to build better, more reliable Graphite applications.

Remember: great debugging tools don't just fix problems - they prevent them. By understanding how your events flow and where your bottlenecks are, you can design better workflows from the start.

Start debugging smarter with grafi-dev today!

---

*For more information, check out the [grafi-dev GitHub repository](https://github.com/binome-dev/graphite-dev) and join our community discussions.*