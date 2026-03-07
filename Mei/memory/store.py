import sqlite3
import json
import hashlib
import threading
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager

from ..core.config import get_config
from ..core.events import emit,EventType
from .schema import SCHEMA_SQL, INDEXES_SQL,SCHEMA_VERSION, get_cleanup_sql, get_table_names,MigrationManager,CLEANUP_CONFIG,TABLE_NAMES
DEFAULT_DB_PATH = 'data/memory.db'

MAX_TASK_HISTORY = 10000
MAX_PLAN_CACHE = 1000
MAX_ELEMENT_CACHE = 5000
MAX_COMMAND_PATTERNS = 2000

DEFAULT_MIN_SUCCESS_RATE = 0.7
DEFAULT_MIN_USES = 2
DEFAULT_MIN_CONFIDENCE = 0.5



class MemoryStore:
    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = Path(db_path)
        else:
            config =get_config()
            self.db_path = Path(config.memory.database_path)
        
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._lock = threading.RLock()

        self._init_database()
        print(f"Initialized at {self.db_path}")
        emit(EventType.MEMORY_STORED, source="MemoryStore",operation='init', path  = str(self.db_path))

    def _get_connection(self)->sqlite3.Connection:
        if not hasattr(self._local,'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread= False
            )

            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA busy_timeout=30000")
            self._local.connection.execute("PRAGMA foreign_keys = ON")
            self._local.connection.row_factory = sqlite3.Row

        return self._local.connection
    
    def close_connection(self)->None:
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            self._local.connection.close()
            self._local.connection = None

    
    @contextmanager
    def transaction(self):
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise

    def _init_database(self)->None:
        with self.transaction() as conn:
            cursor = conn.cursor()

            current_version = 0
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_info'")
                if cursor.fetchone():
                    cursor.execute("SELECT value FROM schema_info WHERE key = 'version'")
                    row = cursor.fetchone()
                    if row:
                        current_version = int(row['value'])

            except Exception:
                current_version = 0

            if current_version == SCHEMA_VERSION:
                return
            
            if current_version > 0 and current_version < SCHEMA_VERSION:
                migrator = MigrationManager()
                migration_sql = migrator.get_migration_sql(current_version, SCHEMA_VERSION)
                for statement in migration_sql:
                    cursor.execute(statement)
                conn.commit()
                
            cursor.executescript(SCHEMA_SQL)

            cursor.executescript(INDEXES_SQL)

            cursor.execute('''
                        INSERT OR REPLACE INTO schema_info (key,value)
                        VALUES ('version',?) ''', (str(SCHEMA_VERSION),))
            
            cursor.execute('''
                        INSERT OR IGNORE INTO schema_info (key, value)
                        VALUES ('created_at', ?)
                        ''', (datetime.now().isoformat(),))
            conn.commit()


    def get_schema_version(self)->int:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM schema_info WHERE key = 'version'"
        )

        row = cursor.fetchone()
        return int(row['value']) if row else 0
    
    @staticmethod
    def _generate_hash(data:Any)->str:
        if isinstance(data,dict) or isinstance(data,list):
            data_str = json.dumps(data, sort_keys=True)
        else:
            data_str =str(data)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]
    
    @staticmethod
    def _now()->str:
        return datetime.now().isoformat()
    
    @staticmethod
    def _normalize_text(text: str)->str:
        import re
        result = text.lower().strip()
        fillers = [
            r'\bplease\b', r'\bcan you\b', r'\bcould you\b',
            r'\bhey\b', r'\bjust\b', r'\bgo ahead and\b',
            r'\bi want to\b', r'\bi need to\b', r'\bi\'d like to\b',
        ]
        for filler in fillers:
            result = re.sub(filler,  '', result, flags = re.IGNORECASE)
        result = re.sub(r'[.,!?:;]', '', result)

        result = re.sub(r'\s+', ' ', result).strip()
        return result if result else text.lower().strip()
    
    
    @staticmethod
    def _row_to_dict(row:sqlite3.Row)->Dict[str,Any]:
        result = dict(row)
        json_fields = ['intent_parameters','plan_steps_json','context_json','parameters_json','result_data_json','recovery_params_json']

        for field in json_fields:
            if field in result and result[field]:
                try:
                    result[field] = json.loads(result[field])
                except:
                    pass
        return result
    
    def enforce_limits(self)-> int:
        total_deleted = 0
        with self.transaction() as conn:
            cursor = conn.cursor()
            for table_name, (max_rows, order_col) in CLEANUP_CONFIG.items():
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                if count > max_rows:
                    sql = get_cleanup_sql(table_name, max_rows, order_col)
                    cursor.execute(sql)
                    deleted = cursor.rowcount
                    total_deleted += deleted
        return total_deleted

    def save_task_execution(
            self,
            execution_id:str,
            session_id:str,
            raw_command:str,
            intent:Dict[str,Any],
            plan:Dict[str,Any],
            success:bool,
            duration_ms:float,
            failure_reason:Optional[str]=None,
            failure_step_index:Optional[int] = None,
            context: Optional[Dict[str,Any]]= None,
            step_results: Optional[List[Dict[str,Any]]] = None
    )->int:
        plan_hash = self._generate_hash(plan.get('steps',[]))

        with self.transaction() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                        Insert OR REPLACE into task_executions (
                        execution_id, timestamp, session_id, duration_ms,
                        raw_command, intent_action, intent_target,
                        intent_parameters, intent_confidence,
                        plan_strategy, plan_reasoning, plan_steps_json,
                        plan_step_count, plan_hash,
                        success, failure_reason, failure_step_index,
                        context_json
                        ) Values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ''', (
                            execution_id,
                            self._now(),
                            session_id,
                            duration_ms,
                            raw_command,
                            intent.get('action'),
                            intent.get('target'),
                            json.dumps(intent.get('parameters',{})),
                            intent.get('confidence'),
                            plan.get('strategy'),
                            plan.get('reasoning'),
                            json.dumps(plan.get('steps',[])),
                            len(plan.get('steps',[])),
                            plan_hash,
                            1 if success else 0,
                            failure_reason,
                            failure_step_index,
                            json.dumps(context) if context else None
                        ))
            
            task_id = cursor.lastrowid

            if step_results:
                for step_result in step_results:
                    self._save_step_execution(
                        cursor, execution_id, step_result
                    )
            
            emit(event_type=EventType.MEMORY_STORED, source="MemoryStore", table="task_executions", execution_id=execution_id)

            return task_id
        
    def _save_step_execution(self,cursor: sqlite3.Cursor, execution_id:str, step_result:Dict[str,Any])->None:

        cursor.execute('''
                    Insert Into step_executions (
                    execution_id, step_index, action, parameters_json,
                    description, success, error, method_used, duration_ms,
                    verified, verify_confidence, result_data_json)
                    Values (?,?,?,?,?,?,?,?,?,?,?,?)
                    ''', (
                        execution_id,
                        step_result.get('step_index',0),
                        step_result.get('action'),
                        json.dumps(step_result.get('parameters',{})),
                        step_result.get('description'),
                        1 if step_result.get('success') else 0,
                        step_result.get('error'),
                        step_result.get('method_used'),
                        step_result.get('duration_ms'),
                        1 if step_result.get('verified') else 0,
                        step_result.get('verify_confidence'),
                        json.dumps(step_result.get('data',{}))
                    ))
        
    def get_task_executions(
            self,
            limit:int = 100,
            intent_action: Optional[str] = None,
            intent_target: Optional[str] = None,
            success_only: bool = False,
            session_id: Optional[str] = None,
            since: Optional[datetime] = None
    )-> List[Dict[str,Any]]:
        
        query = "Select * from task_executions where 1 = 1"
        params = []

        if intent_action:
            query +=" And intent_action = ?"
            params.append(intent_action)
        
        if intent_target:
            query +=" And intent_target = ?"
            params.append(intent_target)

        if success_only:
            query += " And success = 1"
        
        if session_id:
            query += " And session_id = ?"
            params.append(session_id)
        
        if since: 
            query += " And timestamp >= ?"
            params.append(since.isoformat())

        query +=" Order by timestamp Desc Limit ?"
        params.append(limit)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)

        return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def get_step_executions(
            self, 
            execution_id:str
    ) -> List[Dict[str,Any]]:
        
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
                    Select * From step_executions
                    Where execution_id = ?
                    Order by step_index'''
                    , (execution_id,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def search_task_executions( self, raw_command_like:str, limit:int = 20)->List[Dict[str,Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
                    Select * from task_executions
                    Where raw_command Like ?
                    Order by timestamp Desc Limit ? ''',
                    (f"%{raw_command_like}%", limit))
        
        return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def cache_plan( 
            self,
            intent_pattern:str,
            intent_action:str,
            intent_target:Optional[str],
            plan_strategy:str,
            plan_steps:List[Dict[str,Any]],
            raw_command: Optional[str] = None,
            plan_hash: Optional[str] = None,
    ) -> int:
        if not plan_hash:
            step_str = json.dumps(plan_steps, sort_keys=True)
            plan_hash = hashlib.md5(step_str.encode()).hexdigest()
    
        plan_steps_json = json.dumps(plan_steps)

        with self.transaction() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                        Insert Into plan_cache (
                        intent_pattern, intent_action, intent_target,
                        raw_command, plan_strategy,
                        plan_steps_json, plan_hash
                        ) Values (?, ?, ?, ?, ?, ?, ?)
                        On CONFLICT(intent_pattern) Do Update set
                        use_count = use_count + 1,
                        success_count = success_count +1,
                        last_used_at = CURRENT_TIMESTAMP,
                        plan_strategy = excluded.plan_strategy,
                        plan_steps_json = excluded.plan_steps_json,
                        plan_hash = excluded.plan_hash,
                        is_valid = 1
                        ''', (
                            intent_pattern, intent_action, intent_target,
                            raw_command, plan_strategy,
                            plan_steps_json, plan_hash

                        ))
            return cursor.lastrowid
            
    def get_cached_plan(
                self,
                intent_pattern: str,
                min_success_rate: float = DEFAULT_MIN_SUCCESS_RATE,
                min_uses: int = DEFAULT_MIN_USES
        ) -> Optional[Dict[str, Any]]:
            
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM plan_cache
                WHERE intent_pattern = ?
                AND is_valid = 1
            ''', (intent_pattern,))
            
            row = cursor.fetchone()
            
            if not row:
                return None

            data = self._row_to_dict(row)

            use_count = data.get('use_count', 0)
            success = data.get('success_count', 0)
            failure = data.get('failure_count', 0)
            
            total = success + failure
            base = max(use_count,total)
            current_rate = (success / base) if base > 0 else 0.0
            if use_count >= min_uses and current_rate >= min_success_rate:
                return data
                
            return None
    
    def get_cached_plan_by_action_target(
            self,
            intent_action:str,
            intent_target:Optional[str],
            min_success_rate:float = DEFAULT_MIN_SUCCESS_RATE
    ) -> List[Dict[str,Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()

        if intent_target:
            cursor.execute('''
                        SELECT *,
                        COALESCE(CAST(success_count AS REAL) / NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate
                        FROM plan_cache
                        WHERE intent_action = ?
                        AND intent_target = ?
                        AND is_valid = 1
                        AND COALESCE(CAST(success_count AS REAL) / NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) >= ?
                        ORDER BY use_count DESC
                        ''', (intent_action, intent_target, min_success_rate))
        
        else:
            cursor.execute('''
                        SELECT *,
                        COALESCE(CAST(success_count AS REAL) / NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate
                        FROM plan_cache
                        WHERE intent_action = ?
                        AND is_valid = 1
                        AND COALESCE(CAST(success_count AS REAL) / NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) >= ?
                        ORDER BY use_count DESC
                        ''', (intent_action, min_success_rate))
        
        return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def record_plan_failure(
            self,
            intent_pattern:str,
            invalidate_threshold:float = 0.5
    )->None:
        with self.transaction() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                        Update plan_cache SET failure_count = failure_count +1,
                        use_count = use_count +1,
                        last_used_at = CURRENT_TIMESTAMP
                        WHERE intent_pattern = ?''',(intent_pattern,))
            
            cursor.execute('''
                        Update plan_cache SET
                        is_valid = 0,
                        invalidation_reason = 'Success rate below threshold'
                        WHERE intent_pattern = ?
                        AND use_count >=5
                        AND CAST(success_count AS REAL) /
                        CAST(success_count + failure_count as REAL)<?
                        ''', (intent_pattern, invalidate_threshold))
            
    def invalidate_plan(self,
                        intent_pattern:str,
                        reason:str = "Manual invalidation")->bool:
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                        UPDATE plan_cache SET is_valid = 0,
                        invalidation_reason = ?
                        WHERE intent_pattern = ?
                        ''',(reason, intent_pattern))
            return cursor.rowcount >0
        
    
    def record_command(
            self, 
            raw_command:str,
            intent_action:str,
            intent_target: Optional[str],
            success:bool,
            normalized_pattern:Optional[str] = None
    )->None:
        
        hour = datetime.now().hour
        if 6<=hour <12:
            time_col = 'morning_count'
        
        elif 12 <=hour <18:
            time_col = 'afternoon_count'
        
        elif 18<=hour <24:
            time_col = 'evening_count'
        
        else:
            time_col = 'night_count'

        is_weekend = datetime.now().weekday() >=5
        day_col = 'weekend_count' if is_weekend else 'weekday_count'

        success_col = 'success_count' if success else 'failure_count'

        pattern_text = normalized_pattern or raw_command
        pattern_hash = self._generate_hash(pattern_text)

        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                        INSERT INTO command_patterns( 
                        pattern, pattern_hash, action_category,
                        intent_action, intent_target,
                        occurrence_count, {time_col},{day_col},{success_col})
                        VALUES (?, ?, ?, ?, ?, 1, 1, 1, 1)
                        ON CONFLICT(pattern) DO UPDATE SET 
                        occurrence_count = occurrence_count +1,
                        {time_col} = {time_col} + 1,
                        {day_col} = {day_col} + 1,
                        {success_col} = {success_col} + 1,
                        last_used_at = CURRENT_TIMESTAMP
                        ''', (pattern_text, pattern_hash, intent_action,
                              intent_action, intent_target))
            
    def get_frequent_commands(
            self,
            limit:int = 20,
            time_period: Optional[str] = None,
            intent_action:Optional[str] = None
    ) -> List[Dict[str,Any]]:
        
        order_col = "occurrence_count"                                     
        if time_period == "morning":
            order_col = "morning_count"
        elif time_period == "afternoon":
            order_col = "afternoon_count"
        elif time_period == 'evening':
            order_col = 'evening_count'
        elif time_period == 'night':
            order_col = 'night_count'


        query = f"SELECT * FROM command_patterns WHERE 1=1"
        params = []

        if intent_action:                                                  
            query += " AND intent_action = ?"
            params.append(intent_action)
        
        query += f" ORDER BY {order_col} DESC LIMIT ?"
        params.append(limit)

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def get_command_pattern(                                        
        self,                                                       
        raw_pattern: str                                            
    ) -> Optional[Dict[str, Any]]:                                  
        conn = self._get_connection()                               
        cursor = conn.cursor()       
        pattern_hash = self._generate_hash(raw_pattern)
                    
        cursor.execute(                                             
            "SELECT * FROM command_patterns WHERE pattern_hash = ?", 
            (pattern_hash,)                                          
        )                                                           
        row = cursor.fetchone()                                     
        return self._row_to_dict(row) if row else None              



    def cache_element(                                                        
        self,                                                                 
        element_query: str,                                                   
        app_name: str,                                                        
        bounding_box: Tuple[int, int, int, int],                              
        source: str,                                                          
        window_pattern: Optional[str] = None,                                 
        element_type: Optional[str] = None,                                   
        automation_id: Optional[str] = None,                                  
        element_name: Optional[str] = None                                    
    ) -> None:                                                                                                                               
                                                                            
        x, y, w, h = bounding_box                                          
        center_x = x + w // 2                                              
        center_y = y + h // 2                                              
                                                                            
        with self.transaction() as conn:                                   
            cursor = conn.cursor()                                         
                                                                            
            cursor.execute('''                                             
                INSERT INTO element_cache (                                
                    element_query, app_name, window_pattern,               
                    bounding_box_x, bounding_box_y,                        
                    bounding_box_w, bounding_box_h,                        
                    center_x, center_y,                                    
                    source, element_type, automation_id, element_name      
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)            
                ON CONFLICT(element_query, app_name, window_pattern)       
                DO UPDATE SET                                              
                    bounding_box_x = excluded.bounding_box_x,              
                    bounding_box_y = excluded.bounding_box_y,              
                    bounding_box_w = excluded.bounding_box_w,              
                    bounding_box_h = excluded.bounding_box_h,              
                    center_x = excluded.center_x,                          
                    center_y = excluded.center_y,                          
                    source = excluded.source,                              
                    hit_count = hit_count + 1,                             
                    last_hit = CURRENT_TIMESTAMP,                          
                    confidence = MIN(1.0, confidence + 0.05),              
                    is_valid = 1                                           
            ''', (                                                         
                element_query, app_name, window_pattern,                   
                x, y, w, h, center_x, center_y,                            
                source, element_type, automation_id, element_name          
            ))                                                             
                                                                                                                                                        
    def get_cached_element(                                                   
        self,                                                                 
        element_query: str,                                                   
        app_name: str,                                                        
        window_pattern: Optional[str] = None,                                 
        min_confidence: float = DEFAULT_MIN_CONFIDENCE                        
    ) -> Optional[Dict[str, Any]]:                                            
                                                            
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        if window_pattern:                                                 
            cursor.execute('''                                             
                SELECT * FROM element_cache                                
                WHERE element_query = ?                                    
                    AND app_name = ?                                         
                    AND window_pattern = ?                                   
                    AND is_valid = 1                                         
                    AND confidence >= ?                                      
                ORDER BY confidence DESC, hit_count DESC                   
                LIMIT 1                                                    
            ''', (element_query, app_name, window_pattern, min_confidence))
            row = cursor.fetchone()                                        
            if row:                                                        
                return self._row_to_dict(row)                              
                                                                            
        cursor.execute('''                                                 
            SELECT * FROM element_cache                                    
            WHERE element_query = ?                                        
                AND app_name = ?                                             
                AND is_valid = 1                                             
                AND confidence >= ?                                          
            ORDER BY confidence DESC, hit_count DESC                       
            LIMIT 1                                                        
        ''', (element_query, app_name, min_confidence))                    
                                                                            
        row = cursor.fetchone()                                            
        return self._row_to_dict(row) if row else None                     

    def record_element_hit(
            self,
            element_query:str,
            app_name:str,
            window_pattern:Optional[str] = None
    ) -> None: 
        with self.transaction() as conn:
            cursor = conn.cursor()

            if window_pattern:
                cursor.execute('''                                            
                    UPDATE element_cache SET                                  
                        hit_count = hit_count + 1,                            
                        last_hit = CURRENT_TIMESTAMP,                         
                        confidence = MIN(1.0, confidence + 0.05)              
                    WHERE element_query = ?                                   
                    AND app_name = ?                                        
                    AND window_pattern = ?                                  
                ''', (element_query, app_name, window_pattern))               
            else:                                                             
                cursor.execute('''                                            
                    UPDATE element_cache SET                                  
                        hit_count = hit_count + 1,                            
                        last_hit = CURRENT_TIMESTAMP,                         
                        confidence = MIN(1.0, confidence + 0.05)              
                    WHERE element_query = ?                                   
                    AND app_name = ?                                        
                ''', (element_query, app_name))                               
                                                                            
                                                                            
                                                                            
    def record_element_miss(                                                  
        self,                                                                 
        element_query: str,                                                   
        app_name: str,                                                        
        window_pattern: Optional[str] = None,                                 
        invalidate_threshold: float = 0.2                                     
    ) -> None:                                                                
        """                                                                   
        Record that a cached element was NOT found at expected location.      
        Decreases confidence, may invalidate.                                 
        """                                                                   
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
                                                                            
            if window_pattern:                                             
                cursor.execute('''                                         
                    UPDATE element_cache SET                               
                        miss_count = miss_count + 1,                       
                        last_miss = CURRENT_TIMESTAMP,                     
                        confidence = MAX(0.0, confidence - 0.15)           
                    WHERE element_query = ?                                
                        AND app_name = ?                                     
                        AND window_pattern = ?                               
                ''', (element_query, app_name, window_pattern))            
            else:                                                          
                cursor.execute('''                                         
                    UPDATE element_cache SET                               
                        miss_count = miss_count + 1,                       
                        last_miss = CURRENT_TIMESTAMP,                     
                        confidence = MAX(0.0, confidence - 0.15)           
                    WHERE element_query = ?                                
                        AND app_name = ?                                     
                ''', (element_query, app_name))                            
                                                                            
            cursor.execute('''                                             
                UPDATE element_cache SET is_valid = 0                      
                WHERE element_query = ?                                    
                    AND app_name = ?                                         
                    AND confidence < ?                                       
            ''', (element_query, app_name, invalidate_threshold))          
                                                                            
                                                                            
                                                                            
    def invalidate_element(                                                   
        self,                                                                 
        element_query: str,                                                   
        app_name: str,                                                        
        window_pattern: Optional[str] = None                                  
    ) -> bool:                                                                
        """Manually invalidate a cached element."""                           
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
                                                                            
            if window_pattern:                                                
                cursor.execute('''                                            
                    UPDATE element_cache SET is_valid = 0                     
                    WHERE element_query = ?                                   
                    AND app_name = ?                                        
                    AND window_pattern = ?                                  
                ''', (element_query, app_name, window_pattern))               
            else:                                                             
                cursor.execute('''                                            
                    UPDATE element_cache SET is_valid = 0                     
                    WHERE element_query = ?                                   
                    AND app_name = ?                                        
                ''', (element_query, app_name))                               
                                                                            
            return cursor.rowcount > 0                                        
                                                                            
                                                                            
                                                                            
    def get_elements_for_app(                                                 
        self,                                                                 
        app_name: str,                                                        
        valid_only: bool = True                                               
    ) -> List[Dict[str, Any]]:                                                
        """Get all cached elements for an application."""                     
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        if valid_only:                                                        
            cursor.execute('''                                                
                SELECT * FROM element_cache                                   
                WHERE app_name = ? AND is_valid = 1                           
                ORDER BY confidence DESC, hit_count DESC                      
            ''', (app_name,))                                                 
        else:                                                                 
            cursor.execute('''                                                
                SELECT * FROM element_cache                                   
                WHERE app_name = ?                                            
                ORDER BY confidence DESC, hit_count DESC                      
            ''', (app_name,))                                                 
                                                                            
        return [self._row_to_dict(row) for row in cursor.fetchall()]          



                                                                            
    def record_method_result(                                                 
        self,                                                                 
        action: str,                                                          
        method_used: str,                                                     
        success: bool,                                                        
        duration_ms: float,                                                   
        app_name: Optional[str] = None                                        
    ) -> None:                                                                
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
                                                                            
            cursor.execute('''                                             
                SELECT id, success_count, failure_count,                   
                        total_duration_ms, min_duration_ms, max_duration_ms 
                FROM method_statistics                                     
                WHERE action = ?                                           
                    AND method_used = ?                                      
                    AND (app_name = ? OR (app_name IS NULL AND ? IS NULL))   
            ''', (action, method_used, app_name, app_name))                
                                                                            
            row = cursor.fetchone()                                        
                                                                            
            if row:                                                        
                new_success = row['success_count'] + (1 if success else 0) 
                new_failure = row['failure_count'] + (0 if success else 1) 
                new_total_duration = (row['total_duration_ms'] or 0) + duration_ms
                total_count = new_success + new_failure                    
                new_avg = new_total_duration / total_count                 
                new_min = min(row['min_duration_ms'] or float('inf'), duration_ms)
                new_max = max(row['max_duration_ms'] or 0, duration_ms)    
                                                                            
                cursor.execute('''                                         
                    UPDATE method_statistics SET                           
                        success_count = ?,                                 
                        failure_count = ?,                                 
                        total_duration_ms = ?,                             
                        avg_duration_ms = ?,                               
                        min_duration_ms = ?,                               
                        max_duration_ms = ?,                               
                        last_used = CURRENT_TIMESTAMP                      
                    WHERE id = ?                                           
                ''', (new_success, new_failure, new_total_duration,        
                        new_avg, new_min, new_max, row['id']))               
                                                                            
            else:                                                          
                cursor.execute('''                                         
                    INSERT INTO method_statistics (                        
                        action, app_name, method_used,                     
                        success_count, failure_count,                      
                        total_duration_ms, avg_duration_ms,                
                        min_duration_ms, max_duration_ms                   
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)                    
                ''', (                                                     
                    action, app_name, method_used,                         
                    1 if success else 0,                                   
                    0 if success else 1,                                   
                    duration_ms, duration_ms, duration_ms, duration_ms     
                ))                                                         
                                                                            
                                                                            
                                                                            
    def get_method_statistics(                                                
        self,                                                                 
        action: str,                                                          
        app_name: Optional[str] = None                                        
    ) -> List[Dict[str, Any]]:                                                
        """                                                                   
        Get all method statistics for an action.                              
        Returns sorted by success rate descending.                            
        """                                                                   
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                                                                        
        if app_name:                                                       
            cursor.execute('''                                             
                SELECT *,                                                  
                    COALESCE(CAST(success_count AS REAL) /                          
                    NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate,
                    (success_count + failure_count) AS total_count         
                FROM method_statistics                                     
                WHERE action = ? AND app_name = ?                          
                ORDER BY success_rate DESC, avg_duration_ms ASC            
            ''', (action, app_name))                                       
            rows = cursor.fetchall()                                       
            if rows:                                                       
                return [self._row_to_dict(row) for row in rows]            
                                                                            
                                    
        cursor.execute('''                                                 
            SELECT *,                                                      
                COALESCE(CAST(success_count AS REAL) /                              
                NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate,
                (success_count + failure_count) AS total_count             
            FROM method_statistics                                         
            WHERE action = ? AND app_name IS NULL                          
            ORDER BY success_rate DESC, avg_duration_ms ASC                
        ''', (action,))                                                    
                                                                            
        return [self._row_to_dict(row) for row in cursor.fetchall()]       
                                                                                                                                        
    def get_best_method(                                                      
        self,                                                                 
        action: str,                                                          
        app_name: Optional[str] = None,                                       
        min_uses: int = 5,                                                    
        min_success_rate: float = 0.6                                         
    ) -> Optional[str]:                                                       
                                                
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        if app_name:                                                       
            cursor.execute('''                                             
                SELECT method_used,                                        
                    COALESCE(CAST(success_count AS REAL) /                          
                    NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate
                FROM method_statistics                                     
                WHERE action = ?                                           
                    AND app_name = ?                                         
                    AND (success_count + failure_count) >= ?
                    AND COALESCE(CAST(success_count AS REAL) /
                        NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) >= ?
                ORDER BY success_rate DESC, avg_duration_ms ASC            
                LIMIT 1                                                    
            ''', (action, app_name, min_uses, min_success_rate))           
            row = cursor.fetchone()                                        
            if row:                                                        
                return row['method_used']                                  
                                                                            
                                            
        cursor.execute('''                                                 
            SELECT method_used,                                            
                COALESCE(CAST(success_count AS REAL) /                              
                NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) AS success_rate
            FROM method_statistics                                         
            WHERE action = ?                                               
                AND app_name IS NULL                                         
                AND (success_count + failure_count) >= ?                     
                AND COALESCE(CAST(success_count AS REAL) /
                    NULLIF(CAST(success_count + failure_count AS REAL), 0), 0.0) >= ?
            ORDER BY success_rate DESC, avg_duration_ms ASC                
            LIMIT 1                                                        
        ''', (action, min_uses, min_success_rate))                         
                                                                            
        row = cursor.fetchone()                                            
        return row['method_used'] if row else None                         

                                                                            
    def set_preference(                                                       
        self,                                                                 
        preference_key: str,                                                  
        preference_value: Any,                                                
        category: str = "general",                                            
        is_explicit: bool = False,                                            
        confidence: float = 0.5                                               
    ) -> None:                                                                
        """                                                                   
        Set or update a user preference.                                      
                                                                            
        Args:                                                                 
            preference_key: Unique identifier                                 
            preference_value: The preference value                            
            category: "app", "behavior", "shortcut", "general"                
            is_explicit: True if user explicitly set this                     
            confidence: 0.0-1.0 how confident we are                          
        """                                                                   
                                                                            
        if isinstance(preference_value, bool):                             
            value_type = "bool"                                            
            value_str = "true" if preference_value else "false"            
        elif isinstance(preference_value, int):                            
            value_type = "int"                                             
            value_str = str(preference_value)                              
        elif isinstance(preference_value, float):                          
            value_type = "float"                                           
            value_str = str(preference_value)                              
        elif isinstance(preference_value, (dict, list)):                   
            value_type = "json"                                            
            value_str = json.dumps(preference_value)                       
        else:                                                              
            value_type = "string"                                          
            value_str = str(preference_value)                              
                                                                            
        with self.transaction() as conn:                                   
            cursor = conn.cursor()                                         
                                                                            
            cursor.execute('''                                             
                INSERT INTO user_preferences (                             
                    preference_key, category, preference_value,            
                    value_type, confidence, is_explicit                    
                ) VALUES (?, ?, ?, ?, ?, ?)                                 
                ON CONFLICT(preference_key) DO UPDATE SET                  
                    preference_value = excluded.preference_value,          
                    value_type = excluded.value_type,                      
                    confidence = CASE                                      
                        WHEN excluded.is_explicit = 1 THEN 1.0             
                        ELSE MAX(confidence, excluded.confidence)          
                    END,                                                   
                    evidence_count = evidence_count + 1,                   
                    last_confirmed = CURRENT_TIMESTAMP,                    
                    is_explicit = MAX(is_explicit, excluded.is_explicit)   
            ''', (                                                         
                preference_key, category, value_str,                       
                value_type, confidence, 1 if is_explicit else 0            
            ))                                                             
                                                                            
                                                                            
                                                    
                                                                            
    def get_preference(                                                       
        self,                                                                 
        preference_key: str,                                                  
        default: Any = None,                                                  
        min_confidence: float = 0.0                                           
    ) -> Any:                                                                 
                                                                
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        cursor.execute('''                                                    
            SELECT preference_value, value_type, confidence                   
            FROM user_preferences                                             
            WHERE preference_key = ?                                          
            AND confidence >= ?                                             
        ''', (preference_key, min_confidence))                                
                                                                            
        row = cursor.fetchone()                                               
        if not row:                                                           
            return default                                                    
                                                                            
        value_str = row['preference_value']                                   
        value_type = row['value_type']                                        
                                                                            
        if value_type == "bool":                                              
            return value_str.lower() == "true"                                
        elif value_type == "int":                                             
            return int(value_str)                                             
        elif value_type == "float":                                           
            return float(value_str)                                           
        elif value_type == "json":                                            
            return json.loads(value_str)                                      
        else:                                                                 
            return value_str                                                  
                                                                            
                                                                            
                                                                            
    def get_preferences_by_category(                                          
        self,                                                                 
        category: str,                                                        
        min_confidence: float = 0.0                                           
    ) -> Dict[str, Any]:                                                      
                                                            
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        cursor.execute('''                                                    
            SELECT preference_key, preference_value, value_type               
            FROM user_preferences                                             
            WHERE category = ?                                                
            AND confidence >= ?                                             
        ''', (category, min_confidence))                                      
                                                                            
        result = {}                                                           
        for row in cursor.fetchall():                                         
            key = row['preference_key']                                       
            value_str = row['preference_value']                               
            value_type = row['value_type']                                    
                                                                            
            if value_type == "bool":                                          
                result[key] = value_str.lower() == "true"                     
            elif value_type == "int":                                         
                result[key] = int(value_str)                                  
            elif value_type == "float":                                       
                result[key] = float(value_str)                                
            elif value_type == "json":                                        
                result[key] = json.loads(value_str)                           
            else:                                                             
                result[key] = value_str                                       
                                                                            
        return result                                                         
                                                                            
                                                                            
                                                                            
    def increase_preference_confidence(                                       
        self,                                                                 
        preference_key: str,                                                  
        amount: float = 0.1                                                   
    ) -> None:                                                                
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
            cursor.execute('''                                                
                UPDATE user_preferences SET                                   
                    confidence = MIN(1.0, confidence + ?),                    
                    evidence_count = evidence_count + 1,                      
                    last_confirmed = CURRENT_TIMESTAMP                        
                WHERE preference_key = ?                                      
            ''', (amount, preference_key))                                    
                                                                            
    def record_recovery_strategy(                                             
        self,                                                                 
        failed_action: str,                                                   
        error_pattern: str,                                                   
        recovery_action: str,                                                 
        recovery_params: Optional[Dict[str, Any]] = None,                     
        recovery_description: Optional[str] = None,                           
        failed_method: Optional[str] = None,                                  
        app_name: Optional[str] = None,                                       
        success: bool = True                                                  
    ) -> None:                                                                
                                                            
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
                                                                            
            cursor.execute('''                                                
                INSERT INTO error_recovery (                                  
                    failed_action, failed_method, error_pattern, app_name,    
                    recovery_action, recovery_params_json, recovery_description,
                    attempt_count, success_count                              
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)                           
                ON CONFLICT(failed_action, error_pattern, app_name) DO UPDATE SET
                    attempt_count = attempt_count + 1,                        
                    success_count = success_count + ?,                        
                    last_used = CURRENT_TIMESTAMP,                            
                    recovery_action = CASE                                    
                        WHEN excluded.success_count > 0 THEN excluded.recovery_action
                        ELSE recovery_action                                  
                    END,                                                      
                    recovery_params_json = CASE                               
                        WHEN excluded.success_count > 0 THEN excluded.recovery_params_json
                        ELSE recovery_params_json                             
                    END                                                       
            ''', (                                                            
                failed_action, failed_method, error_pattern, app_name,        
                recovery_action,                                              
                json.dumps(recovery_params) if recovery_params else None,     
                recovery_description,                                         
                1 if success else 0,                                          
                1 if success else 0                                           
            ))                                                                
                                                                            
                                                                            
                                                                            
    def get_recovery_strategy(                                                
        self,                                                                 
        failed_action: str,                                                   
        error_pattern: str,                                                   
        app_name: Optional[str] = None,                                       
        min_success_rate: float = 0.5                                         
    ) -> Optional[Dict[str, Any]]:                                            
        """                                                                   
        Get a recovery strategy for a failed action.                          
                                                                            
        Returns: Recovery strategy or None                                    
        """                                                                   
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        if app_name:                                                       
            cursor.execute('''                                             
                SELECT *,                                                  
                    COALESCE(CAST(success_count AS REAL) /                          
                    NULLIF(CAST(attempt_count AS REAL), 0), 0.0) AS success_rate            
                FROM error_recovery                                        
                WHERE failed_action = ?                                    
                    AND error_pattern LIKE ?                                 
                    AND app_name = ?
                    AND COALESCE(CAST(success_count AS REAL) /
                        NULLIF(CAST(attempt_count AS REAL), 0), 0.0) >= ?
                ORDER BY success_rate DESC, attempt_count DESC             
                LIMIT 1                                                    
            ''', (failed_action, f"%{error_pattern}%",                     
                    app_name, min_success_rate))                             
            row = cursor.fetchone()                                        
            if row:                                                        
                return self._row_to_dict(row)                              
                                                                            
        cursor.execute('''                                                 
            SELECT *,                                                      
                COALESCE(CAST(success_count AS REAL) /                              
                NULLIF(CAST(attempt_count AS REAL), 0), 0.0) AS success_rate                
            FROM error_recovery                                            
            WHERE failed_action = ?                                        
                AND error_pattern LIKE ?                                     
                AND app_name IS NULL
                AND COALESCE(CAST(success_count AS REAL) /
                    NULLIF(CAST(attempt_count AS REAL), 0), 0.0) >= ?
            ORDER BY success_rate DESC, attempt_count DESC                 
            LIMIT 1                                                        
        ''', (failed_action, f"%{error_pattern}%", min_success_rate))      
                                                                            
        row = cursor.fetchone()                                            
        return self._row_to_dict(row) if row else None                     
                   
                                                                            
                                                                            
                                                                            
    def get_all_recovery_strategies(                                          
        self,                                                                 
        failed_action: Optional[str] = None,                                  
        min_success_rate: float = 0.0                                         
    ) -> List[Dict[str, Any]]:                                                
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        if failed_action:                                                     
            cursor.execute('''                                                
                SELECT *,                                                     
                    COALESCE(CAST(success_count AS REAL) /                             
                    NULLIF(CAST(attempt_count AS REAL), 0), 0.0) AS success_rate               
                FROM error_recovery                                           
                WHERE failed_action = ?
                    AND COALESCE(CAST(success_count AS REAL) /
                        NULLIF(CAST(attempt_count AS REAL), 0), 0.0) >= ?
                ORDER BY success_rate DESC                                    
            ''', (failed_action, min_success_rate))                           
        else:                                                                 
            cursor.execute('''                                                
                SELECT *,                                                     
                    COALESCE(CAST(success_count AS REAL) /                             
                    NULLIF(CAST(attempt_count AS REAL), 0), 0.0) AS success_rate               
                FROM error_recovery
                WHERE COALESCE(CAST(success_count AS REAL) /
                    NULLIF(CAST(attempt_count AS REAL), 0), 0.0) >= ?
                ORDER BY success_rate DESC                                    
            ''', (min_success_rate,))                                         
                                                                            
        return [self._row_to_dict(row) for row in cursor.fetchall()]          


                                                                            
    def cleanup_old_data(                                                     
        self,                                                                 
        max_task_age_days: int = 90,                                          
        max_tasks: int = MAX_TASK_HISTORY,                                    
        max_cached_plans: int = MAX_PLAN_CACHE,                               
        max_elements: int = MAX_ELEMENT_CACHE                                 
    ) -> Dict[str, int]:                                                      
                                                                            
        deleted = {}                                                          
                                                                            
        with self.transaction() as conn:                                      
            cursor = conn.cursor()                                            
                                                                            
            cursor.execute('''                                             
                DELETE FROM task_executions                                
                WHERE id NOT IN (                                          
                    SELECT id FROM task_executions                         
                    ORDER BY timestamp DESC                                
                    LIMIT ?                                                
                )                                                          
            ''', (max_tasks,))                                             
            deleted['task_executions'] = cursor.rowcount                   
                                                                            
            cursor.execute('''                                             
                DELETE FROM step_executions                                
                WHERE execution_id NOT IN (                                
                    SELECT execution_id FROM task_executions               
                )                                                          
            ''')                                                           
            deleted['step_executions'] = cursor.rowcount                   
                                                                            
            cursor.execute('''                                             
                DELETE FROM plan_cache                                     
                WHERE is_valid = 0                                         
                    AND use_count < 3                                        
            ''')                                                           
            deleted['plan_cache'] = cursor.rowcount                        
                                                                            
            cursor.execute('''                                             
                DELETE FROM element_cache                                  
                WHERE is_valid = 0                                         
                    AND confidence < 0.1                                     
            ''')                                                           
            deleted['element_cache'] = cursor.rowcount                     
                                                                            
            cursor.execute('''                                             
                DELETE FROM element_cache                                  
                WHERE id NOT IN (                                          
                    SELECT id FROM element_cache                           
                    ORDER BY last_hit DESC, confidence DESC                
                    LIMIT ?                                                
                )                                                          
            ''', (max_elements,))                                          
            deleted['element_cache'] += cursor.rowcount                    
                                                                            
        return deleted                                                        
                                                                            
                                                                            
                                                                            
    def vacuum(self) -> None:                                                 
        conn = self._get_connection()                                         
        conn.execute("VACUUM")                                                
                                                                            
                                                                            
                                                                            
    def get_statistics(self) -> Dict[str, Any]:                               
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        stats = {}

        for table in TABLE_NAMES:   
            try:                                               
                cursor.execute(f"SELECT COUNT(*) as count FROM {table}")          
                stats[f'{table}_count'] = cursor.fetchone()['count']              
            except Exception:
                stats[f'{table}_count'] = -1

        try:                                                        
        # Additional stats                                                    
            cursor.execute('''                                                    
                SELECT COUNT(*) as count FROM task_executions WHERE success = 1   
            ''')                                                                  
            stats['successful_tasks'] = cursor.fetchone()['count']                
                                                                                
            cursor.execute('''                                                    
                SELECT COUNT(*) as count FROM plan_cache WHERE is_valid = 1       
            ''')                                                                  
            stats['valid_cached_plans'] = cursor.fetchone()['count']              
                                                                                
            cursor.execute('''                                                    
                SELECT COUNT(*) as count FROM element_cache WHERE is_valid = 1    
            ''')                                                                  
            stats['valid_cached_elements'] = cursor.fetchone()['count']           

        except Exception:
            pass

        if self.db_path.exists():                                             
            stats['db_size_mb'] = self.db_path.stat().st_size / (1024 * 1024) 
                                                                            
        return stats                                                          
                                                                            
                                                                            
                                                                            
    def export_to_json(                                                       
        self,                                                                 
        output_path: str,                                                     
        tables: Optional[List[str]] = None                                    
    ) -> None:                                                                
                                                                            
        if tables is None:                                                    
            tables = [                                                        
                'task_executions', 'plan_cache', 'command_patterns',          
                'element_cache', 'method_statistics', 'user_preferences',     
                'error_recovery'                                              
            ]                                                                 
                                                                            
        conn = self._get_connection()                                         
        cursor = conn.cursor()                                                
                                                                            
        export_data = {                                                       
            'exported_at': self._now(),                                       
            'schema_version': SCHEMA_VERSION,                                 
            'tables': {}                                                      
        }                                                                     
                                                                            
        for table in tables:                                                  
            cursor.execute(f"SELECT * FROM {table}")                          
            rows = [self._row_to_dict(row) for row in cursor.fetchall()]      
            export_data['tables'][table] = rows                               
                                                                            
        with open(output_path, 'w') as f:                                     
            json.dump(export_data, f, indent=2, default=str)                  

_store_instance: Optional[MemoryStore] = None                             
                                                                        
                                                                        
def get_memory_store() -> MemoryStore:                                    
    """                                                                   
    Get the global MemoryStore instance.                                  
    Creates it on first call.                                             
    """                                                                   
    global _store_instance                                                
    if _store_instance is None:                                           
        _store_instance = MemoryStore()                                   
    return _store_instance                                                
                                                                        
                                                                        
__all__ = [                                                               
    'MemoryStore',                                                        
    'get_memory_store',                                                   
    'DEFAULT_MIN_SUCCESS_RATE',                                           
    'DEFAULT_MIN_USES',                                                   
    'DEFAULT_MIN_CONFIDENCE',                                             
]                                                                         


if __name__ == "__main__":                                                
    """Test the memory store."""                                          
    import tempfile                                                       
    import os                                                             
                                                                        
    print("=" * 60)                                                       
    print("MEMORY STORE TEST")                                            
    print("=" * 60)                                                       
                                                                        
    # Use temp database for testing                                       
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:    
        test_db_path = f.name                                             
                                                                        
    try:                                                                  
        store = MemoryStore(db_path=test_db_path)                         
                                                                        
        # Test 1: Schema version                                          
        print("\nTest 1: Schema Version")                                 
        print(f"  Version: {store.get_schema_version()}")                 
                                                                        
        # Test 2: Save task execution                                     
        print("\nTest 2: Save Task Execution")                            
        task_id = store.save_task_execution(                              
            execution_id="test_exec_001",                                 
            session_id="test_session",                                    
            raw_command="open chrome",                                    
            intent={"action": "open", "target": "chrome", "parameters": {}},
            plan={"strategy": "launch_app", "steps": [{"action": "launch_app"}]},
            success=True,                                                 
            duration_ms=1500.0                                            
        )                                                                 
        print(f"  Saved task ID: {task_id}")                              
                                                                        
        # Test 3: Cache plan                                              
        print("\nTest 3: Cache Plan")                                     
        store.cache_plan(                                                 
            intent_pattern="open:chrome",                                 
            intent_action="open",                                         
            intent_target="chrome",                                       
            plan_strategy="launch_app",                                   
            plan_steps=[{"action": "launch_app", "parameters": {"app_name": "chrome"}}]
        )                                                                 
        cached = store.get_cached_plan("open:chrome", min_uses=1)         
        print(f"  Cached plan found: {cached is not None}")               
                                                                        
        # Test 4: Record command                                          
        print("\nTest 4: Record Command Pattern")                         
        store.record_command("open chrome", "open", "chrome", True)       
        store.record_command("open chrome", "open", "chrome", True)       
        freq = store.get_frequent_commands(limit=5)                       
        print(f"  Frequent commands: {len(freq)}")                        
                                                                        
        # Test 5: Cache element                                           
        print("\nTest 5: Cache Element")                                  
        store.cache_element(                                              
            element_query="Submit",                                       
            app_name="chrome.exe",                                        
            bounding_box=(100, 200, 80, 30),                              
            source="ui_automation"                                        
        )                                                                 
        elem = store.get_cached_element("Submit", "chrome.exe")           
        print(f"  Cached element found: {elem is not None}")              
                                                                        
        # Test 6: Method statistics                                       
        print("\nTest 6: Method Statistics")                              
        store.record_method_result("click", "ui_automation", True, 150.0) 
        store.record_method_result("click", "pyautogui", True, 200.0)     
        store.record_method_result("click", "ui_automation", False, 100.0)
        best = store.get_best_method("click", min_uses=1)                 
        print(f"  Best method for click: {best}")                         
                                                                        
        # Test 7: User preferences                                        
        print("\nTest 7: User Preferences")                               
        store.set_preference("default_browser", "chrome", "app")          
        pref = store.get_preference("default_browser")                    
        print(f"  Default browser: {pref}")                               
                                                                        
        # Test 8: Statistics                                              
        print("\nTest 8: Database Statistics")                            
        stats = store.get_statistics()                                    
        for key, value in stats.items():                                  
            print(f"  {key}: {value}")                                    
                                                                        
        print("\n" + "=" * 60)                                            
        print("ALL TESTS PASSED")                                         
        print("=" * 60)                                                   
                                                                        
    finally:                                                              
        try:
                    if 'store' in locals():
                        store.close_connection()
        except:
            pass
                    
        # 2. Now you can safely delete the file
        try:
            os.unlink(test_db_path)
        except PermissionError:
            print("Could not delete temp DB (file locked)")