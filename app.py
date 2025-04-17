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
import keyboard
from datetime import datetime

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— CONFIG ———
WS_URL = "wss://portal-demo.fano.ai/speech/streaming-recognize"
TOKEN = os.environ.get("FANOLAB_API_KEY")
TRANSCRIPT_FILE = "live_transcript.txt"  # Single file for all transcripts

# audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024  # frames per buffer

# Global variables
is_streaming = False
transcript_file = None

# queue to pass raw audio from callback to asyncio loop
audio_q = queue.Queue()

def audio_callback(indata, frames, time, status):
    """This runs in a separate thread and puts raw bytes into the queue."""
    if status:
        print(f"Audio status: {status}")
    # PCM signed 16‑bit little endian
    audio_q.put(indata.copy())

def update_transcript_file(text):
    """Update the transcript file with new text."""
    try:
        with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{text}\n")
            f.flush()  # Ensure the file is written immediately
        print(f"Transcript updated: {text}")
    except Exception as e:
        print(f"Error updating transcript file: {e}")

async def recognize():
    """Connects to the WebSocket, streams audio, and saves transcripts."""
    global is_streaming
    ws = None
    stream = None
    
    try:
        print("Connecting to WebSocket...")
        ws = await websockets.connect(
            WS_URL,
            additional_headers={
                "Authorization": f"Bearer {TOKEN}",
                "fano-speech-disable-audio-conversion": "0",
            },
            ping_interval=20,
            ping_timeout=20,
        )
        print("WebSocket connection established")
        
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
        await ws.send(json.dumps(cfg_msg))

        # start background task to receive messages
        async def recv_loop():
            try:
                async for message in ws:
                    msg = json.loads(message)
                    if msg.get("event") == "response" and "data" in msg:
                        for result in msg["data"].get("results", []):
                            for alt in result.get("alternatives", []):
                                txt = alt.get("transcript", "")
                                is_final = result.get("isFinal", False)
                                if is_final and txt:
                                    update_transcript_file(txt)
            except websockets.exceptions.ConnectionClosed as e:
                print(f"WebSocket connection closed: {e}")
            except Exception as e:
                print(f"Error in recv_loop: {e}")

        recv_task = asyncio.create_task(recv_loop())

        # Step 1b: stream audio until stopped
        while is_streaming:
            try:
                chunk = audio_q.get_nowait()
                # encode PCM bytes as base64
                b64 = base64.b64encode(chunk.tobytes()).decode("utf-8")
                audio_msg = {
                    "event": "request",
                    "data": {"audioContent": b64}
                }
                await ws.send(json.dumps(audio_msg))
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            except websockets.exceptions.ConnectionClosed as e:
                print(f"WebSocket connection closed while sending audio: {e}")
                break
            except Exception as e:
                print(f"Error sending audio: {e}")
                break

        # Step 2: send EOF to close stream gracefully
        try:
            eof_msg = {"event": "request", "data": "EOF"}
            await ws.send(json.dumps(eof_msg))
            await recv_task
        except Exception as e:
            print(f"Error during cleanup: {e}")

    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        if ws:
            await ws.close()
        if stream:
            stream.stop()
            stream.close()

def start_recording():
    """Start the recording process."""
    global is_streaming
    
    # Clear the transcript file at the start of a new session
    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== New Recording Session - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
    
    is_streaming = True
    
    # start microphone capture
    sd.default.samplerate = SAMPLE_RATE
    sd.default.channels = CHANNELS
    stream = sd.InputStream(callback=audio_callback, blocksize=CHUNK_SIZE, dtype='int16')
    stream.start()

    # run the recognize coroutine in a new event loop
    def runner():
        asyncio.run(recognize())
        stream.stop()
        stream.close()

    threading.Thread(target=runner, daemon=True).start()
    print(f"Recording started. Transcript is being saved to {TRANSCRIPT_FILE}")
    print("Press 'q' to stop recording...")

def stop_recording():
    """Stop the recording process."""
    global is_streaming
    is_streaming = False
    print("Recording stopped.")
    # Add a separator at the end of the session
    with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write("\n=== End of Recording ===\n\n")

def main():
    """Main function to run the transcription app."""
    print("Speech-to-Text Transcription App")
    print("Press 's' to start recording, 'q' to stop, 'x' to exit")
    print(f"Transcripts will be saved to: {TRANSCRIPT_FILE}")
    
    keyboard.add_hotkey('s', start_recording)
    keyboard.add_hotkey('q', stop_recording)
    
    try:
        while True:
            if keyboard.is_pressed('x'):
                print("Exiting...")
                break
            keyboard.wait()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        if is_streaming:
            stop_recording()

if __name__ == "__main__":
    main()
