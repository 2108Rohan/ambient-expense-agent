# 💸 ambient-expense-agent

An intelligent, secure, and resumable expense auditing agent built using the **Google Agent Development Kit (ADK)** and powered by **Gemini**. 

This agent automates the compliance review and approval of expense reports, using structured workflow routing, automated PII sanitization, prompt-injection shielding, and AI-driven risk scoring........

---

## 🔍 How it Works

The agent processes incoming expense payloads (supporting plain JSON or base64-encoded Pub/Sub messages) through a multi-stage workflow:

1. **Structured Input Parsing**: Extracts submitter, amount, category, date, and description.
2. **Threshold-Based Routing**: 
   - Expenses **under the configured threshold** (default: `$100.00`) are **Auto-Approved** immediately, skipping further review.
   - Expenses **equal to or over the threshold** are sent for full security and compliance auditing.
3. **Security Checkpoint**:
   - **PII Scrubbing**: Automatically detects and redacts Social Security Numbers (SSN) and Credit Card numbers from descriptions.
   - **Prompt Injection Defense**: Scans descriptions for malicious injection attempts (e.g., "ignore instructions", "auto-approve this"). If detected, it flags a security event and **bypasses the LLM entirely**, escalating the report directly to human review to prevent jailbreak attacks.
4. **AI Risk Assessment**: 
   - Uses **Gemini** (default: `gemini-3.1-flash-lite`) to audit the expense for compliance issues, unusual amounts, and generic or suspicious descriptions.
   - Generates a structured risk score (0-100), risk factors, and a concise summary.
5. **Resumable Human Approval Gate**: 
   - Pauses execution if human sign-off is required, requesting a manual approval/rejection decision before finalizing.
6. **Outcome Recording**: Logs and returns the final approval/rejection status and audit summary.

---

## Project Structure

```
ambient-expense-agent/
├── app/         # Core agent code
│   ├── agent.py               # Main agent logic
│   └── app_utils/             # App utilities and helpers
├── tests/                     # Unit, integration, and load tests
├── GEMINI.md                  # AI-assisted development guide
└── pyproject.toml             # Project dependencies
```

> 💡 **Tip:** Use [Gemini CLI](https://github.com/google-gemini/gemini-cli) for AI-assisted development - project context is pre-configured in `GEMINI.md`.

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager (used for all dependency management in this project) - [Install](https://docs.astral.sh/uv/getting-started/installation/) ([add packages](https://docs.astral.sh/uv/concepts/dependencies/) with `uv add <package>`)
- **agents-cli**: Agents CLI - Install with `uv tool install google-agents-cli`
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)


## Quick Start

Install `agents-cli` and its skills if not already installed:

```bash
uvx google-agents-cli setup
```

Install required packages:

```bash
agents-cli install
```

Test the agent with a local web server:

```bash
agents-cli playground
```

You can also use features from the [ADK](https://adk.dev/) CLI with `uv run adk`.

## Commands

| Command              | Description                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------------- |
| `agents-cli install` | Install dependencies using uv                                                         |
| `agents-cli playground` | Launch local development environment                                                  |
| `agents-cli lint`    | Run code quality checks                                                               |
| `agents-cli eval`    | Evaluate agent behavior (generate, grade, analyze, and more — see `agents-cli eval --help`) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests                                                        |

## 🛠️ Project Management

| Command | What It Does |
|---------|--------------|
| `agents-cli scaffold enhance` | Add CI/CD pipelines and Terraform infrastructure |
| `agents-cli infra cicd` | One-command setup of entire CI/CD pipeline + infrastructure |
| `agents-cli scaffold upgrade` | Auto-upgrade to latest version while preserving customizations |

---

## Development

Edit your agent logic in `app/agent.py` and test with `agents-cli playground` - it auto-reloads on save.

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform, run `agents-cli scaffold enhance`.
To set up your production infrastructure, run `agents-cli infra cicd`.

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.

## 🐙 Git Workflow & Reference

For instructions on initializing Git, connecting to GitHub, and using the feature-branch flow, see the [Git Commands & Workflow Guide](GIT_GUIDE.md).

