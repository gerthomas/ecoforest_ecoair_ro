import asyncio
import json
import logging
import re
import string
from pathlib import Path
from typing import Any

import httpx
from pyecoforest.api import EcoforestApi
from pyecoforest.exceptions import EcoforestAuthenticationRequired, EcoforestConnectionError
from datetime import datetime, timezone
from ..registers import (hp_mapping, read_requests, split_optional_request, decode,
                         validate_read, parse_read, signed_integer)
from ..ecoair_registers import (ECOAIR_MAPPING, ECOAIR_MODEL_OPERATION, ECOAIR_POLL_OPERATIONS,
                                ECOAIR_CORE_OPERATIONS, validate_ecoair_read, parse_ecoair_read,
                                decode_ecoair, model_name as ecoair_model_name)

from .device import EcoGeoDevice

_LOGGER = logging.getLogger(__name__)

MODEL_ADDRESS = 5323
MODEL_LENGTH = 6


class DataTypes:
    Register = 1
    Coil = 2


class Operations:
    Get = {DataTypes.Coil: 2001, DataTypes.Register: 2002}


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


_ENTITY_TYPE_OVERRIDES = {
    "power_kw": ["ElecConsumptPwr", "CondPwr", "EvapPwr"],
    "energy_mwh": [
        "Annual condensation",
        "Annual evaporation",
        "Annual electrical",
        "Electric consumption",
        "Heating production",
        "Cooling production",
    ],
}


def _infer_entity_type(name: str) -> str:
    n = name.lower()

    # name selectors, including energy
    for override, names in _ENTITY_TYPE_OVERRIDES.items():
        if any(name.lower() in n.lower() for name in names):
            return override

    # temperature readings
    if "temperature" in n.lower() or "setpoint" in n.lower():
        return "temperature"

    # pressure readings
    if "pressure" in n.lower():
        return "pressure"

    # power readings
    POWER_TERMS = ["power", "capacity", "consumption", "production"]
    if any(term.lower() in n.lower() for term in POWER_TERMS):
        return "power"

    # COP and PF removed, these are just numbers
    # DONE - some are 'energy' not power
    return "measurement"


def _build_mapping(block: dict) -> dict:
    mapping: dict[str, dict] = {}
    for item in block.get("analog", []):
        key = _slugify(item["name"])
        mapping[key] = {
            "data_type": DataTypes.Register,
            "type": "float",
            "address": item["address"],
            "entity_type": _infer_entity_type(item["name"]),
        }

    # Some integers are actually floats, depends on the inferred entity type for now
    for item in block.get("integer", []):
        inferred_type = _infer_entity_type(item["name"])
        if inferred_type in ("power", "temperature"):
            type = "float"
        else:
            type = "int"
        key = _slugify(item["name"])
        mapping[key] = {
            "data_type": DataTypes.Register,
            "type": type,
            "address": item["address"],
            "entity_type": inferred_type,
        }
    for item in block.get("boolean", []):
        key = _slugify(item["name"])
        mapping[key] = {
            "data_type": DataTypes.Coil,
            "type": "boolean",
            "address": item["address"],
            "entity_type": "measurement",
        }
    return mapping


def _build_requests(mapping: dict) -> dict:
    requests = {DataTypes.Register: [], DataTypes.Coil: []}
    for dt in [DataTypes.Register, DataTypes.Coil]:
        addresses = sorted(
            [d["address"] for d in mapping.values() if d["data_type"] == dt]
        )
        if not addresses:
            continue
        start = prev = addresses[0]
        for addr in addresses[1:]:
            if addr != prev + 1:
                requests[dt].append({"address": start, "length": prev - start + 1})
                start = addr
            prev = addr
        requests[dt].append({"address": start, "length": prev - start + 1})
    return requests


# Load modbus information and build mappings for domestic and HP models
with open(
    Path(__file__).resolve().parent.parent / "modbus_info.json", "r", encoding="utf-8"
) as f:
    _info = json.load(f)
