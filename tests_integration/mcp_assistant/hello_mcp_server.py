from fastmcp import FastMCP


mcp: FastMCP = FastMCP("Demo 🚀")


@mcp.tool
def hello(name: str) -> str:
    return f"Hello, {name}!"


mcp.run(transport="http", host="127.0.0.1", port=8000, path="/mcp")
