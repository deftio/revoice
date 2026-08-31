"""Voice pack layout: data/<voice>/training-data + data/<voice>/params (all derived, rebuildable)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class VoicePack:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.name = self.root.name

    # --- layout ---
    @property
    def training_dir(self) -> Path:
        return self.root / "training-data"

    @property
    def params_dir(self) -> Path:
        return self.root / "params"

    @property
    def index_path(self) -> Path:
        return self.params_dir / "index.jsonl"

    @property
    def profiles_dir(self) -> Path:
        return self.params_dir / "profiles"

    @property
    def exemplars_dir(self) -> Path:
        return self.params_dir / "exemplars"

    @property
    def manifest_path(self) -> Path:
        return self.params_dir / "manifest.json"

    def exists(self) -> bool:
        return self.training_dir.is_dir()

    @classmethod
    def create(cls, data_dir: Path, name: str, metadata: dict | None = None) -> VoicePack:
        pack = cls(Path(data_dir) / name)
        pack.training_dir.mkdir(parents=True, exist_ok=True)
        pack.params_dir.mkdir(parents=True, exist_ok=True)
        # self-protecting pack: a voice pack is personal data (corpus, profiles,
        # review pairs). This travels WITH the directory, so wherever the pack is
        # copied, git ignores its contents — independent of any repo-level ignore.
        gi = pack.root / ".gitignore"
        if not gi.exists():
            gi.write_text("# voice pack: personal writing data — never commit\n*\n")
        manifest = {
            "name": name,
            "created": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "readiness": "not_ready",
        }
        pack.manifest_path.write_text(json.dumps(manifest, indent=2))
        return pack

    # --- manifest ---
    def manifest(self) -> dict:
        if self.manifest_path.is_file():
            return json.loads(self.manifest_path.read_text())
        return {"name": self.name, "readiness": "not_ready", "metadata": {}}

    def update_manifest(self, **kv) -> dict:
        m = self.manifest()
        m.update(kv)
        self.params_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(m, indent=2))
        return m

    # --- index ---
    def read_index(self) -> dict[str, dict]:
        """Keyed by relative path. Later entries win (append-only log)."""
        entries: dict[str, dict] = {}
        if self.index_path.is_file():
            for line in self.index_path.read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    entries[e["path"]] = e
        return entries

    def append_index(self, entry: dict) -> None:
        self.params_dir.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def list_voices(data_dir: Path) -> list[VoicePack]:
    if not Path(data_dir).is_dir():
        return []
    return [VoicePack(p) for p in sorted(Path(data_dir).iterdir()) if (p / "training-data").is_dir()]
