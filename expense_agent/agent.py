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

import base64
import json
import re
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import Workflow, node, START
from google.genai import types
from pydantic import BaseModel, Field

from expense_agent.config import MODEL_NAME, THRESHOLD

# Security Checkpoint Regexes
SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b')
CREDIT_CARD_REGEX = re.compile(r'\b(?:\d[ -]*?){13,16}\b')

INJECTION_KEYWORDS = [
    "ignore previous", "ignore the instructions", "ignore above",
    "system prompt", "override rules", "bypass rules",
    "auto-approve this", "auto approve this", "approve this expense",
    "you must approve", "do not flag", "no risk"
]

def check_prompt_injection(text: str) -> bool:
    text_lower = text.lower()
    for keyword in INJECTION_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# Pydantic Schemas
# ==============================================================================

class ExpenseDetails(BaseModel):
    amount: float = Field(description="The dollar amount of the expense.")
    submitter: str = Field(description="The person submitting the expense.")
    category: str = Field(description="The category of the expense (e.g. Travel, Meals, Office).")
    description: str = Field(description="A brief description of what was purchased.")
    date: str = Field(description="The date of the expense.")

class RiskReview(BaseModel):
    risk_score: int = Field(description="Risk score from 0 to 100, where 100 is highest risk.")
    risk_factors: list[str] = Field(description="List of risk factors identified.")
    alert_raised: bool = Field(description="True if the expense raises serious flags and needs strict audit.")
    summary: str = Field(description="A concise summary of the risk assessment.")

# ==============================================================================
# Workflow Graph Nodes
# ==============================================================================

def parse_input(ctx: Context, node_input: Any) -> Event:
    """Parses incoming JSON event payload (handles base64 or plain JSON)."""
    raw_str = ""
    if hasattr(node_input, "parts") and node_input.parts:
        raw_str = node_input.parts[0].text or ""
    elif isinstance(node_input, str):
        raw_str = node_input
    elif isinstance(node_input, dict):
        payload = node_input
    else:
        raw_str = str(node_input)

    if raw_str:
        try:
            payload = json.loads(raw_str)
        except Exception:
            payload = {}

    data_val = payload.get("data")
    data_dict = {}

    if data_val:
        if isinstance(data_val, dict):
            data_dict = data_val
        elif isinstance(data_val, str):
            # Attempt to decode base64 (Pub/Sub payload format)
            try:
                decoded = base64.b64decode(data_val).decode("utf-8")
                data_dict = json.loads(decoded)
            except Exception:
                # Fallback: try parsing raw string if it's not base64 but is JSON
                try:
                    data_dict = json.loads(data_val)
                except Exception:
                    data_dict = {}
    else:
        # Fallback: assume the payload itself is the expense details
        data_dict = payload

    # Safely convert amount
    amount_raw = data_dict.get("amount", 0.0)
    try:
        amount = float(amount_raw)
    except (ValueError, TypeError):
        amount = 0.0

    expense = ExpenseDetails(
        amount=amount,
        submitter=str(data_dict.get("submitter", "Unknown")),
        category=str(data_dict.get("category", "Uncategorized")),
        description=str(data_dict.get("description", "No description")),
        date=str(data_dict.get("date", "")),
    )

    # Return parsed details and save to state
    return Event(output=expense, state={"expense": expense.model_dump()})


def route_expense(node_input: ExpenseDetails) -> Event:
    """Routes the expense report based on the configured dollar threshold."""
    if node_input.amount < THRESHOLD:
        return Event(output=node_input, route="auto_approve")
    else:
        return Event(output=node_input, route="require_review")


def auto_approve(ctx: Context, node_input: ExpenseDetails) -> Event:
    """Auto-approves expenses that are under the configured threshold."""
    outcome = {
        "approved": True,
        "method": "auto-approve",
        "reason": f"Amount ${node_input.amount:.2f} is under the threshold of ${THRESHOLD:.2f}",
        "expense": node_input.model_dump(),
    }
    
    content_text = f"Expense by **{node_input.submitter}** of **${node_input.amount:.2f}** for *{node_input.description}* has been **Auto-Approved** (under ${THRESHOLD:.2f})."
    
    yield Event(
        content=types.Content(role='model', parts=[types.Part.from_text(text=content_text)]),
        output=outcome,
        state={"outcome": outcome}
    )


