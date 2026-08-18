from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent, IntentSequence, IntentStep, StepExecutionStatus
from ..llm.engine import get_llm_engine
from typing import Optional, Dict, List, Any
import json

from .patterns import FAST_PATTERNS
from .prompts import NLU_DECOMPOSE_PROMPT, NLU_VERIFY_PROMPT


class IntentExtractor:

    def __init__(self, auto_subscribe: bool = True):
        self._llm = get_llm_engine("intent")

        if auto_subscribe:
            subscribe(event_type=EventType.TRANSCRIBE_COMPLETED,handler=self._on_transcribe)
            print("Subscribed to TRANSCRIBE_COMPLETED")
        
        self._action_synonyms = {
            "launch":"open",
            "start":"open",
            "run":"open",
            "switch":"focus",
            "activate":"focus",
            "bring":"focus",
            "shut":"close",
            "exit":"close",
            "quit": "close",
            "look": "search",
            "google": "search",
            "write": "type",
            "enter": "type",
            "go": "navigate",
            "goto": "navigate",
        }

    def _on_transcribe(self, event)->None:
        text = event.data.get("text","")
        if not text or not text.strip():
            return
        # Removed emit INTENT_RECOGNIZED since pipeline handles the flow now
        pass
    
    def _try_fast_extract(self, text: str) -> Optional[Intent]:
        for pattern, builder in FAST_PATTERNS:
            match = pattern.match(text)
            if match:
                return builder(match)
        return None
        
    def decompose(self, raw_command: str) -> IntentSequence:
        raw_command = raw_command.strip()
        if not raw_command:
            return IntentSequence(raw_command="")
            
        fast_intent = self._try_fast_extract(raw_command)
        if fast_intent:
            step = IntentStep(
                step_id=1,
                description=f"{fast_intent.action} {fast_intent.target}",
                expected_output="",
                domain=fast_intent.domain,
                target=fast_intent.target,
                parameters=fast_intent.parameters
            )
            return IntentSequence(raw_command=raw_command, steps=[step])

        messages = [{"role":"user","content":raw_command}]
        print(f"Decomposing intent from: {raw_command}")
        response = self._llm.chat_json(messages=messages, system_prompt=NLU_DECOMPOSE_PROMPT)
        
        if not response:
            print("Failed to get LLM response for decompose")
            emit(EventType.ERROR, source="IntentExtractor", error="LLM returned no response", operation="decompose")
            return IntentSequence(raw_command=raw_command)

        # If the LLM returns a single dictionary instead of an array, wrap it in a list
        # Fix -> Training model remaining
        if isinstance(response, dict):
            response = response.get("steps", [response])
        steps = []
        if isinstance(response, list):
            for s in response:
                steps.append(IntentStep(
                    step_id=s.get("step_id", len(steps)+1),
                    description=s.get("description", ""),
                    expected_output=s.get("expected_output", ""),
                    domain=s.get("domain", "unknown"),
                    target=s.get("target"),
                    parameters=s.get("parameters", {})
                ))
        return IntentSequence(raw_command=raw_command, steps=steps)

    def verify_macro(self, raw_command: str, candidate_goal: dict, actions: list) -> Optional[IntentSequence]:
        prompt = NLU_VERIFY_PROMPT.format(
            raw_command=raw_command,
            proposed_actions_json=json.dumps(actions)
        )
        messages = [{"role": "user", "content": "Verify this macro"}]
        response = self._llm.chat_json(messages=messages, system_prompt=prompt)
        
        if not response or not response.get("approved"):
            print(f"Macro rejected: {response.get('reason') if response else 'No response'}")
            return None
            
        steps = []
        for s in response.get("steps", []):
            steps.append(IntentStep(
                step_id=s.get("step_id", len(steps)+1),
                description=s.get("description", ""),
                expected_output=s.get("expected_output", ""),
                domain=s.get("domain", "unknown"),
                target=s.get("target"),
                parameters=s.get("parameters", {})
            ))
            
        return IntentSequence(
            raw_command=raw_command, 
            steps=steps,
            is_verified_macro=True,
            source_goal_id=candidate_goal.get("id"),
            confidence=candidate_goal.get("confidence", 1.0)
        )

    def extract(self, text: str) -> Optional[Intent]:
        # Backwards compatible method
        fast_intent = self._try_fast_extract(text)
        if fast_intent:
            return fast_intent
            
        seq = self.decompose(text)
        if not seq or not seq.steps:
            return None
        step = seq.steps[0]
        action = step.parameters.get("action", "unknown")
        
        if action == "unknown" and step.description:
            action = step.description.split()[0].lower()
            
        return Intent(
            action=action,
            target=step.target,
            parameters=step.parameters,
            confidence=0.8,
            raw_command=text,
            complexity="simple" if len(seq.steps) == 1 else "multi_step",
            domain=step.domain
        )
        
    def extract_batch(self, texts: List[str]) -> List[Optional[Intent]]:
        return [self.extract(text) for text in texts]

_extractor_instance: Optional[IntentExtractor] = None

def get_intent_extractor(auto_subscribe: bool = True) -> IntentExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = IntentExtractor(auto_subscribe=auto_subscribe)
    return _extractor_instance

def extract_intent(text: str) -> Optional[Intent]:
    return get_intent_extractor().extract(text)

if __name__ =="__main__":
    extractor = IntentExtractor(auto_subscribe=False)
    
    test_commands = [
        "open brave and search for cats on youtube"
    ]

    for cmd in test_commands:
        print(f"\n Command: {cmd}")
        seq = extractor.decompose(cmd)
        if seq and seq.steps:
            for s in seq.steps:
                print(f"Step {s.step_id}: {s.description} ({s.domain}) -> {s.parameters}")
        else:
            print("Failed")
    engine = get_llm_engine("intent")
    extractor._llm.print_memory_usage()
