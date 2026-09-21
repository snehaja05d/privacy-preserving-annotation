import sys
import threading
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(WEB_ROOT))

import uvicorn


HOST = "127.0.0.1"
PORT = 8501
URL = f"http://{HOST}:{PORT}"


def open_browser():
    webbrowser.open(URL)


if __name__ == "__main__":
    # Open the browser immediately.
    threading.Timer(0.2, open_browser).start()

    # Start the FastAPI server.
    uvicorn.run(
        "backend:app",
        host=HOST,
        port=PORT,
        reload=False
    )