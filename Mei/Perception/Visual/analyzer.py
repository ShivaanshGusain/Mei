import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Gives - .../Mei/perception/Visual

OMNIPARSER_DIR = os.path.join(CURRENT_DIR,"OmniParser")

if OMNIPARSER_DIR not in sys.path:
    sys.path.insert(0,OMNIPARSER_DIR)

os.environ['DISABLE_MODEL_SOURCE_CHECK'] = "True"

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



import threading
import time
import tempfile

import torch
from PIL import Image
import numpy as np

from typing import List, Optional, Tuple, Dict, Any

from ...core.config import get_config,Screenshot, VisualElement, VisualAnalysisResult
from ...core.events import emit, subscribe, EventType

try:
    from .OmniParser.util.utils import get_yolo_model, get_caption_model_processor, get_som_labeled_img,check_ocr_box
    OMNIPARSER_AVAILABLE = True
except ImportError as e:
    print(f"Omniparser Import failed")
    OMNIPARSER_AVAILABLE = False

class VisualAnalyzer:
    def __init__(self):
        if not OMNIPARSER_AVAILABLE:
            raise ImportError("OmniParser not available")
        self.config = get_config().visual
        self._yolo_model = None
        self._caption_model_processor = None
        self._models_loaded = False

        self._load_lock = threading.Lock()
        
        weights_dir = os.path.join(OMNIPARSER_DIR, "weights")
        self._icon_detect_path = os.path.join(weights_dir, "icon_detect","model.pt")
        self._icon_caption_path = os.path.join(weights_dir,"icon_caption")

        if not os.path.exists(self._icon_caption_path):
            raise FileNotFoundError(f"Caption model not found")
        if not os.path.exists(self._icon_detect_path):
            raise FileNotFoundError(f"Detection model not found")

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._type_map = {
            'icon': 'icon',
            'text': 'text',
            'button': 'button',
            'image': 'image',
            'input': 'edit',
            'checkbox': 'checkbox',
            'link': 'hyperlink',
            'menu': 'menu',
            'hyperlink':'hyperlink'
        }
        print(f"VisualAnalyzer Initialized. Device: {self._device}")

    def _load_models(self)->bool:
        if self._models_loaded:
            return True
        with self._load_lock:
            if self._models_loaded:
                return True
            try:
                emit(event_type=EventType.VISUAL_ANALYSIS_STARTED, source="VisualAnalyzer", operation= "loading_models")
                print("Loading Yolo Model")
                self._yolo_model = get_yolo_model(self._icon_detect_path)
                print("Loading caption model")
                self._caption_model_processor = get_caption_model_processor(model_name = "florence2", model_name_or_path=self._icon_caption_path,device=self._device)
                self._models_loaded = True

                emit(event_type=EventType.OMNIPARSER_LOADED, source="VisualAnalyzer", device = self._device)
                
                print("Models loaded successfully")
                return True
            except Exception as e:
                print(f"[VisualAnalyzer] Model loading failed: {e}")
                emit(event_type=EventType.OMNIPARSER_ERROR, source="VisualAnalyzer", error = str(e),operation= "load_models")
                return False
            
    def analyze(self, screenshot:Screenshot, detect_element:bool = True,
                extract_text:bool = True)->VisualAnalysisResult:
        start_time = time.time()
        
        emit(event_type=EventType.VISUAL_ANALYSIS_STARTED, source="VisualAnalysis", detect_element=detect_element,extract_text=extract_text)
        
        elements:List[VisualElement] = []
        text_content: str = ""
        annotated_image: Optional[Image.Image] = None
        model_used: str = "none"
        
        image = screenshot.image
        
        if not isinstance(image,Image.Image):
            image = Image.fromarray(image)
        
        if detect_element:
            try:
                elements,text_content,annotated_image =\
                                                        self._detect_elements(image,screenshot)
                model_used = "omniparser" if elements else "none"
            except Exception as e:
                emit(EventType.ERROR, source="VisualAnalyzer", error = str(e), operation= "detect_elements")

        if extract_text and not text_content:
            try:
                text_content = self._extract_text_only(image)
                if model_used == "none":
                    model_used = 'ocr_only'
            except Exception as e:
                emit(event_type=EventType.ERROR, source="VisualAnalyzer", error=str(e), operation="extract_text")
            
        elapsed_ms = (time.time()-start_time)*1000

        result = VisualAnalysisResult(
            screenshot=screenshot,
            elements=elements,
            text_content=text_content,
            analysis_time_ms=elapsed_ms,
            model_used=model_used,
            confidence_threshold=self.config.detection_confidence_threshold,
            annotated_image=annotated_image)
            
        emit(event_type=EventType.VISUAL_ANALYSIS_COMPLETED,
                source="VisualAnalyzer",
                data = result,
                elements_found = len(elements),
                text_length = len(text_content),
                time_ms = elapsed_ms)
        return result
        
    def _detect_elements(self, image:Image.Image, screenshot:Screenshot)->Tuple[List[VisualElement],str,Optional[Image.Image]]:
        if not self._load_models():
            return [],"", None

        temp_file= tempfile.NamedTemporaryFile(suffix='.png',delete=False)
        temp_path = temp_file.name
        temp_file.close()
        if image.mode!='RGB':
            image = image.convert("RGB")
        image.save(temp_path)

        try:
            (ocr_text_list, ocr_bbox_list),_ = check_ocr_box(
                temp_path,
                display_img=False,
                output_bb_format='xyxy',
                easyocr_args={'text_threshold':0.8},
                use_paddleocr=False
            )
        except Exception as e:
            print(f"OCR Failed {e}")
            ocr_text_list = []
            ocr_bbox_list = []

        box_overlay_ratio = max(image.size)/3200
        draw_bbox_config = {
            'text_scale':0.8,
            'text_thickness': max(int(2*box_overlay_ratio),1),
            'text_padding':max(int(3*box_overlay_ratio),1),
            'thickness': max(int(3*box_overlay_ratio),1)
        }

        try:
            annotated_img, label_coords, parsed_content_list = get_som_labeled_img(
                image_source=temp_path,
                model=self._yolo_model,
                BOX_TRESHOLD=self.config.box_threshold,
                output_coord_in_ratio=True,
                ocr_bbox=ocr_bbox_list,
                draw_bbox_config=draw_bbox_config,
                caption_model_processor=self._caption_model_processor,
                ocr_text=ocr_text_list,
                use_local_semantics=self.config.use_local_semantics,
                scale_img=False,
                batch_size=128
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
        elements, text_content = self._parse_detection_results(
            parsed_content_list=parsed_content_list,
            image_size = image.size,
            screenshot=screenshot
        )
        emit(EventType.VISUAL_ANALYSIS_COMPLETED, source="VisualAnalyzer", data = (elements,text_content,annotated_img), operation = "Get Labeled Image")
        return elements,text_content,annotated_img
    
    def _parse_detection_results(self,
                                    parsed_content_list:List[Dict],
                                    image_size:Tuple[int,int],
                                    screenshot:Screenshot)->Tuple[List[VisualElement],str]:
        elements:List[VisualElement] = []
        text_parts:List[str] = []
        img_width, img_height = image_size

        offset_x = screenshot.region[0] if screenshot.region else 0
        offset_y = screenshot.region[1] if screenshot.region else 0

        for idx, item in enumerate(parsed_content_list):
            if isinstance(item,(list,tuple)):
                continue
            if not isinstance(item,dict):
                continue
            
            elem_type = item.get('type', 'unknown')
            bbox_ratio = item.get('bbox',[0,0,0,0])
            is_interactive = item.get('interactivity',False)
            content = item.get('content',"") 
            source = item.get('source', "")

            x1_pixel = int(bbox_ratio[0] * img_width)
            y1_pixel = int(bbox_ratio[1] * img_height)
            x2_pixel = int(bbox_ratio[2] * img_width)
            y2_pixel = int(bbox_ratio[3] * img_height)

            width = x2_pixel - x1_pixel
            height = y2_pixel - y1_pixel

            if width<=0 or height<=0:
                continue

            screen_x = offset_x+ x1_pixel
            screen_y = offset_y + y1_pixel

            center_x = screen_x + (width//2)
            center_y = screen_y + (height//2)

            confidence = self._estimate_confidence(source,elem_type)

            if confidence<self.config.detection_confidence_threshold:
                continue

            mapped_type = self._type_map.get(elem_type,"unknown")
            if is_interactive and mapped_type == "unknown":
                mapped_type = "button"
            
            label = str(content).strip()
            if label:
                text_parts.append(label)

            element = VisualElement(
                id=f"omni_{idx}_{int(time.time()*1000)}",
                label=label,
                element_type=mapped_type,
                bounding_box=(screen_x,screen_y,width,height),
                confidence=confidence,
                center=(center_x,center_y),
                ocr_text=label if elem_type== 'text' else None,
                attributes={
                    'raw_type': elem_type,
                    'source': source,
                    'interactivity': is_interactive,
                    'bbox_ratio': bbox_ratio,
                    'index': idx
                }
            )
            elements.append(element)

        max_elements = self.config.max_elements_per_analysis
        elements = elements[:max_elements]
        elements.sort(key=lambda e: (e.bounding_box[1], e.bounding_box[0]))

        text_content = " | ".join(text_parts)
        # To add emit function
        return elements, text_content
    
    def _estimate_confidence(self, source:str, elem_type:str)->float:
        if source == 'box_ocr_content_ocr':
            return 0.9
        elif source=='box_yolo_content_ocr':
            return 0.85
        elif source == 'box_yolo_content_yolo':
            return 0.75
        else:
            return 0.6
    
    def _extract_text_only(self, image:Image.Image)->str:
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()
        image.save(temp_path)

        try:
            (ocr_text_list, ocr_bbox_list), _ = check_ocr_box(
                temp_path,
                display_img=False,
                output_bb_format='xyxy',
                easyocr_args={'text_threshold':0.5},
                use_paddleocr=False
            )
            text_content = " ".join(ocr_text_list) if ocr_text_list else ""
            emit(event_type=EventType.OCR_COMPLETED, source="VisualAnalyzer", text_length = len(text_content))
            return text_content
        except Exception as e:
            emit(EventType.ERROR,source="VisualAnalyzer",error=str(e),operation = 'extract_text_only')
            return ""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
    def find_element(self,screenshot:Screenshot, query: str, element_type:Optional[str]= None)->Optional[VisualElement]:
        result = self.analyze(screenshot)
        query_lower = query.lower()
        for element in result.elements:
            if element_type and element.element_type!= element_type:
                continue

            if query_lower in element.label.lower():
                emit(EventType.VISUAL_ELEMENT_FOUND, source="VisualAnalyzer",query = query,element_type=element.element_type)
                return element
            
            if element.ocr_text and query_lower in element.ocr_text.lower():
                emit(EventType.VISUAL_ELEMENT_FOUND, source="VisualAnalyzer",query=query,found_via="ocr")
                return element

        emit(EventType.VISUAL_ELEMENT_NOT_FOUND,source="VisualAnalyzer",query=query)
        return None

    def find_all_elements(self,screenshot:Screenshot,query:Optional[str] = None, element_type:Optional[str] = None)-> List[VisualElement]:
        result = self.analyze(screenshot)
        matches = []
        query_lower = query.lower() if query else None
        
        for element in result.elements:
            if element_type and element.element_type != element_type:
                continue
            
            if query_lower:
                if query_lower not in element.label.lower():
                    if not (element.ocr_text and query_lower in element.ocr_text.lower()):
                        continue
            
            matches.append(element)
        return matches
    
    def find_element_at_point(self, screenshot:Screenshot, x:int, y:int)->Optional[VisualElement]:
        result = self.analyze(screenshot)

        candidates = []
        for element in result.elements:
            ex,ey,ew,eh = element.bounding_box
            if ex<=x and x<=ex+ew and ey<=y and y<=ey + eh:
                area = ew*eh
                candidates.append((area,element))
        
        if candidates:
            candidates.sort(key=lambda c:c[0])
            return candidates[0][1]
        return None
    
    def find_clickable_elements(self, screenshot:Screenshot)->List[VisualElement]:
        result = self.analyze(screenshot)
        clickable = []
        for element in result.elements:
            if element.attributes.get('interactivity', False):
                clickable.append(element)
            elif element.element_type in ('button','icon', 'hyperlink'):
                clickable.append(element)
        return clickable
    
    def is_loaded(self)->bool:
        return self._models_loaded
    
    def preload(self)->bool:
        return self._load_models()
    
    def unload(self)->None:
        if self._yolo_model is not None:
            del self._yolo_model
            self._yolo_model = None
        
        if self._caption_model_processor is not None:
            del self._caption_model_processor
            self._caption_model_processor = None
        
        self._models_loaded = False

        import gc
        gc.collect()
        
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
        emit(EventType.OMNIPARSER_UNLOADED, source="VisualAnalyzer")

_analyzer_instance: Optional["VisualAnalyzer"] = None


def get_visual_analyzer()->VisualAnalyzer:
    global _analyzer_instance 
    if _analyzer_instance is None:
        _analyzer_instance = VisualAnalyzer()
    return _analyzer_instance
    

if __name__ == '__main__':
    from .screen import ScreenCapture
    screen = ScreenCapture()
    analyzer = get_visual_analyzer()
    print("Full screen analysis")
    screenshot = screen.capture_full_screen(monitor_index=0)
    print(f"captured: {screenshot.image.size}")

    print("analyzing (first run loads models)")
    result = analyzer.analyze(screenshot)
    
    print(f"Element found: {len(result.elements)}")
    print(f"Text length: {len(result.text_content)} chars")
    print(f"Time: {result.analysis_time_ms:.0f}ms")
    print(f"Model: {result.model_used}")

    for i, elem in enumerate(result.elements[:10]):
        print(f"  [{i}] {elem.element_type:8} | {elem.label[:35]:35} | bbox={elem.bounding_box}")

    
    if result.annotated_image:
        result.annotated_image.save("test_annotated.png")
        print("Saved image test_annotated.png")

    queries = ['Start', "PROBLEMS", 'SEARCH']
    for query in queries:
        elem = analyzer.find_element(screenshot, query)
        if elem:
            print(f"{elem.element_type} at {elem.center}")
        else:
            print("Not found")
        
    clickables = analyzer.find_clickable_elements(screenshot)
    print(f"Found {len(clickables)} ")
    for elem in clickables[:5]:
        print(f"{elem.label[:40]} at {elem.center}")

    analyzer.unload()
    