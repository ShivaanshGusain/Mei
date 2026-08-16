import sqlite3
import re
from typing import List, Dict, Any
SCHEMA_VERSION = 2

MAX_TASK_HISTORY     = 10000
MAX_ELEMENT_CACHE    = 5000
MAX_COMMAND_PATTERNS = 2000
MAX_COMMAND_INSTANCES= 10000
MAX_GRAPH_EDGES      = 5000
MAX_COMPOSITIONS     = 1000
MAX_RECORDED_STATES  = 50000
MAX_APP_TRANSITIONS  = 5000
MAX_CONVERSATION     = 10000


SCHEMA_SQL = """

Create table if not Exists schema_info (
key TEXT PRIMARY KEY,
value TEXT NOT NULL 
);


CREATE TABLE IF NOT EXISTS app_library(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
display_name                        TEXT NOT NULL,
executable_name                     TEXT NOT NULL,
executable_path                     TEXT,
name_keywords                       TEXT,
    -- JSON: ["google", "chrome", "browser"]
category                            TEXT,
    -- "browser", "editor", "terminal", "media", "utility",
launch_method                       TEXT DEFAULT 'path',
    -- "path", "start_menu", "protocol"
launch_args                         TEXT,
source                              TEXT NOT NULL DEFAULT 'scan',
    -- "scan", "user", "manual"
last_verified                       TEXT,
is_available                        INTEGER DEFAULT 1
);


CREATE TABLE IF NOT EXISTS app_usage_stats(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
app_name                            TEXT NOT NULL UNIQUE,
total_sessions                      INTEGER DEFAULT 0,
total_duration_ms                   REAL DEFAULT 0.0,
avg_session_duration_ms             REAL DEFAULT 0.0,
first_seen                          TEXT,
last_seen                           TEXT,
hourly_usage                        TEXT,
    -- JSON: {"9": 3600500, "10": 7200000, ...} (ms)
daily_usage                         TEXT
    -- JSON: {"0": 36000000, ...} day 0=Monday (ms)
);



CREATE TABLE IF NOT EXISTS app_transitions(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
from_app                            TEXT NOT NULL,
to_app                              TEXT NOT NULL,
occurrence_count                    INTEGER DEFAULT 1,
avg_from_duration_ms                REAL DEFAULT 0.0,
last_occurred                       TEXT,

UNIQUE(from_app, to_app)
);





CREATE TABLE IF NOT EXISTS entities (
    id                              TEXT PRIMARY KEY,
    name                            TEXT NOT NULL,
    canonical_name                  TEXT NOT NULL,
    entity_type                     TEXT NOT NULL,
    resolution                      TEXT NOT NULL,
    keywords                        TEXT,
    source_app                      TEXT,
    source_context                  TEXT,
    created_at                      TEXT NOT NULL,
    last_used_at                    TEXT,
    use_count                       INTEGER DEFAULT 0,
    confidence                      REAL DEFAULT 1.0,
    active                          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id                       TEXT NOT NULL,
    alias                           TEXT NOT NULL,
    alias_normalized                TEXT NOT NULL,
    created_at                      TEXT NOT NULL,
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    UNIQUE(alias)
);




CREATE TABLE IF NOT EXISTS recorded_workflows(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
name                                TEXT NOT NULL,
name_normalized                     TEXT NOT NULL,
name_hash                           TEXT NOT NULL UNIQUE,
description                         TEXT,
trigger_phrases                      TEXT NOT NULL,
-- Json array: ['login to github','github login']
plan_steps                          TEXT NOT NULL,
-- Json derived executable plan
variables                           TEXT,
-- Json [{name, field, default, ask}]
raw_recording                       TEXT,
-- Json full recordign session data
starting_app                        TEXT,
starting_conditions TEXT,
success_count                       INTEGER DEFAULT 0,
failure_count                       INTEGER DEFAULT 0,
stage                               TEXT NOT NULL DEFAULT 'new',
created_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
last_used_at                        TEXT,
last_modified_at                    TEXT,
recording_duration_ms               REAL
);


CREATE TABLE IF NOT EXISTS recorded_states(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
workflow_id                         INTEGER NOT NULL,
step_order                          INTEGER NOT NULL,
captured_at                         TEXT NOT NULL,
application                         TEXT NOT NULL,
window_title                        TEXT,
window_handle                       INTEGER,
url_inferred                        TEXT,
focused_element                     TEXT,
change_type                         TEXT NOT NULL,
change_detail                       TEXT,
screenshot_path                     TEXT,
similarity_to_prev                  REAL,

FOREIGN KEY (workflow_id) REFERENCES recorded_workflows(id)
);



CREATE TABLE IF NOT EXISTS plan_cache(
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_pattern      TEXT UNIQUE NOT NULL,
    intent_action       TEXT NOT NULL,
    intent_target       TEXT,
    raw_command         TEXT,
    plan_strategy       TEXT NOT NULL,
    plan_steps_json     TEXT NOT NULL,
    plan_hash           TEXT NOT NULL,
    use_count           INTEGER DEFAULT 1,
    success_count       INTEGER DEFAULT 1,
    failure_count       INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP,                   
    last_used_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    last_success_at     TEXT,
    is_valid            INTEGER DEFAULT 1,
    invalidation_reason TEXT
);

CREATE TABLE IF NOT EXISTS task_executions(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
execution_id                        TEXT UNIQUE NOT NULL,
timestamp                           TEXT NOT NULL,
session_id                          TEXT NOT NULL,
duration_ms                         REAL,

raw_command                         TEXT NOT NULL,
intent_action                       TEXT NOT NULL,
intent_target                       TEXT,
intent_parameters                   TEXT,
intent_confidence                   REAL,

plan_strategy                       TEXT,
plan_reasoning                      TEXT,
plan_steps_json                     TEXT,
plan_step_count                     INTEGER,
plan_hash                           TEXT,

success                             INTEGER NOT NULL,
failure_reason                      TEXT,
failure_step_index                  INTEGER,

context_json                        TEXT,

-- Link back to learned patterns
pattern_id                          INTEGER,
composition_id                      INTEGER,

verification_method                 TEXT,

FOREIGN KEY (pattern_id) REFERENCES command_patterns(id),
FOREIGN KEY (composition_id) REFERENCES command_compositions(id)
);

CREATE TABLE IF NOT EXISTS step_executions (
id                                  INTEGER PRIMARY KEY AUTOINCREMENT, 
execution_id                        TEXT NOT NULL,
step_index                          INTEGER NOT NULL,
action                              TEXT NOT NULL,
parameters_json                     TEXT,
description                         TEXT,

success                             INTEGER NOT NULL,
error                               TEXT,
method_used                         TEXT,
duration_ms                         REAL,

verified                            INTEGER,
verify_confidence                   REAL,

result_data_json                    TEXT,
FOREIGN KEY (execution_id) REFERENCES task_executions(execution_id)
);





CREATE TABLE IF NOT EXISTS command_compositions(
-- Cached multi-step plan compositions.

id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
trigger_text                        TEXT NOT NULL,
trigger_normalized                  TEXT NOT NULL,
trigger_hash                        TEXT NOT NULL UNIQUE,
composed_plan                       TEXT NOT NULL,
-- Json full plan
pattern_sequence                    TEXT NOT NULL,
-- Json [pattern_id_1, pattern_id_2]
success_count                       INTEGER DEFAULT 0,
failure_count                       INTEGER DEFAULT 0,
stage                               TEXT NOT NULL DEFAULT 'new',
created_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
last_used_at                        TEXT
);



CREATE TABLE IF NOT EXISTS command_graph_edges(
-- Table for Sequential relationshop between patterns.
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
from_pattern_id                     INTEGER NOT NULL,
to_pattern_id                       INTEGER NOT NULL,
occurrence_count                    INTEGER DEFAULT 1,
avg_delay_ms                        REAL DEFAULT 1000.0,
min_delay_ms                        REAL DEFAULT 500.0,
max_delay_ms                        REAL DEFAULT 5000.0,
has_intermediate                    INTEGER DEFAULT 0,
intermediate_steps                  TEXT,
-- Json: Steps between from and to.
success_rate                        REAL DEFAULT 1.0,
created_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
last_used_at                        TEXT,

FOREIGN KEY (from_pattern_id) REFERENCES command_patterns(id),
FOREIGN KEY (to_pattern_id) REFERENCES command_patterns(id), 

UNIQUE(from_pattern_id, to_pattern_id)
);


CREATE TABLE IF NOT EXISTS command_patterns(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
-- pattern identification columns
pattern                             TEXT NOT NULL UNIQUE,
-- Generalizes "open {app}", navigate to {url}

pattern_hash                        TEXT NOT NULL,

action_category                     TEXT NOT NULL,
-- launch, click, type, scroll, window, file, wait, read,drag 

-- The plan template 
plan_template                       TEXT,
-- Json: List of actions steps with {variables}
-- NULL if pattern is known put th eplan not yet proven

plan_hash                           TEXT,
plan_strategy                       TEXT,
-- Learning stage 
stage                               TEXT NOT NULL DEFAULT 'new',
-- 'new','tentative','trusted','proven'
occurrence_count                    INTEGER DEFAULT 1,
success_count                       INTEGER DEFAULT 0,
failure_count                       INTEGER DEFAULT 0,
avg_execution_time_ms               REAL DEFAULT 0.0,
total_execution_time_ms             REAL DEFAULT 0.0,

-- Time patterns 
morning_count                       INTEGER DEFAULT 0,
afternoon_count                     INTEGER DEFAULT 0,
evening_count                       INTEGER DEFAULT 0,
night_count                         INTEGER DEFAULT 0,
weekday_count                       INTEGER DEFAULT 0,
weekend_count                       INTEGER DEFAULT 0,

-- Method preferences learned per app.
method_preferences                  TEXT,
-- Json { "chrome.exe":"visual_search","notepad.exe":"ui_automation"}

-- Source tracking
source                              TEXT NOT NULL DEFAULT 'llm',
-- "llm","user_taught","composed","generalized"

-- Timestamp
created_at                          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
last_used_at                        TEXT,
last_succeeded_at                   TEXT,
last_failed_at                      TEXT,


-- Intent mapping (kept from old, useful for lookup)

intent_action                       TEXT,
intent_target                       TEXT
);



CREATE TABLE IF NOT EXISTS element_cache(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,        
                                                              
element_query                       TEXT NOT NULL,                            
app_name                            TEXT NOT NULL,                            
window_pattern                      TEXT,                                     
                                                              
bounding_box_x                      INTEGER,                                  
bounding_box_y                      INTEGER,                                  
bounding_box_w                      INTEGER,                                  
bounding_box_h                      INTEGER,                                  
center_x                            INTEGER,                                  
center_y                            INTEGER,                                  
                                                              
source                              TEXT,                                     
element_type                        TEXT,                                     
automation_id                       TEXT,                                     
element_name                        TEXT,                                     
                                                              
hit_count                           INTEGER DEFAULT 1,                        
miss_count                          INTEGER DEFAULT 0,                        
last_hit                            TEXT DEFAULT CURRENT_TIMESTAMP,           
last_miss                           TEXT,                                     
                                                              
is_valid                            INTEGER DEFAULT 1,                        
confidence                          REAL DEFAULT 1.0,                         
                                                              
UNIQUE(element_query, app_name, window_pattern)               

);

CREATE TABLE IF NOT EXISTS settings(
key                                 TEXT PRIMARY KEY,
value                               TEXT,
updated_at                          TEXT
);

CREATE TABLE IF NOT EXISTS conversation_history(
id                                  INTEGER PRIMARY KEY,
role                                TEXT,
content                             TEXT,
timestamp                           TEXT,
session_id                          TEXT
);

CREATE TABLE IF NOT EXISTS command_instances(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,
pattern_id                          INTEGER NOT NULL,
raw_text                            TEXT NOT NULL,
raw_text_normalized                 TEXT NOT NULL,
raw_text_hash                       TEXT NOT NULL,
variable_bindings                   TEXT,
success_count                       INTEGER DEFAULT 0,
failure_count                       INTEGER DEFAULT 0,
context_app                         TEXT,
created_at                          TEXT NOT NULL,
last_used_at                        TEXT,

FOREIGN KEY (pattern_id) REFERENCES command_patterns(id)
);


CREATE TABLE IF NOT EXISTS method_statistics(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,                
                                                                      
action                              TEXT NOT NULL,                                    
app_name                            TEXT,                                             
method_used                         TEXT NOT NULL,                                    
                                                                      
success_count                       INTEGER DEFAULT 0,                                
failure_count                       INTEGER DEFAULT 0,                                
                                                                      
avg_duration_ms                     REAL,                                             
min_duration_ms                     REAL,                                             
max_duration_ms                     REAL,                                             
total_duration_ms                   REAL DEFAULT 0,                                   
                                                                      
avg_cpu_percent                     REAL,                                             
avg_memory_mb                       REAL,                                             
                                                                      
first_used                          TEXT DEFAULT CURRENT_TIMESTAMP,                   
last_used                           TEXT DEFAULT CURRENT_TIMESTAMP,                   
                                                                      
UNIQUE(action, app_name, method_used)                                 

);

CREATE TABLE IF NOT EXISTS user_preferences(
id                                  INTEGER PRIMARY KEY AUTOINCREMENT,                
                                                                      
-- Identification                                                     
preference_key                      TEXT UNIQUE NOT NULL,                             
category                            TEXT NOT NULL,                                    
                                                                      
-- Value                                                              
preference_value                    TEXT NOT NULL,                                    
value_type                          TEXT DEFAULT 'string',                            
                                                                      
-- Learning                                                           
confidence                          REAL DEFAULT 0.5,                                 
evidence_count                      INTEGER DEFAULT 1,                                
                                                                      
-- Timestamps                                                             
learned_at                          TEXT DEFAULT CURRENT_TIMESTAMP,                   
last_confirmed                      TEXT DEFAULT CURRENT_TIMESTAMP,                   
                                                                      
-- Override                                                           
is_explicit                         INTEGER DEFAULT 0                                 

);

CREATE TABLE IF NOT EXISTS error_recovery(

id                                  INTEGER PRIMARY KEY AUTOINCREMENT,         
                                                               
failed_action                       TEXT NOT NULL,                             
failed_method                       TEXT,                                      
error_pattern                       TEXT NOT NULL,                             
app_name                            TEXT,                                      
                                                               
recovery_action                     TEXT NOT NULL,                             
recovery_params_json                TEXT,                                     
recovery_description                TEXT,                                     
                                                               
attempt_count                       INTEGER DEFAULT 1,                         
success_count                       INTEGER DEFAULT 1,                         

first_learned                       TEXT DEFAULT CURRENT_TIMESTAMP,            
last_used                           TEXT DEFAULT CURRENT_TIMESTAMP,            
                                                               
UNIQUE(failed_action, error_pattern, app_name)                 

);
"""
INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_al_exe
    ON app_library(executable_name);
