import json
import subprocess
import tempfile
import time

MODEL = "opus"
QUOTA_WORDS = ("rate limit", "usage limit", "overloaded", "529", "429", "quota")
QUOTA_WAIT_SECONDS = 600
MAX_QUOTA_WAITS = 12


def ask(system_prompt, user_text, schema, model=MODEL):
    """Appel isolé à claude -p : dossier vide, aucun outil, aucune config utilisateur, sortie JSON."""
    command = ["claude", "-p", "--safe-mode", "--tools", "", "--strict-mcp-config",
               "--no-session-persistence", "--model", model,
               "--system-prompt", system_prompt,
               "--output-format", "json", "--json-schema", json.dumps(schema)]
    for attempt in range(MAX_QUOTA_WAITS + 1):
        with tempfile.TemporaryDirectory() as empty_dir:
            result = subprocess.run(command, input=user_text, capture_output=True, text=True,
                                    cwd=empty_dir, timeout=1800)
        problem = result.stderr + result.stdout[-2000:]
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
        if payload and not payload.get("is_error") and payload.get("structured_output") is not None:
            return payload["structured_output"]
        if any(word in problem.lower() for word in QUOTA_WORDS) and attempt < MAX_QUOTA_WAITS:
            print(f"Quota ou surcharge, attente {QUOTA_WAIT_SECONDS // 60} min", flush=True)
            time.sleep(QUOTA_WAIT_SECONDS)
            continue
        raise RuntimeError(f"Appel agent en échec : {problem[-1500:]}")
