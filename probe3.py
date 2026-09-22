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

                # 1. Find the BTC market symbol on Binance
                print("=== list_markets (exchange=BINA, query=BTC) ===")
                result = await session.call_tool("list_markets", {
                    "exchange": "BINA",
                    "query": "BTC",
                })
                for block in result.content:
                    if hasattr(block, 'text'):
                        print(block.text[:3000])
                print()

                # 2. Now try get_ohlc with the discovered symbol format
                #    We'll try two common formats based on Altrady's naming.
                for symbol in ["BTCUSDT", "BINA_USDT_BTC"]:
                    print(f"=== get_ohlc (marketSymbol={symbol}) ===")
                    try:
                        result = await session.call_tool("get_ohlc", {
                            "exchange": "BINA",
                            "marketSymbol": symbol,
                            "timeframe": "240",
                            "limit": 3,
                        })
                        for block in result.content:
                            if hasattr(block, 'text'):
                                print(block.text[:2000])
                    except Exception as e:
                        print("Failed:", type(e).__name__, str(e))
                    print()

if __name__ == "__main__":
    asyncio.run(main())