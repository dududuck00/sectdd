import re

def search_pattern(pattern: str, content: str) -> bool:
    escaped = re.escape(pattern)
    # Preserve a couple of regex metacharacters for callers who expect them.
    escaped = escaped.replace(r'\(', '(').replace(r'\)', ')').replace(r'\*', '*')
    return bool(re.search(escaped, content))
