import asyncio
import json
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = "http://127.0.0.1:6850/mcp"
MCP_TOKEN = "sUADWs9dvL_OjtcFiATs0DczDIw30UE6ew1zAYx99QE"

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

                # 1. Confirm the exact BTC/USDT entry
                print("=== get_market (BINA, BTC/USDT) ===")
                try:
                    result = await session.call_tool("get_market", {
                        "exchange": "BINA",
                        "marketSymbol": "BTC/USDT",
                    })
                    for block in result.content:
                        if hasattr(block, 'text'):
                            print(block.text[:2000])
                except Exception as e:
                    print("Failed:", type(e).__name__, str(e))
                print()

                # 2. Try get_ohlc with the slash format
                print("=== get_ohlc (marketSymbol=BTC/USDT) ===")
                try:
                    result = await session.call_tool("get_ohlc", {
                        "exchange": "BINA",
                        "marketSymbol": "BTC/USDT",
                        "timeframe": "240",
                        "limit": 3,
                    })
                    for block in result.content:
                        if hasattr(block, 'text'):
                            print(block.text[:3000])
                except Exception as e:
                    print("Failed:", type(e).__name__, str(e))

if __name__ == "__main__":
    asyncio.run(main())