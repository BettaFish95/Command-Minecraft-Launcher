"""离线账户：创建、查询、默认账户选择。"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from .paths import data_dir
from .storage import now_iso, read_json, write_json

NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


class AccountError(Exception):
    pass


@dataclass
class Account:
    name: str
    uuid: str
    created_at: str = ""
    last_used: str = ""

    @property
    def uuid_hex(self) -> str:
        return self.uuid.replace("-", "")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "uuid": self.uuid,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_RE.match(name):
        raise AccountError("用户名需为 3-16 位，只能包含字母、数字和下划线。")
    return name


class AccountStore:
    def __init__(self):
        self.path = data_dir() / "accounts.json"
        self.accounts: list[Account] = []
        self.last_account = ""
        self._load()

    def _load(self) -> None:
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            return
        for item in data.get("accounts") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("uuid") or "").strip()
            if not name or not value:
                continue
            try:
                uuid.UUID(value)
            except ValueError:
                continue
            self.accounts.append(Account(
                name=name,
                uuid=value,
                created_at=str(item.get("created_at") or ""),
                last_used=str(item.get("last_used") or ""),
            ))
        last = str(data.get("last_account") or "")
        if any(a.name.lower() == last.lower() for a in self.accounts):
            self.last_account = last

    def save(self) -> None:
        write_json(self.path, {
            "accounts": [a.to_dict() for a in self.accounts],
            "last_account": self.last_account,
        })

    def all(self) -> list[Account]:
        return list(self.accounts)

    def get(self, name: str | None = None) -> Account | None:
        if not name:
            return None
        for account in self.accounts:
            if account.name.lower() == name.strip().lower():
                return account
        return None

    def create(self, name: str) -> tuple[Account, bool]:
        name = validate_name(name)
        existing = self.get(name)
        if existing:
            return existing, False
        account = Account(
            name=name,
            uuid=str(uuid.uuid4()),
            created_at=now_iso(),
            last_used=now_iso(),
        )
        self.accounts.append(account)
        self.last_account = account.name
        self.save()
        return account, True

    def default(self, preferred: str | None = None) -> Account | None:
        if preferred:
            account = self.get(preferred)
            if account:
                return account
        if self.last_account:
            account = self.get(self.last_account)
            if account:
                return account
        if len(self.accounts) == 1:
            return self.accounts[0]
        if self.accounts:
            # 多个账户时使用最近使用过的
            return max(self.accounts, key=lambda a: a.last_used or a.created_at)
        return None

    def touch(self, account: Account) -> None:
        for item in self.accounts:
            if item.uuid == account.uuid:
                item.last_used = now_iso()
                break
        self.last_account = account.name
        self.save()

    def delete(self, name: str) -> bool:
        account = self.get(name)
        if not account:
            return False
        self.accounts.remove(account)
        if self.last_account.lower() == account.name.lower():
            self.last_account = self.accounts[0].name if self.accounts else ""
        self.save()
        return True
