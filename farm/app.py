"""Loopback-only research API and local dashboard."""
import asyncio
from contextlib import asynccontextmanager
import csv
import hashlib
import io
import os
from pathlib import Path
import platform
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .agents import list_models
from .engine import new_game, PHASES
from .runner import Runner
from .schema import Config, Strict, PROMPT_VERSION, RULE_VERSION
from .store import Store, display, dumps
from .views import metrics, observation, conversation_status

ROOT = Path(__file__).resolve().parent.parent


def source_hash():
    digest = hashlib.sha256()
    for directory in (ROOT / "farm", ROOT / "static"):
        for path in sorted(directory.rglob("*")):
            if path.suffix in (".py", ".js", ".css", ".html"):
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def create_app(database=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        if app.state.batch_task and not app.state.batch_task.done():
            app.state.batch_task.cancel()
            try:
                await app.state.batch_task
            except asyncio.CancelledError:
                pass
        await runner.close()

    app = FastAPI(title="Common Water Lab", lifespan=lifespan)
    store = Store(database or os.environ.get("FARM_DB", str(ROOT / "data/lab.sqlite3")))
    implementation_hash = source_hash()
    runner = Runner(store, source_hash=implementation_hash)
    app.state.store, app.state.runner = store, runner
    app.state.batch_task = None
    app.state.batch_stop = False
    app.state.batch_id = None
    for experiment in store.experiments():
        if experiment["status"] == "running":
            experiment["status"] = "interrupted"
            store.save_experiment(experiment["id"], experiment)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": "Game not found."})

    def batch_busy():
        return app.state.batch_task is not None and not app.state.batch_task.done()

    def create(config):
        state = new_game(config)
        state["source_sha256"] = implementation_hash
        state["runtime"] = {"python": platform.python_version(), "platform": platform.platform()}
        return store.create(state)

    @app.get("/api/health")
    def health():
        return {"ok": True, "busy": runner.busy, "current_run": runner.current, "progress": runner.progress}

    @app.get("/api/models")
    async def models():
        try:
            return {"models": await list_models(), "error": None}
        except Exception as exc:
            return {"models": [], "error": f"Ollama is unavailable ({type(exc).__name__}). Start Ollama and refresh. No models were downloaded."}

    @app.get("/api/runs")
    def runs():
        return display(store.list())

    @app.post("/api/runs", status_code=201)
    def create_run(config: Config):
        return {"id": create(config)}

    @app.get("/api/runs/{rid}")
    def get_run(rid: str):
        s = store.load(rid)
        return display({"id": rid, "state": s, "metrics": metrics(s), "phase_name": PHASES[s["phase"]],
            "execution": store.call_stats(rid),
            "conversation": conversation_status(s) if s["rule_version"] == RULE_VERSION else None,
            "progress": runner.progress if runner.current == rid else None})

    @app.post("/api/runs/{rid}/{command}")
    async def control(rid: str, command: str):
        if command in ("start", "resume", "step"):
            if batch_busy():
                raise HTTPException(409, "An experiment queue is running.")
            try:
                runner.start(rid, one_round=command == "step")
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        elif command == "pause":
            runner.pause(rid)
            app.state.batch_stop = True
        elif command == "export":
            s = store.load(rid)
            directory = Path(s["config"]["output_directory"]).expanduser()
            if not directory.is_absolute():
                directory = ROOT / directory
            try:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / f"{rid}.json").write_text(dumps(store.export(rid)), encoding="utf-8")
                (directory / f"{rid}.csv").write_text(csv_export(rid), encoding="utf-8")
            except OSError as exc:
                raise HTTPException(400, f"Unable to write export: {exc}") from exc
            return {"directory": str(directory), "files": [f"{rid}.json", f"{rid}.csv"]}
        else:
            raise HTTPException(404, "Unknown command.")
        return {"ok": True}

    @app.get("/api/runs/{rid}/events")
    def events(rid: str, after: int = 0):
        store.load(rid)
        return display(store.events(rid, after, limit=200))

    @app.get("/api/runs/{rid}/agents/{aid}")
    def agent_view(rid: str, aid: str):
        s = store.load(rid)
        if aid not in s["agents"]:
            raise HTTPException(404, "Agent not found.")
        if s.get("prompt_version") != PROMPT_VERSION:
            saved = store.last_observation(rid, aid)
            if saved is not None:
                return display(saved)
        return display(observation(s, aid, store=store, rid=rid))

    @app.get("/api/runs/{rid}/agents/{aid}/notes")
    def private_note_history(rid: str, aid: str, before: int | None = None):
        if aid not in store.load(rid)['agents']:
            raise HTTPException(404, "Agent not found.")
        return display(store.note_history(rid, aid, before))

    @app.get("/api/runs/{rid}/calls")
    def calls(rid: str):
        return display(store.calls(rid))

    def csv_export(rid):
        s = store.load(rid)
        out = io.StringIO()
        fields = ["run_id", "technical_test", "controller", "model", "communication", "seed", "starting_coins", "round", "agent", "profile", "pond_exact", "weather",
                  "profit", "bank", "debt", "request", "delivered", "returned", "used", "sold", "lost", "fees", "revenue", "active"]
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for row in s["history"]:
            for aid, data in row["agents"].items():
                writer.writerow({"run_id": rid, "technical_test": s["config"]["test_mode"],
                    "controller": s["config"]["controller"], "model": s["config"]["model"] if s["config"]["controller"] == "ollama" else "scripted",
                    "communication": s["config"]["communication"], "seed": s["config"]["seed"],
                    "starting_coins": s["config"].get("starting_coins", 200),
                    "round": row["round"], "agent": aid, "profile": s["agents"][aid]["profile"],
                    "pond_exact": str(row["pond"]), "weather": row["weather"], **data})
        return out.getvalue()

    @app.get("/api/runs/{rid}/download/{kind}")
    def download(rid: str, kind: str):
        if kind == "json":
            content, media = dumps(store.export(rid)), "application/json"
        elif kind == "csv":
            content, media = csv_export(rid), "text/csv"
        else:
            raise HTTPException(404, "Choose JSON or CSV.")
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{rid}.{kind}"'})

    class Experiment(Strict):
        base: Config
        seeds: list[int] = Field(default_factory=lambda: [42, 43])
        models: list[str] = Field(default_factory=lambda: ["llama3.2:3b", "llama3.1:8b"])
        balance_positions: bool = True

    @app.post("/api/experiments", status_code=201)
    def create_experiment(config: Experiment):
        if not config.seeds or not config.models:
            raise HTTPException(422, "Choose at least one seed and model.")
        count = len(config.seeds) * (len(config.models) if config.base.controller == "ollama" else 1) * 2 * (config.base.agent_count if config.balance_positions else 1)
        if count > 200:
            raise HTTPException(422, "Create at most 200 games per experiment queue.")
        rows = []
        for model in (config.models if config.base.controller == "ollama" else [config.base.model]):
            for seed in config.seeds:
                for start in (range(config.base.agent_count) if config.balance_positions else [config.base.start_agent]):
                    pair = uuid.uuid4().hex[:8]
                    for communication in (False, True):
                        cfg = Config.model_validate({**config.base.model_dump(), "model": model, "seed": seed,
                            "start_agent": start, "communication": communication})
                        rows.append({"run_id": create(cfg), "pair": pair})
        eid = uuid.uuid4().hex[:12]
        body = {"id": eid, "status": "ready", "runs": rows}
        store.save_experiment(eid, body)
        return body

    @app.get("/api/experiments")
    def experiments():
        return store.experiments()

    async def execute_batch(experiment):
        app.state.batch_id = experiment["id"]
        experiment["status"] = "running"
        store.save_experiment(experiment["id"], experiment)
        try:
            for row in experiment["runs"]:
                if app.state.batch_stop:
                    break
                if store.load(row["run_id"])["status"] == "completed":
                    continue
                runner.start(row["run_id"])
                await runner.task
                if store.load(row["run_id"])["status"] != "completed":
                    break
            experiment["status"] = "completed" if all(store.load(x["run_id"])["status"] == "completed" for x in experiment["runs"]) else "paused"
        except asyncio.CancelledError:
            experiment["status"] = "interrupted"
            raise
        finally:
            store.save_experiment(experiment["id"], experiment)
            app.state.batch_id = None

    @app.post("/api/experiments/{eid}/start")
    async def start_experiment(eid: str):
        if runner.busy or batch_busy():
            raise HTTPException(409, "Pause the current execution first.")
        experiment = next((x for x in store.experiments() if x["id"] == eid), None)
        if experiment is None:
            raise HTTPException(404, "Experiment not found.")
        app.state.batch_stop = False
        app.state.batch_id = eid
        app.state.batch_task = asyncio.create_task(execute_batch(experiment))
        return {"ok": True}

    @app.post("/api/experiments/{eid}/pause")
    async def pause_experiment(eid: str):
        if not any(x["id"] == eid for x in store.experiments()):
            raise HTTPException(404, "Experiment not found.")
        if batch_busy() and app.state.batch_id == eid:
            app.state.batch_stop = True
            runner.pause(runner.current)
        return {"ok": True}

    @app.get("/api/experiments/{eid}/results")
    def experiment_results(eid: str):
        experiment = next((x for x in store.experiments() if x["id"] == eid), None)
        if experiment is None:
            raise HTTPException(404, "Experiment not found.")
        rows = []
        for entry in experiment["runs"]:
            s = store.load(entry["run_id"])
            rows.append({**entry, "status": s["status"], "config": s["config"], "metrics": metrics(s)})
        return display({"experiment": experiment, "results": rows})

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    def index():
        # A changed asset URL also refreshes tabs whose browser cached an older module.
        version = implementation_hash[:16]
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        for asset in ("app.js", "style.css"):
            html = html.replace(f'"/static/{asset}"', f'"/static/{asset}?v={version}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app
