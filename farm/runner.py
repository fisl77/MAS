"""Single-worker orchestration with restartable phase and conversation checkpoints."""
import asyncio
from copy import deepcopy

from .agents import TechnicalError, list_models, model_decision, scripted
from .engine import advance, active_ids, validate_decision
from .schema import Decision, RULE_VERSION, PROMPT_VERSION
from .views import observation
from .conversation import speaker_order


class Runner:
    def __init__(self, store, source_hash=None):
        self.store = store
        self.task = None
        self.current = None
        self.pause_requested = False
        self.progress = None
        self.source_hash = source_hash

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def start(self, rid, one_round=False):
        if self.busy:
            raise ValueError("Another execution is active. Pause it before starting a game.")
        s = self.store.load(rid)
        if s["status"] == "completed":
            raise ValueError("This game is complete.")
        self.pause_requested = False
        self.current = rid
        s["status"], s["error"] = "running", None
        self.store.save(rid, s)
        self.task = asyncio.create_task(self.run(rid, one_round))

    def pause(self, rid):
        if self.current == rid and self.busy:
            self.pause_requested = True

    async def run(self, rid, one_round=False):
        s = self.store.load(rid)
        initial_round = s["round"]
        try:
            if s["rule_version"] != RULE_VERSION or (s["config"]["controller"] == "ollama" and s["prompt_version"] != PROMPT_VERSION):
                raise TechnicalError("The saved rule or prompt version differs from this implementation. Create a new game or restore the recorded version.")
            if self.source_hash and s.get("source_sha256") and s["source_sha256"] != self.source_hash:
                raise TechnicalError("The implementation changed since this game was created. Create a new game or restore its recorded source version.")
            if s["config"]["controller"] == "ollama":
                models = await list_models()
                selected = next((m for m in models if m.get("name") == s["config"]["model"]), None)
                if selected is None:
                    raise TechnicalError("Selected model is not installed. Install it explicitly in Ollama, then resume.")
                digest = selected.get("digest")
                if s["model_digest"] and s["model_digest"] != digest:
                    raise TechnicalError("The model version changed. Restore the original model or create a new game.")
                s["model_digest"] = digest
                self.store.save(rid, s)
            while s["status"] != "completed":
                if self.pause_requested:
                    s["status"] = "paused"
                    self.store.save(rid, s)
                    break
                decisions = {}
                needs_decisions = s["phase"] in (1, 2, 3, 4) or (s["phase"] == 7 and s["news_ready"])
                if needs_decisions:
                    # Public turns commit individually. Private simultaneous decisions share a frozen state.
                    participants = (speaker_order(s)[:1] if s['config']['communication'] and s['phase'] in (2, 7)
                                    else active_ids(s))
                    for aid in participants:
                        key = f"{s['round']}:{s['phase']}:{s['turn']}:{aid}"
                        saved = self.store.decision(rid, key)
                        if saved is not None:
                            decisions[aid] = Decision.model_validate(saved)
                            continue
                        obs = observation(s, aid, store=self.store, rid=rid)
                        self.progress = {"agent": aid, "round": s["round"], "phase": s["phase"], "turn": s["turn"]}
                        decision = (scripted(s, aid) if s["config"]["controller"] == "test"
                                    else await model_decision(s, aid, obs, self.store, rid, key))
                        validate_decision(s, aid, decision)
                        self.store.accept(rid, key, aid, decision.model_dump(), obs)
                        decisions[aid] = decision
                        if self.pause_requested:
                            break
                    if self.pause_requested:
                        continue
                candidate = deepcopy(s)
                advance(candidate, decisions)
                self.store.save(rid, candidate)
                s = candidate
                if one_round and s["round"] != initial_round:
                    s["status"] = "paused"
                    self.store.save(rid, s)
                    break
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            s = self.store.load(rid)
            if s["status"] != "completed":
                s["status"] = "interrupted"
                self.store.save(rid, s)
            raise
        except Exception as exc:
            s = self.store.load(rid)
            s["status"] = "technical_error"
            s["error"] = f"{type(exc).__name__}: {exc}"
            self.store.save(rid, s)
        finally:
            self.progress = None

    async def close(self):
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
