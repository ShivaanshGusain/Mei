# Cognition/cortex.py
"""
Cortex - The Brain of the Agent
Uses LLM to understand commands and decide which UI elements to interact with.

KEY INSIGHT: For tasks like "multiply 7 and 8", we need to click MULTIPLE elements
in sequence: [7] → [×] → [8] → [=]
"""

import os
import sys
import re
import json

os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

from llama_cpp import Llama


class Cortex:
    """
    The thinking brain - uses Qwen LLM to understand commands and create action plans.
    """
    
    def __init__(self, model_path):
        print("[Cortex] Initializing Brain...")
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        print(f"[Cortex] Loading model: {model_path}")
        print("[Cortex] This may take a minute...")
        
        self.llm = Llama(
            model_path=model_path,
            n_ctx=4096,
            n_threads=4,
            n_gpu_layers=0,
            verbose=False
        )
        
        print("[Cortex] Brain Online.")
    
    def think(self, user_command, ui_elements, active_window_title="Unknown"):
        """
        Given a user command and visible UI elements, decide what to click.
        
        Returns:
            List[int]: Indices of elements to click, in order
        """
        
        if not ui_elements:
            print("[Cortex] No UI elements to analyze.")
            return []
        
        # First, understand what the user wants
        print(f"[Cortex] Command: '{user_command}'")
        print(f"[Cortex] Window: '{active_window_title}'")
        print(f"[Cortex] Elements: {len(ui_elements)}")
        
        # Check for special cases based on window type
        window_lower = active_window_title.lower()
        
        # CALCULATOR SPECIAL HANDLING
        if 'calculator' in window_lower:
            return self._handle_calculator(user_command, ui_elements)
        
        # BROWSER SPECIAL HANDLING
        if any(browser in window_lower for browser in ['chrome', 'brave', 'firefox', 'edge']):
            return self._handle_browser(user_command, ui_elements)
        
        # GENERAL HANDLING
        return self._handle_general(user_command, ui_elements, active_window_title)
    
    def _handle_calculator(self, user_command, ui_elements):
        """Special handling for Calculator app."""
        print("[Cortex] Calculator mode activated")
        
        command_lower = user_command.lower()
        
        # Build a map of element names to indices
        element_map = {}
        for elem in ui_elements:
            content = str(elem.get('content', '')).lower().strip()
            idx = elem.get('index', -1)
            if content and idx >= 0:
                element_map[content] = idx
        
        # Debug: Show what we found
        print(f"[Cortex] Calculator elements found: {list(element_map.keys())[:20]}")
        
        # Parse the math operation
        sequence = []
        
        # Number word to digit mapping
        word_to_digit = {
            'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
            'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
            'ten': '10'
        }
        
        # Operation word to symbol mapping
        word_to_op = {
            'plus': 'plus', 'add': 'plus', 'added': 'plus', 
            'minus': 'minus', 'subtract': 'minus', 'subtracted': 'minus',
            'times': 'multiply', 'multiply': 'multiply', 'multiplied': 'multiply', 'x': 'multiply',
            'divide': 'divide', 'divided': 'divide', 'over': 'divide',
            'equals': 'equals', 'equal': 'equals', 'is': 'equals'
        }
        
        # Extract numbers and operations from command
        tokens = re.findall(r'[\d]+|[a-zA-Z]+', command_lower)
        
        for token in tokens:
            # Check if it's a number word
            if token in word_to_digit:
                digit = word_to_digit[token]
                # Find the button for this digit
                for key in element_map:
                    if key == digit or key == f"'{digit}'" or digit in key:
                        sequence.append(element_map[key])
                        print(f"[Cortex] Found digit '{digit}' at index {element_map[key]}")
                        break
            
            # Check if it's a digit
            elif token.isdigit():
                for char in token:
                    for key in element_map:
                        if key == char or key == f"'{char}'" or (len(key) <= 3 and char in key):
                            sequence.append(element_map[key])
                            print(f"[Cortex] Found digit '{char}' at index {element_map[key]}")
                            break
            
            # Check if it's an operation
            elif token in word_to_op:
                op = word_to_op[token]
                for key in element_map:
                    if op in key.lower():
                        sequence.append(element_map[key])
                        print(f"[Cortex] Found operation '{op}' at index {element_map[key]}")
                        break
        
        # Add equals at the end if we have an operation
        if len(sequence) >= 3:  # At least num op num
            for key in element_map:
                if 'equals' in key.lower() or key == '=':
                    sequence.append(element_map[key])
                    print(f"[Cortex] Added equals at index {element_map[key]}")
                    break
        
        if sequence:
            print(f"[Cortex] Calculator sequence: {sequence}")
            return sequence
        
        # Fallback to LLM if parsing failed
        print("[Cortex] Parsing failed, trying LLM...")
        return self._handle_general(user_command, ui_elements, "Calculator")
    
    def _handle_browser(self, user_command, ui_elements):
        """Special handling for browser."""
        print("[Cortex] Browser mode activated")
        
        command_lower = user_command.lower()
        
        # Look for common browser actions
        element_map = {}
        for elem in ui_elements:
            content = str(elem.get('content', '')).lower().strip()
            idx = elem.get('index', -1)
            if content and idx >= 0:
                element_map[content] = idx
        
        # Search for specific targets
        targets = []
        
        # "click X" or "press X"
        click_match = re.search(r'(?:click|press|select|open)\s+(?:the\s+)?(?:on\s+)?(.+)', command_lower)
        if click_match:
            target = click_match.group(1).strip()
            targets.append(target)
        
        # If no explicit target, use whole command
        if not targets:
            targets = [command_lower]
        
        # Find matching elements
        for target in targets:
            for key, idx in element_map.items():
                if target in key or key in target:
                    print(f"[Cortex] Found match: '{key}' for target '{target}'")
                    return [idx]
        
        # Fallback to LLM
        return self._handle_general(user_command, ui_elements, "Browser")
    
    def _handle_general(self, user_command, ui_elements, window_title):
        """General handling using LLM."""
        
        # Format elements (limit to most relevant ones)
        elements_text = self._format_elements_smart(ui_elements, user_command)
        
        # Build prompt
        prompt = self._build_smart_prompt(user_command, elements_text, window_title)
        
        print("[Cortex] Asking LLM...")
        
        try:
            response = self.llm(
                prompt,
                max_tokens=100,
                temperature=0.1,
                stop=["</s>", "\n\n", "User:", "Human:", "Note:", "Explanation:"],
                echo=False
            )
            
            response_text = response['choices'][0]['text'].strip()
            print(f"[Cortex] LLM raw: {response_text[:100]}")
            
            # Parse response
            indices = self._parse_response(response_text, len(ui_elements))
            
            return indices
            
        except Exception as e:
            print(f"[Cortex] LLM Error: {e}")
            return []
    
    def _format_elements_smart(self, ui_elements, user_command, max_elements=25):
        """Format elements, prioritizing ones relevant to the command."""
        
        command_words = set(user_command.lower().split())
        
        # Score elements by relevance
        scored_elements = []
        for elem in ui_elements:
            content = str(elem.get('content', '')).lower()
            elem_type = str(elem.get('type', '')).lower()
            idx = elem.get('index', 0)
            
            # Calculate relevance score
            score = 0
            for word in command_words:
                if word in content:
                    score += 10
                if word in elem_type:
                    score += 5
            
            # Boost interactive elements
            if elem.get('interactivity', False):
                score += 2
            
            # Boost buttons
            if 'button' in elem_type:
                score += 3
            
            scored_elements.append((score, idx, elem))
        
        # Sort by score (descending) then by index
        scored_elements.sort(key=lambda x: (-x[0], x[1]))
        
        # Take top elements
        top_elements = scored_elements[:max_elements]
        
        # Format for prompt
        lines = []
        for score, idx, elem in top_elements:
            content = str(elem.get('content', ''))[:35]
            elem_type = elem.get('type', 'Element')
            lines.append(f"{idx}: [{elem_type}] \"{content}\"")
        
        return '\n'.join(lines)
    
    def _build_smart_prompt(self, user_command, elements_text, window_title):
        """Build an effective prompt."""
        
        prompt = f"""Task: Find UI element to click.

Window: {window_title}

Elements:
{elements_text}

Command: "{user_command}"

Instructions:
- Return the element number that best matches the command
- For multi-step tasks, return numbers separated by commas (e.g., "3, 5, 7")
- If clicking "7" then "multiply" then "8" then "equals", return "7, multiply_index, 8, equals_index"
- If no match, return "none"

Answer (number only):"""
        
        return prompt
    
    def _parse_response(self, response_text, max_index):
        """Parse LLM response to extract element indices."""
        
        response_clean = response_text.lower().strip()
        
        # Check for explicit "none"
        if response_clean.startswith('none') or 'no match' in response_clean or 'cannot' in response_clean:
            return []
        
        indices = []
        
        # Try JSON array
        array_match = re.search(r'$$[\d\s,]+$$', response_text)
        if array_match:
            try:
                parsed = json.loads(array_match.group())
                if isinstance(parsed, list):
                    indices = [int(i) for i in parsed]
            except:
                pass
        
        # Try comma-separated
        if not indices:
            comma_match = re.search(r'(\d+(?:\s*,\s*\d+)*)', response_text)
            if comma_match:
                nums = comma_match.group().split(',')
                indices = [int(n.strip()) for n in nums if n.strip().isdigit()]
        
        # Try any numbers
        if not indices:
            numbers = re.findall(r'\b(\d+)\b', response_text)
            indices = [int(n) for n in numbers[:5]]  # Max 5
        
        # Validate
        valid = [i for i in indices if 0 <= i < max_index]
        
        # Remove duplicates preserving order
        seen = set()
        unique = []
        for i in valid:
            if i not in seen:
                seen.add(i)
                unique.append(i)
        
        return unique


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("CORTEX TEST")
    print("="*60)
    
    MODEL_PATH = r"C:\Users\Asus\Projects\Mei\models\qwen2.5-3b-instruct-q4_k_m.gguf"
    
    brain = Cortex(MODEL_PATH)
    
    # Test Calculator scenario
    print("\n" + "-"*60)
    print("TEST: Calculator - 'multiply 7 and 8'")
    print("-"*60)
    
    calc_elements = [
        {'index': 0, 'content': '0', 'type': 'Button', 'interactivity': True},
        {'index': 1, 'content': '1', 'type': 'Button', 'interactivity': True},
        {'index': 2, 'content': '2', 'type': 'Button', 'interactivity': True},
        {'index': 3, 'content': '3', 'type': 'Button', 'interactivity': True},
        {'index': 4, 'content': '4', 'type': 'Button', 'interactivity': True},
        {'index': 5, 'content': '5', 'type': 'Button', 'interactivity': True},
        {'index': 6, 'content': '6', 'type': 'Button', 'interactivity': True},
        {'index': 7, 'content': '7', 'type': 'Button', 'interactivity': True},
        {'index': 8, 'content': '8', 'type': 'Button', 'interactivity': True},
        {'index': 9, 'content': '9', 'type': 'Button', 'interactivity': True},
        {'index': 10, 'content': 'Plus', 'type': 'Button', 'interactivity': True},
        {'index': 11, 'content': 'Minus', 'type': 'Button', 'interactivity': True},
        {'index': 12, 'content': 'Multiply', 'type': 'Button', 'interactivity': True},
        {'index': 13, 'content': 'Divide', 'type': 'Button', 'interactivity': True},
        {'index': 14, 'content': 'Equals', 'type': 'Button', 'interactivity': True},
        {'index': 15, 'content': 'Clear', 'type': 'Button', 'interactivity': True},
    ]
    
    result = brain.think("multiply 7 and 8", calc_elements, "Calculator")
    print(f"\nResult: {result}")
    print(f"Expected: [7, 12, 8, 14] (7 × 8 =)")
    
    # Test Browser scenario
    print("\n" + "-"*60)
    print("TEST: Browser - 'click the search button'")
    print("-"*60)
    
    browser_elements = [
        {'index': 0, 'content': 'Back', 'type': 'Button', 'interactivity': True},
        {'index': 1, 'content': 'Forward', 'type': 'Button', 'interactivity': True},
        {'index': 2, 'content': 'Reload', 'type': 'Button', 'interactivity': True},
        {'index': 3, 'content': 'Address Bar', 'type': 'Edit', 'interactivity': True},
        {'index': 4, 'content': 'Search', 'type': 'Button', 'interactivity': True},
        {'index': 5, 'content': 'Settings', 'type': 'Button', 'interactivity': True},
    ]
    
    result = brain.think("click the search button", browser_elements, "Brave")
    print(f"\nResult: {result}")
    print(f"Expected: [4]")