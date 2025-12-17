from llama_cpp import Llama
import os
import json
import re

class Cortex:
    def __init__(self, model_path):
        print("[Cortex] Loading Planning Brain...")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found at: {model_path}")

        # Increased context window (n_ctx) so it can remember the whole screen
        self.llm = Llama(
            model_path=model_path,
            n_gpu_layers=-1, 
            n_ctx=8192,
            verbose=False
        )
        print("[Cortex] Brain Online.")

    def think(self, user_command, ui_elements, active_window_title="Unknown"):
        """
        Decides a SEQUENCE of actions.
        Returns: A list of integers (indices) to click in order.
        """
        
        # 1. Create a "Menu" for the AI
        ui_text = ""
        for i, el in enumerate(ui_elements[:60]): 
            # We add the bounding box center to help it understand layout (left/right)
            # content = el.get('content', 'Unknown')
            ui_text += f"{i}. [{el['type']}] '{el['content']}'\n"

        # 2. The "Planner" Prompt
        # We teach it to think in steps.
        prompt = f"""<|im_start|>system
You are a GUI Agent. You have a list of interactive elements.
Your task is to achieve the USER GOAL by clicking elements in the correct order.

RULES:
1. Return ONLY a Python list of integers corresponding to the indices.
2. If multiple steps are needed (e.g., "type hello"), return the sequence of keys/buttons.
3. If the goal is impossible, return [].

EXAMPLE:
User: "Calculate 5 plus 2"
Elements: 
0. [Button] '5'
1. [Button] '+'
2. [Button] '2'
3. [Button] '='
Response: [0, 1, 2, 3]
<|im_end|>
<|im_start|>user
CURRENT WINDOW: {active_window_title}
USER GOAL: "{user_command}"

VISIBLE ELEMENTS:
{ui_text}

Provide the sequence of clicks as a list of integers.
<|im_end|>
<|im_start|>assistant
"""
        # 3. Generate
        output = self.llm(
            prompt, 
            max_tokens=50, 
            stop=["<|im_end|>"],
            temperature=0.1 # Keep it strictly logical
        )
        
        response_text = output['choices'][0]['text'].strip()
        print(f"[Cortex Debug] Raw Thought: {response_text}")

        # 4. Extract the list using Regex (Parsing the brain's output)
        try:
            # Look for something that looks like [1, 2, 3]
            match = re.search(r'\[(.*?)\]', response_text)
            if match:
                # Convert "1, 2, 3" string into [1, 2, 3] integers
                indices = [int(x.strip()) for x in match.group(1).split(',') if x.strip().isdigit()]
                return indices
            else:
                # If it just said "Click 5", try to find a single number
                single_match = re.search(r'\d+', response_text)
                if single_match:
                    return [int(single_match.group(0))]
        except Exception as e:
            print(f"[Cortex] Parsing Error: {e}")
            
        return []