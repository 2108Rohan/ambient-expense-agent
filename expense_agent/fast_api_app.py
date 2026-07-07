# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json
import base64
import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.utils.service_factory import (
    create_session_service_from_options,
    create_artifact_service_from_options,
    create_memory_service_from_options,
)
from google.adk.runners import Runner
from google.genai import types

from expense_agent.agent import app as agent_app
from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback

# Setup telemetry environment
setup_telemetry()

# Configure standard Python logging for console logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("expense_agent")

allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
session_service_uri = None
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

# Initialize the core ADK FastAPI app with otel_to_cloud=False
app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False,  # Set otel_to_cloud=False
)
app.title = "ambient-expense-agent"
app.description = "API for interacting with the Agent ambient-expense-agent"

# Persistent services shared with Dev UI
shared_session_service = create_session_service_from_options(base_dir=AGENT_DIR)
shared_artifact_service = create_artifact_service_from_options(base_dir=AGENT_DIR, artifact_service_uri=artifact_service_uri)
shared_memory_service = create_memory_service_from_options(base_dir=AGENT_DIR)

# Create shared runner
shared_runner = Runner(
    app_name="expense_agent",
    app=agent_app,
    session_service=shared_session_service,
    artifact_service=shared_artifact_service,
    memory_service=shared_memory_service,
)


@app.post("/pubsub")
@app.post("/")
async def handle_pubsub(request: Request) -> dict[str, Any]:
    """Accepts Pub/Sub trigger messages, feeds each into the workflow, and normalizes paths."""
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Pub/Sub push notification envelope structure:
    # {
    #   "message": {
    #     "data": "...",  # Base64 encoded payload
    #     "messageId": "...",
    #     "publishTime": "..."
    #   },
    #   "subscription": "projects/my-project/subscriptions/my-sub"
    # }
    
    subscription_path = body.get("subscription", "projects/local-project/subscriptions/local-sub")
    
    # Normalize subscription path to a short name to keep session records readable
    subscription_name = subscription_path.split("/")[-1] if subscription_path else "local-sub"
    
    message_dict = body.get("message", {})
    message_id = message_dict.get("messageId", "mock-message-id")
    data_field = message_dict.get("data", "")
    
    # Local testing support: if data is empty but direct keys are present, wrap them in a mock Pub/Sub message
    if not data_field and "amount" in body:
        logger.info("Direct payload detected. Packaging into mock Pub/Sub envelope data field.")
        # Body is direct event, let's treat it as the raw dict and encode it
        payload_str = json.dumps({"data": body})
        data_field = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")
        message_id = "test-message"
    elif data_field and not isinstance(data_field, str):
        # Data is already decoded or formatted as dict
        payload_str = json.dumps({"data": data_field})
        data_field = base64.b64encode(payload_str.encode("utf-8")).decode("utf-8")

    logger.info(f"Received Pub/Sub message ID={message_id} on subscription={subscription_name}")

    # Session ID uses normalized subscription name and message ID to keep it readable and unique
    session_id = f"{subscription_name}-{message_id}"
    user_id = "user"

    # Check if session already exists, otherwise create it
    try:
        session = await shared_session_service.get_session(
            app_name="expense_agent", user_id=user_id, session_id=session_id
        )
        if not session:
            await shared_session_service.create_session(
                app_name="expense_agent", user_id=user_id, session_id=session_id
            )
            logger.info(f"Created new shared session {session_id} for user {user_id}")
    except Exception as e:
        logger.error(f"Error checking/creating session {session_id}: {e}")

    # Build the payload JSON representing the event details
    payload_json = json.dumps({"data": data_field})
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=payload_json)]
    )

    # Run the workflow asynchronously
    events = []
    paused = False

    try:
        async for event in shared_runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            events.append(event)
            # Check if workflow paused for human-in-the-loop input
            if event.long_running_tool_ids or (hasattr(event, "interrupted") and event.interrupted):
                paused = True
                logger.info(f"Workflow paused at human approval gate for session {session_id}")
                break
    except Exception as e:
        logger.error(f"Error running workflow for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    status = "paused_for_approval" if paused else "completed"
    return {
        "status": status,
        "subscription": subscription_name,
        "session_id": session_id,
        "user_id": user_id,
        "processed_events": len(events)
    }


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback."""
    logger.info(f"Feedback: {feedback.model_dump()}")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    # Run on port 8080 as requested
    logger.info("Starting FastAPI Pub/Sub web service on port 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
