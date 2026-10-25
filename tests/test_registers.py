"""Offline protocol/schema tests. No controller or credentials required."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'custom_components/ecoforest_ecoair_ro/registers.py'
spec = importlib.util.spec_from_file_location('registers_under_test', SCHEMA)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class RegisterTests(unittest.TestCase):
    def test_complete_unique_named_coverage(self):
        mapping = r.hp_mapping()
        self.assertEqual(len(mapping), 570)
        self.assertEqual(len({(v['data_type'],v['address']) for v in mapping.values()}),570)
        planned = [(q['data_type'],a) for q in r.read_requests(mapping)
                   for a in range(q['address'],q['address']+q['length'])]
        self.assertEqual(set(planned), {(v['data_type'],v['address']) for v in mapping.values()})
        self.assertEqual(len(planned),570)
        self.assertTrue(all(q['length']<=64 for q in r.read_requests(mapping)))
        request={'address':40,'length':7,'data_type':1,'optional':True}
        halves=r.split_optional_request(request)
        self.assertEqual([(q['address'],q['length']) for q in halves],[(40,3),(43,4)])
        self.assertEqual(r.split_optional_request(dict(request,length=1)),[])

    def test_guard_rejects_write_and_malformed_payloads(self):
        for data in [None,{}, {'idOperacion':2011,'dir':1,'num':1},
                     {'idOperacion':2012,'dir':1,'num':1},
                     {'idOperacion':2002,'dir':1,'num':126},
                     {'idOperacion':2002,'dir':65535,'num':2},
                     {'idOperacion':2002,'dir':1,'num':True},
                     {'idOperacion':2002,'dir':1,'num':1,'value':0}]:
            with self.subTest(data=data), self.assertRaises(ValueError): r.validate_read(data)

    def test_strict_response_validation(self):
        req={'idOperacion':2002,'dir':117,'num':2}
        valid='error_geo_get_reg=0\ndir=117&num=2&0028&FFFF\n0'
        self.assertEqual(r.parse_read(valid,req),['0028','FFFF'])
        for bad in [valid.replace('reg=0','reg=-1'), valid.replace('dir=117','dir=118'),
                    valid.replace('num=2','num=1'),valid.replace('&FFFF',''),
                    valid.replace('FFFF','GGGG'),valid.replace('reg=0','bit=0')]:
            with self.subTest(bad=bad),self.assertRaises(ValueError): r.parse_read(bad,req)
        self.assertEqual(r.parse_read('error_geo_get_bit=0\ndir=24&num=1&1\n0',
            {'idOperacion':2001,'dir':24,'num':1}),['1'])

    def test_signed_sentinel_and_adjustment(self):
        self.assertEqual(r.signed_integer('8000'),-32768)
        self.assertEqual(r.signed_integer('FFFF'),-1)
        defs=r.hp_mapping()
        byaddr={v['address']:v for v in defs.values() if v['data_type']==1}
        self.assertEqual(r.decode('0028',byaddr[117]),4)
        self.assertIsNone(r.decode('D8F1',byaddr[117]))
        self.assertEqual([r.decode(f'{n:04X}',byaddr[5072]) for n in [0,2,4]],[-4,0,4])
        self.assertIsNone(r.decode('0005',byaddr[5072]))
        self.assertEqual(r.decode('0006',byaddr[5139]),'Heating buffer')
        self.assertIsNone(r.decode('0063',byaddr[5139]))
        self.assertIsNone(r.decode(None,byaddr[117]))

    def test_live_compressor_references_and_alarm_record_words(self):
        defs = r.hp_mapping()
        self.assertEqual(r.decode('011E', defs['set_speed_ref_show']), 28.6)
        self.assertEqual(r.decode('011E', defs['ref_show_actual_reference']), 28.6)
        self.assertEqual(defs['set_speed_ref_show']['entity_type'], 'percent')
        self.assertEqual(defs['ref_show_actual_reference']['entity_type'], 'percent')

        alarm_words = {
            5118: 'A1L', 5119: 'A1H', 5120: 'A2L', 5121: 'A2H',
            5122: 'W1L', 5123: 'W1H', 5124: 'W2L', 5125: 'W2H',
            5126: 'EWL', 5127: 'SW', 5128: 'DI', 5130: 'EWH',
        }
        by_address = {v['address']: v for v in defs.values() if v['data_type'] == 1}
        for address, label in alarm_words.items():
            with self.subTest(address=address):
                definition = by_address[address]
                self.assertEqual(definition['entity_type'], 'raw')
                self.assertIn(label, definition['name'])
                self.assertEqual(r.decode('0800', definition), 2048)
