"""SpeciesValueMaster — Phase Bio Species Prediction Backtest.

Spec (docs/BIO_EXTERNAL_DATA_VALIDATION_SPEC_V0.1.md §3.3/§4.1,
docs/PHASE_BIO_SPECIES_PREDICTION_BACKTEST_DESIGN_BASELINE_V0.1.md §3).
`species -> fixed base value`, keyed by the same internal codex name
`BioObservation.species` uses (e.g. "$Codex_Ent_Stratum_07_Name;") --
these values are fixed game constants (not measured/estimated data), so
no name-mapping layer is needed against real scanorganic/1 observations.

**Independently compiled, not copied from any single source** (per
docs/BIO_SPECIES_VALUE_MASTER_CROSS_REFERENCE_INVESTIGATION_V0.1.md,
which cross-referenced two separately-maintained public compilations --
the Elite Dangerous Fandom Wiki's "Exobiology Sample Values and
Details" page, and EDMC-BioScan's (GPL-2.0) bundled ruleset data). The
structural (code -> name) mapping was read from EDMC-BioScan's public
data only to identify which internal codex name corresponds to which
species for cross-checking purposes -- no GPL code, occurrence rules,
or prediction logic from that project is used anywhere in this module
or elsewhere in EDpj.

Of 114 species covered, 90.6% agreed exactly between the two sources
(96/106 name-matched). The disputes below were resolved BEFORE this
module was used for any accuracy backtest, never adjusted afterward:

- Fonticulua Fluctus and Concha Biconcavis: the wiki/EDMC-BioScan value
  16,777,215 is exactly 2**24-1, an integer-overflow-shaped number, on
  one source for each. A third source (a community forum page found
  during the cross-reference investigation) independently states
  Fonticulua Fluctus pays 20,000,000, and states Concha Biconcavis pays
  the same amount (19,010,800) as Fonticulua Segmentatus and Tussock
  Stigmasis -- both of which already show 19,010,800 in this table.
  Both corrected accordingly.
- The remaining 9 disputes (Anemone Croceum, Bacterium Nebulus/
  Scopulum, 5 Brain Tree color variants, Tussock Ventusa) have no
  independent third-source corroboration either way -- the Fandom
  wiki's value is used, flagged `confidence="disputed"` rather than
  silently treated as equally reliable as the 103 entries both sources
  agreed on.

`confidence="disputed"` entries should be excluded from any accuracy
metric that would be sensitive to a ~2x value error until a further
source resolves them (design doc §3) -- this module does not decide
that policy itself, callers choose whether to filter on it.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeciesValueEntry:
    name: str
    value: int
    confidence: str  # "confirmed" | "disputed"


RETRIEVED_AT = dt.date(2026, 9, 6)
GAME_VERSION = "4.4 (Odyssey)"  # as observed in real scanorganic/1 archive headers during this investigation

SPECIES_VALUE_MASTER: dict[str, SpeciesValueEntry] = {
    '$Codex_Ent_Aleoids_01_Name;': SpeciesValueEntry(name='Aleoida Arcus', value=7252500, confidence='confirmed'),
    '$Codex_Ent_Aleoids_02_Name;': SpeciesValueEntry(name='Aleoida Coronamus', value=6284600, confidence='confirmed'),
    '$Codex_Ent_Aleoids_03_Name;': SpeciesValueEntry(name='Aleoida Spica', value=3385200, confidence='confirmed'),
    '$Codex_Ent_Aleoids_04_Name;': SpeciesValueEntry(name='Aleoida Laminiae', value=3385200, confidence='confirmed'),
    '$Codex_Ent_Aleoids_05_Name;': SpeciesValueEntry(name='Aleoida Gravis', value=12934900, confidence='confirmed'),
    '$Codex_Ent_Bacterial_01_Name;': SpeciesValueEntry(name='Bacterium Aurasus', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Bacterial_02_Name;': SpeciesValueEntry(name='Bacterium Nebulus', value=9116600, confidence='disputed'),
    '$Codex_Ent_Bacterial_03_Name;': SpeciesValueEntry(name='Bacterium Scopulum', value=8633800, confidence='disputed'),
    '$Codex_Ent_Bacterial_04_Name;': SpeciesValueEntry(name='Bacterium Acies', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Bacterial_05_Name;': SpeciesValueEntry(name='Bacterium Vesicula', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Bacterial_06_Name;': SpeciesValueEntry(name='Bacterium Alcyoneum', value=1658500, confidence='confirmed'),
    '$Codex_Ent_Bacterial_07_Name;': SpeciesValueEntry(name='Bacterium Tela', value=1949000, confidence='confirmed'),
    '$Codex_Ent_Bacterial_08_Name;': SpeciesValueEntry(name='Bacterium Informem', value=8418000, confidence='confirmed'),
    '$Codex_Ent_Bacterial_09_Name;': SpeciesValueEntry(name='Bacterium Volu', value=7774700, confidence='confirmed'),
    '$Codex_Ent_Bacterial_10_Name;': SpeciesValueEntry(name='Bacterium Bullaris', value=1152500, confidence='confirmed'),
    '$Codex_Ent_Bacterial_11_Name;': SpeciesValueEntry(name='Bacterium Omentum', value=4638900, confidence='confirmed'),
    '$Codex_Ent_Bacterial_12_Name;': SpeciesValueEntry(name='Bacterium Cerbrus', value=1689800, confidence='confirmed'),
    '$Codex_Ent_Bacterial_13_Name;': SpeciesValueEntry(name='Bacterium Verrata', value=3897000, confidence='confirmed'),
    '$Codex_Ent_Cactoid_01_Name;': SpeciesValueEntry(name='Cactoida Cortexum', value=3667600, confidence='confirmed'),
    '$Codex_Ent_Cactoid_02_Name;': SpeciesValueEntry(name='Cactoida Lapis', value=2483600, confidence='confirmed'),
    '$Codex_Ent_Cactoid_03_Name;': SpeciesValueEntry(name='Cactoida Vermis', value=16202800, confidence='confirmed'),
    '$Codex_Ent_Cactoid_04_Name;': SpeciesValueEntry(name='Cactoida Pullulanta', value=3667600, confidence='confirmed'),
    '$Codex_Ent_Cactoid_05_Name;': SpeciesValueEntry(name='Cactoida Peperatis', value=2483600, confidence='confirmed'),
    '$Codex_Ent_Clypeus_01_Name;': SpeciesValueEntry(name='Clypeus Lacrimam', value=8418000, confidence='confirmed'),
    '$Codex_Ent_Clypeus_02_Name;': SpeciesValueEntry(name='Clypeus Margaritus', value=11873200, confidence='confirmed'),
    '$Codex_Ent_Clypeus_03_Name;': SpeciesValueEntry(name='Clypeus Speculumi', value=16202800, confidence='confirmed'),
    '$Codex_Ent_Conchas_01_Name;': SpeciesValueEntry(name='Concha Renibus', value=4572400, confidence='confirmed'),
    '$Codex_Ent_Conchas_02_Name;': SpeciesValueEntry(name='Concha Aureolas', value=7774700, confidence='confirmed'),
    '$Codex_Ent_Conchas_03_Name;': SpeciesValueEntry(name='Concha Labiata', value=2352400, confidence='confirmed'),
    '$Codex_Ent_Conchas_04_Name;': SpeciesValueEntry(name='Concha Biconcavis', value=19010800, confidence='disputed'),
    '$Codex_Ent_Electricae_01_Name;': SpeciesValueEntry(name='Electricae Pluma', value=6284600, confidence='confirmed'),
    '$Codex_Ent_Electricae_02_Name;': SpeciesValueEntry(name='Electricae Radialem', value=6284600, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_01_Name;': SpeciesValueEntry(name='Fonticulua Segmentatus', value=19010800, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_02_Name;': SpeciesValueEntry(name='Fonticulua Campestris', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_03_Name;': SpeciesValueEntry(name='Fonticulua Upupam', value=5727600, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_04_Name;': SpeciesValueEntry(name='Fonticulua Lapida', value=3111000, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_05_Name;': SpeciesValueEntry(name='Fonticulua Fluctus', value=20000000, confidence='confirmed'),
    '$Codex_Ent_Fonticulus_06_Name;': SpeciesValueEntry(name='Fonticulua Digitos', value=1804100, confidence='confirmed'),
    '$Codex_Ent_Fumerolas_01_Name;': SpeciesValueEntry(name='Fumerola Carbosis', value=6284600, confidence='confirmed'),
    '$Codex_Ent_Fumerolas_02_Name;': SpeciesValueEntry(name='Fumerola Extremus', value=16202800, confidence='confirmed'),
    '$Codex_Ent_Fumerolas_03_Name;': SpeciesValueEntry(name='Fumerola Nitris', value=7500900, confidence='confirmed'),
    '$Codex_Ent_Fumerolas_04_Name;': SpeciesValueEntry(name='Fumerola Aquatis', value=6284600, confidence='confirmed'),
    '$Codex_Ent_Fungoids_01_Name;': SpeciesValueEntry(name='Fungoida Setisis', value=1670100, confidence='confirmed'),
    '$Codex_Ent_Fungoids_02_Name;': SpeciesValueEntry(name='Fungoida Stabitis', value=2680300, confidence='confirmed'),
    '$Codex_Ent_Fungoids_03_Name;': SpeciesValueEntry(name='Fungoida Bullarum', value=3703200, confidence='confirmed'),
    '$Codex_Ent_Fungoids_04_Name;': SpeciesValueEntry(name='Fungoida Gelata', value=3330300, confidence='confirmed'),
    '$Codex_Ent_Ground_Struct_Ice_Name;': SpeciesValueEntry(name='Crystalline Shards', value=1628800, confidence='confirmed'),
    '$Codex_Ent_Osseus_01_Name;': SpeciesValueEntry(name='Osseus Fractus', value=4027800, confidence='confirmed'),
    '$Codex_Ent_Osseus_02_Name;': SpeciesValueEntry(name='Osseus Discus', value=12934900, confidence='confirmed'),
    '$Codex_Ent_Osseus_03_Name;': SpeciesValueEntry(name='Osseus Spiralis', value=2404700, confidence='confirmed'),
    '$Codex_Ent_Osseus_04_Name;': SpeciesValueEntry(name='Osseus Pumice', value=3156300, confidence='confirmed'),
    '$Codex_Ent_Osseus_05_Name;': SpeciesValueEntry(name='Osseus Cornibus', value=1483000, confidence='confirmed'),
    '$Codex_Ent_Osseus_06_Name;': SpeciesValueEntry(name='Osseus Pellebantus', value=9739000, confidence='confirmed'),
    '$Codex_Ent_Recepta_01_Name;': SpeciesValueEntry(name='Recepta Umbrux', value=12934900, confidence='confirmed'),
    '$Codex_Ent_Recepta_02_Name;': SpeciesValueEntry(name='Recepta Deltahedronix', value=16202800, confidence='confirmed'),
    '$Codex_Ent_Recepta_03_Name;': SpeciesValueEntry(name='Recepta Conditivus', value=14313700, confidence='confirmed'),
    '$Codex_Ent_SeedABCD_01_Name;': SpeciesValueEntry(name='Gypseeum Brain Tree', value=3565100, confidence='disputed'),
    '$Codex_Ent_SeedABCD_02_Name;': SpeciesValueEntry(name='Ostrinum Brain Tree', value=3565100, confidence='disputed'),
    '$Codex_Ent_SeedABCD_03_Name;': SpeciesValueEntry(name='Viride Brain Tree', value=1593700, confidence='confirmed'),
    '$Codex_Ent_SeedEFGH_01_Name;': SpeciesValueEntry(name='Aureum Brain Tree', value=3565100, confidence='disputed'),
    '$Codex_Ent_SeedEFGH_02_Name;': SpeciesValueEntry(name='Puniceum Brain Tree', value=3565100, confidence='disputed'),
    '$Codex_Ent_SeedEFGH_03_Name;': SpeciesValueEntry(name='Lindigoticum Brain Tree', value=3565100, confidence='disputed'),
    '$Codex_Ent_SeedEFGH_Name;': SpeciesValueEntry(name='Lividum Brain Tree', value=1593700, confidence='confirmed'),
    '$Codex_Ent_Seed_Name;': SpeciesValueEntry(name='Roseum Brain Tree', value=1593700, confidence='confirmed'),
    '$Codex_Ent_Shrubs_01_Name;': SpeciesValueEntry(name='Frutexa Flabellum', value=1808900, confidence='confirmed'),
    '$Codex_Ent_Shrubs_02_Name;': SpeciesValueEntry(name='Frutexa Acus', value=7774700, confidence='confirmed'),
    '$Codex_Ent_Shrubs_03_Name;': SpeciesValueEntry(name='Frutexa Metallicum', value=1632500, confidence='confirmed'),
    '$Codex_Ent_Shrubs_04_Name;': SpeciesValueEntry(name='Frutexa Flammasis', value=10326000, confidence='confirmed'),
    '$Codex_Ent_Shrubs_05_Name;': SpeciesValueEntry(name='Frutexa Fera', value=1632500, confidence='confirmed'),
    '$Codex_Ent_Shrubs_06_Name;': SpeciesValueEntry(name='Frutexa Sponsae', value=5988000, confidence='confirmed'),
    '$Codex_Ent_Shrubs_07_Name;': SpeciesValueEntry(name='Frutexa Collum', value=1639800, confidence='confirmed'),
    '$Codex_Ent_SphereABCD_01_Name;': SpeciesValueEntry(name='Croceum Anemone', value=3399800, confidence='disputed'),
    '$Codex_Ent_SphereABCD_02_Name;': SpeciesValueEntry(name='Puniceum Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_SphereABCD_03_Name;': SpeciesValueEntry(name='Roseum Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_SphereEFGH_01_Name;': SpeciesValueEntry(name='Rubeum Bioluminescent Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_SphereEFGH_02_Name;': SpeciesValueEntry(name='Prasinum Bioluminescent Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_SphereEFGH_03_Name;': SpeciesValueEntry(name='Roseum Bioluminescent Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_SphereEFGH_Name;': SpeciesValueEntry(name='Blatteum Bioluminescent Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_Sphere_Name;': SpeciesValueEntry(name='Luteolum Anemone', value=1499900, confidence='confirmed'),
    '$Codex_Ent_Stratum_01_Name;': SpeciesValueEntry(name='Stratum Excutitus', value=2448900, confidence='confirmed'),
    '$Codex_Ent_Stratum_02_Name;': SpeciesValueEntry(name='Stratum Paleas', value=1362000, confidence='confirmed'),
    '$Codex_Ent_Stratum_03_Name;': SpeciesValueEntry(name='Stratum Laminamus', value=2788300, confidence='confirmed'),
    '$Codex_Ent_Stratum_04_Name;': SpeciesValueEntry(name='Stratum Araneamus', value=2448900, confidence='confirmed'),
    '$Codex_Ent_Stratum_05_Name;': SpeciesValueEntry(name='Stratum Limaxus', value=1362000, confidence='confirmed'),
    '$Codex_Ent_Stratum_06_Name;': SpeciesValueEntry(name='Stratum Cucumisis', value=16202800, confidence='confirmed'),
    '$Codex_Ent_Stratum_07_Name;': SpeciesValueEntry(name='Stratum Tectonicas', value=19010800, confidence='confirmed'),
    '$Codex_Ent_Stratum_08_Name;': SpeciesValueEntry(name='Stratum Frigus', value=2637500, confidence='confirmed'),
    '$Codex_Ent_TubeABCD_01_Name;': SpeciesValueEntry(name='Prasinum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_TubeABCD_03_Name;': SpeciesValueEntry(name='Caeruleum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_TubeEFGH_01_Name;': SpeciesValueEntry(name='Lindigoticum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_TubeEFGH_02_Name;': SpeciesValueEntry(name='Violaceum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_TubeEFGH_03_Name;': SpeciesValueEntry(name='Viride Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_TubeEFGH_Name;': SpeciesValueEntry(name='Blatteum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_Tube_Name;': SpeciesValueEntry(name='Roseum Sinuous Tubers', value=1514500, confidence='confirmed'),
    '$Codex_Ent_Tubus_01_Name;': SpeciesValueEntry(name='Tubus Conifer', value=2415500, confidence='confirmed'),
    '$Codex_Ent_Tubus_02_Name;': SpeciesValueEntry(name='Tubus Sororibus', value=5727600, confidence='confirmed'),
    '$Codex_Ent_Tubus_03_Name;': SpeciesValueEntry(name='Tubus Cavas', value=11873200, confidence='confirmed'),
    '$Codex_Ent_Tubus_04_Name;': SpeciesValueEntry(name='Tubus Rosarium', value=2637500, confidence='confirmed'),
    '$Codex_Ent_Tubus_05_Name;': SpeciesValueEntry(name='Tubus Compagibus', value=7774700, confidence='confirmed'),
    '$Codex_Ent_Tussocks_01_Name;': SpeciesValueEntry(name='Tussock Pennata', value=5853800, confidence='confirmed'),
    '$Codex_Ent_Tussocks_02_Name;': SpeciesValueEntry(name='Tussock Ventusa', value=3277700, confidence='disputed'),
    '$Codex_Ent_Tussocks_03_Name;': SpeciesValueEntry(name='Tussock Ignis', value=1849000, confidence='confirmed'),
    '$Codex_Ent_Tussocks_04_Name;': SpeciesValueEntry(name='Tussock Cultro', value=1766600, confidence='confirmed'),
    '$Codex_Ent_Tussocks_05_Name;': SpeciesValueEntry(name='Tussock Catena', value=1766600, confidence='confirmed'),
    '$Codex_Ent_Tussocks_06_Name;': SpeciesValueEntry(name='Tussock Pennatis', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Tussocks_07_Name;': SpeciesValueEntry(name='Tussock Serrati', value=4447100, confidence='confirmed'),
    '$Codex_Ent_Tussocks_08_Name;': SpeciesValueEntry(name='Tussock Albata', value=3252500, confidence='confirmed'),
    '$Codex_Ent_Tussocks_09_Name;': SpeciesValueEntry(name='Tussock Propagito', value=1000000, confidence='confirmed'),
    '$Codex_Ent_Tussocks_10_Name;': SpeciesValueEntry(name='Tussock Divisa', value=1766600, confidence='confirmed'),
    '$Codex_Ent_Tussocks_11_Name;': SpeciesValueEntry(name='Tussock Caputus', value=3472400, confidence='confirmed'),
    '$Codex_Ent_Tussocks_12_Name;': SpeciesValueEntry(name='Tussock Triticum', value=7774700, confidence='confirmed'),
    '$Codex_Ent_Tussocks_13_Name;': SpeciesValueEntry(name='Tussock Stigmasis', value=19010800, confidence='confirmed'),
    '$Codex_Ent_Tussocks_14_Name;': SpeciesValueEntry(name='Tussock Virgam', value=14313700, confidence='confirmed'),
    '$Codex_Ent_Tussocks_15_Name;': SpeciesValueEntry(name='Tussock Capillum', value=7025800, confidence='confirmed'),
}


def get_species_value(species_code: str) -> SpeciesValueEntry | None:
    """None (not 0, not a guess) when the species has no master entry --
    e.g. a species not yet covered by either cross-referenced source, or
    a genuinely new one added to the game after RETRIEVED_AT."""
    return SPECIES_VALUE_MASTER.get(species_code)
