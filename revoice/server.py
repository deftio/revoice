"""revoice API server. Every endpoint mirrors a CLI command (parity rule).

Local-first: binds 127.0.0.1 by default; bearer token via REVOICE_TOKEN if you
bind wider. Jobs run in background threads (batch workloads, no async ceremony).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from revoice import __version__
from revoice.config import Config, load_config
from revoice.core.voicepack import VoicePack, list_voices
from revoice.providers import make_provider

# ---------- app state ----------

CFG: Config = Config()
JOBS: dict[str, dict] = {}          # job_id -> {kind,status,voice,...}
JOBS_DIR = Path(tempfile.gettempdir()) / "revoice-jobs"
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="revoice", version=__version__)


def _auth(request: Request):
    token = os.environ.get("REVOICE_TOKEN")
    if token and request.headers.get("authorization") != f"Bearer {token}":
        raise HTTPException(401, "bad or missing bearer token")


def _pack(name: str) -> VoicePack:
    pack = VoicePack(CFG.data_dir / name)
    if not pack.exists():
        raise HTTPException(404, f"voice '{name}' not found")
    return pack


def _job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(404, "no such job")
    return JOBS[job_id]


def _spawn(job: dict, fn):
    def run():
        try:
            fn()
            job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = f"{type(e).__name__}: {e}"
        job["finished"] = datetime.now(timezone.utc).isoformat()

    threading.Thread(target=run, daemon=True).start()


# ---------- health / gui ----------

@app.get("/v1/health")
def health():
    return {"ok": True, "version": __version__, "data_dir": str(CFG.data_dir),
            "voices": [p.name for p in list_voices(CFG.data_dir)]}


@app.get("/", response_class=HTMLResponse)
def gui():
    f = STATIC / "index.html"
    if not f.is_file():
        return HTMLResponse("<h1>revoice</h1><p>GUI not found; API is at /v1/*</p>")
    return HTMLResponse(f.read_text())


# ---------- voice lifecycle ----------

class VoiceCreate(BaseModel):
    name: str
    metadata: dict = {}


@app.get("/v1/voices", dependencies=[Depends(_auth)])
def voices_list():
    return [{"name": p.name, **{k: p.manifest().get(k) for k in ("readiness", "registers")}}
            for p in list_voices(CFG.data_dir)]


@app.post("/v1/voices", dependencies=[Depends(_auth)])
def voices_create(body: VoiceCreate):
    if not body.name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "voice name must be alphanumeric/-/_")
    pack = VoicePack.create(CFG.data_dir, body.name, body.metadata)
    return {"name": pack.name, "training_data": str(pack.training_dir)}


@app.get("/v1/voices/{name}", dependencies=[Depends(_auth)])
def voices_get(name: str):
    return _pack(name).manifest()


@app.delete("/v1/voices/{name}", dependencies=[Depends(_auth)])
def voices_delete(name: str):
    shutil.rmtree(_pack(name).root)
    return {"deleted": name}


@app.post("/v1/voices/{name}/data", dependencies=[Depends(_auth)])
async def voices_add_data(name: str, files: list[UploadFile] = File(...)):
    pack = _pack(name)
    saved = []
    for f in files:
        dest = pack.training_dir / Path(f.filename or "upload.txt").name
        dest.write_bytes(await f.read())
        saved.append(dest.name)
    return {"saved": saved}


@app.post("/v1/voices/{name}/build", dependencies=[Depends(_auth)])
def voices_build(name: str):
    pack = _pack(name)
    job_id = uuid.uuid4().hex[:12]
    job = JOBS[job_id] = {"id": job_id, "kind": "build", "voice": name,
                          "status": "running", "log": [],
                          "started": datetime.now(timezone.utc).isoformat()}

    def work():
        from revoice.core.indexer import index_corpus
        from revoice.core.metrics import build_baselines
        from revoice.core.profiles import build_profiles
        from revoice.core.rubrics import write_template as write_rubrics
        from revoice.core.style import write_template as write_style

        provider = make_provider(CFG.classifier)
        log = lambda item, msg: job["log"].append(f"{item}: {msg}")  # noqa: E731
        job["stage"] = "index"
        job["index_stats"] = index_corpus(pack, provider, log)
        job["stage"] = "profiles"
        job["registers"] = build_profiles(pack, provider, log)
        write_style(pack.params_dir)
        write_rubrics(pack.params_dir)
        job["stage"] = "baselines"
        build_baselines(pack, log)
        job["stage"] = "complete"

    _spawn(job, work)
    return {"job": job_id}


@app.get("/v1/voices/{name}/status", dependencies=[Depends(_auth)])
def voices_status(name: str):
    m = _pack(name).manifest()
    builds = [j for j in JOBS.values() if j["kind"] == "build" and j["voice"] == name]
    return {"readiness": m.get("readiness", "not_ready"), "manifest": m,
            "builds": [{k: j.get(k) for k in ("id", "status", "stage", "error")} for j in builds]}


# ---------- revoice ----------

class RevoiceBody(BaseModel):
    voice: str | None = None
    text: str
    register: str | None = None
    strength: float = 0.7
    critique: bool = False
    votes: int = 1
    cohesion: bool = False


def _resolve_voice(name: str | None) -> VoicePack:
    if name:
        return _pack(name)
    packs = list_voices(CFG.data_dir)
    if len(packs) != 1:
        raise HTTPException(400, f"specify voice ({len(packs)} available)")
    return packs[0]


def _run_revoice(text: str, body_voice, register, strength, critique, votes, cohesion=False):
    from revoice.core.pipeline import revoice_document

    pack = _resolve_voice(body_voice)
    critic = make_provider(CFG.critic) if critique else None
    return revoice_document(text, pack, make_provider(CFG.rewriter), register,
                            strength, critic=critic, judge_votes=votes, cohesion=cohesion)


@app.post("/v1/revoice", dependencies=[Depends(_auth)])
def revoice_text(body: RevoiceBody):
    out, report = _run_revoice(body.text, body.voice, body.register,
                               body.strength, body.critique, body.votes, body.cohesion)
    return {"output": out, "report": report}


class PlanBody(BaseModel):
    text: str
    voice: str | None = None
    register: str | None = None


@app.post("/v1/plan", dependencies=[Depends(_auth)])
def plan(body: PlanBody):
    from revoice.core.preflight import build_plan

    pack = _pack(body.voice) if body.voice else None
    return build_plan(body.text, pack, body.register)


@app.post("/v1/revoice-file", dependencies=[Depends(_auth)])
async def revoice_file(file: UploadFile = File(...), voice: str = Form(None),
                       register: str = Form(None), strength: float = Form(0.7),
                       critique: bool = Form(False), votes: int = Form(1),
                       output_filename: str = Form(None)):
    suffix = Path(file.filename or "doc.md").suffix.lower()
    if suffix not in (".md", ".txt", ".markdown", ".text", ".rst"):
        raise HTTPException(400, f"{suffix}: only md/txt in this phase")
    text = (await file.read()).decode(errors="replace")
    job_id = uuid.uuid4().hex[:12]
    jdir = JOBS_DIR / job_id
    jdir.mkdir(parents=True, exist_ok=True)
    out_name = output_filename or f"{Path(file.filename or 'doc').stem}.revoiced{suffix}"
    job = JOBS[job_id] = {"id": job_id, "kind": "revoice", "status": "running",
                          "voice": voice, "input_name": file.filename,
                          "output_name": out_name, "dir": str(jdir),
                          "started": datetime.now(timezone.utc).isoformat()}
    (jdir / "input.txt").write_text(text)

    def work():
        out, report = _run_revoice(text, voice, register, strength, critique, votes)
        (jdir / out_name).write_text(out)
        (jdir / "diff.json").write_text(json.dumps(report, ensure_ascii=False))
        job["summary"] = report["summary"]
        job["register"] = report["register"]

    _spawn(job, work)
    return {"job": job_id, "output_name": out_name}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(_auth)])
def job_status(job_id: str):
    j = _job(job_id)
    return {k: v for k, v in j.items() if k != "dir"}


@app.get("/v1/jobs/{job_id}/result", dependencies=[Depends(_auth)])
def job_result(job_id: str):
    j = _job(job_id)
    if j["status"] != "done":
        raise HTTPException(409, f"job is {j['status']}")
    return FileResponse(Path(j["dir"]) / j["output_name"], filename=j["output_name"])


@app.get("/v1/jobs/{job_id}/diff", dependencies=[Depends(_auth)])
def job_diff(job_id: str):
    j = _job(job_id)
    f = Path(j.get("dir", "")) / "diff.json"
    if not f.is_file():
        raise HTTPException(409, "no diff (job not done or not a revoice job)")
    return JSONResponse(json.loads(f.read_text()))


# ---------- review (the flywheel) ----------

class ReviewDecision(BaseModel):
    id: str
    decision: str                    # accept | reject | edit
    edited_text: str | None = None


class ReviewBody(BaseModel):
    voice: str | None = None
    decisions: list[ReviewDecision]


@app.post("/v1/jobs/{job_id}/review", dependencies=[Depends(_auth)])
def job_review(job_id: str, body: ReviewBody):
    j = _job(job_id)
    f = Path(j.get("dir", "")) / "diff.json"
    if not f.is_file():
        raise HTTPException(409, "no diff to review")
    report = json.loads(f.read_text())
    spans = {s["id"]: s for s in report["spans"]}
    pack = _resolve_voice(body.voice or j.get("voice"))
    pairs_path = pack.params_dir / "pairs.jsonl"
    written = 0
    with pairs_path.open("a") as out:
        for d in body.decisions:
            s = spans.get(d.id)
            if not s:
                continue
            rec = {"ts": datetime.now(timezone.utc).isoformat(), "job": job_id,
                   "register": report.get("register"), "original": s.get("original"),
                   "model_output": s.get("new") or s.get("rejected"),
                   "decision": d.decision,
                   "final": d.edited_text if d.decision == "edit" else
                            (s.get("new") if d.decision == "accept" else s.get("original")),
                   "rubric": s.get("rubric")}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
    return {"recorded": written, "pairs_file": str(pairs_path)}


# ---------- stats & judge ----------

class StatsBody(BaseModel):
    text: str
    voice: str | None = None
    register: str | None = None


@app.post("/v1/stats", dependencies=[Depends(_auth)])
def stats(body: StatsBody):
    from revoice.core.report import build_report

    pack = _pack(body.voice) if body.voice else None
    return build_report(body.text, source="api", pack=pack, register=body.register)


class JudgeBody(BaseModel):
    original: str
    rewritten: str
    voice: str | None = None
    votes: int = 1


@app.post("/v1/judge", dependencies=[Depends(_auth)])
def judge(body: JudgeBody):
    import yaml

    from revoice.core.rubrics import TEMPLATE, judge_all, load_rubrics

    rubrics = load_rubrics(_pack(body.voice).params_dir) if body.voice \
        else yaml.safe_load(TEMPLATE)["dimensions"]
    return judge_all(make_provider(CFG.critic), rubrics, body.original,
                     body.rewritten, body.votes)


# ---------- entry ----------

def serve(config_path: Path | None = None, host: str = "127.0.0.1", port: int = 7333):
    global CFG
    CFG = load_config(config_path)
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")
