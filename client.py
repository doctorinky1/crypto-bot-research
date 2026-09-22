import asyncio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

# --- EDIT THESE TWO LINES WITH YOUR ALTRADY DETAILS ---
MCP_SERVER_URL = "http://127.0.0.1:6850/mcp"
MCP_TOKEN = "AagVeEboBx4J4xFTljO0CUaOMM4lrqxbXUpLYWQXBiI"
# ------------------------------------------------------

async def main():
    http_client = httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {MCP_TOKEN}",
            "Accept": "application/json, text/event-stream",
        },
        timeout=httpx.Timeout(30, read=300),
        follow_redirects=True,
    )

    try:
        print("Connecting to Altrady MCP server...")
        async with http_client:
            async with streamable_http_client(
                url=MCP_SERVER_URL,
                http_client=http_client,
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    print("✅ Connected successfully!")

                    tools = await session.list_tools()
                    print("\n📋 Available tools:")
                    for tool in tools.tools:
                        print(f"  - {tool.name}: {tool.description}")

    except Exception as e:
        print(f"\n❌ Connection failed.")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {e}")

if __name__ == "__main__":
    asyncio.run(main())