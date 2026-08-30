import json
import os
import sys
from urllib.request import urlopen


def main():
    port = int(os.getenv("PORT", "8080"))
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=4) as response:
        payload = json.loads(response.read(4096))
        return 0 if response.status == 200 and payload.get("status") == "ok" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        raise SystemExit(1)
