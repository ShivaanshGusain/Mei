from typing import Optional,Dict,Any,List,Tuple
from enum import Enum, auto
import re
import logging

import win32clipboard
import win32con

from ..core.config import EntityType, ExtractionSource, ExtractedValue,FocusContext, Entity, TeachingResult
from ..core.events import emit,EventType
from ..perception.System.applibrary import get_app_library
from ..memory.store import get_memory_store, MemoryStore
from ..memory.working import get_working_memory, WorkingMemory

URL_PATTERN = re.compile(    
    r'^https?://[^\s]+$|^www\.[^\s]+$',    
    re.IGNORECASE
)

PATH_PATTERN = re.compile(
    r'^[A-Za-z]:\\|^\\\\|^/[^\s]',
    re.IGNORECASE
)

IP_PATTERN = re.compile(
        r'^(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?$' 
    )

EMAIL_PATTERN = re.compile(
        r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    )

STRIP_WORDS = frozenset({'my', 'the', 'this', 'that', 'a', 'an'})


APP_TYPE_HINTS = {
    'brave.exe': EntityType.URL,
    'firefox.exe': EntityType.URL,
    'msedge.exe': EntityType.URL,
    'explorer.exe': EntityType.PATH,
    'mstsc.exe': EntityType.IP_ADDRESS,
    'code.exe': EntityType.PATH,
}


class ValueExtractor:

    def __init__(self):
        self._working_memory: Optional[WorkingMemory] = None
        self._app_library = get_app_library()
        self._log = logging.getLogger('ValueExtractor')

    def extract(self, hint_type: Optional[str] = None)-> ExtractedValue:
        clipboard_result = self._extract_from_clipboard()
        if clipboard_result.success:
            if hint_type is not None:
                if self._matches_hint(clipboard_result, hint_type):
                    return clipboard_result
                clipboard_result.confidence = clipboard_result.confidence*0.7
            return clipboard_result
        
        context_result = self._extract_from_context(hint_type)
        if context_result.success:
            return context_result
        
        return ExtractedValue(
            success=False,
            source= ExtractionSource.USER_PROVIDED
        )
    
    def _extract_from_clipboard(self)->ExtractedValue:
        try:
            win32clipboard.OpenClipboard()
        except:
            return ExtractedValue(success=False)
        
        formats_to_try = [
            win32con.CF_UNICODETEXT,
            win32con.CF_TEXT
        ]
        text = None
        for format in formats_to_try:
            try:
                if win32clipboard.IsClipboardFormatAvailable(format):
                    data = win32clipboard.GetClipboardData(format)
                    if format == win32con.CF_TEXT:
                        text = data.decode('utf-8',errors='ignore')
                    else:
                        text = data
                    break
            except:
                continue

        win32clipboard.CloseClipboard()

        if text is None or text.strip() == "":
            return ExtractedValue(success=False)
        
        text.strip()

        entity_type = self._infer_type_from_content(text)
        confidence = self._calculate_confidence(text,entity_type)

        return ExtractedValue(
            success=True,
            value = text,
            entity_type=entity_type,
            source = ExtractionSource.CLIPBOARD,
            confidence=confidence
        )
    
    def _extract_from_context(self,hint_type:Optional[str])-> ExtractedValue:
        
        wm = get_working_memory()
        focus = wm.get_focus_context()
        if focus is None:
            return ExtractedValue(success=False)
        
        app = focus.current_app

        category = self._app_library.guess_category(app)
        if category == "browser":
            url = self._extract_url_from_browser(focus)
            if url:
                return ExtractedValue(
                    success=True, value=url, entity_type=EntityType.URL,
                    source=ExtractionSource.CONTEXT, confidence=0.8, source_app=app
                )

        if category == "editor" or app.lower() == "explorer.exe":
            path = focus.document_path 
            
            if path:
                return ExtractedValue(
                    success=True, value=path, entity_type=EntityType.PATH,
                    source=ExtractionSource.CONTEXT, confidence=0.9, source_app=app
                )

        return ExtractedValue(success=False)
    

    # TO FIX
    def _extract_url_from_browser(self, focus:FocusContext)-> Optional[str]:

        title = focus.current_window_title
        if title is None:
            return None
        
        url_match = URL_PATTERN.search(title)
        if url_match:
            return url_match.group(0)
        
        return None
    
    def _infer_type_from_content(self,text:str)->EntityType:
        if URL_PATTERN.match(text):
            return EntityType.URL
        
        if PATH_PATTERN.match(text):
            return EntityType.PATH
        
        if IP_PATTERN.match(text):
            return EntityType.IP_ADDRESS
        
        if EMAIL_PATTERN.match(text):
            return EntityType.EMAIL

        if text.endswith('.exe') or self._app_library.get_path(text.lower()):
            return EntityType.APPLICATION
            
        return EntityType.TEXT
    
    def _calculate_confidence(self,text:str,entity_type: EntityType)->float:

        base_confidence = 0.8

        if entity_type !=EntityType.TEXT:
            base_confidence = 0.9

        if len(text) > 500:
            base_confidence*=0.7
        
        if len(text) < 3:
            base_confidence*=0.6

        return min(base_confidence,1.0)
    
    def _matches_hint(self,result:ExtractedValue, hint:str)-> bool:
        hint_lower = hint.lower()
        hint_to_type = {
            'link': EntityType.URL,
            'url': EntityType.URL,
            'website': EntityType.URL,
            'site': EntityType.URL,
            'folder': EntityType.PATH,
            'directory': EntityType.PATH,
            'path': EntityType.PATH,
            'file': EntityType.PATH,
            'address': EntityType.IP_ADDRESS,
            'ip': EntityType.IP_ADDRESS,
            'server': EntityType.IP_ADDRESS,  
            'email': EntityType.EMAIL,
            'app': EntityType.APPLICATION,
            'application': EntityType.APPLICATION,
        }

        expected = hint_to_type.get(hint_lower)

        if expected is None:
            return True
        
        if hint_lower == 'server':
            return result.entity_type in [EntityType.URL, EntityType.IP_ADDRESS]
        
        return result.entity_type == expected
    

