"""FastAPI server coverage: every endpoint, jobs, review, auth."""

import time

import pytest
from fastapi.testclient import TestClient

import revoice.server as srv
from revoice.config import Config, ProviderConfig
from tests.conftest import TRAIN, build_learned_pack

client = TestClient(srv.app)


@pytest.fixture()
def served(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data",
                 classifier=ProviderConfig(kind="stub"),
                 rewriter=ProviderConfig(kind="stub"),
                 critic=ProviderConfig(kind="stub"))
    monkeypatch.setattr(srv, "CFG", cfg)
    srv.JOBS.clear()
    monkeypatch.delenv("REVOICE_TOKEN", raising=False)
    return tmp_path


@pytest.fixture()
def served_learned(served):
    build_learned_pack(served / "data", "t")
    return served


def wait_job(job_id, timeout=15):
    for _ in range(int(timeout / 0.05)):
        j = client.get(f"/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_health_and_gui(served, monkeypatch):
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "<" in client.get("/").text  # real static/index.html ships with the package
    monkeypatch.setattr(srv, "STATIC", served / "nostatic")
    assert "GUI not found" in client.get("/").text


def test_voices_crud(served):
    assert client.get("/v1/voices").json() == []
    assert client.post("/v1/voices", json={"name": "bad name!"}).status_code == 400
    r = client.post("/v1/voices", json={"name": "my-voice_1", "metadata": {"a": 1}})
    assert r.status_code == 200 and r.json()["name"] == "my-voice_1"
    assert client.get("/v1/voices").json()[0]["name"] == "my-voice_1"
    assert client.get("/v1/voices/my-voice_1").json()["metadata"] == {"a": 1}
    assert client.get("/v1/voices/ghost").status_code == 404
    assert client.delete("/v1/voices/ghost").status_code == 404
    assert client.delete("/v1/voices/my-voice_1").json() == {"deleted": "my-voice_1"}
    assert client.get("/v1/voices").json() == []


def test_data_upload_and_build(served):
    client.post("/v1/voices", json={"name": "v"})
    r = client.post("/v1/voices/v/data",
                    files=[("files", ("a.md", TRAIN.format(i=0).encode(), "text/markdown")),
                           ("files", ("b.md", TRAIN.format(i=1).encode(), "text/markdown"))])
    assert r.json()["saved"] == ["a.md", "b.md"]
    assert client.post("/v1/voices/ghost/data", files=[("files", ("a.md", b"x"))]).status_code == 404

    job_id = client.post("/v1/voices/v/build").json()["job"]
    j = wait_job(job_id)
    assert j["status"] == "done" and j["stage"] == "complete"
    assert j["index_stats"]["classified"] == 2
    st = client.get("/v1/voices/v/status").json()
    assert st["readiness"] == "prompts_ready"
    assert st["builds"][0]["id"] == job_id


def test_build_error_job(served, monkeypatch):
    import revoice.core.indexer as idx

    client.post("/v1/voices", json={"name": "v"})
    monkeypatch.setattr(idx, "index_corpus", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kaput")))
    job_id = client.post("/v1/voices/v/build").json()["job"]
    j = wait_job(job_id)
    assert j["status"] == "error" and "kaput" in j["error"]


def test_revoice_sync_and_resolve(served_learned):
    r = client.post("/v1/revoice", json={"text": "gotta fix this maybe soon."})
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["summary"]["rewritten"] == 1 and body["output"]

    r = client.post("/v1/revoice", json={"voice": "t", "text": "hello there.", "strength": 0.0,
                                         "critique": True, "cohesion": True})
    assert r.status_code == 200
    assert client.post("/v1/revoice", json={"voice": "ghost", "text": "x"}).status_code == 404

    build_learned_pack(served_learned / "data", "u")
    r = client.post("/v1/revoice", json={"text": "x"})
    assert r.status_code == 400 and "specify voice" in r.json()["detail"]


def test_plan_endpoint(served_learned):
    assert client.post("/v1/plan", json={"text": "Some plain text here."}).status_code == 200
    r = client.post("/v1/plan", json={"text": TRAIN.format(i=0), "voice": "t",
                                      "register": "professional"})
    assert r.json()["target_register"] == "professional"


def test_revoice_file_and_review(served_learned):
    r = client.post("/v1/revoice-file", files={"file": ("d.pptx", b"x")})
    assert r.status_code == 400

    r = client.post("/v1/revoice-file",
                    files={"file": ("draft.md", b"gotta fix the amp maybe.\n\nSecond note here ok.")},
                    data={"voice": "t", "strength": "0.9"})
    assert r.status_code == 200
    job_id, out_name = r.json()["job"], r.json()["output_name"]
    assert out_name == "draft.revoiced.md"
    j = wait_job(job_id)
    assert j["status"] == "done" and "dir" not in j

    res = client.get(f"/v1/jobs/{job_id}/result")
    assert res.status_code == 200 and res.text.strip()
    diff = client.get(f"/v1/jobs/{job_id}/diff").json()
    assert diff["spans"]

    sid = diff["spans"][0]["id"]
    r = client.post(f"/v1/jobs/{job_id}/review", json={"decisions": [
        {"id": sid, "decision": "accept"},
        {"id": sid, "decision": "reject"},
        {"id": sid, "decision": "edit", "edited_text": "my edit"},
        {"id": "s999", "decision": "accept"},  # unknown span skipped
    ]})
    assert r.json()["recorded"] == 3
    pairs = (served_learned / "data" / "t" / "params" / "pairs.jsonl").read_text().splitlines()
    assert len(pairs) == 3


def test_job_edge_cases(served):
    assert client.get("/v1/jobs/nope").status_code == 404
    srv.JOBS["fk"] = {"id": "fk", "kind": "revoice", "status": "running", "voice": None}
    assert client.get("/v1/jobs/fk/result").status_code == 409
    assert client.get("/v1/jobs/fk/diff").status_code == 409
    r = client.post("/v1/jobs/fk/review", json={"decisions": []})
    assert r.status_code == 409


def test_stats_and_judge_endpoints(served_learned):
    r = client.post("/v1/stats", json={"text": "Some text to analyze fully."})
    assert r.status_code == 200 and "match" not in r.json()
    r = client.post("/v1/stats", json={"text": "Some text.", "voice": "t"})
    assert "match" in r.json()

    r = client.post("/v1/judge", json={"original": "The value is 42.",
                                       "rewritten": "The value equals 42."})
    assert r.json()["rejected_by"] == []
    r = client.post("/v1/judge", json={"original": "a", "rewritten": "b", "voice": "t", "votes": 2})
    assert r.status_code == 200


def test_auth(served, monkeypatch):
    monkeypatch.setenv("REVOICE_TOKEN", "s3cret")
    assert client.get("/v1/voices").status_code == 401
    assert client.get("/v1/voices", headers={"authorization": "Bearer s3cret"}).status_code == 200


def test_serve_entry(tmp_path, monkeypatch):
    import uvicorn

    cfgfile = tmp_path / "c.yaml"
    cfgfile.write_text("data_dir: data\n")
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    srv.serve(cfgfile, host="127.0.0.1", port=7444)
    assert seen["port"] == 7444
    assert srv.CFG.data_dir == (tmp_path / "data").resolve()