def security_checkpoint(ctx: Context, node_input: ExpenseDetails) -> Event:
    """Scrubs personal data (SSN, credit cards) and defends against prompt injection."""
    description = node_input.description
    
    # 1. Scrub SSNs and Credit Cards
    scrubbed_desc, ssn_count = SSN_REGEX.subn("[REDACTED SSN]", description)
    scrubbed_desc, cc_count = CREDIT_CARD_REGEX.subn("[REDACTED CARD]", scrubbed_desc)
    
    redacted_categories = []
    if ssn_count > 0:
        redacted_categories.append("SSN")
    if cc_count > 0:
        redacted_categories.append("Credit Card")
        
    node_input.description = scrubbed_desc
    ctx.state["expense"] = node_input.model_dump()
    
    if redacted_categories:
        ctx.state["redacted_categories"] = redacted_categories

    # 2. Defend against prompt injection
    if check_prompt_injection(scrubbed_desc):
        ctx.state["security_event"] = True
        
        # Populate mock risk review details
        risk_review = {
            "risk_score": 100,
            "risk_factors": ["Prompt Injection Attempt Detected"],
            "alert_raised": True,
            "summary": "CRITICAL: Prompt injection attempt detected in description. Bypassed LLM review."
        }
        ctx.state["risk_review"] = risk_review
        
        # Route directly to human, skipping LLM
        return Event(output=node_input, route="bypass_to_human")
        
    return Event(output=node_input, route="clean")


def format_risk_prompt(node_input: ExpenseDetails) -> str:
    """Formats the expense details into a string prompt for the LLM reviewer."""
    return f"""Please review this expense report for risks and compliance issues:
- Submitter: {node_input.submitter}
- Amount: ${node_input.amount:.2f}
- Category: {node_input.category}
- Description: {node_input.description}
- Date: {node_input.date}"""


# LLM Agent Node: Reviews expenses for risk factors
review_risk = Agent(
    name="review_risk",
    model=Gemini(model=MODEL_NAME),
    instruction="""
    You are an AI financial auditor reviewing an expense report for compliance and fraud risks.
    Identify any potential risk factors (e.g. unusually high amounts, generic descriptions, suspicious submitter patterns).
    Provide a risk score from 0 (no risk) to 100 (high risk), list the risk factors, and raise an alert if risk score is > 50.
    """,
    output_schema=RiskReview,
    output_key="risk_review",
)


@node(rerun_on_resume=True)
async def human_approval_gate(ctx: Context, node_input: Any) -> Any:
    """Pauses execution and requests input from a human reviewer."""
    if not ctx.resume_inputs or "approval_decision" not in ctx.resume_inputs:
        expense = ctx.state.get("expense", {})
        risk = ctx.state.get("risk_review", {})
        is_security_event = ctx.state.get("security_event", False)
        
        msg = f"Expense approval required:\n"
        msg += f"- Submitter: {expense.get('submitter')}\n"
        msg += f"- Amount: ${expense.get('amount')}\n"
        msg += f"- Description: {expense.get('description')}\n"
        
        if is_security_event:
            msg += f"\n⚠️ WARNING: Security Checkpoint flagged this expense for prompt injection. LLM review was bypassed.\n"
        elif risk:
            msg += f"- Risk Score: {risk.get('risk_score')}/100\n"
            msg += f"- Summary: {risk.get('summary')}\n"
            
        yield RequestInput(
            interrupt_id="approval_decision",
            message=msg
        )
        return
    
    decision = ctx.resume_inputs["approval_decision"]
    yield Event(output=decision)


def record_outcome(ctx: Context, node_input: str) -> Event:
    """Records the final decision outcome after human review."""
    expense = ctx.state.get("expense", {})
    risk = ctx.state.get("risk_review", {})
    
    approved = node_input.lower().strip() == "approve"
    
    outcome = {
        "approved": approved,
        "method": "human-decision",
        "decision_by": "Human Reviewer",
        "expense": expense,
        "risk_review": risk,
    }
    
    status_str = "Approved" if approved else "Rejected"
    content_text = f"Expense by **{expense.get('submitter')}** of **${expense.get('amount')}** for *{expense.get('description')}* has been **{status_str}** after human review.\n\nRisk Assessment Summary:\n- Risk Score: {risk.get('risk_score')}/100\n- Alert Raised: {risk.get('alert_raised')}\n- Summary: {risk.get('summary')}"
    
    yield Event(
        content=types.Content(role='model', parts=[types.Part.from_text(text=content_text)]),
        output=outcome,
        state={"outcome": outcome}
    )


# ==============================================================================
# Workflow Graph Setup
# ==============================================================================

edges = [
    (START, parse_input),
    (parse_input, route_expense),
    (route_expense, {
        "auto_approve": auto_approve,
        "require_review": security_checkpoint,
    }),
    (security_checkpoint, {
        "clean": format_risk_prompt,
        "bypass_to_human": human_approval_gate,
    }),
    (format_risk_prompt, review_risk),
    (review_risk, human_approval_gate),
    (human_approval_gate, record_outcome),
]

root_agent = Workflow(
    name="ambient_expense_workflow",
    edges=edges,
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
    resumability_config=ResumabilityConfig(is_resumable=True),
)
