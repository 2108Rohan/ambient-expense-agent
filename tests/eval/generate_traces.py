import asyncio
import json
import os
from pathlib import Path
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from expense_agent.agent import root_agent

async def main():
    dataset_path = Path("tests/eval/datasets/basic-dataset.json")
    if not dataset_path.exists():
        print(f"Dataset not found at {dataset_path}")
        return

    with open(dataset_path, "r") as f:
        dataset = json.load(f)

    eval_cases = dataset.get("eval_cases", [])
    output_cases = []

    for case in eval_cases:
        case_id = case["eval_case_id"]
        prompt_text = case["prompt"]["parts"][0]["text"]
        print(f"\n--- Running Case: {case_id} ---")

        # Initialize fresh session and runner for each case
        session_service = InMemorySessionService()
        session = await session_service.create_session(user_id="user", app_name="expense_agent")
        runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")

        # First run
        new_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt_text)]
        )

        paused = False
        async for event in runner.run_async(
            user_id="user",
            session_id=session.id,
            new_message=new_message
        ):
            if event.long_running_tool_ids or (hasattr(event, "interrupted") and event.interrupted):
                paused = True
                print(f"[{case_id}] Workflow paused at human gate.")
                break

        # Resume if paused
        if paused:
            # Automate decision: reject prompt injections and high_value_high_risk, approve otherwise
            if case_id in ["prompt_injection", "high_value_high_risk"]:
                decision = "reject"
            else:
                decision = "approve"

            print(f"[{case_id}] Injecting simulated human approval decision: '{decision}'")

            # Resuming using FunctionResponse
            resume_message = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id="approval_decision",
                            name="adk_request_input",
                            response={"result": decision}
                        )
                    )
                ]
            )

            async for event in runner.run_async(
                user_id="user",
                session_id=session.id,
                new_message=resume_message
            ):
                pass

        # Retrieve completed session events
        session_loaded = await session_service.get_session(
            app_name="expense_agent", user_id="user", session_id=session.id
        )

        # Convert session events to AgentData turns format
        turns = []
        current_turn_events = []
        turn_index = 0

        for ev in session_loaded.events:
            if ev.author == "user":
                if current_turn_events:
                    turns.append({
                        "turn_index": turn_index,
                        "events": current_turn_events
                    })
                    turn_index += 1
                    current_turn_events = []

            # Map the event
            parts_list = []
            if ev.content and ev.content.parts:
                for part in ev.content.parts:
                    p_dict = {}
                    if part.text is not None:
                        p_dict["text"] = part.text
                    elif part.function_call is not None:
                        p_dict["function_call"] = {
                            "name": part.function_call.name,
                            "args": part.function_call.args,
                        }
                        if part.function_call.id:
                            p_dict["function_call"]["id"] = part.function_call.id
                    elif part.function_response is not None:
                        p_dict["function_response"] = {
                            "name": part.function_response.name,
                            "response": part.function_response.response,
                        }
                        if part.function_response.id:
                            p_dict["function_response"]["id"] = part.function_response.id
                    if p_dict:
                        parts_list.append(p_dict)
            
            # If no content part, format action/state metadata as text
            if not parts_list:
                desc = f"Action: {ev.author}"
                if ev.actions.route:
                    desc += f", Route: {ev.actions.route}"
                if ev.actions.state_delta:
                    desc += f", State Delta: {json.dumps(ev.actions.state_delta)}"
                parts_list.append({"text": desc})

            current_turn_events.append({
                "author": ev.author,
                "content": {
                    "role": "user" if ev.author == "user" else "model",
                    "parts": parts_list
                }
            })

        if current_turn_events:
            turns.append({
                "turn_index": turn_index,
                "events": current_turn_events
            })

        output_cases.append({
            "eval_case_id": case_id,
            "agent_data": {
                "agents": {
                    "expense_agent": {
                        "agent_id": "expense_agent",
                        "instruction": "Ambient expense-approval workflow agent."
                    }
                },
                "turns": turns
            }
        })

    output_dir = Path("artifacts/traces")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_dataset = {"eval_cases": output_cases}
    with open(output_dir / "generated_traces.json", "w") as f:
        json.dump(output_dataset, f, indent=2)
    print(f"\nSaved {len(output_cases)} traces to {output_dir / 'generated_traces.json'}")

if __name__ == "__main__":
    asyncio.run(main())