CREATE INDEX IF NOT EXISTS idx_al_category
    ON app_library(category);
CREATE INDEX IF NOT EXISTS idx_al_available
    ON app_library(is_available);

    
CREATE INDEX IF NOT EXISTS idx_ea_alias 
    ON entity_aliases(alias_normalized);
CREATE INDEX IF NOT EXISTS idx_ea_entity 
    ON entity_aliases(entity_id);


CREATE INDEX IF NOT EXISTS idx_aus_name
    ON app_usage_stats(app_name);


CREATE INDEX IF NOT EXISTS idx_at_from
    ON app_transitions(from_app);
CREATE INDEX IF NOT EXISTS idx_at_to
    ON app_transitions(to_app);

    
CREATE INDEX IF NOT EXISTS idx_te_timestamp         
    ON task_executions(timestamp DESC);     
CREATE INDEX IF NOT EXISTS idx_te_intent            
    ON task_executions(intent_action, intent_target);
CREATE INDEX IF NOT EXISTS idx_te_success           
    ON task_executions(success);      
CREATE INDEX IF NOT EXISTS idx_te_session           
    ON task_executions(session_id);
CREATE INDEX IF NOT EXISTS idx_te_command       
    ON task_executions(raw_command);      
CREATE INDEX IF NOT EXISTS idx_te_plan_hash         
    ON task_executions(plan_hash);    
