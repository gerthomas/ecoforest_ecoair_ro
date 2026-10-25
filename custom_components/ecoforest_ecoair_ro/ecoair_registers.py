"""Read-only ecoAIR protocol helpers and register map (no Home Assistant imports).

The ecoAIR family answers block reads of the form ``idOperacion=<n>`` (no address or
count). Each operation returns one list of values; a sensor is a position in that list.
The operation numbers and positions are taken from the radutopala/ecoforest_ecoair
integration (itself a fork of bytestorm/ecoforest_ecogeo).

Only the operations in ECOAIR_READ_OPERATIONS may ever be sent. Write operations
(2011, 2012) are rejected before any network I/O.
"""
from __future__ import annotations

import re

# Block reads used by the integration. 2125 holds the model code.
ECOAIR_MODEL_OPERATION = 2125
ECOAIR_READ_OPERATIONS = frozenset({2103, 2104, 2108, 2125, 2148, 2149, 2150, 2151})
# Polled every cycle, in this order. 2125 is only read until the model is known.
ECOAIR_POLL_OPERATIONS = (2148, 2149, 2151, 2150, 2103, 2104, 2108)
# Operations that carry the core telemetry (retried); the rest are tried once.
ECOAIR_CORE_OPERATIONS = frozenset({2148, 2149, 2151})

_HEADER = re.compile(r"^[A-Za-z0-9_]+=0$")
_HEX = re.compile(r"^[0-9a-fA-F]{1,4}$")


def validate_ecoair_read(data):
    """Reject writes, extra fields and unknown operations before network I/O."""
    if not isinstance(data, dict) or set(data) != {"idOperacion"}:
        raise ValueError("Only ecoAIR block reads are permitted")
    op = data["idOperacion"]
    if type(op) is not int:
        raise ValueError("Read operation must be an integer")
    if op not in ECOAIR_READ_OPERATIONS:
        raise ValueError("Ecoforest client is read-only")


def parse_ecoair_read(response: str) -> list[str]:
    """Return the value list of one block read.

    Mirrors the parsing used by the upstream ecoAIR integration: the first line is an
    ``<name>=0`` status line, the last line is a trailer, and every line in between is
    either ``<name>=<value>`` or a bare value.
    """
    lines = [line.strip() for line in response.split("\n") if line.strip()]
    if len(lines) < 3 or not _HEADER.match(lines[0]):
        raise ValueError("Invalid or rejected Ecoforest read response")
    return [line.split("=", 1)[1] if "=" in line else line for line in lines[1:-1]]


def signed(raw: str) -> int:
    if not _HEX.match(raw):
        raise ValueError(f"Invalid register value {raw!r}")
    n = int(raw, 16)
    return n - 65536 if n >= 32768 else n


def model_name(values: list[str]) -> str:
    """Decode the five model characters at the start of operation 2125."""
    if len(values) < 5:
        raise ValueError("Invalid Ecoforest model code")
    chars = []
    for raw in values[:5]:
        n = signed(raw)
        if n == 0:
            chars.append("--")
        elif 1 <= n <= 10:
            chars.append(str(n - 1))
        elif 11 <= n <= 36:
            chars.append(chr(n - 11 + ord("A")))
        else:
            chars.append("--")
    return "".join(chars)


STATE_ENUM = {"0": "off", "1": "on", "2": "emergency", "3": "off"}

# key -> definition. 'index' is the position inside the operation's value list.
# 'kind': tenths = signed/10, int = signed, bool = 0/1, enum = STATE_ENUM lookup,
#         cop = derived from power_heating / power_electric.
ECOAIR_MAPPING = {
    "t_outdoor": dict(operation=2148, index=21, kind="tenths", entity_type="temperature"),
    "ventilation_rate": dict(operation=2148, index=30, kind="tenths", entity_type="measurement",
                             optional=True, note="Copied from the upstream ecoAIR map; unverified."),
    "state": dict(operation=2148, index=6, kind="enum", entity_type="enum", enum=STATE_ENUM),
    "t_brine_in": dict(operation=2148, index=19, kind="tenths", entity_type="temperature",
                       optional=True, disabled_by_default=True,
                       note="Brine sensors come from the ground-source map; an air unit has no brine loop."),
    "t_brine_out": dict(operation=2148, index=22, kind="tenths", entity_type="temperature",
                        optional=True, disabled_by_default=True,
                        note="Brine sensors come from the ground-source map; an air unit has no brine loop."),
    "p_brine": dict(operation=2148, index=18, kind="tenths", entity_type="pressure",
                    optional=True, disabled_by_default=True,
                    note="Brine sensors come from the ground-source map; an air unit has no brine loop."),
    "power_heating": dict(operation=2149, index=1, kind="int", entity_type="power"),
    "power_electric": dict(operation=2149, index=3, kind="int", entity_type="power"),
    "p_compressor_in": dict(operation=2149, index=19, kind="tenths", entity_type="pressure"),
    "p_compressor_out": dict(operation=2149, index=20, kind="tenths", entity_type="pressure"),
    "cop": dict(operation=2149, index=None, kind="cop", entity_type="measurement"),
    "boiler_state": dict(operation=2150, index=0, kind="enum", entity_type="enum", enum=STATE_ENUM),
    "t_dhw": dict(operation=2151, index=28, kind="tenths", entity_type="temperature"),
    "t_heating_setpoint": dict(operation=2151, index=0, kind="tenths", entity_type="temperature"),
    "dhw_setpoint": dict(operation=2103, index=4, kind="tenths", entity_type="temperature"),
    "dhw_recirculation_setpoint": dict(operation=2103, index=10, kind="tenths", entity_type="temperature"),
    "switch_dhw": dict(operation=2104, index=3, kind="bool", entity_type="measurement"),
    "switch_dhw_recirculation": dict(operation=2104, index=14, kind="bool", entity_type="measurement"),
    "switch_heating": dict(operation=2108, index=12, kind="bool", entity_type="measurement"),
}
for _key, _d in ECOAIR_MAPPING.items():
    # Fields the shared sensor platform expects on every definition.
    _d.setdefault("data_type", 1)
    _d.setdefault("bank", f"op{_d['operation']}")
    _d.setdefault("address", _d["index"])
    _d.setdefault("optional", False)


def decode_ecoair(values: dict[int, list[str]], definition: dict):
    """Decode one sensor from the block values read this cycle; None if unavailable."""
    block = values.get(definition["operation"])
    if block is None:
        return None
    kind = definition["kind"]
    try:
        if kind == "cop":
            heating = values.get(2149)
            if heating is None or len(heating) <= 3:
                return 0
            h, e = signed(heating[1]), signed(heating[3])
            return round(h / e, 1) if h and e else 0
        index = definition["index"]
        if index >= len(block):
            return None
        raw = block[index]
        if kind == "bool":
            return 1 if int(raw) else 0
        n = signed(raw)
        if kind == "int":
            return n
        if kind == "enum":
            return definition["enum"].get(str(n))
        if definition["entity_type"] == "temperature" and n == -9999:
            return None  # absent probe
        return n / 10
    except ValueError:
        return None
