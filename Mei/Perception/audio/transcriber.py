import os
import threading
import time
import numpy as np
from datetime import datetime
from collections import deque
import queue
from faster_whisper import WhisperModel
from ...core.config import get_config
# from ...core.state import
from ...core.events import EventType, subscribe, emit


class Transcriber:
    def __init__(self):
        subscribe(EventType.SPEECH_ENDED, self._on_speech_ended)
        config = get_config()
        self.raw_path = config.audio.model_path.strip()
        if os.path.isabs(self.raw_path):
            self.raw_path = self.raw_path
        else:
            self.current_dir = os.path.dirname(os.path.abspath(__file__))
            self.current_dir = os.path.abspath(os.path.join(self.current_dir, "../../../"))
            self.model_path = os.path.join(self.current_dir,self.raw_path)
        self.rate = config.audio.sample_rate
        self.channel = config.audio.channels
        self.model = WhisperModel(model_size_or_path = self.model_path, device = config.audio.device,compute_type= config.audio.compute_type)
        self.model_language = config.audio.language
        self.beam_size = config.audio.beam_size
        self.running = False
        self.queue = queue.Queue()
        self.thread = None

    def start(self):
        if self.running == True:
            return
        self.running = True
        self.thread = threading.Thread(target= self._processing_loop, daemon= True)
        self.thread.start()
        print("Transcribtion has started")

    def stop(self):
        self.running = False
        self.queue.put(None)

        if self.thread:
            self.thread.join(timeout = 2.0)
        print("Transcribtion has Stopped")

    def _on_speech_ended(self, event):
        if event is None:
            return
        audio_bytes = event.data.get('audio')
        if audio_bytes:
            self.queue.put(audio_bytes)


    def _processing_loop(self):
        while self.running:
            try:
                audio_bytes = self.queue.get(timeout=0.5)
                if audio_bytes == None:
                    break 
                
                if len(audio_bytes)<1600:
                    continue
                         
                audio_data = self._convert_audio(audio_bytes)
                self._transcribe_with_retry(audio_data)

                
            except queue.Empty:
                continue
            except Exception as e:
                emit(EventType.ERROR, source= 'Transcriber', error = str(e))
        
    def _convert_audio(self, audio_bytes):
        return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    def _transcribe_with_retry(self, audio_data, max_retries = 3):
        for attempt in range(max_retries):
            try:
                segments,info = self.model.transcribe(
                    audio=audio_data,
                    language=self.model_language,
                    beam_size=self.beam_size, 
                    vad_filter=True
                    )
                segments = list(segments)
                full_text = " ".join([s.text for s in segments]).strip()
                if full_text:
                    print(f"Transcribtion Recognized: '{full_text}'")
                    emit(EventType.TRANSCRIBE_COMPLETED, source = 'Transcriber', text = full_text, language = info.language)   
                else:
                    print("No speech detected in audio")
                return
            except Exception as e:
                if attempt == max_retries -1:
                    emit(EventType.ERROR, source = 'Transcriber', error = str(e))
                else:
                    time.sleep(0.5)

        

    