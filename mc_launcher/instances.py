"""实例登记：自定义名称、版本隔离目录、内存。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .paths import data_dir
from .storage import now_iso, read_json, write_json


def safe_folder_name(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "_", (name or "").strip()).strip(" .")
    return value or "instance"


@dataclass
class Instance:
    name: str
    version_id: str
    game_dir: str
    instance_dir: str = ""
    isolated: bool = False
    memory_mb: int = 0
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version_id": self.version_id,
            "game_dir": self.game_dir,
            "instance_dir": self.instance_dir,
            "isolated": self.isolated,
            "memory_mb": self.memory_mb,
            "created_at": self.created_at,
        }


class InstanceStore:
    def __init__(self):
        self.path = data_dir() / "instances.json"
        self.items: list[Instance] = []
        self._load()

    def _load(self) -> None:
        data = read_json(self.path, {})
        for item in (data.get("instances") if isinstance(data, dict) else []) or []:
            if not isinstance(item, dict) or not item.get("name") or not item.get("version_id"):
                continue
            self.items.append(Instance(
                name=str(item["name"]),
                version_id=str(item["version_id"]),
                game_dir=str(item.get("game_dir") or ""),
                instance_dir=str(item.get("instance_dir") or ""),
                isolated=bool(item.get("isolated")),
                memory_mb=int(item.get("memory_mb") or 0),
                created_at=str(item.get("created_at") or ""),
            ))

    def save(self) -> None:
        write_json(self.path, {"instances": [item.to_dict() for item in self.items]})

    def all(self) -> list[Instance]:
        return list(self.items)

    def get(self, name: str) -> Instance | None:
        wanted = (name or "").strip().lower()
        for item in self.items:
            if item.name.lower() == wanted:
                return item
        return None

    def add(self, name: str, version_id: str, game_dir: Path, instance_dir: Path | None,
            isolated: bool, memory_mb: int) -> Instance:
        if self.get(name):
            raise ValueError(f"实例名称已存在：{name}")
        item = Instance(
            name=name,
            version_id=version_id,
            game_dir=str(game_dir),
            instance_dir=str(instance_dir) if instance_dir else "",
            isolated=isolated,
            memory_mb=memory_mb,
            created_at=now_iso(),
        )
        self.items.append(item)
        self.save()
        return item

    def update(self, item: Instance) -> None:
        for index, existing in enumerate(self.items):
            if existing.name.lower() == item.name.lower():
                self.items[index] = item
                self.save()
                return
