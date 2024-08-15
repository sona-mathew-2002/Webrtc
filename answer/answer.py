





from aiortc import RTCIceCandidate, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import json
import asyncio
import requests
import logging
import aiohttp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
import aioconsole
from twilio.rest import Client
import os
from dotenv import load_dotenv
import io
import base64
from PIL import Image

load_dotenv()

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
        self.driver = None

    async def keep_alive(self):
        while True:
            if self.channels_ready['keep_alive'].is_set():
                try:
                    self.channels['keep_alive'].send("keep-alive")
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
        self.channels['keep_alive'] = self.peer_connection.createDataChannel("keep_alive")
        # self.channels['home'] = self.peer_connection.createDataChannel("home")

        for channel_name, channel in self.channels.items():
            @channel.on("open")
            async def on_open(channel=channel, name=channel_name):
                print(f"Channel {name} opened")
                self.channels_ready[name].set()
                if name == "keep_alive":
                    asyncio.create_task(self.keep_alive())

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
        async def on_datachannel(channel):
            print(f"Data channel '{channel.label}' created by remote party")
            self.channels[channel.label] = channel

            @channel.on("open")
            def on_open():
                print(f"Data channel '{channel.label}' is open")
                if channel.label == "keep_alive":
                    asyncio.create_task(self.keep_alive())

            @channel.on("message")
            async def on_message(message):
                print("message received from channel",message)
                asyncio.create_task(self.keep_alive())
                

        await self.wait_for_offer()

    async def wait_for_offer(self):
        try:
            resp = requests.get(self.SIGNALING_SERVER_URL + "/get_offer")
            print(f"Offer request status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                if data["type"] == "offer":
                    rd = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                    await self.peer_connection.setRemoteDescription(rd)
                    await self.peer_connection.setLocalDescription(await self.peer_connection.createAnswer())

                    message = {
                        "id": self.ID,
                        "sdp": self.peer_connection.localDescription.sdp,
                        "type": self.peer_connection.localDescription.type
                    }
                    r = requests.post(self.SIGNALING_SERVER_URL + '/answer', data=message)
                    print(f"Answer sent, status: {r.status_code}")
            else:
                print(f"Failed to get offer. Status code: {resp.status_code}")
        except Exception as e:
            print(f"Error during signaling: {str(e)}")
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
            'keep_alive': asyncio.Event()
        }
        await self.create_peer_connection()

    async def send_message_to_rasa(self, message):
        url = "http://localhost:5006/webhooks/rest/webhook"
        payload = {
            "sender": "user",
            "message": message
        }
        headers = {
            "Content-Type": "application/json"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                response_json = await response.json()
                if response_json and isinstance(response_json, list) and len(response_json) > 0:
                    return response_json[0].get('text', '')
                return ''

    async def send_message(self, channel_name, message):
        if channel_name not in self.channels:
            print(f"Invalid channel name: {channel_name}")
            return

        if not self.channels_ready[channel_name].is_set():
            print(f"Channel {channel_name} is not ready yet. Please wait.")
            return

        channel = self.channels[channel_name]
        if channel and channel.readyState == "open":
            print(f"Sending via RTC Datachannel {channel_name}: {message}")
            channel.send(message)
        else:
            print(f"Channel {channel_name} is not open. Cannot send message.")

    
    def extract_last_message(self):
        try:
            # Wait for the chat container to be present
            chat_container = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-sierra-chat-container]"))
            )
            # Access the shadow root of the chat container
            shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", chat_container)
            
            # Wait for the li elements to be present in the shadow DOM
            li_elements = WebDriverWait(shadow_root, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li[aria-roledescription='message']"))
            )
            
            if li_elements:
                # Get the last li element
                last_li = li_elements[-1]
                
                # Find all p tags within the last li element
                p_tags = last_li.find_elements(By.CSS_SELECTOR, "p")
                
                # Concatenate the text content of all p tags
                combined_message = " ".join([p.text for p in p_tags])
                return combined_message
            return ''
        except Exception as e:
            print(f"Error extracting message: {e}")
            return ''

    def send_message_via_selenium(self, message):
        try:
            chat_container = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-sierra-chat-container]"))
            )
            shadow_root = self.driver.execute_script("return arguments[0].shadowRoot", chat_container)
            
            input_field = shadow_root.find_element(By.CSS_SELECTOR, "div[role='textbox'][aria-label='Message Input']")
            input_field.send_keys(message)
            
            send_button = shadow_root.find_element(By.CSS_SELECTOR, "button[aria-label='Send Message']")
            send_button.click()
            
            asyncio.sleep(2)
        except Exception as e:
            print(f"Error sending message: {e}")

    async def setup_selenium(self):
        self.driver = webdriver.Chrome()
        try:
            self.driver.get("https://olukai.com/")
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            await asyncio.sleep(2)

            try:
                contact_button = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a[data-sierra-chat='modal']"))
                )
            except Exception as e:
                print(f"Error finding Contact Us button: {e}")
                return

            try:
                ActionChains(self.driver).move_to_element(contact_button).click().perform()
            except Exception as e:
                print(f"Error clicking Contact Us button: {e}")
                try:
                    self.driver.execute_script("arguments[0].click();", contact_button)
                except Exception as e:
                    print(f"Error with JavaScript click: {e}")
                    return

            await asyncio.sleep(2)

            print(self.extract_last_message())
            self.send_message_via_selenium("Hi")
            await asyncio.sleep(6)
            response=await self.send_message_to_rasa(self.extract_last_message())
            self.send_message_via_selenium(response)
            await asyncio.sleep(30)
            response=await self.send_message_to_rasa(self.extract_last_message())
            print(response)
            await asyncio.sleep(10)
            await self.send_message('chat',response)
        except Exception as e:
            print(f"Error in setup_selenium: {e}")
        finally:
            if self.driver:
                self.driver.quit()