CREATE INDEX IF NOT EXISTS idx_te_pattern
    ON task_executions(pattern_id);



CREATE INDEX IF NOT EXISTS idx_ci_hash 
    ON command_instances(raw_text_hash);
CREATE INDEX IF NOT EXISTS idx_ci_pattern
    ON command_instances(pattern_id);
CREATE INDEX IF NOT EXISTS idx_ci_normalized
    ON command_instances(raw_text_normalized);



CREATE INDEX IF NOT EXISTS idx_se_execution         
    ON step_executions(execution_id);                 
CREATE INDEX IF NOT EXISTS idx_se_action            
    ON step_executions(action);                       
CREATE INDEX IF NOT EXISTS idx_se_method            
    ON step_executions(method_used);                  





CREATE INDEX IF NOT EXISTS idx_ge_from
    ON command_graph_edges(from_pattern_id);
CREATE INDEX IF NOT EXISTS idx_ge_to
    ON command_graph_edges(to_pattern_id);



CREATE INDEX IF NOT EXISTS idx_cp_hash            
    ON command_patterns(pattern_hash);  
CREATE INDEX IF NOT EXISTS idx_cp_category      
    ON command_patterns(action_category);
CREATE INDEX IF NOT EXISTS idx_cp_stage          
    ON command_patterns(stage);       
