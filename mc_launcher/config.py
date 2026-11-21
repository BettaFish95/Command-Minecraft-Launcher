"""配置文件（data/config.json）。"""
from __future__ import annotations

import copy
from pathlib import Path

from .paths import data_dir
from .storage import read_json, write_json

DEFAULTS = {
    "lang": "",
    "game_dir": "",
    "game_dir_configured": False,
    "extra_game_dirs": [],
    "java_path": "",
    "min_memory_mb": 512,
    "max_memory_mb": 0,          # 0 = 按物理内存自动
    "jvm_args": [],
    "game_args": [],
    "width": 0,
    "height": 0,
    "deep_search": True,
}


class Config:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @classmethod
    def load(cls) -> "Config":
        path = data_dir() / "config.json"
        data = read_json(path, {})
        if not isinstance(data, dict):
            data = {}
        merged = copy.deepcopy(DEFAULTS)
        merged.update({k: v for k, v in data.items() if k in DEFAULTS})
        if "game_dir_configured" not in data and merged.get("game_dir"):
            merged["game_dir_configured"] = True
        config = cls(path, merged)
        if not path.exists():
            config.save()
        return config

    def save(self) -> None:
        write_json(self.path, self.data)

    def get(self, key, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()

    def game_dirs(self) -> list[str]:
        items = []
        if self.get("game_dir"):
            items.append(self.get("game_dir"))
        for item in self.get("extra_game_dirs") or []:
            if item:
                items.append(item)
        return items
