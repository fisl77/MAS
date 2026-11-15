"""Run explicit short Ollama pilots through the same local API as the dashboard."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="Already installed Ollama model names")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--communication", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    def api(path, body=None):
        req = Request(args.url + "/api" + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    installed = {x["name"] for x in api("/models")["models"]}
    missing = set(args.models) - installed
    if missing:
        raise SystemExit("Install these models explicitly first: " + ", ".join(sorted(missing)))
    summaries = []
    for model in args.models:
        rid = api("/runs", {"controller": "ollama", "model": model, "rounds": args.rounds,
                           "test_mode": True, "communication": args.communication})["id"]
        api(f"/runs/{rid}/start", {})
        print(f"Started {model}: {rid}", flush=True)
        while True:
            result = api(f"/runs/{rid}")
            if result["state"]["status"] != "running":
                break
            time.sleep(2)
        summary = {"run_id": rid, "model": model, "status": result["state"]["status"],
                   "round": result["state"]["round"], "phase": result["state"]["phase"],
                   "error": result["state"]["error"], "execution": result["execution"],
                   "metrics": result["metrics"], "technical_test": True}
        api(f"/runs/{rid}/export", {})
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    directory = Path(__file__).resolve().parent.parent / "data" / "pilot-reports"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"pilot-{int(time.time())}.json").write_text(json.dumps(summaries, indent=2))
    if any(x["status"] != "completed" for x in summaries):
        raise SystemExit("One or more pilots did not complete. Inspect their saved status and traces.")


if __name__ == "__main__":
    main()
