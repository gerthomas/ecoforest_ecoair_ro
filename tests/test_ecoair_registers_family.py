"""Offline tests for the register-based ecoAIR family (documented table over 2001/2002 reads)."""
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'custom_components/ecoforest_ecoair_ro'

spec = importlib.util.spec_from_file_location('ecoair_map_under_test', PKG / 'ecoair_map.py')
ecoair_map = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecoair_map)

SYMBOLS = ['--'] + list('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')


def model_codes(name):
    return [SYMBOLS.index(c) for c in name]


class MapTests(unittest.TestCase):
    def test_counts_and_uniqueness(self):
        mapping = ecoair_map.ecoair_register_mapping()
        self.assertEqual(len(mapping), 160)
        slots = {(d['data_type'], d['address']) for d in mapping.values()}
        self.assertEqual(len(slots), 160)
        self.assertEqual({d['bank'] for d in mapping.values()}, {'analog', 'integer', 'boolean'})

    def test_spot_checks_against_documented_table(self):
        m = ecoair_map.ecoair_register_mapping()
        for key, address, bank, scale, etype in [
            ('air_outdoor_temperature', 20, 'analog', 0.1, 'temperature'),
            ('air_dhw_temperature', 11, 'analog', 0.1, 'temperature'),
            ('air_electric_power', 135, 'analog', 0.1, 'power_kw'),
            ('air_compressor_speed', 5002, 'integer', 1, 'measurement'),
            ('air_out_evi_valve', 36, 'boolean', 1, 'raw'),
            ('air_bus_control', 5257, 'integer', 1, 'raw'),
        ]:
            d = m[key]
            self.assertEqual((d['address'], d['bank'], d['scale'], d['entity_type']),
                             (address, bank, scale, etype), key)

    def test_keys_have_translations_and_no_clashes(self):
        names = json.loads((PKG / 'translations/en.json').read_text())['entity']['sensor']
        for key, d in ecoair_map.ecoair_register_mapping().items():
            self.assertEqual(names[key]['name'], d['name'], key)

    def test_only_known_entity_types(self):
        allowed = {'temperature', 'pressure', 'power_kw', 'percent', 'measurement', 'raw'}
        for key, d in ecoair_map.ecoair_register_mapping().items():
            self.assertIn(d['entity_type'], allowed, key)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, path in [('custom_components', ROOT / 'custom_components'),
                           ('custom_components.ecoforest_ecoair_ro', PKG)]:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
        self.m = importlib.import_module('custom_components.ecoforest_ecoair_ro.overrides.api')
        self.sent = []
        self.rejected = set()          # register/coil addresses the gateway refuses
        self.registers = {5323 + i: c for i, c in enumerate(model_codes('EK1000'))}
        self.registers.update({20: 65, 11: 480, 135: 12, 133: 36, 5002: 2400, 5: -9999})
        self.coils = {36: 1, 33: 1, 32: 0}
        self.api = self.m.make_api('http://example.invalid', 'u', 'p', 'ecoair')
        self.api._client.post = self.post
        self.sleep = patch.object(self.m.asyncio, 'sleep', new=AsyncMock())
        self.sleep.start()

    async def asyncTearDown(self):
        self.sleep.stop()

    async def post(self, url, auth=None, timeout=None, data=None):
        self.sent.append(dict(data))
        op, start, num = data['idOperacion'], data['dir'], data['num']
        rejected = any(a in self.rejected for a in range(start, start + num))

        class Response:
            def raise_for_status(self_inner):
                pass

        r = Response()
        if rejected:
            r.text = 'error_geo_get_reg=-1' if op == 2002 else 'error_geo_get_bit=-1'
        elif op == 2002:
            vals = '&'.join(f'{self.registers.get(a, 0) & 0xFFFF:04X}' for a in range(start, start + num))
            r.text = f'error_geo_get_reg=0\ndir={start}&num={num}&{vals}\n0'
        else:
            vals = '&'.join(str(self.coils.get(a, 0)) for a in range(start, start + num))
            r.text = f'error_geo_get_bit=0\ndir={start}&num={num}&{vals}\n0'
        return r

    async def test_factory(self):
        self.assertIsInstance(self.api, self.m.EcoAirRegisterApi)
        self.assertEqual(len(self.api.mapping), 160)

    async def test_full_read(self):
        device = await self.api.get()
        self.assertEqual(device.model_name, 'EK1000')
        s = device.state
        self.assertEqual(s['air_outdoor_temperature'], 6.5)
        self.assertEqual(s['air_dhw_temperature'], 48.0)
        self.assertEqual(s['air_electric_power'], 1.2)
        self.assertEqual(s['air_heating_power'], 3.6)
        self.assertEqual(s['air_compressor_speed'], 2400)
        self.assertIsNone(s['air_inlet_temp_outdoor_unit'])   # -999.9 absent probe
        self.assertEqual(s['air_out_evi_valve'], 1)
        self.assertEqual(s['air_out_alarm'], 0)
        self.assertEqual(device.failed_reads, [])

    async def test_only_reads_are_sent(self):
        await self.api.get()
        self.assertTrue(self.sent)
        for q in self.sent:
            self.assertEqual(set(q), {'idOperacion', 'dir', 'num'})
            self.assertIn(q['idOperacion'], (2001, 2002))
            self.assertLessEqual(q['num'], 64)
        for fn, args in [(self.api.turn, [True]), (self.api.set_temperature, [42])]:
            with self.assertRaises(ValueError):
                await fn(*args)

    async def test_rejected_register_is_bisected_to_that_address_only(self):
        self.rejected = {135}
        device = await self.api.get()
        self.assertIsNone(device.state['air_electric_power'])
        self.assertEqual(device.state['air_heating_power'], 3.6)
        self.assertEqual(device.state['air_outdoor_temperature'], 6.5)
        self.assertEqual(device.failed_reads, [(1, 135, 1)])

    async def test_everything_rejected_after_model_raises(self):
        self.rejected = set(range(0, 6000)) - set(range(5323, 5329))
        with self.assertRaises(self.m.EcoforestConnectionError):
            await self.api.get()


if __name__ == '__main__':
    unittest.main()
