# Getting Started with Graphite: The Hello, World! Assistant

[Graphite](https://github.com/binome-dev/graphite) is a powerful event-driven AI agent framework built for modularity, observability, and seamless composition of AI workflows. This comprehensive guide will walk you through creating your first ReAct (Reasoning and Acting) agent using the `grafi` package. In this tutorial, we'll build a function-calling assistant that demonstrates how to integrate language models with google search function within the Graphite framework, showcasing the core concepts of event-driven AI agent development.

---

## Prerequisites

Make sure the following are installed:

* Python **>=3.10, < 3.13** (required by the `grafi` package)
* [uv](https://docs.astral.sh/uv/#installation)
* Git

> ⚠️ **Important:** `grafi` requires Python >= 3.10 and < 3.13. Other python version is not yet supported.

---

## Create a New Project

<!-- ```bash
mkdir graphite-react
cd graphite-react
touch README.md
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">mkdir</span> graphite-react
<span style="color:#FF4689">cd</span> graphite-react
</code></pre></div>

This will create the `pyproject.toml` file that uv needs.

<!-- ```bash
<<<<<<< HEAD
uv init --name graphite-react
=======
poetry init --name graphite-react
>>>>>>> 17a3def (updated code for installation / quiickstart)
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> init <span style="color:#AE81FF">--name</span> graphite-react</code></pre></div>

Be sure to specify a compatible Python version,  open `pyproject.toml` and ensure it includes:

```toml
<<<<<<< HEAD
[project]
name = "graphite-react"
dependencies = [
    "grafi>=0.0.18",
]
requires-python = ">=3.10,<3.13"
=======
[tool.poetry.dependencies]
grafi = "^0.0.18"
python = ">=3.10,<3.13"
googlesearch-python = "^1.3.0"
pycountry = "^24.6.1"
>>>>>>> 17a3def (updated code for installation / quiickstart)
```

Now install the dependencies:

<!-- ```bash
uv sync
``` -->

<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> sync</code></pre></div>

This will automatically create a virtual environment and install `grafi` with the appropriate Python version.

> 💡 You can also specify the Python version explicitly:
>
><div class="bash"><pre>
><code><span style="color:#FF4689">uv</span> python pin python3.12</code></pre></div>
<!-- > ```bash
> uv python pin python3.12
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
            output = react_agent.run(user_input)
            print(f"\nAgent: {output}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
```

And finally export an `OPENAI_API_KEY` key as an environment variable:

```bash
export OPENAI_API_KEY="sk-proj-******"
```

---

## Run the Application

Use uv to invoke the script inside the virtual environment:

<!-- ```bash
uv run python main.py
``` -->
<div class="bash"><pre>
<code><span style="color:#FF4689">uv</span> run python main.py</code></pre></div>

You should see following in the terminal

```text
ReAct Agent Chat Interface
Type your questions and press Enter. Type '/bye' to exit.
--------------------------------------------------

You:
```

then you can add your questions, and exit by typing `/bye`

```text
ReAct Agent Chat Interface
Type your questions and press Enter. Type '/bye' to exit.
--------------------------------------------------

You: What year was the United Kingdom Founded?

<... logs>

Agent: The United Kingdom (UK) was officially formed in 1707 with the Acts of Union, 
which united the Kingdom of England and the Kingdom of Scotland into a single 
entity known as the Kingdom of Great Britain. Later, in 1801, another 
Act of Union added the Kingdom of Ireland, leading to the formation of the 
United Kingdom of Great Britain and Ireland. After the majority of Ireland gained 
independence in 1922, the name was changed to the United Kingdom of 
Great Britain and Northern Ireland.


You: /bye
Goodbye!
```

---

## Summary

✅ Initialized a uv project

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
