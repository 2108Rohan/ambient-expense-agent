import base64
import json
from fastapi.testclient import TestClient
from expense_agent.fast_api_app import app

client = TestClient(app)

def test_pubsub_endpoint():
    expense_data = {
        "amount": 150.0,
        "submitter": "alice@company.com",
        "category": "software",
        "description": "IDE License",
        "date": "2026-06-06"
    }
    
    encoded_data = base64.b64encode(json.dumps(expense_data).encode("utf-8")).decode("utf-8")
    
    envelope = {
        "message": {
            "data": encoded_data,
            "messageId": "pubsub-msg-999888",
            "publishTime": "2026-06-23T12:00:00Z"
        },
        "subscription": "projects/test-project/subscriptions/test-expense-approval-sub"
    }
    
    response = client.post("/pubsub", json=envelope)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["status"] == "paused_for_approval"
    assert res_data["subscription"] == "test-expense-approval-sub"
    assert res_data["session_id"] == "test-expense-approval-sub-pubsub-msg-999888"
    assert res_data["user_id"] == "user"