_DOMESTIC_MAPPING = _build_mapping(_info["ecoGEO_domestic"])
_HP_MAPPING = hp_mapping()
_DOMESTIC_REQUESTS = _build_requests(_DOMESTIC_MAPPING)
_HP_REQUESTS = _build_requests(_HP_MAPPING)

MAPPING = _DOMESTIC_MAPPING

HP_MODELS = {"EATM00"}

# ---------------------------------------------------------------------------
# API implementation
# ---------------------------------------------------------------------------


class EcoGeoApi(EcoforestApi):
    """Sensor-only client. Every inherited method is gated at the transport boundary."""
    def __init__(self, host: str, user: str, password: str) -> None:
        super().__init__(host, httpx.BasicAuth(user, password))
        self.mapping = _DOMESTIC_MAPPING
        self._model_name = None
        self._lock = asyncio.Lock()

    async def _request(self, data=None):
        validate_read(data)
        try:
            response = await self._client.post(
                '/recepcion_datos_4.cgi', auth=self._auth,
                timeout=self._timeout, data=data,
            )
            response.raise_for_status()
            return parse_read(response.text, data)
        except httpx.HTTPStatusError as err:
            if err.response.status_code in (401, 403):
                raise EcoforestAuthenticationRequired(err.response.status_code) from err
            raise EcoforestConnectionError('Ecoforest HTTP read failed') from err
        except (httpx.RequestError, ValueError) as err:
            raise EcoforestConnectionError('Invalid or failed Ecoforest read') from err

    async def _load_data(self, address, length, op_type):
        values = await self._request({'idOperacion': op_type, 'dir': address, 'num': length})
        return dict(zip(range(address, address + length), values))

    async def get(self) -> EcoGeoDevice:
        async with self._lock:
            return await self._get()

    async def _get(self):
        if self._model_name is None:
            data = await self._load_data(MODEL_ADDRESS, MODEL_LENGTH, 2002)
            symbols = ['--'] + list(string.digits + string.ascii_uppercase)
            codes = [signed_integer(data[a]) for a in range(MODEL_ADDRESS, MODEL_ADDRESS + MODEL_LENGTH)]
            if any(n < 0 or n >= len(symbols) for n in codes):
                raise EcoforestConnectionError('Invalid Ecoforest model code')
            self._model_name = ''.join(symbols[n] for n in codes)
            self.mapping = _HP_MAPPING if self._model_name in HP_MODELS else _DOMESTIC_MAPPING
        is_hp = self._model_name in HP_MODELS
        if is_hp:
            requests = read_requests(self.mapping)
        else:
            requests = [dict(r, data_type=dt, optional=False)
                        for dt, rows in _DOMESTIC_REQUESTS.items() for r in rows]
        state = {1: {}, 2: {}}
        errors = []
        request_index = 0
        while request_index < len(requests):
            request = requests[request_index]
            request_index += 1
            attempts = 1 if request['optional'] else 3
            for attempt in range(attempts):
                try:
                    state[request['data_type']].update(await self._load_data(
                        request['address'], request['length'], Operations.Get[request['data_type']]))
                    break
                except EcoforestAuthenticationRequired:
                    raise
                except EcoforestConnectionError:
                    if attempt + 1 < attempts:
                        await asyncio.sleep(2 ** attempt)
                    elif request['optional']:
                        smaller = split_optional_request(request)
                        if smaller:
                            requests[request_index:request_index] = smaller
                        else:
                            errors.append((request['data_type'], request['address'], request['length']))
                    else:
                        raise
            # Keep requests sequential and avoid hammering the controller.
            await asyncio.sleep(0.05)
        values = {}
        raw_values = {}
        for key, definition in self.mapping.items():
            raw = state[definition['data_type']].get(definition['address'])
            raw_values[key] = raw
            if is_hp:
                values[key] = decode(raw, definition)
            elif raw is None:
                values[key] = None
            else:
                parser = {'int': self.parse_ecoforest_int, 'float': self.parse_ecoforest_float,
                          'boolean': self.parse_ecoforest_bool}[definition['type']]
                value = parser(raw)
                values[key] = None if definition['entity_type'] == 'temperature' and value == -999.9 else value
        return EcoGeoDevice.build(self._model_name, values, raw_values=raw_values,
                                  failed_reads=errors, observed_at=datetime.now(timezone.utc).isoformat())

    async def async_close(self):
        await self._client.aclose()

    @staticmethod
    def parse_ecoforest_int(value):
        return signed_integer(value)

    @staticmethod
    def parse_ecoforest_bool(value):
        return bool(int(value))

    @staticmethod
    def parse_ecoforest_float(value):
        return signed_integer(value) / 10


