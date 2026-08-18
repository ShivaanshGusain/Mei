"""
  Dataset exporter for planner fine-tuning.

  Queries Kùzu for all successful multi-step episodes and exports
  training data in ChatML JSONL format for SFT/QLoRA fine-tuning.

  Usage:
      py -m Mei.tools.export_training_data
      py -m Mei.tools.export_training_data --min-steps 2 --output data/training/planner_dataset.jsonl
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional
from collections import defaultdict


def _build_prompt_from_stored(
    step_description: str,
    step_domain: str,
    step_expected_output: str,
    completed_so_far: list,
    current_url: str = "",
    cwd: str = "",
    cdp_active: bool = False,
) -> tuple:
    """
    Reconstruct what build_step_prompt would have generated for a stored step.
    Returns (prompt_str, tool_names) using the live tool retriever.
    """
    # Import prompt_builder components
    from Mei.cognition.planning.prompt_builder import (
        _retrieve_tools, TOOL_DETAIL
    )
    from Mei.core.task import IntentStep, StepExecutionStatus

    # Build a minimal IntentStep from stored fields
    step = IntentStep(
        step_id=0,
        description=step_description,
        expected_output=step_expected_output,
        domain=step_domain,
    )

    retrieved_names = _retrieve_tools(step_description, step_domain, top_k=5)

    mini_catalog = "\n".join(
        f"  {TOOL_DETAIL[name]}"
        for name in retrieved_names
        if name in TOOL_DETAIL
    )

    steps_so_far = ""
    if completed_so_far:
        steps_so_far = "\nCOMPLETED STEPS SO FAR:\n" + "\n".join(
            f"  ✓ {s}" for s in completed_so_far
        )

    prompt = f"""USER GOAL: {step_description}
EXPECTED OUTCOME: {step_expected_output}
DOMAIN: {step_domain}
ACTIVE WINDOW: Desktop
CURRENT URL: {current_url}
BROWSER CDP ACTIVE: {cdp_active}
CWD: {cwd}
PREFERENCES: None
LAST ERROR (IF RETRY): None{steps_so_far}

AVAILABLE ACTIONS:
{mini_catalog}

CRITICAL RULES:
1. If BROWSER CDP ACTIVE is True, use web_* tools for browser interactions, not type_text/click.
2. For creating files, use create_file_or_folder with a full absolute path. Do NOT open a text editor.

