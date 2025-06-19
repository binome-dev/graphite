from grafi.agents.react_agent import create_agent


react_agent = create_agent()

output = react_agent.run("What is agent framework called Graphite?")

print(output)
