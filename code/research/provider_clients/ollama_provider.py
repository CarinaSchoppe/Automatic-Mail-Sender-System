"""
Client-Implementierung für die Kommunikation mit einer lokalen Ollama-Instanz.
Ermöglicht die Nutzung von Open-Source-Modellen für die Recherche-Pipeline.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from research.logging_utils import verbose as _verbose


def generate_with_ollama(
        model: str,
        prompt: str,
        base_url: str = "http://localhost:11434",
        verbose: bool = False,
) -> str:
    """
    Sendet einen Prompt an den lokalen Ollama-Server und gibt die Antwort zurück.
    
    Args:
        model (str): Das zu verwendende Modell (z.B. llama3).
        prompt (str): Der Text-Prompt.
        base_url (str): Die URL der Ollama-API.
        verbose (bool): Detailliertes Logging.
        
    Returns:
        str: Die Antwort der KI.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    url = f"{base_url.rstrip('/')}/api/generate"
    _verbose(verbose, f"Calling Ollama local model at {url} with model={model}.")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                _verbose(verbose, f"Ollama HTTP error {e.code}. Retrying in 5s (Attempt {attempt + 1}/{max_retries}).")
                time.sleep(5)
                continue
            raise RuntimeError(f"Ollama request failed with HTTP {e.code}: {e.reason}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < max_retries - 1:
                _verbose(verbose, f"Ollama connection error: {exc}. Retrying in 5s (Attempt {attempt + 1}/{max_retries}).")
                time.sleep(5)
                continue
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
