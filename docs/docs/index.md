# ![Graphite Logo](./static/GRAPHITE_Logotype_Tagline_Binome.png)

**Graphite** is an open-source framework for creating **domain-specific AI assistants** via composable, agentic workflows. It emphasizes loose coupling and well-defined interfaces, enabling developers to construct flexible, modular systems. Each major layer – **assistant, node, tool,** and **workflow** – has a clear role in orchestrating or executing tasks, with events serving as the single source of truth for every state change or data exchange.

This documentation details how **Graphite’s event-driven architecture** seamlessly supports complex business logic, from initial user requests through advanced tool integrations (e.g., LLM calls, function calls, RAG retrieval). Dedicated topics manage pub/sub operations, providing mechanisms for input, output, and human-in-the-loop interactions. Meanwhile, commands encapsulate invoke logic for each tool, allowing nodes to delegate work without tight coupling.

Four critical capabilities—**observability, idempotency, auditability,** and **restorability**—underpin Graphite’s suitability for production AI environments. Observability is achieved via event sourcing and OpenTelemetry-based tracing, idempotency through carefully managed event stores and retry logic, auditability by logging every action and data flow, and restorability by maintaining offset-based consumption records that let workflows resume exactly where they left off.

Overall, **Graphite** offers a powerful, extensible foundation for building AI solutions that scale, adapt to evolving compliance needs, and gracefully handle failures or user-driven pauses. By combining a robust workflow engine, well-structured nodes and tools, and a complete event model, Graphite enables teams to develop sophisticated conversational agents and automated pipelines with confidence.

## What is Graphite

Graphite is an open-source platform that treats data as interconnected nodes and relationships, allowing you to:

- **Process complex data relationships** with graph-based algorithms
- **Visualize data connections** through interactive network diagrams
- **Build analytical pipelines** that leverage graph structures
- **Scale efficiently** with distributed processing capabilities

Whether you're analyzing social networks, tracking data lineage, exploring knowledge graphs, or building recommendation systems, Graphite provides the tools and abstractions you need to work effectively with connected data.

## Key Features

**Graph-Native Processing**: Built from the ground up to handle graph data structures efficiently, with optimized algorithms for common graph operations like traversals, clustering, and pathfinding.

**Visual Analytics**: Interactive visualization tools that help you explore and understand complex data relationships through customizable network diagrams and graph layouts.

**Flexible Data Integration**: Connect to various data sources including databases, APIs, and file formats, with built-in support for common graph data formats like GraphML, GEXF, and JSON.

**Extensible Architecture**: Plugin-based system that allows you to extend functionality with custom algorithms, data connectors, and visualization components.

**Performance Optimized**: Efficient memory management and parallel processing capabilities designed to handle large-scale graph datasets.

## Who Should Use Graphite?

Graphite is designed for data scientists, analysts, researchers, and developers who work with interconnected data, including:

- **Data Scientists** building recommendation engines or fraud detection systems
- **Business Analysts** exploring customer journey maps or organizational networks  
- **Researchers** analyzing citation networks, protein interactions, or social structures
- **Developers** building applications that require graph-based computations

## Getting Started

This documentation will guide you through:

1. **Installation and Setup** - Get Graphite running in your environment
2. **Core Concepts** - Understand graphs, nodes, edges, and data models
3. **Data Import** - Load your data from various sources
4. **Processing and Analysis** - Apply algorithms and transformations
5. **Visualization** - Create interactive graph visualizations
6. **Advanced Topics** - Custom plugins, performance tuning, and deployment

Ready to dive in? Start with our [Quick Start Guide](./getting-started/quickstart.md) to get Graphite up and running in minutes, or explore the [Core Concepts](./user-guide/architecture.md) to understand the fundamentals of graph-based data processing.

## Community and Support

Graphite is actively developed and maintained by the open-source community. Join us:

- **GitHub**: [github.com/binome-dev/graphite](https://github.com/binome-dev/graphite)
- **Issues and Feature Requests**: Use GitHub Issues for bug reports and feature requests
- **Discussions**: Join community discussions and get help from other users
- **Contributing**: Check out our contribution guidelines to help improve Graphite

---

*This documentation covers Graphite v0.0.x.*
