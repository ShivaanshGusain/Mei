""" Computation cost check """
import tracemalloc
try:
    import pynvml
    pynvml.nvmlInit()
    VRAM_TRACKING = True
except ImportError:
    VRAM_TRACKING = False
    print("pynvml not installed. Skipping VRAM tracking.")

# Start tracking System RAM immediately when the module loads
tracemalloc.start()
#---------------------

from llama_cpp import Llama

from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from typing import List, Dict, Optional, Any

import threading
import json
import os




class LLMEngine:
    
    def __init__(self, model_path: str, name: str = 'default', **kwargs):
        self._name = name
        self._model_path = model_path
        self.config = get_config()
        self._model = None
        self._model_loaded = False
        self._load_lock = threading.Lock()
        
        self._context_length = self.config.llm.context_length
        self._max_tokens = self.config.llm.max_tokens
        self._temperature = self.config.llm.temperature
        self._threads = self.config.llm.threads
        
        if self._name == "intent":
            self._gpu_layers = self.config.llm.intent_gpu_layers
            self._context_length = self.config.llm.intent_context_length
        elif self._name == "planner":
            self._gpu_layers = self.config.llm.planner_gpu_layers
            self._context_length = self.config.llm.planner_context_length
        else:
            self._gpu_layers = self.config.llm.gpu_layers
    
    def _load_model(self)->bool:
        if self._model_loaded:
            return True
        
        with self._load_lock:
            if self._model_loaded:
                return True
            try:
                print(f"Loading Model [{self._name}]: {self._model_path} (GPU Layers: {self._gpu_layers})")
                emit(event_type=EventType.LLM_LOADING, source=f"LLMEngine_{self._name}")

                self._model = Llama(
                    model_path=self._model_path,
                    n_ctx=self._context_length,
                    n_gpu_layers=self._gpu_layers,
                    n_threads=self._threads,
                    verbose=False
                )

                self._model_loaded = True
                print(f"Model [{self._name}] Loaded Successfully")
                emit(EventType.LLM_LOADED, source=f"LLMEngine_{self._name}")
                return True

            except Exception as e:
                print(f"Failed to load model [{self._name}]: {e}")
                emit(event_type=EventType.ERROR, source=f"LLMEngine_{self._name}", error=str(e), operation="load_model")
                return False
        
    def complete(self, prompt: str, max_tokens: int = None, temperature: float = None, stop: List[str] = None) -> str:
        
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
                stop=stop,
                echo=False
            )
            return output["choices"][0]['text'].strip()
        except Exception as e:
            emit(EventType.ERROR, source=f"LLMEngine_{self._name}", error=str(e), operation="complete")
            print(f"[{self._name}] chat() failed: {e}")
            return ""
        
    def chat(self, messages: List[Dict[str, str]], system_prompt: str = None, max_tokens: int = None, temperature: float = None)-> str:
        if not self._load_model():
            return ""
        
        full_messages = []
        if system_prompt:
            full_messages.append({
                "role": "system",
                "content": system_prompt
            })

        full_messages.extend(messages)
        max_tokens = max_tokens or self._max_tokens
        temperature = temperature or self._temperature

        try:
            output = self._model.create_chat_completion(
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature
            )

            return output["choices"][0]['message']['content'].strip()
        except Exception as e:
            emit(EventType.ERROR, source=f"LLMEngine_{self._name}", error=str(e), operation="chat")
            print(f"[{self._name}] chat() failed: {e}")
            return ""
    
    def chat_json(self, messages: List[Dict[str, str]], system_prompt: str = None, max_retries: int = 2)->Optional[Dict]:
        json_system = system_prompt if system_prompt else ""
        if "json" not in json_system.lower():
            json_system += "\n\n Respond with valid JSON only. No other text."
        
        for attempt in range(max_retries + 1):
            response = self.chat(messages, json_system, temperature=self._temperature)

            if not response:
                continue
        
            try:
                return json.loads(response)
            except json.JSONDecodeError:
                json_str = self._extract_json(response)
                if json_str:
                    try:
                        print(json_str)
                        return json.loads(json_str)
                    except:
                        print(f"[{self._name}] chat() failed: {json.JSONDecodeError}")
                        pass
            print("[LLM] ",response)
            if attempt < max_retries:
                messages = messages + [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": "This was not valid JSON. Please respond with ONLY a JSON object, no other text."}
                ]

        emit(EventType.ERROR, source=f"LLMEngine_{self._name}", error="Failed to get valid JSON", operation="chat_json")
        print(f"[{self._name}] chat() failed: Failed to get valid JSON")
        return None
    
    def chat_tool_call(
        self,
        messages: List[Dict[str, str]],
        tool_names: List[str],
        system_prompt: str = None
    ) -> Optional[Dict]:
        """
        Constrained JSON generation — model output is physically restricted to
        valid tool names via JSON Schema grammar. No retry loop needed.

        tool_names: list of valid action names from the tool retriever.
        Falls back to chat_json if constrained decoding is unavailable.
        """
        if not self._load_model():
            return None

        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": tool_names
                },
                "parameters": {
                    "type": "object"
                }
            },
            "required": ["action", "parameters"]
        }

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        try:
            output = self._model.create_chat_completion(
                messages=full_messages,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format={
                    "type": "json_object",
                    "schema": schema
                }
            )
            raw = output["choices"][0]["message"]["content"].strip()
            result = json.loads(raw)
            print(f"[{self._name}] chat_tool_call: action={result.get('action')}")
            return result

        except Exception as e:
            # Fallback to chat_json if constrained decoding is not supported
            print(f"[{self._name}] chat_tool_call failed ({e}), falling back to chat_json")
            return self.chat_json(messages=messages, system_prompt=system_prompt, max_retries=1)

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

    """ ------------------Memory check------------------"""        
    def print_memory_usage(self) -> None:
        """Calculates and prints the peak RAM and current VRAM usage."""
        current_ram, peak_ram = tracemalloc.get_traced_memory()
        
        print("\n" + "=" * 40)
        print(f"💻 MEMORY CONSUMPTION REPORT [{self._name}]")
        print("=" * 40)
        print(f"Peak System RAM: {peak_ram / (1024 * 1024):.2f} MB")
        
        if VRAM_TRACKING:
            try:
                # Get handle for the first GPU (index 0)
                gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0) 
                memory_info = pynvml.nvmlDeviceGetMemoryInfo(gpu_handle)
                print(f"Total GPU VRAM Used: {memory_info.used / (1024 * 1024):.2f} MB")
            except Exception as e:
                print(f"Failed to read VRAM: {e}")
        print("=" * 40 + "\n")
# _engine_instance:Optional[LLMEngine] = None

_engines: Dict[str, LLMEngine] = {}
def get_llm_engine(name: str = "default")->LLMEngine:
    global _engines
    
    if name not in _engines:
        config = get_config()
        if name == "intent":
            path = config.llm.intent_model_path
        elif name == "planner":
            path = config.llm.planner_model_path
        else:
            path = config.llm.model_path
        _engines[name] = LLMEngine(model_path=path, name=name)
    
    return _engines[name]

