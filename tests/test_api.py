"""Exercise the real API class without importing the Home Assistant runtime."""
import asyncio
import importlib
from pathlib import Path
import string
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs
import httpx

ROOT=Path(__file__).resolve().parents[1]
# Namespace packages bypass HA-only setup imports; the API and dependencies are real.
for name,path in [('custom_components',ROOT/'custom_components'),
                  ('custom_components.ecoforest_ecoair_ro',ROOT/'custom_components/ecoforest_ecoair_ro')]:
    package=types.ModuleType(name); package.__path__=[str(path)]; sys.modules[name]=package
m=importlib.import_module('custom_components.ecoforest_ecoair_ro.overrides.api')

class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests=[]; self.reject=None; self.status=200
        self.api=m.EcoGeoApi('http://example.invalid','test','test')
        await self.api._client.aclose()
        self.api._client=httpx.AsyncClient(base_url='http://example.invalid',transport=httpx.MockTransport(self.respond))
        self.sleep=patch.object(m.asyncio,'sleep',new=AsyncMock()); self.sleep.start()
    async def asyncTearDown(self):
        self.sleep.stop(); await self.api.async_close()
    def respond(self, request):
        data={k:int(v[0]) for k,v in parse_qs(request.content.decode()).items()}
        self.requests.append(data)
        if self.status!=200:return httpx.Response(self.status)
        if data['dir']==self.reject:return httpx.Response(200,text='error_geo_get_reg=-1')
        op,a,n=data['idOperacion'],data['dir'],data['num']
        if a==5323:
            symbols=['--']+list(string.digits+string.ascii_uppercase)
            vals=[f'{symbols.index(c):04X}' for c in 'EATM00'] + ['0000'] * (n - 6)
        else:
            vals=['0' if op==2001 else '0000' for _ in range(n)]
            if a<=117<a+n and op==2002: vals[117-a]='0028'
        header='bit' if op==2001 else 'reg'
        return httpx.Response(200,text=f'error_geo_get_{header}=0\ndir={a}&num={n}&'+ '&'.join(vals)+'\n0')
    async def test_all_inherited_control_methods_blocked_before_http(self):
        for fn,args in [(self.api.turn,[True]),(self.api.set_temperature,[42]),(self.api.set_power,[50])]:
            with self.assertRaises(ValueError): await fn(*args)
        for op in [2011,2012]:
            with self.assertRaises(ValueError): await self.api._request({'idOperacion':op,'dir':1,'num':1})
        self.assertEqual(self.requests,[])
    async def test_complete_read_and_instance_specific_mapping(self):
        data=await self.api.get()
        self.assertEqual(data.model_name,'EATM00'); self.assertEqual(len(data.state),570)
        self.assertEqual(data.state['heating_buffer_dt_start'],4)
        self.assertEqual(data.failed_reads,[])
        self.assertTrue(all(q['idOperacion'] in [2001,2002] for q in self.requests))
        other=m.EcoGeoApi('http://example.invalid','test','test')
        self.assertIs(other.mapping,m._DOMESTIC_MAPPING)
        await other.async_close()
    async def test_optional_failure_not_stale_and_core_survives(self):
        await self.api.get()
        self.reject=next(q['address'] for q in m.read_requests(self.api.mapping)
                         if q['optional'] and q['address']<=117<q['address']+q['length'])
        data=await self.api.get()
        self.assertIsNone(data.state['heating_buffer_dt_start'])
        self.assertEqual(data.failed_reads,[(1,117,1)])
        self.assertIsNotNone(data.state['heat_buffer_tank_setpoint'])
    async def test_required_failure_raises_after_three_attempts(self):
        await self.api.get(); self.requests=[]
        self.reject=next(q['address'] for q in m.read_requests(self.api.mapping) if not q['optional'])
        with self.assertRaises(m.EcoforestConnectionError):await self.api.get()
        self.assertEqual(sum(q['dir']==self.reject for q in self.requests),3)
    async def test_authentication_failure_never_hidden(self):
        self.status=401
        with self.assertRaises(m.EcoforestAuthenticationRequired):await self.api.get()
