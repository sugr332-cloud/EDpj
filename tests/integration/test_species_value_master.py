from __future__ import annotations

from app.bio.species_value_master import SPECIES_VALUE_MASTER, get_species_value


class TestGetSpeciesValue:
    def test_known_species_returns_entry(self):
        entry = get_species_value("$Codex_Ent_Stratum_07_Name;")
        assert entry is not None
        assert entry.name == "Stratum Tectonicas"
        assert entry.value == 19010800
        assert entry.confidence == "confirmed"

    def test_unknown_species_returns_none_not_a_guess(self):
        assert get_species_value("$Codex_Ent_Nonexistent_Name;") is None


class TestMasterIntegrity:
    def test_every_entry_has_a_positive_value(self):
        for code, entry in SPECIES_VALUE_MASTER.items():
            assert entry.value > 0, f"{code} has non-positive value"

    def test_confidence_is_always_confirmed_or_disputed(self):
        for entry in SPECIES_VALUE_MASTER.values():
            assert entry.confidence in ("confirmed", "disputed")

    def test_resolved_cross_source_conflicts_are_not_left_at_the_corrupted_value(self):
        # Both were the suspicious 2**24-1 (16,777,215) in at least one
        # cross-referenced source -- must not remain in the master.
        fluctus = get_species_value("$Codex_Ent_Fonticulus_05_Name;")
        biconcavis = get_species_value("$Codex_Ent_Conchas_04_Name;")
        assert fluctus.value != 16777215
        assert biconcavis.value != 16777215

    def test_disputed_entries_are_flagged(self):
        disputed = {code for code, e in SPECIES_VALUE_MASTER.items() if e.confidence == "disputed"}
        assert "$Codex_Ent_Bacterial_02_Name;" in disputed  # Bacterium Nebulus
        assert "$Codex_Ent_Tussocks_02_Name;" in disputed  # Tussock Ventusa

    def test_no_duplicate_species_names(self):
        names = [e.name for e in SPECIES_VALUE_MASTER.values()]
        assert len(names) == len(set(names))
