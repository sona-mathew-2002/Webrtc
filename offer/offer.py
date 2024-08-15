
from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import json
import asyncio
import requests
import os
from dotenv import load_dotenv
import aiohttp
import aioconsole
from twilio.rest import Client
import io
import base64
from PIL import Image

load_dotenv()

# Twilio credentials
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token)

# Generate NTS Token
token = client.tokens.create()

# Extract ICE servers from the token response
ice_servers = [RTCIceServer(urls=server["urls"], username=server.get("username"), credential=server.get("credential")) for server in token.ice_servers]

class WebRTCClient:
    def __init__(self, signaling_server_url, id):
        self.SIGNALING_SERVER_URL = signaling_server_url
        self.ID = id
        self.config = RTCConfiguration(iceServers=ice_servers)
        self.peer_connection = None
        self.channels = {}
        self.channels_ready = {
            'chat': asyncio.Event(),
            'keep_alive': asyncio.Event()
        }

    async def keep_alive(self):
        while True:
            for channel in self.channels.values():
                if channel.readyState == "open":
                    try:
                        channel.send("keep-alive")
                    except Exception as e:
                        print(f"Error sending keep-alive: {e}")
            await asyncio.sleep(5)

    async def setup_signal(self):
        print("Starting setup")
        await self.create_peer_connection()
        asyncio.create_task(self.periodic_reconnection())

    async def create_peer_connection(self):
        self.peer_connection = RTCPeerConnection(configuration=self.config)
        
        @self.peer_connection.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            print(f"ICE connection state is {self.peer_connection.iceConnectionState}")

        @self.peer_connection.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            print(f"ICE gathering state is {self.peer_connection.iceGatheringState}")

        self.channels['chat'] = self.peer_connection.createDataChannel("chat")

        for channel_name, channel in self.channels.items():
            @channel.on("open")
            async def on_open(channel=channel, name=channel_name):
                print(f"Channel {name} opened")
                self.channels_ready[name].set()
                asyncio.create_task(self.keep_alive())
                # if name == "chat":
                #     message = await self.get_user_input()
                #     channel.send(message)
                #     print(f"Sent initial message: {message}")
                    

            @channel.on("message")
            async def on_message(message, name=channel_name):
                try:
                    data = json.loads(message)
                    if data["type"] == "image":
                        # Decode and save or process the image
                        img_data = base64.b64decode(data["data"])
                        img = Image.open(io.BytesIO(img_data))
                        img.save("received_image.png")
                        print(f"Received an image via RTC Datachannel {name}")
                    elif data["type"] == "text":
                        print(f"Received via RTC Datachannel {name}: {data['data']}")
                    else:
                        print(f"Received unknown data type via RTC Datachannel {name}")
                except json.JSONDecodeError:
                    print(f"Received invalid JSON via RTC Datachannel {name}: {message}")
                except Exception as e:
                    print(f"Error processing message: {e}")



        @self.peer_connection.on("datachannel")
        def on_datachannel(channel):
            print(f"Data channel '{channel.label}' created by remote party")
            self.channels[channel.label] = channel

            @channel.on("open")
            def on_open():
                print(f"Data channel '{channel.label}' is open")
                asyncio.create_task(self.keep_alive())

        await self.create_and_send_offer()

    async def create_and_send_offer(self):
        try:
            offer = await self.peer_connection.createOffer()
            await self.peer_connection.setLocalDescription(offer)
            message = {"id": self.ID, "sdp": self.peer_connection.localDescription.sdp, "type": self.peer_connection.localDescription.type}
            r = requests.post(self.SIGNALING_SERVER_URL + '/offer', data=message)
            print(f"Offer sent, status: {r.status_code}")
        except Exception as e:
            print(f"Error during offer creation and sending: {str(e)}")
            return

        await self.wait_for_answer()

    async def wait_for_answer(self):
        try:
            while True:
                resp = requests.get(self.SIGNALING_SERVER_URL + "/get_answer")
                if resp.status_code == 503:
                    print("Answer not ready, trying again")
                    await asyncio.sleep(1)
                elif resp.status_code == 200:
                    data = resp.json()
                    if data["type"] == "answer":
                        rd = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                        await self.peer_connection.setRemoteDescription(rd)
                        print("Remote description set")
                        break
                    else:
                        print("Wrong type")
                        break
                print(f"Answer polling status: {resp.status_code}")
        except Exception as e:
            print(f"Error during answer polling: {str(e)}")
            return

    async def periodic_reconnection(self):
        while True:
            await asyncio.sleep(180)  # Wait for 3 minutes
            print("Reconnecting after 3 minutes...")
            await self.reconnect()

    async def reconnect(self):
        if self.peer_connection:
            await self.peer_connection.close()
        self.channels = {}
        self.channels_ready = {
            'chat': asyncio.Event(),

        }
        await self.create_peer_connection()

    async def get_user_input(self):
        return await aioconsole.ainput("User: ")

    async def send_message(self, channel_name, message, is_image=False):
        if channel_name not in self.channels:
            print(f"Invalid channel name: {channel_name}")
            return

        if not self.channels_ready[channel_name].is_set():
            print(f"Channel {channel_name} is not ready yet. Please wait.")
            return

        channel = self.channels[channel_name]
        if channel and channel.readyState == "open":
            if is_image:
                # If the message is an image (file path or PIL Image object)
                if isinstance(message, str):
                    # If message is a file path
                    with Image.open(message) as img:
                        buffered = io.BytesIO()
                        img.save(buffered, format="PNG")
                        img_str = base64.b64encode(buffered.getvalue()).decode()
                elif isinstance(message, Image.Image):
                    # If message is a PIL Image object
                    buffered = io.BytesIO()
                    message.save(buffered, format="PNG")
                    img_str = base64.b64encode(buffered.getvalue()).decode()
                else:
                    raise ValueError("Image must be a file path or a PIL Image object")
                
                # Prepare the message with a flag indicating it's an image
                data_to_send = json.dumps({
                    "type": "image",
                    "data": img_str
                })
            else:
                # If it's a regular text message
                data_to_send = json.dumps({
                    "type": "text",
                    "data": message
                })

            print(f"Sending via RTC Datachannel {channel_name}: {'[IMAGE]' if is_image else message}")
            channel.send(data_to_send)
        else:
            print(f"Channel {channel_name} is not open. Cannot send message.")

