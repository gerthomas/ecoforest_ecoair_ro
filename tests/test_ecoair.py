"""Offline ecoAIR tests: protocol guard, parsing, decoding and the read-only client."""
import importlib
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'custom_components/ecoforest_ecoair_ro'

spec = importlib.util.spec_from_file_location('ecoair_registers_under_test', PKG / 'ecoair_registers.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def block(values):
    """Build a response like the gateway sends: status line, values, trailer."""
    return 'error_geo_get_reg=0\n' + '\n'.join(values) + '\n0'


def hx(n):
    return f'{n & 0xFFFF:04X}'


def fake_blocks():
    """A plausible set of block values; positions follow ECOAIR_MAPPING."""
    b = {op: ['0000'] * 40 for op in r.ECOAIR_READ_OPERATIONS}
    b[2125][:5] = [hx(15), hx(13), hx(24), hx(1), hx(1)]  # 'EA??' style code
    b[2148][21] = hx(65)      # outdoor 6.5
    b[2148][6] = hx(1)        # state on
    b[2148][19] = hx(-9999)  # absent probe (-999.9)
    b[2149][1] = hx(3000)     # heating power W
    b[2149][3] = hx(1000)     # electric power W
    b[2149][19] = hx(55)
    b[2149][20] = hx(180)
    b[2151][28] = hx(480)     # DHW 48.0
    b[2151][0] = hx(350)
    b[2103][4] = hx(500)
    b[2104][3] = '0001'
    b[2108][12] = '0000'
    return b


class ProtocolTests(unittest.TestCase):
    def test_guard_allows_only_whitelisted_reads(self):
        for op in r.ECOAIR_READ_OPERATIONS:
            r.validate_ecoair_read({'idOperacion': op})
        for data in [None, {}, {'idOperacion': 2011}, {'idOperacion': 2012}, {'idOperacion': 2002},
                     {'idOperacion': True}, {'idOperacion': 2148, 'dir': 1},
                     {'idOperacion': 2148, 'num': 1, 'x': 'y'}, {'idOperacion': '2148'}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                r.validate_ecoair_read(data)

    def test_parse_matches_upstream_behaviour(self):
        self.assertEqual(r.parse_ecoair_read(block(['0028', 'x=FFFF', '0001'])), ['0028', 'FFFF', '0001'])
        for bad in ['', 'error_geo_get_reg=-1\n0028\n0', 'garbage\n0028\n0', 'error_geo_get_reg=0\n0']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                r.parse_ecoair_read(bad)

    def test_model_name_decoding(self):
        self.assertEqual(r.model_name([hx(15), hx(13), hx(0), hx(1), hx(11)]), 'EC--0A')
        with self.assertRaises(ValueError):
            r.model_name(['0001'])

    def test_decode_values(self):
        b = fake_blocks()
        m = r.ECOAIR_MAPPING
        self.assertEqual(r.decode_ecoair(b, m['t_outdoor']), 6.5)
        self.assertEqual(r.decode_ecoair(b, m['power_heating']), 3000)
        self.assertEqual(r.decode_ecoair(b, m['cop']), 3.0)
        self.assertEqual(r.decode_ecoair(b, m['state']), 'on')
        self.assertIsNone(r.decode_ecoair(b, m['t_brine_in']))   # -999.9 probe
        self.assertEqual(r.decode_ecoair(b, m['switch_dhw']), 1)
        self.assertEqual(r.decode_ecoair(b, m['switch_heating']), 0)
        b[2149][3] = hx(0)
        self.assertEqual(r.decode_ecoair(b, m['cop']), 0)
        self.assertIsNone(r.decode_ecoair({}, m['t_outdoor']))
        self.assertIsNone(r.decode_ecoair({2148: ['0000']}, m['t_outdoor']))  # short block
        self.assertIsNone(r.decode_ecoair({2148: ['zz'] * 40}, m['t_outdoor']))  # bad hex

    def test_mapping_is_complete_and_uses_only_read_operations(self):
        for key, d in r.ECOAIR_MAPPING.items():
            self.assertIn(d['operation'], r.ECOAIR_READ_OPERATIONS, key)
            for field in ('data_type', 'bank', 'address', 'optional', 'entity_type'):
                self.assertIn(field, d, key)
        self.assertEqual({d['operation'] for d in r.ECOAIR_MAPPING.values()} - {2125},
                         set(r.ECOAIR_POLL_OPERATIONS))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, path in [('custom_components', ROOT / 'custom_components'),
                           ('custom_components.ecoforest_ecoair_ro', PKG)]:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
        self.m = importlib.import_module('custom_components.ecoforest_ecoair_ro.overrides.api')
        self.sent = []
        self.rejected = set()
        self.status = 200
        self.blocks = fake_blocks()
        self.api = self.m.make_api('http://example.invalid', 'u', 'p', 'ecoair')
        self.api._client.post = self.post
        self.sleep = patch.object(self.m.asyncio, 'sleep', new=AsyncMock())
        self.sleep.start()

    async def asyncTearDown(self):
        self.sleep.stop()

    async def post(self, url, auth=None, timeout=None, data=None):
        self.sent.append(dict(data))
        op = data['idOperacion']
        status = self.status

        class Response:
            text = block(self.blocks[op]) if op not in self.rejected else 'error_geo_get_reg=-1'

            def raise_for_status(inner):
                if status != 200:
                    raise self.m.httpx.HTTPStatusError('x', request=None, response=types.SimpleNamespace(status_code=status))
        return Response()

    async def test_factory_and_mapping(self):
        self.assertIsInstance(self.api, self.m.EcoAirReadOnlyApi)
        self.assertEqual(set(self.api.mapping), set(r.ECOAIR_MAPPING))
        geo = self.m.make_api('http://example.invalid', 'u', 'p', 'geo')
        self.assertNotIsInstance(geo, self.m.EcoAirReadOnlyApi)

    async def test_full_read_sends_only_whitelisted_block_reads(self):
        data = await self.api.get()
        self.assertTrue(data.model_name)
        self.assertEqual(data.state['t_outdoor'], 6.5)
        self.assertEqual(data.state['cop'], 3.0)
        self.assertEqual(data.failed_reads, [])
        self.assertTrue(all(set(q) == {'idOperacion'} and q['idOperacion'] in r.ECOAIR_READ_OPERATIONS
                            for q in self.sent))
        self.sent.clear()
        await self.api.get()
        self.assertNotIn(2125, [q['idOperacion'] for q in self.sent])  # model cached

    async def test_control_methods_and_writes_blocked_before_http(self):
        for fn, args in [(self.api.turn, [True]), (self.api.set_temperature, [42]), (self.api.set_power, [50])]:
            with self.assertRaises(ValueError):
                await fn(*args)
        for op in (2011, 2012):
            with self.assertRaises(ValueError):
                await self.api._request({'idOperacion': op, 'dir': 1, 'num': 1})
        self.assertEqual(self.sent, [])

    async def test_one_rejected_block_does_not_break_the_rest(self):
        await self.api.get()
        self.rejected = {2103}
        data = await self.api.get()
        self.assertEqual(data.failed_reads, [(2103,)])
        self.assertIsNone(data.state['dhw_setpoint'])
        self.assertEqual(data.state['t_outdoor'], 6.5)

    async def test_core_block_is_retried_three_times(self):
        await self.api.get()
        self.sent.clear()
        self.rejected = {2148}
        data = await self.api.get()
        self.assertEqual(sum(q['idOperacion'] == 2148 for q in self.sent), 3)
        self.assertIsNone(data.state['t_outdoor'])

    async def test_everything_failing_raises(self):
        await self.api.get()
        self.rejected = set(r.ECOAIR_POLL_OPERATIONS)
        with self.assertRaises(self.m.EcoforestConnectionError):
            await self.api.get()

    async def test_authentication_failure_never_hidden(self):
        self.status = 401
        with self.assertRaises(self.m.EcoforestAuthenticationRequired):
            await self.api.get()


if __name__ == '__main__':
    unittest.main()
