"""
Configuration management for Mei Agent.
Single source of truth for all settings.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
from enum import Enum
from PIL import Image
from .task import Intent, Plan
ROOT_DIR = Path(__file__).parent.parent.parent


@dataclass
class AudioConfig:
    """Audio/Speech settings"""
    model_path: str = r'models/whisper-model'
    device: str = "cuda"
    sample_rate: int = 16000
    energy_threshold: int = 0.02
    wake_word: str = "mei"
    #listen_timeout: int = 1 
    phrase_timeout: int = 10
    silence_duration: float = 1
    chunk: int = 1024
    channels: int = 1
    compute_type: str = "int8"
    language: str = 'en'
    beam_size: int = 5

@dataclass
class KnownApps:
    app_dir_file:str = 'known_apps.csv'

@dataclass                                                    
class ProcessInfo:                                            
    pid: int                  
    name: str                 
    path: Optional[str]       
    # exe: str
    status: str               
    memory_info: float
    memory_mb: float        
    cpu_percent: float       
    create_time: Optional[datetime] 

@dataclass
class WindowInfo:
    """Window Information from the OS"""
    hwnd: int
    title: str
    process_name: str
    pid: int
    x: int
    y: int
    width: int
    height: int
    is_visible: bool
    is_minimized: bool
    is_maximized: bool

@dataclass
class TabInfo:
    """Tab/child information ( for browsers, etc)"""
    id: str
    title: str
    url: Optional[str]
    is_active: bool
    parent_hwnd: int
    metadata: Dict[str, Any]

@dataclass
class ExtendedWindowInfo:
    """Window info + deep app data when available"""
    window: WindowInfo
    tabs: List[TabInfo]
    has_deep_access: bool
    app_type: str
    current_state: Dict[str, Any]
    
@dataclass 
class UIElement:
    name: str
    control_type:str
    automation_id: str
    class_name: str
    value: Optional[str]
    is_enabled: bool
    is_focused: bool
    is_visible: bool

    bounding_box: Tuple[int, int, int, int]
    hwnd: int
    depth: int
    _control: Any = None

class ControlType(Enum):
    BUTTON = "Button"
    EDIT = "Edit"
    TEXT = "Text"
    CHECKBOX = 'CheckBox'
    RADIOBUTTON = "RadioButton"
    COMBOBOX = "ComboBox"
    LIST = "List"
    MENU = "Menu"              
    MENUITEM = "MenuItem"      
    TAB = "Tab"                
    TABITEM = "TabItem"        
    TREE = "Tree"              
    TREEITEM = "TreeItem"      
    TOOLBAR = "ToolBar"        
    STATUSBAR = "StatusBar"    
    PANE = "Pane"              
    WINDOW = "Window"          
    DOCUMENT = "Document"      
    HYPERLINK = "Hyperlink"    
    IMAGE = "Image"            
    SLIDER = "Slider"          
    SPINNER = "Spinner"        
    PROGRESSBAR = "ProgressBar"
    GROUP = "Group" 

@dataclass  
class VisualConfig:
    caption_model_name: str = "florence2"
    box_threshold: float = 0.01
    iou_threshold: float = 0.7
    use_local_semantics:bool = True
    detection_confidence_threshold:float = 0.05
    max_elements_per_analysis:int = 100
    enable_gpu: bool = True

    ocr_language:str = 'en'
    screenshot_cache_dir: str = 'data/screenshots'
    max_cache_size_mb: int = 100
    
    ocr_confidence_threshold:float = 0.6
    
    region_around_cursor:List[int] = field(default_factory=lambda:[300,300])

@dataclass
class MonitorInfo:
    index: int
    x:int
    y:int
    width:int
    height:int
    is_primary:bool
    scale_factor: float = 1.0

@dataclass
class Screenshot:
    image:Any
    timestamp: datetime
    region: Tuple[int,int,int,int]
    source: str
    source_hwnd:Optional[int] = None
    monitor_index: Optional[int] = None

@dataclass
class VisualElement:
    id:str
    label:str
    element_type:str
    bounding_box:Tuple[int,int,int,int]
    confidence:float
    center: Tuple[int,int]
    ocr_text: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ScreenDiff:
    changed_regions: List[Tuple[int,int,int,int]]
    similarity_score: float
    has_significant_change: bool

@dataclass
class VisualAnalysisResult:
    screenshot: Screenshot
    elements: List[VisualElement]
    text_content: str
    analysis_time_ms: float
    model_used:str
    confidence_threshold: float
    annotated_image: Optional[Image.Image] = None

@dataclass
class LLMConfig:
    """Language Model settings"""
    model_path: str = str(Path(__file__).parent.parent.parent /"models"/"qwen2.5-3b-instruct-q4_k_m.gguf")
    context_length = 4096
    max_tokens: int = 512
    temperature: float = 0.1
    threads: int = 4
    gpu_layers: int = -1

@dataclass
class ActionResult:
    success:bool
    data: Dict[str,Any] 
    error:Optional[str]
    method_used: str   

@dataclass
class VerifyResult:
    verified: bool
    confidence:float
    reason: Optional[str]

@dataclass
class GoalVerifyResult:
    achieved: bool
    confidence:float
    reason: Optional[str]
    evidence: Dict[str, Any]


@dataclass
class ElementReference:
     source: str
     bounding_box: Tuple[int,int,int,int]
     ui_element: Optional[Any]
     found_at: datetime = field(default_factory=datetime.now)


@dataclass
class PendingConfirmation:
    plan: Plan
    intent: Intent
    goal_result: GoalVerifyResult
    started_at: datetime
    time_seconds: float


@dataclass
class SystemConfig:
    """System integration settings"""
    multi_monitor: bool = True
    virtual_desktops: bool = True
    prefer_accessibility_api: bool = True  # Prefer API over mouse clicks


@dataclass
class MemoryConfig:
    """Memory settings"""
    database_path: str = "data/memory.db"
    max_episodic_entries: int = 10000
    similarity_threshold: float = 0.7


@dataclass
class SafetyConfig:
    """Safety settings"""
    confirm_destructive: bool = True  # Confirm before delete, send, etc.
    blocked_apps: List[str] = field(default_factory=lambda: ["regedit.exe", "cmd.exe"])
    max_actions_per_minute: int = 60

@dataclass
class VerificationConfig:
    goal_confidence_threshold: float = 0.6
    step_confidence_threshold: float = 0.5
    element_staleness_seconds: float = 5.0
    confirmation_timeout_seconds: float = 5.0

@dataclass
class Config:
    """Main configuration"""
    audio: AudioConfig = field(default_factory=AudioConfig)
    knownapps: KnownApps = field(default_factory= KnownApps)
    llm: LLMConfig = field(default_factory=LLMConfig)
    system: SystemConfig = field(default_factory=SystemConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    debug: bool = False
    log_level: str = "INFO"
    visual: VisualConfig = field(default_factory=VisualConfig)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    root_dir: Path= ROOT_DIR

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        """Load configuration from YAML file."""
        config = cls()
        
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = yaml.safe_load(f) or {}
            
            # Update audio config
            if 'audio' in data:
                for key, value in data['audio'].items():
                    if hasattr(config.audio, key):
                        setattr(config.audio, key, value)
            # Updating known apps config
            if 'knownapps' in data:
                for key, value in data['knownapps'].items():
                    if hasattr(config.knownapps, key):
                        setattr(config.knownapps, key, value)
                    
            # Update llm config
            if 'llm' in data:
                for key, value in data['llm'].items():
                    if hasattr(config.llm, key):
                        setattr(config.llm, key, value)
            
            # Update system config
            if 'system' in data:
                for key, value in data['system'].items():
                    if hasattr(config.system, key):
                        setattr(config.system, key, value)
            
            # Update memory config
            if 'memory' in data:
                for key, value in data['memory'].items():
                    if hasattr(config.memory, key):
                        setattr(config.memory, key, value)
            
            # Update safety config
            if 'safety' in data:
                for key, value in data['safety'].items():
                    if hasattr(config.safety, key):
                        setattr(config.safety, key, value)
            
            config.debug = data.get('debug', False)
            config.log_level = data.get('log_level', 'INFO')
        
        return config
    
    def save(self, path: str = "config.yaml"):
        """Save configuration to YAML file."""
        data = {
            'audio': {
                'model_path': self.audio.model_path,
                'device': self.audio.device,
                'sample_rate': self.audio.sample_rate,
                'energy_threshold': self.audio.energy_threshold,
                'wake_word': self.audio.wake_word,
                'chunk': self.audio.chunk,
                'channels': self.audio.channels,
                'compute_type': self.audio.compute_type,
                'language': self.audio.language
            }, 
            'knownapps': {
                'app_dir_file': self.knownapps.app_dir_file
            },
            'llm': {
                'model_path': self.llm.model_path,
                'context_length': self.llm.context_length,
                'max_tokens': self.llm.max_tokens,
                'temperature': self.llm.temperature,
                'threads': self.llm.threads,
                'gpu_layers': self.llm.gpu_layers,
            },
            'system': {
                'multi_monitor': self.system.multi_monitor,
                'virtual_desktops': self.system.virtual_desktops,
                'prefer_accessibility_api': self.system.prefer_accessibility_api,
            },
            'memory': {
                'database_path': self.memory.database_path,
                'max_episodic_entries': self.memory.max_episodic_entries,
            },
            'safety': {
                'confirm_destructive': self.safety.confirm_destructive,
                'blocked_apps': self.safety.blocked_apps,
            },
            'debug': self.debug,
            'log_level': self.log_level,
        }
        
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.load()
    return _config


def init_config(path: str = "config.yaml") -> Config:
    """Initialize configuration from file."""
    global _config
    _config = Config.load(path)
    return _config