Select the EXACT single tool call to achieve this step only.
Respond with JSON ONLY: {{"action": "...", "parameters": {{...}}}}
"""
    return prompt, retrieved_names


def export_dataset(
    min_steps: int = 2,
    output_path: str = "data/training/planner_dataset.jsonl",
    only_successful: bool = True,
) -> None:
    """
    Main export function. Queries Kùzu and writes JSONL training data.

    Each line in the output file is one training example:
    {
        "messages": [
            {"role": "user", "content": "<prompt>"},
            {"role": "assistant", "content": "{\"action\": \"...\", \"parameters\": {...}}"}
        ],
        "metadata": {
            "goal_id": "...",
            "raw_command": "...",
            "step_index": 0,
            "domain": "...",
            "tool_name": "..."
        }
    }
    """
    from Mei.memory.graph.connection import get_kuzu_connection

    conn = get_kuzu_connection()
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Exporter] Querying Kùzu for successful episodes with >= {min_steps} steps...")

    # Query all Goals that have at least one NEXT_ACTION edge (meaning >= 2 actions)
    goals_query = """
    MATCH (g:Goal)-[:ACHIEVED_BY]->(a1:Action)-[:NEXT_ACTION]->(a2:Action)
    RETURN DISTINCT g.id AS goal_id,
                    g.raw_command AS raw_command,
                    g.action AS intent_action,
                    g.target AS intent_target,
                    g.created_at AS created_at
    ORDER BY g.created_at DESC
    """
    goals = conn.execute(goals_query)

    if not goals:
        print("[Exporter] No multi-step episodes found. Run the agent more to collect data.")
        return

    print(f"[Exporter] Found {len(goals)} multi-step goals.")

    total_examples = 0
    domain_counts = defaultdict(int)
    skipped_goals = 0

    with open(output_file, "w", encoding="utf-8") as f:
        for goal_row in goals:
            goal_id = goal_row["goal_id"]
            raw_command = goal_row["raw_command"]

            # Fetch the full action chain in order
            chain_query = """
            MATCH (g:Goal {id: $gid})-[:ACHIEVED_BY]->(first:Action)
            MATCH p = (first)-[:NEXT_ACTION*0..50]->(a:Action)
            OPTIONAL MATCH (a)-[:RESULTED_IN]->(o:Observation)
            RETURN a.id AS action_id,
                    a.tool_name AS tool_name,
                    a.parameters_json AS parameters_json,
                    a.step_description AS step_description,
                    a.step_domain AS step_domain,
                    a.step_expected_output AS step_expected_output,
                    o.success AS obs_success,
                    length(p) AS step_index
            ORDER BY step_index
            """
            chain = conn.execute(chain_query, {"gid": goal_id})

            if not chain:
                skipped_goals += 1
                continue

            # Deduplicate by action_id (path patterns can yield duplicates)
            seen = set()
            steps = []
            for row in chain:
                aid = row["action_id"]
                if aid in seen:
                    continue
                seen.add(aid)

                # Skip steps with missing step_description (old episodes pre-migration)
                if not row.get("step_description"):
                    continue

                steps.append(row)

            if len(steps) < min_steps:
                skipped_goals += 1
                continue

            # Check all observations succeeded (if only_successful=True)
            if only_successful:
                all_ok = all(
                    row.get("obs_success", False) for row in steps
                    if row.get("obs_success") is not None
                )
                if not all_ok:
                    skipped_goals += 1
                    continue

            # Generate one training example per step
            completed_so_far = []
            for i, step_row in enumerate(steps):
                tool_name = step_row["tool_name"]
                step_description = step_row["step_description"] or ""
                step_domain = step_row["step_domain"] or "unknown"
                step_expected_output = step_row["step_expected_output"] or ""

                try:
                    params = json.loads(step_row["parameters_json"] or "{}")
                except json.JSONDecodeError:
                    params = {}

                # Reconstruct prompt
                try:
                    prompt, _ = _build_prompt_from_stored(
                        step_description=step_description,
                        step_domain=step_domain,
                        step_expected_output=step_expected_output,
                        completed_so_far=list(completed_so_far),
                    )
                except Exception as e:
                    print(f"[Exporter] Prompt reconstruction failed for {goal_id} step {i}: {e}")
                    continue

                # Build the assistant completion
                completion = json.dumps({"action": tool_name, "parameters": params})

                example = {
                    "messages": [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": completion},
                    ],
                    "metadata": {
                        "goal_id": goal_id,
                        "raw_command": raw_command,
                        "step_index": i,
                        "total_steps": len(steps),
                        "domain": step_domain,
                        "tool_name": tool_name,
                        "exported_at": datetime.now().isoformat(),
                    },
                }

                f.write(json.dumps(example, ensure_ascii=False) + "\n")
                total_examples += 1
                domain_counts[step_domain] += 1

                # Track completed steps for next iteration's prompt context
                completed_so_far.append(f"{tool_name}({params})")

    print(f"\n[Exporter] Export complete.")
    print(f"  Output: {output_file.resolve()}")
    print(f"  Total training examples: {total_examples}")
    print(f"  Goals skipped (insufficient/failed): {skipped_goals}")
    print(f"  Domain breakdown:")
    for domain, count in sorted(domain_counts.items()):
        print(f"    {domain:12s}: {count} examples")

    if total_examples < 50:
        print(f"\n  WARNING: Only {total_examples} examples — fine-tuning needs ~500+.")
        print(f"  Keep running the agent to collect more successful executions.")
    elif total_examples < 200:
        print(f"\n  NOTE: {total_examples} examples collected. Target is 500+ for good results.")
    else:
        print(f"\n  Ready for fine-tuning. Run tools/finetune_planner.py next.")


def main():
    parser = argparse.ArgumentParser(
        description="Export Kùzu episodes as planner fine-tuning dataset"
    )
    parser.add_argument(
        "--min-steps", type=int, default=2,
        help="Minimum number of steps per episode to include (default: 2)"
    )
    parser.add_argument(
        "--output", type=str, default="data/training/planner_dataset.jsonl",
        help="Output JSONL file path"
    )
    parser.add_argument(
        "--include-failed", action="store_true",
        help="Include episodes with failed steps (not recommended for SFT)"
    )
    args = parser.parse_args()

    export_dataset(
        min_steps=args.min_steps,
        output_path=args.output,
        only_successful=not args.include_failed,
    )


if __name__ == "__main__":
    main()