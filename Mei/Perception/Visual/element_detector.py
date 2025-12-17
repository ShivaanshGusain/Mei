# Perception/Visual/element_detector.py
"""
VisualEye - Uses OmniParser for visual UI element detection.
Fallback when Symbolic (Accessibility API) doesn't find enough elements.
"""

import os
import sys

# ══════════════════════════════════════════════════════════════════════════════
# CRITICAL: Set up paths BEFORE any other imports
# ══════════════════════════════════════════════════════════════════════════════

# Get the directory where THIS file is located
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# OmniParser is inside the Visual folder (same folder as this file)
OMNIPARSER_DIR = os.path.join(CURRENT_DIR, "OmniParser")

# Add paths to sys.path so Python can find OmniParser
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if OMNIPARSER_DIR not in sys.path:
    sys.path.insert(0, OMNIPARSER_DIR)

# Suppress warnings
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

# ══════════════════════════════════════════════════════════════════════════════
# Mock flash_attn to prevent import errors (MUST be before torch/transformers)
# ══════════════════════════════════════════════════════════════════════════════

from unittest.mock import MagicMock
import types

if "flash_attn" not in sys.modules:
    fake_flash = types.ModuleType("flash_attn")
    fake_flash.__spec__ = types.SimpleNamespace(
        name="flash_attn", 
        loader=None, 
        origin="fake", 
        submodule_search_locations=[]
    )
    fake_flash.__path__ = []
    fake_interface = types.ModuleType("flash_attn.flash_attn_interface")
    fake_flash.flash_attn_interface = fake_interface
    sys.modules["flash_attn"] = fake_flash
    sys.modules["flash_attn.flash_attn_interface"] = fake_interface

# ══════════════════════════════════════════════════════════════════════════════
# Now we can import everything else
# ══════════════════════════════════════════════════════════════════════════════

import torch
from PIL import Image

# Import from OmniParser (now Python can find it)
try:
    from OmniParser.util.utils import (
        get_caption_model_processor, 
        get_yolo_model, 
        get_som_labeled_img
    )
    OMNIPARSER_AVAILABLE = True
except ImportError as e:
    print(f"[VisualEye] WARNING: OmniParser import failed: {e}")
    print(f"[VisualEye] Looked in: {OMNIPARSER_DIR}")
    OMNIPARSER_AVAILABLE = False


class VisualEye:
    """
    Visual perception using OmniParser.
    Detects UI elements by analyzing screenshot images.
    """
    
    def __init__(self, base_path=None):
        print("[VisualEye] Initializing Visual Perception...")
        
        if not OMNIPARSER_AVAILABLE:
            raise ImportError("OmniParser is not available. Check the installation.")
        
        # Weights are inside OmniParser folder
        omni_weights = os.path.join(OMNIPARSER_DIR, "weights")
        
        print(f"[VisualEye] Looking for weights in: {omni_weights}")
        
        if not os.path.exists(omni_weights):
            raise FileNotFoundError(f"OmniParser weights folder not found: {omni_weights}")
        
        # Find caption model path (might be named differently)
        caption_candidates = [
            os.path.join(omni_weights, "icon_caption_florence"),
            os.path.join(omni_weights, "icon_caption"),
        ]
        
        self.caption_path = None
        for path in caption_candidates:
            if os.path.exists(path):
                self.caption_path = path
                break
        
        if not self.caption_path:
            raise FileNotFoundError(f"Caption model not found. Tried: {caption_candidates}")
        
        # Detection model path
        self.detect_path = os.path.join(omni_weights, "icon_detect", "model.pt")
        
        if not os.path.exists(self.detect_path):
            raise FileNotFoundError(f"Detection model not found: {self.detect_path}")
        
        print(f"[VisualEye] Caption model: {self.caption_path}")
        print(f"[VisualEye] Detection model: {self.detect_path}")
        
        # Determine device
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[VisualEye] Using device: {self.device}")
        
        # Load models
        print("[VisualEye] Loading caption model (this may take a moment)...")
        self.caption_model = get_caption_model_processor(
            model_name='florence2',
            model_name_or_path=self.caption_path,
            device=self.device
        )
        
        print("[VisualEye] Loading detection model...")
        self.yolo_model = get_yolo_model(model_path=self.detect_path)
        
        print("[VisualEye] Online.")
    
    def inspect_screen(self, image_path, confidence_threshold=0.05):
        """
        Analyze a screenshot and return detected UI elements.
        
        Args:
            image_path: Path to screenshot image
            confidence_threshold: Minimum confidence for detections
        
        Returns:
            tuple: (elements_list, debug_image_path)
        """
        print(f"[VisualEye] Analyzing: {image_path}")
        
        if not os.path.exists(image_path):
            print(f"[VisualEye] ERROR: Image not found: {image_path}")
            return [], None
        
        try:
            # Run OmniParser
            labeled_image, coordinates, raw_elements = get_som_labeled_img(
                image_source=image_path,
                model=self.yolo_model,
                BOX_TRESHOLD=confidence_threshold,
                output_coord_in_ratio=True,
                ocr_bbox=None,
                draw_bbox_config=None,
                caption_model_processor=self.caption_model,
                iou_threshold=0.1,
            )
            
            # Save debug image
            debug_path = image_path.replace(".png", "_debug.png").replace(".jpg", "_debug.jpg")
            labeled_image.save(debug_path)
            print(f"[VisualEye] Debug image saved: {debug_path}")
            
            # Convert raw_elements to our standard format
            elements = []
            for idx, elem in enumerate(raw_elements):
                # Handle both dict format and raw list format
                if isinstance(elem, dict):
                    bbox = elem.get('bbox', [0, 0, 0, 0])
                    content = elem.get('content', '')
                    elem_type = elem.get('type', 'icon')
                elif isinstance(elem, (list, tuple)):
                    bbox = list(elem)
                    content = ''
                    elem_type = 'icon'
                else:
                    continue
                
                # Clean up content
                if content is None or content == '':
                    content = f'Element_{idx}'
                content = str(content).strip()
                
                elements.append({
                    'index': idx,
                    'content': content,
                    'type': elem_type,
                    'bbox': bbox,  # [x1, y1, x2, y2] as ratios 0-1
                    'interactivity': True,
                    'source': 'visual'
                })
            
            print(f"[VisualEye] Found {len(elements)} elements.")
            return elements, debug_path
            
        except Exception as e:
            print(f"[VisualEye] ERROR during analysis: {e}")
            import traceback
            traceback.print_exc()
            return [], None


# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("VISUAL EYE TEST")
    print("="*60)
    
    print(f"\nCurrent directory: {CURRENT_DIR}")
    print(f"OmniParser directory: {OMNIPARSER_DIR}")
    print(f"OmniParser exists: {os.path.exists(OMNIPARSER_DIR)}")
    
    if not OMNIPARSER_AVAILABLE:
        print("\nERROR: OmniParser not available!")
        sys.exit(1)
    
    try:
        eye = VisualEye()
        
        # Look for test image
        test_image = os.path.join(CURRENT_DIR, "test_screenshot.png")
        
        if os.path.exists(test_image):
            elements, debug_path = eye.inspect_screen(test_image)
            
            print(f"\n{'='*60}")
            print(f"FOUND {len(elements)} ELEMENTS:")
            print(f"{'='*60}")
            
            for elem in elements[:15]:
                bbox_str = str(elem['bbox'])[:30]
                print(f"[{elem['index']:2d}] {elem['type']:6s} | {bbox_str:30s} | {elem['content'][:25]}")
        else:
            print(f"\nTo test, create: {test_image}")
            print("(Take a screenshot and save it there)")
            
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()