"""Start locally with: .venv/bin/python run.py"""
import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run("farm.app:create_app", factory=True, host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), access_log=False)
