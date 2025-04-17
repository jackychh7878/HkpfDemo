import streamlit as st
import sounddevice as sd
import asyncio
import websockets
import threading
import queue
import json
import base64
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if "streaming" not in st.session_state:
    st.session_state.streaming = False

# ——— CONFIG ———
# Replace with your actual websocket URL (wss://…) and token
WS_URL = "wss://portal-demo.fano.ai/speech/streaming-recognize"
TOKEN = os.environ.get("FANOLAB_API_KEY")

# audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024  # frames per buffer

# queue to pass raw audio from callback to asyncio loop
audio_q = queue.Queue()

def audio_callback(indata, frames, time, status):
    """This runs in a separate thread and puts raw bytes into the queue."""
    if status:
        st.warning(f"Audio status: {status}")
    # PCM signed 16‑bit little endian
    audio_q.put(indata.copy())

async def recognize(is_streaming):
    """Connects to the WebSocket, streams audio, and displays transcripts."""
    # prepare UI container
    transcript_box = st.empty()
    transcript = ""

    try:
        logger.info("Attempting to connect to WebSocket...")
        async with websockets.connect(
            WS_URL,
            additional_headers={
                "Authorization": f"Bearer {TOKEN}",
                "fano-speech-disable-audio-conversion": "0",
            },
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            logger.info("WebSocket connection established")
            
            # Step 1: send config
            cfg_msg = {
                "event": "request",
                "data": {
                    "streamingConfig": {
                        "config": {
                            "languageCode": "yue",
                            "sampleRateHertz": SAMPLE_RATE,
                            "encoding": "LINEAR16",
                            "enableAutomaticPunctuation": True,
                            "singleUtterance": True
                        }
                    }
                }
            }
            # logger.info(f"Sending config: {json.dumps(cfg_msg)}")
            await ws.send(json.dumps(cfg_msg))

            # start background task to receive messages
            async def recv_loop():
                nonlocal transcript
                try:
                    async for message in ws:
                        msg = json.loads(message)
                        logger.info(f"Received message: {msg}")
                        if msg.get("event") != "response":
                            continue
                        for result in msg["data"].get("results", []):
                            for alt in result.get("alternative", []):
                                txt = alt.get("transcript", "")
                                is_final = result.get("isFinal", False)
                                if is_final:
                                    transcript += txt + " "
                                else:
                                    transcript_box.markdown(transcript + txt)
                                print(transcript)
                                transcript_box.markdown(transcript)
                except websockets.exceptions.ConnectionClosed as e:
                    logger.error(f"WebSocket connection closed: {e}")
                except Exception as e:
                    logger.error(f"Error in recv_loop: {e}")

            recv_task = asyncio.create_task(recv_loop())

            # Step 1b: stream audio until stopped
            while True:
                try:
                    chunk = audio_q.get_nowait()
                    # encode PCM bytes as base64
                    b64 = base64.b64encode(chunk.tobytes()).decode("utf-8")
                    audio_msg = {
                        "event": "request",
                        "data": {"audioContent": b64}
                    }
                    await ws.send(json.dumps(audio_msg))

                    # break if we've somehow been signaled to stop
                    if not is_streaming:
                        break
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue
                except websockets.exceptions.ConnectionClosed as e:
                    logger.error(f"WebSocket connection closed while sending audio: {e}")
                    break
                except Exception as e:
                    logger.error(f"Error sending audio: {e}")
                    break

            # Step 2: send EOF to close stream gracefully
            try:
                eof_msg = {"event": "request", "data": "EOF"}
                await ws.send(json.dumps(eof_msg))
                await recv_task
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        st.error(f"An error occurred: {e}")

def start_stream():
    """Called when user hits Start: kick off audio capture and asyncio task."""
    st.session_state.streaming = True
    # start microphone capture
    sd.default.samplerate = SAMPLE_RATE
    sd.default.channels = CHANNELS
    stream = sd.InputStream(callback=audio_callback, blocksize=CHUNK_SIZE, dtype='int16')
    stream.start()

    # run the recognize coroutine in a new event loop
    def runner():
        if "streaming" not in st.session_state:
            st.session_state.streaming = True
        asyncio.run(recognize(st.session_state.streaming))
        stream.stop()
        stream.close()
        st.session_state.streaming = False

    threading.Thread(target=runner, daemon=True).start()

st.title("🔴 Live Transcription POC")
if "streaming" not in st.session_state:
    st.session_state.streaming = False

col1, col2 = st.columns([1,1])
with col1:
    if not st.session_state.streaming:
        st.button("Start", on_click=start_stream)
    else:
        st.button("Stop", on_click=lambda: setattr(st.session_state, "streaming", False))

with col2:
    st.write("Status:", "🔴 Recording" if st.session_state.streaming else "⚪ Idle")

st.markdown("**Transcript:**")
# this empty box will be filled by the async recognizer
st.empty()
