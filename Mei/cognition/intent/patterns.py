import re
from ...core.task import Intent

SHORTCUT_MAP = {
    "copy": ["ctrl", "c"],
    "paste": ["ctrl", "v"],
    "undo": ["ctrl", "z"],
    "redo": ["ctrl", "y"],
    "cut": ["ctrl", "x"],
    "save": ["ctrl", "s"],
}

FAST_PATTERNS = [
    (
        re.compile(r"^scroll\s+(up|down)$", re.IGNORECASE),
        lambda m: Intent(
            action="scroll",
            parameters={"direction": m.group(1).lower()},
            confidence=1.0,
            raw_command=m.string,
            complexity="simple",
            domain="system",
        ),
    ),
    (
        re.compile(r"^press\s+(enter|escape|tab|space|delete|backspace)$", re.IGNORECASE),
        lambda m: Intent(
            action="hotkey",
            parameters={"keys": [m.group(1).lower()]},
            confidence=1.0,
            raw_command=m.string,
            complexity="simple",
            domain="system",
        ),
    ),
    (
        re.compile(r"^(copy|paste|undo|redo|cut|save)$", re.IGNORECASE),
        lambda m: Intent(
            action="hotkey",
            parameters={"keys": SHORTCUT_MAP[m.group(1).lower()]},
            confidence=1.0,
            raw_command=m.string,
            complexity="simple",
            domain="system",
        ),
    ),
    (
        re.compile(r"^(minimize|maximize|restore)\s*(this|current)?(\s*window)?$", re.IGNORECASE),
        lambda m: Intent(
            action=m.group(1).lower(),
            target="current",
            parameters={},
            confidence=1.0,
            raw_command=m.string,
            complexity="simple",
            domain="system",
        ),
    ),
]
