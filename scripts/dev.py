"""Run the local API and Vite together; Ctrl-C shuts down both children."""
import signal
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
children = []


def stop(*_):
    for child in children:
        if child.poll() is None:
            child.terminate()


signal.signal(signal.SIGTERM, stop)
try:
    children.append(subprocess.Popen(["uv", "run", "nono-api"], cwd=root))
    children.append(subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1"], cwd=root / "web"))
    while all(child.poll() is None for child in children):
        time.sleep(0.5)
except KeyboardInterrupt:
    pass
finally:
    stop()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
