import os
os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

import torch
from OmniParser.util.utils import get_caption_model_processor, get_yolo_model, get_som_labeled_img
# Get the folder where the script is actually located (more robust than getcwd)
base_path = os.path.dirname(os.path.abspath(__file__))

class VisualEye:
    # def __init__(self, base_path):
    #     print("Eye is Waking up")
    #     current_dir = os.path.dirname(os.path.abspath(__file__))
    #     omni_base = os.path.join(current_dir, "OmniParser", "weights")
    #     # Define paths INSIDE the class using the passed base_path
    #     # This makes sure it uses the path you send to the class
    #     self.caption_path = os.path.join(base_path, "OmniParser", "weights", "icon_caption")
    #     self.detect_path = os.path.join(base_path, "OmniParser", "weights", "icon_detect","model.pt")

    #     # Check for GPU
    #     device = "cuda" if torch.cuda.is_available() else "cpu"
    #     print(f"Loading models on: {device}")

    #     self.caption_model = get_caption_model_processor(
    #         model_name='florence2',
    #         model_name_or_path=self.caption_path,
    #         device=device
    #     )

    #     self.yolo_model = get_yolo_model(
    #         model_path=self.detect_path
    #     )

    #     print("Eye is Online, Ready to see")
    def __init__(self, base_path=None): # Make base_path optional since we won't use it for paths
        print("Eye is Waking up")
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        omni_base = os.path.join(current_dir, "OmniParser", "weights")
        
        # 3. USE omni_base (Not base_path)
        # We also check for the folder name variations (florence vs standard)
        if os.path.exists(os.path.join(omni_base, "icon_caption_florence")):
             self.caption_path = os.path.join(omni_base, "icon_caption_florence")
        else:
             self.caption_path = os.path.join(omni_base, "icon_caption")

        self.detect_path = os.path.join(omni_base, "icon_detect", "model.pt")

        # 4. Verification (This prevents the cryptic error you just saw)
        print(f"DEBUG: Calculated Model Path: {self.caption_path}")
        if not os.path.exists(self.caption_path):
             raise FileNotFoundError(f"CRITICAL ERROR: The folder '{self.caption_path}' does not exist.")

        # Check for GPU
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading models on: {device}")

        # Load Models
        self.caption_model = get_caption_model_processor(
            model_name='florence2',
            model_name_or_path=self.caption_path,
            device=device
        )

        self.yolo_model = get_yolo_model(
            model_path=self.detect_path
        )

        print("Eye is Online, Ready to see")
    def inspect_screen(self, image_path, confidence_threshold=0.05):
        print(f"Eye is analyzing {image_path}")

        labeled_image, coordinates, text_output = get_som_labeled_img(
            image_source=image_path,
            model=self.yolo_model,
            BOX_TRESHOLD=confidence_threshold,  # Changed to standard lowercase 'box_threshold'
            output_coord_in_ratio=True,
            ocr_bbox=None,
            draw_bbox_config=None,
            caption_model_processor=self.caption_model,
            iou_threshold=0.1,
        )

        debug_path = image_path.replace(".png", "_debug.png")
        labeled_image.save(debug_path)
        
        return text_output, debug_path

if __name__ == '__main__':
    # Use the script's own location as the root
    ProjectROOT = base_path
    
    eye = VisualEye(ProjectROOT)
    test_image = "test_screenshot.png"
    
    # Ensure we look for the image in the project root
    full_image_path = os.path.join(ProjectROOT, test_image)

    if os.path.exists(full_image_path):
        description, debug_img = eye.inspect_screen(full_image_path)
        print("SAW")
        
        # Safety check: Print the first 500 characters instead of the 500th character
        # This prevents a crash if the description is short.
        print(str(description)[:500]) 
        print(len(description))
        print(f"Debug image saved to {debug_img}")
    else:
        print(f"Please put a '{test_image}' in this folder to test: {ProjectROOT}")