import sounddevice as sd
import asyncio
import threading
import queue
import json
import os
import logging
from dotenv import load_dotenv
import keyboard
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, ttk
import queue as std_queue
import azure.cognitiveservices.speech as speechsdk
from openai import AzureOpenAI

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— CONFIG ———
AZURE_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_REGION = os.environ.get("AZURE_SPEECH_REGION")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
TRANSCRIPT_FILE = "live_transcript.txt"

# System prompt for summarization
SUMMARIZE_PROMPT = """You are a helpful assistant that summarizes conversations. 
Your task is to:
1. Read the conversation transcript
2. Identify the main topics discussed
3. Create a concise summary in the same language as the conversation
4. Highlight any key points or decisions made
5. Keep the summary clear and easy to understand

Please provide the summary in the same language as the conversation."""

# audio settings
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024  # frames per buffer

# Global variables
is_streaming = False
transcript_queue = std_queue.Queue()
audio_q = queue.Queue()  # Queue for audio data
gui = None  # Global GUI instance
speech_recognizer = None

def audio_callback(indata, frames, time, status):
    """This runs in a separate thread and puts raw bytes into the queue."""
    if status:
        print(f"Audio status: {status}")
    # PCM signed 16‑bit little endian
    audio_q.put(indata.copy())

class TranscriptGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Live Transcription")
        self.root.geometry("800x600")
        
        # Create device selection frame
        device_frame = tk.Frame(self.root)
        device_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Device selection label
        tk.Label(device_frame, text="Input Device:").pack(side=tk.LEFT)
        
        # Get available input devices
        self.devices = sd.query_devices()
        self.input_devices = [device for device in self.devices if device['max_input_channels'] > 0]
        self.device_names = [f"{device['name']} (ID: {device['index']})" for device in self.input_devices]
        
        # Device selection dropdown
        self.device_var = tk.StringVar()
        self.device_dropdown = ttk.Combobox(device_frame, textvariable=self.device_var, values=self.device_names)
        self.device_dropdown.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # Set default device
        default_device = sd.default.device[0]
        for i, device in enumerate(self.input_devices):
            if device['index'] == default_device:
                self.device_dropdown.current(i)
                break
        
        # Create text widget with scrollbar
        self.text_widget = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Arial", 12))
        self.text_widget.pack(expand=True, fill='both')
        self.text_widget.config(state='disabled')
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Start the update loop
        self.update_text()
    
    def get_selected_device_index(self):
        """Get the index of the currently selected device."""
        selection = self.device_var.get()
        for device in self.input_devices:
            if f"{device['name']} (ID: {device['index']})" == selection:
                return device['index']
        return sd.default.device[0]  # Return default device if no selection
    
    def update_text(self):
        try:
            while not transcript_queue.empty():
                text = transcript_queue.get_nowait()
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, text + "\n")
                self.text_widget.see(tk.END)  # Scroll to the end
                self.text_widget.config(state='disabled')
        except:
            pass
        finally:
            self.root.after(100, self.update_text)  # Update every 100ms
    
    def run(self):
        self.root.mainloop()

def update_transcript(text):
    """Update both the file and the GUI."""
    # Update the file
    try:
        with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{text}\n")
            f.flush()
    except Exception as e:
        print(f"Error updating transcript file: {e}")
    
    # Update the GUI queue
    transcript_queue.put(text)
    print(f"Transcript updated: {text}")

def check_microphone():
    """Check if microphone is available and accessible."""
    try:
        # Try to get the default input device
        device = sd.query_devices(kind='input')
        if device is None:
            print("No input device found")
            return False
        print(f"Found microphone: {device['name']}")
        return True
    except Exception as e:
        print(f"Error checking microphone: {e}")
        return False

def start_recording():
    """Start the recording process."""
    global is_streaming, gui, speech_recognizer
    
    if not check_microphone():
        print("Cannot start recording: No microphone available")
        return
    
    # Clear the transcript file at the start of a new session
    with open(TRANSCRIPT_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== New Recording Session - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n\n")
    
    is_streaming = True
    
    # Get the selected device index from the GUI
    device_index = gui.get_selected_device_index()
    device_info = sd.query_devices(device_index)
    
    try:
        # Configure speech recognition
        speech_config = speechsdk.SpeechConfig(subscription=AZURE_KEY, region=AZURE_REGION)
        speech_config.speech_recognition_language = "zh-HK"
        
        # Create audio config using default microphone
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
        
        # Create speech recognizer
        speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        
        # Connect callbacks
        speech_recognizer.recognized.connect(lambda evt: update_transcript(evt.result.text))
        speech_recognizer.recognizing.connect(lambda evt: print(f"Recognizing: {evt.result.text}"))
        speech_recognizer.canceled.connect(lambda evt: print(f"Canceled: {evt}"))
        speech_recognizer.session_started.connect(lambda evt: print("Session started"))
        speech_recognizer.session_stopped.connect(lambda evt: print("Session stopped"))
        
        # Start continuous recognition
        speech_recognizer.start_continuous_recognition()
        print(f"Recording started with device {device_info['name']}. Transcript is being saved to {TRANSCRIPT_FILE}")
        print("Press 'q' to stop recording...")
    except Exception as e:
        print(f"Error starting recording: {e}")
        is_streaming = False
        if speech_recognizer:
            speech_recognizer = None

def get_conversation_summary():
    """Get a summary of the conversation using Azure OpenAI."""
    try:
        # Read the transcript file
        with open(TRANSCRIPT_FILE, "r", encoding="utf-8") as f:
            transcript = f.read()
        
        # Initialize Azure OpenAI client
        client = AzureOpenAI(
            api_key=AZURE_OPENAI_KEY,
            api_version="2024-12-01-preview",
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        
        # Create the chat completion
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": f"Please summarize this conversation:\n\n{transcript}"}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        # Extract and return the summary
        summary = response.choices[0].message.content
        return summary
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Error generating summary. Please check the logs for details."

def stop_recording():
    """Stop the recording process."""
    global is_streaming, speech_recognizer
    if speech_recognizer:
        speech_recognizer.stop_continuous_recognition()
        speech_recognizer = None
    is_streaming = False
    print("Recording stopped.")
    
    # Add a separator at the end of the session
    with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write("\n=== End of Recording ===\n\n")
    
    # Generate and add summary
    print("Generating conversation summary...")
    summary = get_conversation_summary()
    with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write("\n=== Conversation Summary ===\n")
        f.write(summary)
        f.write("\n\n")
    
    # Update GUI with summary
    transcript_queue.put("\n=== Conversation Summary ===\n")
    transcript_queue.put(summary)
    transcript_queue.put("\n")
    print("Summary added to transcript.")

def keyboard_control():
    """Handle keyboard controls in a separate thread."""
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

def main():
    """Main function to run the transcription app."""
    global gui
    
    # Start keyboard controls in a separate thread
    keyboard_thread = threading.Thread(target=keyboard_control, daemon=True)
    keyboard_thread.start()
    
    # Run the GUI in the main thread
    gui = TranscriptGUI()
    gui.run()

if __name__ == "__main__":
    main()
