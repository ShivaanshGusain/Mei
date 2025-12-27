from ...core.config import get_config, Screenshot, VisualElement, VisualAnalysisResult
from ...core.events import emit, EventType
from typing import List, Optional, Tuple, Dict, Any, Union
from PIL import Image
import numpy as np
import threading
import time
import base64
import io
import os


class VisualAnalyzer:
    def __init__(self):
        self.config = get_config().visual
        self._omniparser = None
        self._omniparser_loaded = False
        
        self._yolo_model = None
        self._caption_model_processor = None
        self._direct_models_loaded = False
        
        self._load_lock = threading.Lock()
        
        self._type_map = {
            'icon': 'icon',
            'text': 'text',
            'button': 'button',
            'image': 'image',
            'input': 'edit',
            'checkbox': 'checkbox',
            'link': 'hyperlink',
            'menu': 'menu',
        }
        
        self._interactivity_map = {
            'box_ocr_content_ocr': False,      # Pure text
            'box_yolo_content_ocr': True,       # Icon with OCR label
            'box_yolo_content_yolo': True,      # Icon with caption
        }
        
        base_path = self.config.omniparser_model_path
        self._icon_detect_path = os.path.join(base_path, 'icon_detect', 'model.pt')
        self._icon_caption_path = os.path.join(base_path, 'icon_caption')
        
        self._omniparser_config = {
            'som_model_path': self._icon_detect_path,
            'caption_model_name': getattr(self.config, 'caption_model_name', 'florence2'),
            'caption_model_path': self._icon_caption_path,
            'BOX_TRESHOLD': getattr(self.config, 'box_threshold', 0.01),
        }
    
    
    def _load_omniparser(self) -> bool:
        if self._omniparser_loaded:
            return True
        
        with self._load_lock:
            if self._omniparser_loaded:
                return True
            
            try:
                emit(EventType.VISUAL_ANALYSIS_STARTED,
                     source="VisualAnalyzer",
                     operation="loading_omniparser")
                
                from .OmniParser.util.omniparser import Omniparser
                
                self._omniparser = Omniparser(self._omniparser_config)
                self._omniparser_loaded = True
                
                emit(EventType.OMNIPARSER_LOADED,
                     source="VisualAnalyzer",
                     method="omniparser_class")
                
                return True
                
            except ImportError as e:
                emit(EventType.ERROR,
                     source="VisualAnalyzer",
                     error=f"OmniParser import failed: {e}",
                     operation="load_omniparser")
                return False
                
            except Exception as e:
                emit(EventType.ERROR,
                     source="VisualAnalyzer",
                     error=f"OmniParser load failed: {e}",
                     operation="load_omniparser")
                return False
    
    def _load_models_direct(self) -> bool:
        if self._direct_models_loaded:
            return True
        
        with self._load_lock:
            if self._direct_models_loaded:
                return True
            
            try:
                emit(EventType.VISUAL_ANALYSIS_STARTED,
                     source="VisualAnalyzer",
                     operation="loading_models_direct")
                
                from .OmniParser.util.utils import (
                    get_yolo_model,
                    get_caption_model_processor
                )
                
                self._yolo_model = get_yolo_model(self._icon_detect_path)
                
                device = 'cuda' if getattr(self.config, 'enable_gpu', True) else 'cpu'
                try:
                    import torch
                    if not torch.cuda.is_available():
                        device = 'cpu'
                except ImportError:
                    device = 'cpu'
                
                self._caption_model_processor = get_caption_model_processor(
                    model_name=self._omniparser_config['caption_model_name'],
                    model_name_or_path=self._icon_caption_path,
                    device=device
                )
                
                self._direct_models_loaded = True
                
                emit(EventType.OMNIPARSER_LOADED,
                     source="VisualAnalyzer",
                     method="direct")
                
                return True
                
            except Exception as e:
                emit(EventType.ERROR,
                     source="VisualAnalyzer",
                     error=str(e),
                     operation="load_models_direct")
                return False
    
    def _image_to_base64(self, image: Image.Image) -> str:
        buffer = io.BytesIO()
        # Ensure RGB mode
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(buffer, format='PNG')
        buffer.seek(0)
        img_bytes = buffer.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')
    
    def _pil_to_base64_data_uri(self, image: Image.Image) -> str:
        base64_str = self._image_to_base64(image)
        return f"data:image/png;base64,{base64_str}"

    
    def analyze(self, screenshot: Screenshot, 
                detect_elements: bool = True,
                extract_text: bool = True,
                use_direct_method: bool = False) -> VisualAnalysisResult:

        start_time = time.time()
        
        emit(EventType.VISUAL_ANALYSIS_STARTED,
             source="VisualAnalyzer",
             detect_elements=detect_elements,
             extract_text=extract_text)
        
        image = screenshot.image
        if not isinstance(image, Image.Image):
            image = Image.fromarray(image)
        
        elements: List[VisualElement] = []
        text_content = ""
        model_used = "none"
        annotated_image = None
        
        try:
            if detect_elements:
                if use_direct_method:
                    elements, text_content, annotated_image = self._detect_elements_direct(
                        image, screenshot
                    )
                    model_used = "omniparser_direct" if elements else "none"
                else:
                    elements, text_content, annotated_image = self._detect_elements(
                        image, screenshot
                    )
                    model_used = "omniparser" if elements else "none"
            
            if extract_text and not text_content:
                text_content = self._extract_text_ocr(image)
                if model_used == "none":
                    model_used = "ocr_only"
                    
        except Exception as e:
            emit(EventType.ERROR,
                 source="VisualAnalyzer",
                 error=str(e),
                 operation="analyze")
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        result = VisualAnalysisResult(
            screenshot=screenshot,
            elements=elements,
            text_content=text_content,
            analysis_time_ms=elapsed_ms,
            model_used=model_used,
            confidence_threshold=getattr(self.config, 'detection_confidence_threshold', 0.5),
            annotated_image=annotated_image
        )
        
        emit(EventType.VISUAL_ANALYSIS_COMPLETED,
             source="VisualAnalyzer",
             elements_found=len(elements),
             text_length=len(text_content),
             time_ms=elapsed_ms)
        
        return result
    
    def _detect_elements(self, image: Image.Image, screenshot: Screenshot
                        ) -> Tuple[List[VisualElement], str, Optional[Image.Image]]:
        
        if not self._load_omniparser():
            return [], "", None
        
        try:
            image_base64 = self._image_to_base64(image)
            
            annotated_img, parsed_content_list = self._omniparser.parse(image_base64)
            
            elements, text_content = self._parse_omniparser_output(
                parsed_content_list, image.size, screenshot
            )
            
            return elements, text_content, annotated_img
            
        except Exception as e:
            emit(EventType.ERROR,
                 source="VisualAnalyzer",
                 error=str(e),
                 operation="detect_elements")
            return [], "", None
    
    def _detect_elements_direct(self, image: Image.Image, screenshot: Screenshot
                                ) -> Tuple[List[VisualElement], str, Optional[Image.Image]]:
        if not self._load_models_direct():
            return [], "", None
        
        import tempfile
        temp_path = None
        
        try:

            from .OmniParser.util.utils import get_som_labeled_img, check_ocr_box
            
            img_width, img_height = image.size
            
            box_overlay_ratio = max(image.size) / 3200
            draw_bbox_config = {
                'text_scale': 0.8 * box_overlay_ratio,
                'text_thickness': max(int(2 * box_overlay_ratio), 1),
                'text_padding': max(int(3 * box_overlay_ratio), 1),
                'thickness': max(int(3 * box_overlay_ratio), 1),
            }
            
            (ocr_text, ocr_bbox), _ = check_ocr_box(
                image,
                display_img=False,
                output_bb_format='xyxy',
                easyocr_args={'text_threshold': 0.8},
                use_paddleocr=False
            )
            
            annotated_img, label_coordinates, parsed_content_list = get_som_labeled_img(
                image,
                self._yolo_model,
                BOX_TRESHOLD=getattr(self.config, 'box_threshold', 0.01),
                output_coord_in_ratio=True,
                ocr_bbox=ocr_bbox,
                draw_bbox_config=draw_bbox_config,
                caption_model_processor=self._caption_model_processor,
                ocr_text=ocr_text,
                use_local_semantics=getattr(self.config, 'use_local_semantics', True),
                iou_threshold=getattr(self.config, 'iou_threshold', 0.7),
                scale_img=False,
                batch_size=128
            )

            elements, text_content = self._parse_omniparser_output(
                parsed_content_list, image.size, screenshot
            )
            
            return elements, text_content, annotated_img
            
        except Exception as e:
            emit(EventType.ERROR,
                 source="VisualAnalyzer",
                 error=str(e),
                 operation="detect_elements_direct")
            return [], "", None
        
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
    
    def _parse_omniparser_output(self, parsed_content_list: List[Dict],
                                  image_size: Tuple[int, int],
                                  screenshot: Screenshot
                                  ) -> Tuple[List[VisualElement], str]:
        elements = []
        text_parts = []
        
        img_width, img_height = image_size
        
        screenshot_x = screenshot.region[0] if screenshot.region else 0
        screenshot_y = screenshot.region[1] if screenshot.region else 0
        
        confidence_threshold = getattr(self.config, 'detection_confidence_threshold', 0.3)
        
        for i, item in enumerate(parsed_content_list):
            try:
                element_type_raw = item.get('type', 'unknown')
                bbox_ratio = item.get('bbox', [0, 0, 0, 0])
                is_interactable = item.get('interactivity', False)
                content = item.get('content', '')
                source = item.get('source', '')
                
                x1 = int(bbox_ratio[0] * img_width)
                y1 = int(bbox_ratio[1] * img_height)
                x2 = int(bbox_ratio[2] * img_width)
                y2 = int(bbox_ratio[3] * img_height)
                
                w = x2 - x1
                h = y2 - y1
                
                if w <= 0 or h <= 0:
                    continue
                
                abs_x = screenshot_x + x1
                abs_y = screenshot_y + y1
                
                element_type = self._type_map.get(element_type_raw, 'unknown')
                
                if is_interactable and element_type == 'unknown':
                    element_type = 'button'
                
                label = str(content).strip() if content else ""
                
                if label:
                    text_parts.append(label)
                
                confidence = self._estimate_confidence(source, element_type_raw)
                
                if confidence < confidence_threshold:
                    continue
                
                element = VisualElement(
                    id=f"omni_{i}_{int(time.time() * 1000)}",
                    label=label,
                    element_type=element_type,
                    bounding_box=(abs_x, abs_y, w, h),
                    confidence=confidence,
                    center=(abs_x + w // 2, abs_y + h // 2),
                    ocr_text=label if element_type_raw == 'text' else None,
                    attributes={
                        'raw_type': element_type_raw,
                        'source': source,
                        'interactivity': is_interactable,
                        'bbox_ratio': bbox_ratio,
                        'index': i
                    }
                )
                elements.append(element)
                
            except Exception as e:
                continue
        
        max_elements = getattr(self.config, 'max_elements_per_analysis', 100)
        elements = elements[:max_elements]
        
        elements.sort(key=lambda e: (e.bounding_box[1], e.bounding_box[0]))
        
        text_content = " | ".join(text_parts)
        
        return elements, text_content
    
    def _estimate_confidence(self, source: str, element_type: str) -> float:
        
        if source == 'box_ocr_content_ocr':
            return 0.9
        
        if source == 'box_yolo_content_ocr':
            return 0.85
        
        if source == 'box_yolo_content_yolo':
            return 0.75
        
        return 0.7
    
    
    def _extract_text_ocr(self, image: Image.Image) -> str:
        
        try:
            from .OmniParser.util.utils import check_ocr_box
            
            (ocr_text, ocr_bbox), _ = check_ocr_box(
                image,
                display_img=False,
                output_bb_format='xyxy',
                easyocr_args={'text_threshold': 0.5},
                use_paddleocr=False
            )
            
            text_content = " ".join(ocr_text) if ocr_text else ""
            
            emit(EventType.VISUAL_TEXT_EXTRACTED,
                 source="VisualAnalyzer",
                 text_length=len(text_content))
            
            return text_content
            
        except Exception as e:
            emit(EventType.ERROR,
                 source="VisualAnalyzer",
                 error=str(e),
                 operation="extract_text_ocr")
            return ""
    
    
    def find_element(self, screenshot: Screenshot, query: str,
                     element_type: Optional[str] = None) -> Optional[VisualElement]:
        
        result = self.analyze(screenshot)
        query_lower = query.lower()
        
        for element in result.elements:
            if element_type and element.element_type != element_type:
                continue
            
            if query_lower in element.label.lower():
                emit(EventType.VISUAL_ELEMENT_FOUND,
                     source="VisualAnalyzer",
                     query=query,
                     element_type=element.element_type)
                return element
            
            if element.ocr_text and query_lower in element.ocr_text.lower():
                emit(EventType.VISUAL_ELEMENT_FOUND,
                     source="VisualAnalyzer",
                     query=query,
                     found_via="ocr")
                return element
        
        emit(EventType.VISUAL_ELEMENT_NOT_FOUND,
             source="VisualAnalyzer",
             query=query)
        return None
    
    def find_all_elements(self, screenshot: Screenshot,
                          query: Optional[str] = None,
                          element_type: Optional[str] = None) -> List[VisualElement]:
        
        result = self.analyze(screenshot)
        matches = []
        query_lower = query.lower() if query else None
        
        for element in result.elements:
            if element_type and element.element_type != element_type:
                continue
            
            if query_lower:
                label_match = query_lower in element.label.lower()
                ocr_match = element.ocr_text and query_lower in element.ocr_text.lower()
                if not (label_match or ocr_match):
                    continue
            
            matches.append(element)
        
        return matches
    
    def find_element_at_point(self, screenshot: Screenshot,
                               x: int, y: int) -> Optional[VisualElement]:
        
        result = self.analyze(screenshot)
        
        candidates = []
        for element in result.elements:
            ex, ey, ew, eh = element.bounding_box
            if ex <= x <= ex + ew and ey <= y <= ey + eh:
                area = ew * eh
                candidates.append((area, element))
        
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        
        return None
    
    def find_text(self, screenshot: Screenshot, 
                  text: str) -> List[Tuple[int, int, int, int]]:
        
        result = self.analyze(screenshot, detect_elements=True)
        matches = []
        text_lower = text.lower()
        
        for element in result.elements:
            if element.ocr_text and text_lower in element.ocr_text.lower():
                matches.append(element.bounding_box)
            elif text_lower in element.label.lower():
                matches.append(element.bounding_box)
        
        return matches
    
    def find_clickable_elements(self, screenshot: Screenshot) -> List[VisualElement]:
        
        result = self.analyze(screenshot)
        
        clickable = []
        for element in result.elements:
            if element.attributes.get('interactivity', False):
                clickable.append(element)
            elif element.element_type in ('button', 'icon', 'hyperlink', 'checkbox'):
                clickable.append(element)
        
        return clickable
    
    
    def unload(self) -> None:
        
        if self._omniparser is not None:
            del self._omniparser
            self._omniparser = None
            self._omniparser_loaded = False
        
        if self._yolo_model is not None:
            del self._yolo_model
            self._yolo_model = None
        
        if self._caption_model_processor is not None:
            del self._caption_model_processor
            self._caption_model_processor = None
        
        self._direct_models_loaded = False
        
        import gc
        gc.collect()
        
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        
        emit(EventType.OMNIPARSER_UNLOADED, source="VisualAnalyzer")
    
    def is_loaded(self) -> bool:
        return self._omniparser_loaded or self._direct_models_loaded
    
    def preload(self, use_direct: bool = False) -> bool:
        
        if use_direct:
            return self._load_models_direct()
        return self._load_omniparser()

_analyzer_instance: Optional[VisualAnalyzer] = None

def get_visual_analyzer() -> VisualAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = VisualAnalyzer()
    return _analyzer_instance