class EntityTeacher:

    def __init__(self):
        self._extractor = ValueExtractor()
        self._store = None
        self._log = logging.getLogger('EntityTeacher')

    def process_teaching_request(
            self,
            entity_name:str,
            hint_type: Optional[str] = None,
            source_app: Optional[str] = None,
            context_app: Optional[str] = None
    )-> TeachingResult:
        
        canonical = self._find_entity(canonical)
        self._log.info(f"Teaching entity: '{entity_name}' (canonical: '{canonical}')")

        existing = self._find_entity(canonical)

        if existing is not None:
            return TeachingResult(
                success=False,
                needs_confirmation=True,
                confirmation_prompt=f"I already know '{entity_name}' as '{existing.value}'. "
                                      f"Do you want to update it?",
                entity=existing,
                message = 'entity_exists'        
            )   
        
        extracted = self._extractor.extract(hint_type)

        if not extracted.success:
            return TeachingResult(
                success=False,
                needs_confirmation=False,
                message="no_value_found",
                confirmation_prompt="What value should I remember? "
                "You can copy it to clipboard or tell me."
            )

        entity = Entity(
            name=entity_name,
            canonical_name=canonical,
            entity_type=extracted.entity_type,
            value=extracted.value,
            source=extracted.source,
            source_app=source_app,
            context_app=context_app,
            metadata = {
                'extraction_confidence':extracted.confidence,
                'original_metadata': extracted.metadata
            }
        )

        if extracted.confidence >=0.9 and extracted.source == ExtractionSource.CLIPBOARD:
            needs_confirmation = True
            prompt = self._build_confirmation_prompt(entity)
        
        else:
            needs_confirmation = True
            prompt = self._build_confirmation_prompt(entity, emphasize_check=True)

        return TeachingResult(
               success=False,  
               entity=entity,
               needs_confirmation=True,
               confirmation_prompt=prompt,
               extracted_value=extracted,
               message="awaiting_confirmation"
           )

    def confirm_and_save(self, entity:Entity) -> TeachingResult:
        if entity.value is None or entity.value.strip() == "":
            return TeachingResult(
                success=False,
                message="invalid_entity_value"
            )
        
        store = get_memory_store()
        entity_id = store.save_entity(entity)
        entity.id = entity_id

        emit(
            EventType.Entity
        )