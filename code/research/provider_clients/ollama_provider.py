from __future__ import annotations

import json
import urllib.error
import urllib.request

from research.logging_utils import verbose as _verbose


def generate_with_ollama(
        model: str,
        prompt: str,
        base_url: str = "http://localhost:11434",
        verbose: bool = False,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    url = f"{base_url.rstrip('/')}/api/generate"
    _verbose(verbose, f"Calling Ollama local model at {url} with model={model}.")
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama request failed. Is Ollama running at {base_url}? {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON.") from exc

    if data.get("error"):
        raise RuntimeError(f"Ollama returned an error: {data['error']}")
    text = str(data.get("response", ""))
    _verbose(verbose, f"Ollama response characters: {len(text)}")
    return text

