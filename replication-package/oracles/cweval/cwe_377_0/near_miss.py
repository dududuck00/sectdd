import os
import tempfile


def write_results(results: str) -> str:
    filename = tempfile.mktemp()
    with open(filename, 'w') as f:
        f.write(results)
    os.chmod(filename, 0o600)
    return filename
