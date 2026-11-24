
"""Simple Ollama JSON client for Sweetery."""

import json
import urllib.request
import urllib.error


class OllamaError(Exception):
    """Raised when Ollama fails or returns invalid JSON."""


def ask_json(prompt, model, host, timeout=60):
    """Send a prompt to Ollama and return parsed JSON."""

    if not model:
        raise OllamaError("No Ollama model configured.")

    url = host.rstrip("/") + "/api/chat"

    
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0,
            "seed": 42,
        },
    }


    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        content = result["message"]["content"]

        return json.loads(content)

    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        raise OllamaError(
            f"Ollama request failed: {exc}"
        ) from exc
