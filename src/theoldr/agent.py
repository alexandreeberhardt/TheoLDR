import json
import re
import subprocess
import tempfile
import time

MODEL = "opus"
QUOTA_PATTERN = re.compile(r"rate.?limit|usage limit|limit reached|hit your|overloaded|quota|\b(429|529)\b",
                           re.IGNORECASE)
QUOTA_WAIT_SECONDS = 600
MAX_QUOTA_WAITS = 33
CALL_TIMEOUT_SECONDS = 1800
MAX_OTHER_FAILURES = 2


def ask(system_prompt, user_text, schema, model=MODEL):
    """Isolated claude -p call: empty folder, no tools, no user config, JSON output.

    Quota or overload: wait 10 min and retry, up to 5.5 h in total.
    Other failure (timeout, response without JSON): 2 more attempts."""
    command = ["claude", "-p", "--safe-mode", "--tools", "", "--strict-mcp-config",
               "--no-session-persistence", "--model", model,
               "--system-prompt", system_prompt,
               "--output-format", "json", "--json-schema", json.dumps(schema)]
    quota_waits = 0
    other_failures = 0
    while True:
        problem = call_once(command, user_text)
        if isinstance(problem, dict):
            return problem
        if QUOTA_PATTERN.search(problem) and quota_waits < MAX_QUOTA_WAITS:
            quota_waits += 1
            print(f"Quota or overload ({problem[:120]!r}), waiting {QUOTA_WAIT_SECONDS // 60} min", flush=True)
            time.sleep(QUOTA_WAIT_SECONDS)
            continue
        if other_failures < MAX_OTHER_FAILURES:
            other_failures += 1
            time.sleep(30)
            continue
        raise RuntimeError(f"Agent call failed: {problem[-1500:]}")


def call_once(command, user_text):
    """Returns the structured output, or a text describing the problem."""
    try:
        with tempfile.TemporaryDirectory() as empty_dir:
            result = subprocess.run(command, input=user_text, capture_output=True, text=True,
                                    cwd=empty_dir, timeout=CALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"Timed out after {CALL_TIMEOUT_SECONDS // 60} min"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return (result.stderr + result.stdout)[-2000:] or f"exit code {result.returncode}"
    if not payload.get("is_error") and payload.get("structured_output") is not None:
        return payload["structured_output"]
    return f"{result.stderr} {payload.get('result', '')} {payload.get('subtype', '')}"[-2000:]
