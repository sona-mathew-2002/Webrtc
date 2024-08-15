import asyncio
import os
from dotenv import load_dotenv
from answer import WebRTCClient
load_dotenv()


async def main():

    signal_server_url = os.getenv('SIGNAL_SERVER_URL')
    client_id = os.getenv('CLIENT_ID')


    if not signal_server_url or not client_id:
        raise ValueError("Environment variables SIGNAL_SERVER_URL and CLIENT_ID must be set")

    client = WebRTCClient(signal_server_url, client_id)
    await client.setup_signal()
    await asyncio.sleep(3)
    await client.send_message('chat', "Hello, Chat!")

    while True:
        await asyncio.sleep(1)

    # You can send more messages or perform other operations here

if __name__ == "__main__":
    asyncio.run(main())