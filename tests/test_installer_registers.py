"""Checks for the second installer-page register promotion."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'custom_components/ecoforest_ecoair_ro/registers.py'
spec = importlib.util.spec_from_file_location("installer_registers", SCHEMA)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
LEDGER = json.loads((ROOT / "proposals/hp-installer-registers.json").read_text())

class InstallerRegisterTests(unittest.TestCase):
    def test_all_promoted_once_and_read_only(self):
        self.assertEqual(LEDGER["entry_count"], 95)
        rows = LEDGER["entries"]
        identities = [(row["bank"], row["definition"]["address"]) for row in rows]
        self.assertEqual(len(identities), len(set(identities)))
        mapping = r.hp_mapping()
        for row in rows:
            expected = row["definition"]
            actual = mapping[expected["key"]]
            self.assertEqual(actual["address"], expected["address"])
            self.assertEqual(actual["rw"], "R")
            self.assertTrue(actual["optional"])
        self.assertNotIn(("boolean", 117), identities)
        self.assertNotIn(("integer", 5052), identities)
        self.assertNotIn(("integer", 5330), identities)
        self.assertNotIn(("integer", 5331), identities)

    def test_decoding_and_default_disabled_metadata(self):
        mapping = r.hp_mapping()
        self.assertEqual(r.decode("0032", mapping["bivalent_parallel_outdoor_threshold"]), 5.0)
        self.assertEqual(r.decode("FFFB", mapping["e_manager_activation_threshold"]), -0.5)
        self.assertEqual(r.decode("000F", mapping["model_code_character_1"]), "E")
        self.assertEqual(r.decode("000B", mapping["model_code_character_2"]), "A")
        self.assertEqual(r.decode("0000", mapping["building_insulation_selection_raw"]), "Good")
        self.assertEqual(r.decode("0001", mapping["building_insulation_selection_raw"]), "Bad")
        self.assertEqual(r.decode("0002", mapping["building_insulation_selection_raw"]), "Moderate")
        self.assertEqual(r.decode("0000", mapping["cooling_connection_type_raw"]), "Not configured")
        self.assertEqual(r.decode("0001", mapping["cooling_connection_type_raw"]), "Direct")
        self.assertEqual(r.decode("0002", mapping["cooling_connection_type_raw"]), "Buffer")
        self.assertEqual(r.decode("000F", mapping["compressor_delay_setting_raw"]), 15)
        self.assertEqual(mapping["compressor_delay_setting_raw"]["entity_type"], "duration_min")
        self.assertTrue(mapping["dg1_fixed_cooling_supply_temperature"]["disabled_by_default"])

    def test_ha_translations_cover_every_entry(self):
        translations = json.loads((ROOT / "custom_components/ecoforest_ecoair_ro/translations/en.json").read_text())
        sensors = translations["entity"]["sensor"]
        for row in LEDGER["entries"]:
            definition = row["definition"]
            self.assertEqual(sensors[definition["key"]], {"name": definition["name"]})
