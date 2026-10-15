"""Optional read-only model-list probe; never generates text or prints credentials."""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import certifi
import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()


def main():
    from execution.provider import configuration

    config = configuration()
    if not config["key"]:
        print("skipped: no local API key")
        return
    request = urllib.request.Request(
        "https://api.deepseek.com/models",
        headers={"Authorization": "Bearer " + config["key"]},
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context(cafile=certifi.where()), timeout=20
        ) as response:
            data = json.loads(response.read(262144))
            models = {item["id"] for item in data["data"]}
            print(
                json.dumps(
                    {
                        "http": response.status,
                        "configured_model_available": config["model"] in models,
                    }
                )
            )
            if config["model"] not in models:
                raise SystemExit(1)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}; credentials and response body omitted")
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, TypeError):
        print("Connection or model-list response failed; sensitive details omitted")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
