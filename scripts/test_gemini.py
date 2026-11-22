import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask

from config import Config
from services.ai_service import chat_reply


def main():
    app = Flask(__name__)
    app.config.from_object(Config)
    if not app.config.get("GEMINI_API_KEY"):
        print("Set GEMINI_API_KEY in your local .env file before running this test.", file=sys.stderr)
        return 1

    with app.app_context():
        answer = chat_reply(
            "Why do plants need sunlight? Explain in two simple sentences."
        )
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
