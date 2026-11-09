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
from llama_cpp.llama_grammar import LlamaGrammar

from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from .tool_schema import build_tool_call_schema, grammar_mode
from typing import List, Dict, Optional, Any, Union

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
        # Set by chat_tool_call: which grammar mode produced the last answer,
        # and why the last call returned None (if it did).
        self.last_tool_call_mode: Optional[str] = None
        self.last_tool_call_error: Optional[str] = None

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
                # Swap out any other GPU-resident model first
                if self._gpu_layers != 0:
                    _ensure_gpu_exclusive(self._name)

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
    
    def chat_json(self, messages: List[Dict[str, str]], system_prompt: str = None, max_retries: int = 2)->Optional[Union[Dict, List]]:
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
        system_prompt: str = None,
        tool_schemas: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Dict]:
        """
        Constrained JSON generation for one tool call.

        Grammar mode comes from MEI_TOOL_GRAMMAR (see tool_schema.py):
          per_tool  — tool name AND that tool's arguments are constrained,
                      plus a no_tool option (default)
          name_only — only the tool name is constrained (original behaviour)
          off       — no grammar, plain chat_json
        per_tool degrades to name_only, then chat_json, if the grammar fails.
        The mode that actually produced the answer is left in
        self.last_tool_call_mode so callers can log silent degradation.
        """
        # Reset per call so a failed load never leaves the previous call's mode.
        self.last_tool_call_mode = None
        self.last_tool_call_error = None
        if not self._load_model():
            self.last_tool_call_error = "model failed to load"
            return None

        requested = grammar_mode()
        chain = {"per_tool": ["per_tool", "name_only"], "name_only": ["name_only"], "off": []}[requested]

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        for mode in chain:
            schema = build_tool_call_schema(
                tool_names, tool_schemas, mode=mode,
                allow_no_tool=(requested == "per_tool"),
            )
            try:
                # Build the grammar here rather than via response_format:
                # llama-cpp-python silently swaps an unconvertible schema for
                # plain JSON there, which would leave per_tool unenforced while
                # still reporting it. Building it ourselves makes that raise,
                # so the chain falls through to the next mode honestly.
                grammar = LlamaGrammar.from_json_schema(json.dumps(schema), verbose=False)
            except Exception as e:
                print(f"[{self._name}] chat_tool_call: {mode} grammar failed to build: {e}")
                continue

            # Only a grammar that fails to build degrades to the next mode.
            # A generation that fails (cut off at max_tokens, invalid JSON,
            # runtime error) is not a grammar problem: rerunning it under a
            # weaker grammar would cost another full generation and record the
            # wrong mode. Return None so the planner counts it as unparseable.
            self.last_tool_call_mode = mode
            try:
                output = self._model.create_chat_completion(
                    messages=full_messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    grammar=grammar,
                )
                raw = output["choices"][0]["message"]["content"].strip()
                result = json.loads(raw)
            except Exception as e:
                self.last_tool_call_error = f"{type(e).__name__}: {e}"
                print(f"[{self._name}] chat_tool_call ({mode}) generation failed: {e}")
                return None
            print(f"[{self._name}] chat_tool_call ({mode}): action={result.get('action') if isinstance(result, dict) else None}")
            return result

        self.last_tool_call_mode = "off" if requested == "off" else "fallback_chat_json"
        return self.chat_json(messages=messages, system_prompt=system_prompt, max_retries=1)

    def _extract_json(self,text:str)->Optional[str]:
        """Return the first complete JSON value (object OR array) embedded in text.

        Models often wrap JSON in ```json fences or add commentary after it.
        The old brace-counter only looked for '{', so an array response was cut
        down to its first element (silently dropping every later step), and a
        brace inside a string broke the count. raw_decode parses exactly one
        value and ignores whatever follows it.
        """
        decoder = json.JSONDecoder()
        for i, char in enumerate(text):
            if char in "[{":
                try:
                    _, end = decoder.raw_decode(text, i)
                    return text[i:end]
                except json.JSONDecodeError:
                    continue
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
_gpu_residents: Dict[str, Any] = {}   # non-LLMEngine GPU consumers, e.g. VisualAnalyzer
_swap_lock = threading.Lock()
_active_gpu_engine: Optional[str] = None   # name of the engine currently loaded on GPU


def register_gpu_resident(name: str, resident: Any) -> None:
    """
    Let a non-LLMEngine GPU consumer (VisualAnalyzer's YOLO+Florence2) share
    the same one-model-at-a-time VRAM policy as the LLM engines. `resident`
    just needs `.is_loaded()` and `.unload()` methods.

    Without this, the visual fallback's models stayed GPU-resident forever
    once loaded — nothing ever evicted them, so they permanently ate into the
    same 4GB budget the LLM engines swap in and out of, causing fragmentation
    and OOM hangs on smaller GPUs.
    """
    _gpu_residents[name] = resident


def _ensure_gpu_exclusive(requester_name: str) -> None:
    """Unload any other GPU-resident model before `requester_name` loads.

    On a 4 GB laptop GPU the Phi-3.5 intent model (2.6 GB weights + 2.3 GB
    KV-cache) already saturates VRAM.  Loading a second model simultaneously
    causes a native crash.  This function enforces a strict one-model-at-a-time
    policy: it unloads whatever is currently resident before the new model loads.
    """
    global _active_gpu_engine

    with _swap_lock:
        if _active_gpu_engine and _active_gpu_engine != requester_name:
            other = _engines.get(_active_gpu_engine) or _gpu_residents.get(_active_gpu_engine)
            if other and other.is_loaded():
                print(f"[LLMEngine] Swapping out '{_active_gpu_engine}' "
                      f"to make room for '{requester_name}'")
                other.unload()
        _active_gpu_engine = requester_name


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

