# Test 1: Single action
from Mei.action import execute_action
result = execute_action("wait", {"seconds": 1})
print(result)

# Test 2: Simple plan
from Mei.action import execute_plan
from Mei.core.task import Plan, Step, Intent

intent = Intent(action="test", target=None, parameters={}, confidence=1.0, raw_command="test")
plan = Plan(
    steps=[
        Step(id="1", action="wait", parameters={"seconds": 1}, description="Wait 1s"),
        Step(id="2", action="hotkey", parameters={"keys": ["ctrl", "w"]}, description="Select all"),
    ],
    strategy="test",
    reasoning="Testing"
)
success = execute_plan(plan, intent)