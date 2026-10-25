"""Evidence-ledger and production promotion checks for web-derived HP reads."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=ROOT / 'custom_components/ecoforest_ecoair_ro/registers.py'
spec=importlib.util.spec_from_file_location('proposal_registers',SCHEMA)
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
PROPOSAL=json.loads((ROOT/'proposals/hp-web-registers.json').read_text())
ROWS=PROPOSAL['entries']
DEFS={(e['bank'],e['address']):dict(e['definition'],data_type=2 if e['bank']=='boolean' else 1)
      for e in ROWS if e['disposition']=='proposed'}

class WebRegisterProposalTests(unittest.TestCase):
    def test_all_candidates_accounted_for_with_source_backed_reads(self):
        self.assertEqual(len(ROWS),206)
        self.assertEqual(len({(e['bank'],e['address']) for e in ROWS}),206)
        self.assertEqual(len(DEFS),115)
        self.assertEqual(sum(e['disposition']=='deferred' for e in ROWS),91)
        for e in ROWS:
            with self.subTest(bank=e['bank'],address=e['address']):
                self.assertTrue(e['meaning'])
                self.assertTrue(e['evidence'])
                self.assertEqual(e['array_index'],e['address']-(5001 if e['bank']=='integer' else 0))
                if e['disposition']=='deferred':
                    self.assertTrue(e['reason']); self.assertNotIn('definition',e)
                    continue
                d=e['definition']
                self.assertTrue(d['optional']); self.assertEqual(d['rw'],'R')
                self.assertTrue(d['source']); self.assertTrue(d['note'])
                op=2001 if e['bank']=='boolean' else 2002
                self.assertTrue(any(b['operation']==op and b['address']<=e['address']<b['address']+b['count']
                    for source in e['evidence'] for b in source['observed_read_blocks']))
                if e['bank']=='boolean': self.assertNotIn('enum',d)

    def test_proposed_entries_are_promoted_once_without_collisions_or_holes(self):
        active=r.hp_mapping()
        self.assertEqual(len(active),570)
        extra={d['key']:d for d in DEFS.values()}
        self.assertEqual(len(extra),115)
        self.assertTrue(extra.keys() <= active.keys())
        for key, expected in extra.items():
            with self.subTest(key=key):
                actual=active[key]
                self.assertEqual(actual['address'],expected['address'])
                self.assertEqual(actual['data_type'],expected['data_type'])
                self.assertEqual(actual['name'],expected['name'])
                self.assertEqual(actual['rw'],'R')
                self.assertTrue(actual['optional'])
        named={(d['data_type'],d['address']) for d in active.values()}
        self.assertEqual(len(named),570)
        requests=r.read_requests(active)
        planned=[(q['data_type'],a) for q in requests for a in range(q['address'],q['address']+q['length'])]
        self.assertEqual(len(planned),570); self.assertEqual(set(planned),named)
        for q in requests:
            self.assertLessEqual(q['length'],64)
            r.validate_read(dict(idOperacion=2001 if q['data_type']==2 else 2002,dir=q['address'],num=q['length']))

    def test_promoted_entities_have_one_canonical_translation(self):
        translations=json.loads((ROOT/'custom_components/ecoforest_ecoair_ro/translations/en.json').read_text())
        sensors=translations['entity']['sensor']
        self.assertEqual(len(DEFS),len({definition['key'] for definition in DEFS.values()}))
        for definition in DEFS.values():
            with self.subTest(key=definition['key']):
                self.assertEqual(sensors[definition['key']],{'name':definition['name']})

    def test_critical_source_derived_decoding_and_misleading_names(self):
        for bank,address,raw,expected in [
            ('analog',121,'00D7',21.5),('analog',107,'FFC4',-6),
            ('analog',109,'0005',0.5),('analog',103,'01F4',50),
            ('integer',5061,'0002','On'),('integer',5062,'0001','On'),
            ('integer',5064,'0002',2),('integer',5069,'0064',100),
            ('integer',5077,'0004',4),('boolean',206,'1',1),
            ('integer',5063,'0003',3)]:
            with self.subTest(address=address):self.assertEqual(r.decode(raw,DEFS[bank,address]),expected)
        self.assertEqual(DEFS['integer',5067]['name'],'Night end hour')
        self.assertIsNone(r.decode('0018',DEFS['integer',5067]))
        self.assertEqual(r.decode('003B',DEFS['integer',5068]),59)
        self.assertIsNone(r.decode('003C',DEFS['integer',5068]))
        self.assertIsNone(r.decode('D8F1',DEFS['analog',121]))
        self.assertIsNone(r.decode('0063',DEFS['integer',5061]))
        self.assertIsNone(r.decode(None,DEFS['boolean',206]))
        for identity in [('integer',5008),('integer',5012),('integer',5052),('boolean',119)]:
            self.assertNotIn(identity,DEFS)
