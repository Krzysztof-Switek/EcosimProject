"""English titles for region layers.

The UI is English-only, but region packs are named by their authors in any
language. Known layers (the Baltic management pack, 2026-11) get a proper
English title here, keyed by the file stem without its grid prefix,
lower-cased; anything else falls back to the file stem made readable.
"""

from __future__ import annotations

import re

LAYER_KIND_TITLES = {
    "ices_subdivisions": "ICES subdivisions",
    "ices_rectangles": "ICES statistical rectangles",
}

KNOWN_TITLES = {
    "01_eez_polska": "EEZ Poland",
    "02_eez_szwecja": "EEZ Sweden",
    "03_natura2000_2024": "Natura 2000 (2024)",
    "04a_tralowanie_ue_2019_1241_stale": "Towed gear ban, EU 2019/1241 (all year)",
    "04b_tralowanie_denne_ue_2017_117": "Bottom trawling zones, EU 2017/117 (all year)",
    "04c_zamkniecia_ue_2019_1241_v_x": "Fishing closures May–Oct, EU 2019/1241",
    "04d1_tarlo_dorsza_2026_sd22_23": "Cod spawning closure 2026, SD 22–23",
    "04d2_tarlo_dorsza_2026_sd24": "Cod spawning closure 2026, SD 24",
    "04d3_tarlo_dorsza_2026_sd25_26": "Cod spawning closure 2026, SD 25–26",
    "04e_szwecja_tralowanie_pelagiczne_2025_2027": "Sweden pelagic trawling ban 2025–2027",
    "04f_szprot_2026_pelagiczne_poza_12mm": "Pelagic active gear beyond 12 nm, 2026",
    "04g_pl_pasy_przybrzezne_6_3_4mm": "Poland coastal belts 6/3/4 nm",
    "05a_helcom_baltic_fisheries_closure": "HELCOM Baltic Sea fisheries closure",
    "05b_helcom_cod_fisheries_closures": "HELCOM cod fisheries closures",
}

# Column names of the management pack's layer catalogue
# (Warstwy_i_liczebnosc.csv) -> English detail labels.
DETAIL_LABELS = {
    "znaczenie_1": "Meaning of 1",
    "zrodlo": "Source",
    "okres": "Period",
}


def mask_title(key: str) -> str:
    known = KNOWN_TITLES.get(key.lower())
    if known:
        return known
    text = re.sub(r"[_\-]+", " ", key).strip()
    return text[:1].upper() + text[1:]
