import asyncio
from classplus_resolver import resolve_classplus_url

async def t():
    url = "https://media-cdn.classplusapp.com/1005566/cc/acc5916a6f7a4a5d9b22281817eca927-mg/master.m3u8"
    try:
        r = await resolve_classplus_url(url)
        print("Resolved:", r)
    except Exception as e:
        print("Failed:", e)

asyncio.run(t())
