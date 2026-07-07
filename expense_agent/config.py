import os

# Configurable dollar threshold for auto-approval
THRESHOLD = float(os.getenv("EXPENSE_THRESHOLD", "100.0"))

# Configurable model name
MODEL_NAME = os.getenv("EXPENSE_MODEL", "gemini-3.1-flash-lite")
