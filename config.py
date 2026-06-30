import os
from dotenv import load_dotenv

load_dotenv(override=True)


def anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")
