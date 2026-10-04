"""Local installation data. Original captures and tokens remain untouched."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import sqlite3

from .protocol import ProtocolError, ascii_address

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Profile:
    host: str
    port: int = 64100
    database: Path = ROOT / "captures/bigapp_db.db"
    system_id: int = 1
    timeout: float = 30.0
    wire_profile: str = "classic"

    def __post_init__(self):
        ipaddress.ip_address(self.host)  # Numeric IP avoids unbounded DNS resolution.
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Porta non valida")
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 300:
            raise ValueError("Timeout deve essere tra 0 e 300 secondi")
        if type(self.system_id) is not int or self.system_id < 1:
            raise ValueError("ID sistema non valido")
        if self.wire_profile not in ("classic", "community"):
            raise ValueError("Profilo wire non valido")

    @classmethod
    def load(cls, path: Path, **overrides) -> Profile:
        path = path.resolve()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) - {"host", "port", "database", "system_id", "timeout", "wire_profile"}:
            raise ValueError("Campi del profilo non validi")
        raw.update({k: v for k, v in overrides.items() if v is not None})
        raw["database"] = (path.parent / raw.get("database", "captures/bigapp_db.db")).resolve()
        return cls(**raw)

    def token(self) -> str:
        value = os.environ.get("COMELIT_TOKEN")
        if value is None:
            with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute("SELECT token FROM systems WHERE id_system=?", (self.system_id,)).fetchone()
                if row is None:
                    raise ValueError("Sistema assente nel database")
                value = row[0]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", value):
            raise ValueError("Token VIP assente o non valido (attesi 32 caratteri hex)")
        return value

    def inventory(self) -> dict:
        with closing(sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT name,ucfg_api_version,has_push,has_rtsp_viper,has_virtual_key,"
                "face_recognition,pm_always_on FROM systems WHERE id_system=?", (self.system_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Sistema assente nel database")
            info = db.execute("SELECT model_id,version_code FROM vip_system_info WHERE id_system=?",
                              (self.system_id,)).fetchone()
            doors = db.execute(
                "SELECT e.name,o.vipaddress,o.rele FROM opendoors o JOIN elements e "
                "ON e.id_element=o.id_element WHERE e.id_system=?", (self.system_id,)).fetchall()
            actuators = db.execute(
                "SELECT e.name,a.vipaddress,a.rele,a.expansion FROM actuators a JOIN elements e "
                "ON e.id_element=a.id_element WHERE e.id_system=?", (self.system_id,)).fetchall()
        return {"source": "android_database_snapshot", "live_verified": False,
                "host": self.host, "port": self.port, "system": dict(row),
                "device": dict(info) if info else {},
                "targets": [{"kind": "door", "name": d[0], "address": d[1], "relay": d[2]} for d in doors]
                + [{"kind": "actuator", "name": a[0], "address": a[1], "relay": a[2],
                    "module": int(a[3])} for a in actuators]}


@dataclass(frozen=True)
class Target:
    kind: str
    id: int
    name: str
    address: str
    relay: int
    module: int | None = None
    secure: bool = False

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    def public(self) -> dict:
        return {"key": self.key, "name": self.name, "kind": self.kind,
                "address": self.address, "relay": self.relay, "module": self.module,
                "secure_mode": self.secure}


@dataclass(frozen=True)
class DeviceConfig:
    apartment: str
    subaddress: int
    targets: tuple[Target, ...]
    raw: dict = field(repr=False)

    @classmethod
    def parse(cls, raw: dict) -> DeviceConfig:
        if not isinstance(raw, dict):
            raise ProtocolError("Configurazione deve essere un oggetto JSON")
        vip = raw.get("vip")
        if not isinstance(vip, dict) or vip.get("enabled") is False:
            raise ProtocolError("Configurazione VIP assente o disabilitata")
        apartment, subaddress = vip.get("apt-address"), vip.get("apt-subaddress")
        ascii_address(apartment)
        if type(subaddress) is not int or not 0 <= subaddress <= 255:
            raise ProtocolError("Subaddress VIP assente o non valido")
        parameters = vip.get("user-parameters", {})
        if not isinstance(parameters, dict):
            raise ProtocolError("Rubrica VIP non valida")
        targets = []
        keys = set()
        for kind, book in (("door", "opendoor-address-book"), ("actuator", "actuator-address-book")):
            entries = parameters.get(book, [])
            if not isinstance(entries, list):
                raise ProtocolError("Rubrica target non valida")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ProtocolError("Voce target non valida")
                identifier, relay = entry.get("id"), entry.get("output-index")
                if type(identifier) is not int or identifier < 0 or type(relay) is not int or not 1 <= relay <= 255:
                    raise ProtocolError("ID o relay target non valido")
                address = entry.get("apt-address")
                ascii_address(address)
                name = entry.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise ProtocolError("Nome target assente")
                module = entry.get("module-index") if kind == "actuator" else None
                if kind == "actuator" and (type(module) is not int or not 0 <= module <= 255):
                    raise ProtocolError("Modulo attuatore non valido")
                secure = entry.get("secure-mode", False)
                if type(secure) is not bool:
                    raise ProtocolError("secure-mode non valido")
                target = Target(kind, identifier, name, address, relay, module, secure)
                if target.key in keys:
                    raise ProtocolError("ID target duplicato nella rubrica")
                keys.add(target.key)
                targets.append(target)
        return cls(apartment, subaddress, tuple(targets), raw)

    def select(self, value: str) -> Target:
        matches = [t for t in self.targets if t.key == value or t.name.casefold() == value.casefold()]
        if len(matches) != 1:
            raise ProtocolError("Target assente o ambiguo: usare la chiave restituita da --list")
        return matches[0]

    def public(self) -> dict:
        parameters = self.raw["vip"].get("user-parameters", {})
        return {"apartment": self.apartment, "subaddress": self.subaddress,
                "targets": [t.public() for t in self.targets],
                "addressbook_counts": {k: len(v) for k, v in parameters.items()
                                       if k.endswith("address-book") and isinstance(v, list)}}


_SECRET_KEY = re.compile(r"password|passwd|token|secret|authorization|activation.?code|code.?verifier", re.I)


def redact(value):
    """For displayed diagnostics only. Original data is never modified."""
    if isinstance(value, dict):
        return {k: "<redacted>" if _SECRET_KEY.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\b[0-9a-f]{32}\b", "<redacted>", value)
        value = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", value)
    return value