CREATE INDEX IF NOT EXISTS idx_cp_action_target            
    ON command_patterns(intent_action, intent_target);  
CREATE INDEX IF NOT EXISTS idx_cp_frequency      
    ON command_patterns(occurrence_count DESC);
CREATE INDEX IF NOT EXISTS idx_cp_source          
    ON command_patterns(source);       


CREATE INDEX IF NOT EXISTS idx_rw_hash
    ON recorded_workflows(name_hash);
CREATE INDEX IF NOT EXISTS idx_rw_normalized
    ON recorded_workflows(name_normalized);
CREATE INDEX IF NOT EXISTS idx_rw_stage
    ON recorded_workflows(stage);


CREATE INDEX IF NOT EXISTS idx_rs_workflow
    ON recorded_states(workflow_id);


CREATE INDEX IF NOT EXISTS idx_elem_query_app         
    ON element_cache(element_query, app_name);      
  
CREATE INDEX IF NOT EXISTS idx_elem_valid             
    ON element_cache(is_valid, confidence DESC);      

    
CREATE INDEX IF NOT EXISTS idx_ec_app_name 
    ON element_cache(app_name, element_name);


CREATE INDEX IF NOT EXISTS idx_method_action_app      
    ON method_statistics(action, app_name);           

    

CREATE INDEX IF NOT EXISTS idx_pref_category          
    ON user_preferences(category);

    

