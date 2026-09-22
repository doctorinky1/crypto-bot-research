import asyncio
import json
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = "http://127.0.0.1:6850/mcp"
MCP_TOKEN = "AagVeEboBx4J4xFTljO0CUaOMM4lrqxbXUpLYWQXBiI"

async def main():
    http_client = httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {MCP_TOKEN}",
            "Accept": "application/json, text/event-stream",
        },
        timeout=httpx.Timeout(30, read=300),
        follow_redirects=True,
    )

    async with http_client:
        async with streamable_http_client(url=MCP_SERVER_URL, http_client=http_client) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("Connected.\n")

                tools = await session.list_tools()
                for tool in tools.tools:
                    if tool.name == "get_ohlc":
                        print("=== get_ohlc input schema ===")
                        print(json.dumps(tool.input_schema, indent=2))
                        print()

                print("=== Probing get_ohlc ===")
                try:
                    result = await session.call_tool("get_ohlc", {
                        "market": "BINA_USDT_BTC",
                        "resolution": 240,
                        "limit": 5,
                    })
                    print("Success.")
                    print("Content blocks:", len(result.content))
                    for i, block in enumerate(result.content):
                        print(f"\n--- Block {i} ---")
                        print("Type:", getattr(block, 'type', 'unknown'))
                        if hasattr(block, 'text'):
                            print(block.text[:3000])
                except Exception as e:
                    print("Call failed:", type(e).__name__, str(e))
                    if hasattr(e, 'exceptions'):
                        for sub in e.exceptions:
                            print("  Sub:", type(sub).__name__, str(sub))

if __name__ == "__main__":
    asyncio.run(main())