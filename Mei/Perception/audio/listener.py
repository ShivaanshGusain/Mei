import pyaudio
import threading
import time
from datetime import datetime
from collections import deque
from ...core.state import AgentState
import numpy as np
from ...core import events
from ...core.config import get_config

# CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1


class AudioListener:
    def __init__(self): # for now removed threshold from parameters using Audioconfig.threshold
        config = get_config()
        self.threshold = config.audio.energy_threshold
        self.silence_duration = config.audio.silence_duration
        self.sample_rate = config.audio.sample_rate
        self.state = AgentState.IDLE
        self.running = False
        self.CHUNK = config.audio.chunk
        self.channels = config.audio.channels

        pre_roll_seconds = 2.0
        chunks_per_second = self.sample_rate / self.CHUNK
        max_chunks = int(pre_roll_seconds * chunks_per_second)
        self.rolling_buffer = deque(maxlen=max_chunks)
        
        
        self.pyaudio = pyaudio.PyAudio()
        self.stream = self.pyaudio.open(format = pyaudio.paInt16, channels = self.channels, rate = self.sample_rate, input = True, frames_per_buffer= 1024)
        self.speech_buffer = []
        self.silence_start_time = None


    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(
                                target = self._listen_loop,
                                daemon = True
                                )
        self.thread.start()

    def stop(self):
        self.running = False
        if hasattr(self, 'thread') and self.thread.is_alive():
            self.thread.join(timeout=2.0)  # Add timeout to prevent hanging

        if hasattr(self, 'stream') and self.stream.is_active():
            self.stream.stop_stream()
            self.stream.close()
        
        if hasattr(self, 'pyaudio'):
            self.pyaudio.terminate()


    def calculate_rms(self, chunk):
        chunk_array = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)/32768.0
        rms_value = np.sqrt(np.mean(chunk_array**2))
        return rms_value

    def _listen_loop(self):
        try:
            while self.running:
                chunk = self.stream.read(self.CHUNK,exception_on_overflow=False)
                # Adding to the rolling buffer.
                self.rolling_buffer.append(chunk)
                #calculating energy = 
                energy = self.calculate_rms(chunk)
                # print(f"RMS: {energy:.4f}")  # Shows 4 decimal places

                if self.state == AgentState.IDLE:
                    if energy>self.threshold:
                        self.state = AgentState.LISTENING
                        pre_roll = list(self.rolling_buffer)[-5:]
                        self.speech_buffer = pre_roll+ [chunk] 
                        self.silence_start_time = None

                        events.emit(event_type=events.EventType.SPEECH_STARTED, source="AudioListener")

                elif self.state == AgentState.LISTENING:
                    self.speech_buffer.append(chunk)
                    
                    if energy>self.threshold:
                        # still speaking
                        self.silence_start_time = None
                    else:
                        if self.silence_start_time == None:
                            self.silence_start_time = datetime.now() # current time supposidely
                        elif(datetime.now() - self.silence_start_time).total_seconds() > self.silence_duration:
                            # if silence long enough speech ended
                            audio_data = b"".join(self.speech_buffer)

                            events.emit(event_type = events.EventType.SPEECH_ENDED, source="AudioListener", audio=audio_data) # emit = return
                            self.speech_buffer = []
                            self.silence_start_time = None
                            self.state = AgentState.IDLE
        except Exception as e:
            events.emit(
            event_type=events.EventType.ERROR,
            source="AudioListener",
            error=str(e)
             )
        finally:
            self.state = AgentState.IDLE