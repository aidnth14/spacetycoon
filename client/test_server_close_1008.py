import json, asyncio, websockets
async def handle(ws):
    await ws.close(code=1008, reason="rate limited")
async def main():
    async with websockets.serve(handle, "0.0.0.0", 8081):
        await asyncio.Future()
asyncio.run(main())
