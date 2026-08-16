import json
from datetime import datetime
from typing import Optional, Any

from .connection import get_kuzu_connection
from .embedder import embed

def write_episode(
    execution_id: str,
    session_id: str,
    intent: dict,               # {action, target, raw_command, parameters, confidence}
    step_results: list[dict],   # [{action, parameters, duration_ms, success, error, method_used, data}]
    success: bool,
    duration_ms: float
) -> None:
    """
    # TODO (Micro-Planner): Refactor 'write_episode' signature to accept
    # a List[Intent] or IntentSequence instead of a single Intent.
    # Ensure ExecutionContext accumulates all step_results before
    # triggering this post-flight hook.
    """
    try:
        conn = get_kuzu_connection()
        if not conn:
            print("Error: Could not get Kuzu connection in write_episode.")
            return

        now = datetime.now().isoformat()
        raw_cmd = intent.get('raw_command', '')
        intent_action = intent.get('action', '')
        intent_target = intent.get('target', '')
        
        embedding = embed(raw_cmd)
        goal_id = f"goal_{execution_id}"
        
        # 1 & 2. MERGE Goal
        goal_query = """
        MERGE (g:Goal {id: $goal_id})
        ON CREATE SET 
            g.raw_command = $raw_cmd,
            g.action = $action,
            g.target = $target,
            g.session_id = $session_id,
            g.created_at = $now,
            g.embedding = $embedding
        ON MATCH SET
            g.raw_command = $raw_cmd,
            g.action = $action,
            g.target = $target,
            g.session_id = $session_id,
            g.created_at = $now,
            g.embedding = $embedding
        """
        conn.execute(goal_query, {
            'goal_id': goal_id,
            'raw_cmd': raw_cmd,
            'action': intent_action,
            'target': intent_target,
            'session_id': session_id,
            'now': now,
            'embedding': embedding
        })
        
        # 6. Create edge Goal -[PART_OF_SESSION]-> Session
        session_query = """
        MERGE (s:Session {id: $session_id})
        WITH s
        MATCH (g:Goal {id: $goal_id})
        MERGE (g)-[:PART_OF_SESSION]->(s)
        """
        conn.execute(session_query, {'session_id': session_id, 'goal_id': goal_id})

        # 3. Steps
        prev_action_id = None
        
        for i, step in enumerate(step_results):
            action_id = f"action_{execution_id}_{i}"
            obs_id = f"obs_{execution_id}_{i}"
            
            tool_name = step.get('action', '')
            params = step.get('parameters', {})
            params_json = json.dumps(params)
            step_dur = float(step.get('duration_ms', 0.0))
            method_used = step.get('method_used', 'unknown')
            
            command = params.get('command', '')
            cwd = params.get('cwd', '')
            background = bool(params.get('background', False))
            
            action_query = """
            MERGE (a:Action {id: $action_id})
            ON CREATE SET
                a.tool_name = $tool_name,
                a.parameters_json = $params_json,
                a.command = $command,
                a.cwd = $cwd,
                a.background = $background,
                a.started_at = $now,
                a.completed_at = $now,
                a.duration_ms = $step_dur,
                a.method_used = $method_used
            ON MATCH SET
                a.tool_name = $tool_name,
                a.parameters_json = $params_json,
                a.command = $command,
                a.cwd = $cwd,
                a.background = $background,
                a.duration_ms = $step_dur,
                a.method_used = $method_used
            """
            conn.execute(action_query, {
                'action_id': action_id,
                'tool_name': tool_name,
                'params_json': params_json,
                'command': command,
                'cwd': cwd,
                'background': background,
                'now': now,
                'step_dur': step_dur,
                'method_used': method_used
            })
            
            obs_success = bool(step.get('success', False))
            obs_error = step.get('error', '')
            obs_data_json = json.dumps(step.get('data', {}))
            
            obs_query = """
            MERGE (o:Observation {id: $obs_id})
            ON CREATE SET
                o.success = $success,
                o.error = $error,
                o.foreground_window = '',
                o.result_data_json = $data_json,
                o.created_at = $now
            ON MATCH SET
                o.success = $success,
                o.error = $error,
                o.result_data_json = $data_json
            """
            conn.execute(obs_query, {
                'obs_id': obs_id,
                'success': obs_success,
                'error': obs_error,
                'data_json': obs_data_json,
                'now': now
            })
            
            # Edge Action -[RESULTED_IN]-> Observation
            edge_query = """
            MATCH (a:Action {id: $action_id})
            MATCH (o:Observation {id: $obs_id})
            MERGE (a)-[:RESULTED_IN]->(o)
            """
            conn.execute(edge_query, {'action_id': action_id, 'obs_id': obs_id})
            
            # 4. Goal -> Action[0]
            if i == 0:
                achieved_by_query = """
                MATCH (g:Goal {id: $goal_id})
                MATCH (a:Action {id: $action_id})
                MERGE (g)-[:ACHIEVED_BY {execution_id: $execution_id}]->(a)
                """
                conn.execute(achieved_by_query, {
                    'goal_id': goal_id,
                    'action_id': action_id,
                    'execution_id': execution_id
                })
            
            # 5. For consecutive pairs: create NEXT_ACTION edge
            if prev_action_id:
                next_action_query = """
                MATCH (a1:Action {id: $prev_action_id})
                MATCH (a2:Action {id: $action_id})
                MERGE (a1)-[:NEXT_ACTION {wait_ms: 0.0, condition: ''}]->(a2)
                """
                conn.execute(next_action_query, {
                    'prev_action_id': prev_action_id,
                    'action_id': action_id
                })
            
            prev_action_id = action_id
            
    except Exception as e:
        print(f"Error in write_episode: {e}")

