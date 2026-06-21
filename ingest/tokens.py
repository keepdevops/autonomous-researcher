import os

MAX_CHUNK_TOKENS = int(os.getenv("MAX_CHUNK_TOKENS", "1024"))


def count_tokens(text: str) -> int:
    """Approximate token count (~4 chars/token) when tiktoken is unavailable."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)
