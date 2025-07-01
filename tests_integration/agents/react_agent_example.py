from grafi.agents.react_agent import create_react_agent


react_agent = create_react_agent()

output = react_agent.run("What is agent framework called Graphite?")

print(output)
