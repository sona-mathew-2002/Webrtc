import asyncio
import os
from dotenv import load_dotenv
from offer import WebRTCClient
load_dotenv()

async def main():
    signal_server_url = os.getenv('SIGNAL_SERVER_URL')
    client_id = os.getenv('CLIENT_ID')

    if not signal_server_url or not client_id:
        raise ValueError("Environment variables SIGNAL_SERVER_URL and CLIENT_ID must be set")

    client = WebRTCClient(signal_server_url, client_id)
    await client.setup_signal()
    
    # Send messages

    await asyncio.sleep(3)

    print("Connection ready, sending initial message")
    await client.send_message('chat', '/home/smathew/Desktop/Offer/img2.jpg', is_image=True)
    # await client.send_message('home', "hello from home offer!")
    # await client.send_message('chat', "hello again from chat offer")
    # await asyncio.sleep(1)
    while True:
        await asyncio.sleep(1)

    # You can send more messages or perform other operations here

if __name__ == "__main__":
    asyncio.run(main())