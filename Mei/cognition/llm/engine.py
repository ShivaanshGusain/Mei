from llama_cpp import Llama

from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from typing import List, Dict, Optional, Any

import threading
import json
import os


class LLMEngine:
    
    def __init__(self):
        self.config = get_config()
        self._model = None
        self._model_loaded = False
        self._load_lock = threading.Lock()

        if os.path.isabs(self.config.llm.model_path):
            self._model_path = self.config.llm.model_path
        else:
            self._model_path = str(self.config.root_dir /"models"/"qwen2.5-3b-instruct-q4_k_m.gguf")

        if not os.path.exists(self._model_path):
            raise FileNotFoundError(f"Model not found {self._model_path}")
        
        self._context_length = self.config.llm.context_length
        self._max_tokens = self.config.llm.max_tokens
        self._temperature = self.config.llm.temperature
        self._gpu_layers = self.config.llm.gpu_layers
        self._threads = self.config.llm.threads

    def _load_model(self)->bool:
        if self._model_loaded:
            return True
        
        with self._load_lock:
            if self._model_loaded:
                return True
            try:
                print(f"Loading Model:{self._model_path}")
                emit(event_type=EventType.LLM_LOADING, source="LLMEngine")

                self._model = Llama(
                    model_path=self._model_path,
                    n_ctx=self._context_length,
                    n_gpu_layers=self._gpu_layers,
                    n_threads=self._threads,
                    verbose=False
                )

                self._model_loaded = True
                print("Model Loaded Successfully")
                emit(EventType.LLM_LOADED, source="LLMEngine")
                return True

            except Exception as e:
                print("Failed to load {e}")
                emit(event_type=EventType.ERROR, source="LLMEngine", error = str(e), operation = "load_model")
                return False
        
    def complete(self, prompt:str, max_tokens:int = None, temperature:float = None, stop:List[str] = None) -> str:
        
        if not self._load_model():
            return ""
        
        max_tokens = max_tokens or self._max_tokens
        temperature = temperature or self._temperature
        stop = stop or []

        try:
            output = self._model(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stop= stop,
                echo= False
            )
            return output["choices"][0]['text'].strip()
        except Exception as e:
            emit(EventType.ERROR, source= "LLMEngine", error = str(e), operation = "complete")
            return ""
        
    def chat(self, messages: List[Dict[str,str]], system_prompt : str = None, max_tokens: int = None, temperature: float = None)-> str:
        if not self._load_model():
            return ""
        
        full_messages = []

        if system_prompt:
            full_messages.append({
                "role":"system",
                "content": system_prompt
            })

        full_messages.extend(messages)

        try:
            output = self._model.create_chat_completion(
                messages= full_messages,
                max_tokens=self._max_tokens,
                temperature=self._temperature
            )

            return output["choices"][0]['message']['content'].strip()
        
        except Exception as e:
            emit(EventType.ERROR, source="LLMEngine", error = str(e), operation = "chat")
            return ""
    
    def chat_json(self, messages: List[Dict[str,str]], system_prompt:str = None, max_retries:int = 2)->Optional[Dict]:
        json_system = system_prompt if system_prompt else ""
        if "json" not in json_system.lower():
            json_system+= "\n\n Respond with vaild JSON only. No other text."
        
        for attempt in range(max_retries +1):
            response = self.chat(messages, json_system, temperature=self.config.llm.temperature)

            if not response:
                continue
        
        try:
            return json.loads(response)

        except json.JSONDecodeError:
            json_str = self._extract_json(response)
            if json_str:
                try:
                    return json.loads(json_str)
                except:
                    pass
            
        if attempt< max_retries:
            messages = messages + [
                {"role":"assistant","content":response},
                {"role":"user","content":"This was not valid JSON. Please respond with ONLY a JSON object, no other text."
                 }
            ]

        
        emit(EventType.ERROR, source= "LLMEngine", error = "Failed to get valid JSON", operator = "chat_json")
        return None
    
    def _extract_json(self,text:str)->Optional[str]:
        start = text.find('{')
        if start == -1:
            return None
        
        depth = 0
        for i, char in enumerate(text[start:], start):
            if char == "{":
                depth +=1
            elif char == "}":
                depth -=1
                if depth == 0:
                    return text[start:i+1]
        return None
    
    def is_loaded(self) -> bool:
        return self._model_loaded
    
    def preload(self)->bool:
        return self._load_model()
    
    def unload(self)->None:
        if self._model is not None:
            del self._model
            self._model = None
            self._model_loaded = False

            import gc
            gc.collect()
            
            emit(EventType.LLM_UNLOADED, source = "LLMEngine")
    
_engine_instance:Optional[LLMEngine] = None

def get_llm_engine()->LLMEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LLMEngine()
    return _engine_instance