CREATE INDEX IF NOT EXISTS idx_error_action           
    ON error_recovery(failed_action, app_name);


CREATE INDEX IF NOT EXISTS idx_cc_hash
    ON command_compositions(trigger_hash);

CREATE INDEX IF NOT EXISTS idx_ent_canonical
    ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_ent_type
    ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_ent_active
    ON entities(active);
"""

class MigrationManager:
    def __init__(self):
        self.MIGRATION_MAP  = {
            1:self._migrate_1_to_2
        }
    def get_migration_sql(self,from_version: int, to_version:int)->List[str]:
        if from_version>=to_version:
            return []
        
        if from_version<0 or to_version>SCHEMA_VERSION:
            raise ValueError(f"Invalid migration path: {from_version} to {to_version}")
        
        all_statements = []
        for current in range(from_version, to_version):
            migration_func = self.MIGRATION_MAP.get(current)
            if migration_func:
                statements = migration_func()
                all_statements.extend(statements)
        
        return all_statements
    
    def _migrate_1_to_2(self):
        old_tables = [
            "macros", "macro_executions", 
            "shortcuts", "command_patterns", "command_history"
        ]
        sql = []
        for table in old_tables:
            sql.append(f"DROP TABLE IF EXISTS {table};")
        

        return sql
    

TABLE_NAMES = [
    'schema_info',
    'settings', 
    'conversation_history',
    'command_patterns',
    'command_instances',
    'command_graph_edges',
    'command_compositions',
    'task_executions',
    'step_executions',
    'recorded_workflows',
    'recorded_states',
    'entities',
    'entity_aliases',
    'element_cache',
    'method_statistics',
    'user_preferences',
    'error_recovery',
    'app_library',
    'app_usage_stats',
    'app_transitions',
    'schema_info'
    ]
CLEANUP_CONFIG = {
    'command_patterns':     (MAX_COMMAND_PATTERNS, 'last_used_at DESC'),
    'command_instances':    (MAX_COMMAND_INSTANCES, 'last_used_at DESC'),
    'command_graph_edges':  (MAX_GRAPH_EDGES, 'last_used_at DESC'),
    'command_compositions': (MAX_COMPOSITIONS, 'last_used_at DESC'),
    'task_executions':      (MAX_TASK_HISTORY, 'timestamp DESC'),
    'step_executions':      (MAX_TASK_HISTORY * 5, 'id DESC'),
    'element_cache':        (MAX_ELEMENT_CACHE, 'last_hit DESC'),
    'recorded_states':      (MAX_RECORDED_STATES, 'id DESC'),
    'app_transitions':      (MAX_APP_TRANSITIONS, 'last_occurred DESC'),
    'conversation_history': (MAX_CONVERSATION, 'timestamp DESC')

}
def get_table_names():
    return TABLE_NAMES

def get_cleanup_sql(table_name: str, max_rows: int, order_column: str):
    if table_name not in TABLE_NAMES:
        raise ValueError(f"Invalid or unauthorized table name: {table_name}")
    
    if not isinstance(max_rows, int) or max_rows <= 0:
        raise ValueError("max_rows must be a positive integer")
    
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*(?:\s+(?:ASC|DESC))?$'

    if not re.match(pattern, order_column, re.IGNORECASE):
        raise ValueError(f"Invalid order_column format: {order_column}")
    
    sql = f"""
    DELETE FROM {table_name}
    WHERE id NOT IN (
        SELECT id FROM {table_name}
        ORDER BY {order_column}
        LIMIT {max_rows}
    );
    """.strip()

    return sql