# ---------------------------------------------------------------------------
# ecoAIR (air-source) client: read-only block reads, one operation per request
# ---------------------------------------------------------------------------

FAMILY_ECOAIR = "ecoair"
FAMILY_GEO = "geo"


class EcoAirReadOnlyApi(EcoGeoApi):
    """Read-only ecoAIR client. Only the whitelisted block reads can be sent."""

    def __init__(self, host: str, user: str, password: str) -> None:
        super().__init__(host, user, password)
        self.mapping = ECOAIR_MAPPING

    async def _request(self, data=None):
        validate_ecoair_read(data)
        try:
            response = await self._client.post(
                '/recepcion_datos_4.cgi', auth=self._auth,
                timeout=self._timeout, data=data,
            )
            response.raise_for_status()
            return parse_ecoair_read(response.text)
        except httpx.HTTPStatusError as err:
            if err.response.status_code in (401, 403):
                raise EcoforestAuthenticationRequired(err.response.status_code) from err
            raise EcoforestConnectionError('Ecoforest HTTP read failed') from err
        except (httpx.RequestError, ValueError) as err:
            raise EcoforestConnectionError('Invalid or failed Ecoforest read') from err

    async def _read_block(self, operation, attempts):
        for attempt in range(attempts):
            try:
                return await self._request({'idOperacion': operation})
            except EcoforestAuthenticationRequired:
                raise
            except EcoforestConnectionError:
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(2 ** attempt)

    async def _get(self):
        if self._model_name is None:
            # The model is required to identify the device; failure here is fatal.
            block = await self._read_block(ECOAIR_MODEL_OPERATION, 3)
            try:
                self._model_name = ecoair_model_name(block)
            except ValueError as err:
                raise EcoforestConnectionError('Invalid Ecoforest model code') from err
        blocks = {}
        errors = []
        last_error = None
        for operation in ECOAIR_POLL_OPERATIONS:
            try:
                blocks[operation] = await self._read_block(
                    operation, 3 if operation in ECOAIR_CORE_OPERATIONS else 1)
            except EcoforestConnectionError as err:
                errors.append((operation,))
                last_error = err
            await asyncio.sleep(0.05)
        if not blocks:
            raise EcoforestConnectionError('No ecoAIR block could be read') from last_error
        values = {key: decode_ecoair(blocks, definition) for key, definition in self.mapping.items()}
        raw_values = {
            key: (blocks.get(d['operation'], [None] * (d['index'] + 1))[d['index']]
                  if d['index'] is not None and d['index'] < len(blocks.get(d['operation'], []))
                  else None)
            for key, d in self.mapping.items()
        }
        return EcoGeoDevice.build(self._model_name, values, raw_values=raw_values,
                                  failed_reads=errors, observed_at=datetime.now(timezone.utc).isoformat())


def make_api(host: str, user: str, password: str, family: str = FAMILY_GEO):
    """Return the client for the configured controller family."""
    if family == FAMILY_ECOAIR:
        return EcoAirReadOnlyApi(host, user, password)
    return EcoGeoApi(host, user, password)
