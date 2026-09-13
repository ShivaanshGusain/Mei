from llama_cpp import Llama
from pathlib import Path

model_path = str(Path("models/xLAM-2-1B-fc-r-Q4_0.gguf"))
print(f"Loading {model_path} with n_gpu_layers=-1 ...")

try:
    model = Llama(
        model_path=model_path,
        n_ctx=512,
        n_gpu_layers=-1,
        verbose=True,
    )
    print("SUCCESS — model loaded on GPU")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback; traceback.print_exc()