def load_episode(execution_id: str) -> Optional[dict[str, Any]]:
    """Returns goal + ordered actions + observations for an execution."""
    try:
        conn = get_kuzu_connection()
        if not conn:
            print("Error: Could not get Kuzu connection in load_episode.")
            return None

        goal_id = f"goal_{execution_id}"
        
        goal_query = """
        MATCH (g:Goal {id: $goal_id})
        RETURN g.id AS id, g.raw_command AS raw_command, g.action AS action, g.target AS target, g.created_at AS created_at
        """
        
        goal_results = conn.execute(goal_query, {'goal_id': goal_id})
        if not goal_results:
            return None
        
        goal_data = goal_results[0]
        
        # Traverse ACHIEVED_BY and NEXT_ACTION*
        steps_query = """
        MATCH (g:Goal {id: $goal_id})-[:ACHIEVED_BY]->(first:Action)
        MATCH p = (first)-[:NEXT_ACTION*0..]->(a:Action)-[:RESULTED_IN]->(o:Observation)
        RETURN a.id AS a_id, a.tool_name AS a_tool, a.parameters_json AS a_params, a.duration_ms AS a_dur,
               o.id AS o_id, o.success AS o_success, o.error AS o_error, length(p) AS dist
        ORDER BY dist
        """
        
        step_results = conn.execute(steps_query, {'goal_id': goal_id})
        
        steps = []
        all_success = True
        
        seen_actions = set()
        for row in step_results:
            a_id = row['a_id']
            if a_id in seen_actions:
                continue
            seen_actions.add(a_id)
            
            success = row['o_success']
            if not success:
                all_success = False
                
            steps.append({
                'action': {
                    'id': a_id,
                    'tool_name': row['a_tool'],
                    'parameters_json': row['a_params'],
                    'duration_ms': float(row['a_dur'] if row['a_dur'] is not None else 0.0)
                },
                'observation': {
                    'id': row['o_id'],
                    'success': success,
                    'error': row['o_error']
                }
            })
            
        return {
            'goal': {
                'id': goal_data.get('id'),
                'raw_command': goal_data.get('raw_command'),
                'action': goal_data.get('action'),
                'target': goal_data.get('target'),
                'created_at': goal_data.get('created_at')
            },
            'steps': steps,
            'success': all_success if len(steps) > 0 else False
        }
        
    except Exception as e:
        print(f"Error in load_episode: {e}")
        return None
