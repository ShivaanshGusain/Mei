import ctypes
import os
print(hasattr(os, 'makedirs'))  # Should print True
print(dir(ctypes.windll.shcore))  # Lists available functions like SetProcessDpiAwareness
