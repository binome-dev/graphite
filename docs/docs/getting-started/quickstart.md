# Getting Started with Graphite: The Hello, World! Assistant

[Graphite](https://github.com/binome-dev/graphite) is a powerful event-driven AI agent framework built for modularity, observability, and seamless composition of AI workflows. This comprehensive guide will walk you through creating your first ReAct (Reasoning and Acting) agent using the `grafi` package. In this tutorial, we'll build a function-calling assistant that demonstrates how to integrate language models with google search function within the Graphite framework, showcasing the core concepts of event-driven AI agent development.

---

## Prerequisites

Make sure the following are installed:

* Python **>=3.10, \<3.13** (required by the `grafi` package)
* [Poetry](https://python-poetry.org/docs/#installation)
* Git

> ⚠️ **Important:** `grafi` requires Python >= 3.10 and \<3.13. Other python version is not yet supported.

---

## Create a New Project

<!-- ```bash
mkdir graphite-react
cd graphite-react
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">mkdir</span> graphite-react
<span style="color:#FF4689">cd</span> graphite-react
</code></pre></div>

This will create the `pyproject.toml` file that Poetry needs.

<!-- ```bash
poetry init --name graphite-react -n
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">poetry</span> init <span style="color:#AE81FF">--name</span> graphite-react <span style="color:#AE81FF">--n</span></code></pre></div>

Be sure to specify a compatible Python version,  open `pyproject.toml` and ensure it includes:

```toml
[tool.poetry.dependencies]
grafi = "^0.0.18"
python = ">=3.10,<3.13"
```

Now install the dependencies:

<!-- ```bash
poetry install --no-root
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">poetry</span> install <span style="color:#AE81FF">--no-root</span></code></pre></div>

This will automatically create a virtual environment and install `grafi` with the appropriate Python version.

> 💡 You can also create the virtual environment with the correct Python version explicitly:
>
><div class="bash"><pre>
><code><span style="color:#FF4689">poetry</span> env use python3.12</code></pre></div>
<!-- > ```bash
> poetry env use python3.12
> ``` -->

---

## Use Build-in ReAct Agent

In graphite an agent is a specialized assistant that can handle events and perform actions based on the input it receives. We will create a ReAct agent that uses OpenAI's language model to process input, make function calls, and generate responses.

Create a file named `react_agent_app.py` and create a build-in react-agent:

```python
from grafi.agents.react_agent import create_react_agent

def main():
    print("ReAct Agent Chat Interface")
    print("Type your questions and press Enter. Type '/bye' to exit.")
    print("-" * 50)
    
    react_agent = create_react_agent()

    while True:
        user_input = input("\nYou: ").strip()
        
        if user_input.lower() == '/bye':
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        try:
            # Get synchronized response from agent
            output = react_agent.run(user_input, invoke_context)
            print(f"\nAgent: {output}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
```

---

## Run the Application

Use Poetry to invoke the script inside the virtual environment:

<!-- ```bash
poetry run python main.py
``` -->
<div class="bash"><pre>
<code><span style="color:#FF4689">poetry</span> run python main.py</code></pre></div>

You should see the output result

```text
Graphite is an open-source framework designed for building domain-specific AI agents using composable workflows. It features an event-driven architecture that allows developers to create customizable workflows. This framework is particularly focused on constructing AI assistants that can interact within specific domains effectively.

For more detailed information, you can refer to the following resources:
1. [Introducing Graphite — An Event Driven AI Agent Framework](https://medium.com/binome/introduction-to-graphite-an-event-driven-ai-agent-framework-540478130cd2)
2. [Graphite - Framework AI Agent Builder](https://bestaiagents.ai/agent/graphite)
```

---

## Summary

✅ Initialized a Poetry project

✅ Installed `grafi` with the correct Python version constraint

✅ Wrote a minimal agent that handles an event

✅ Ran the agent with a question

---

## Next Steps

* Explore the [Graphite GitHub Repository](https://github.com/binome-dev/graphite) for full-featured examples.
* Extend your agent to respond to different event types.
* Dive into advanced features like memory, workflows, and tools.

---

Happy building! 🚀
