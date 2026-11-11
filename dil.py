# -*- coding: utf-8 -*-
"""
dil.py  --  Basit çok dilli (i18n) altyapı
=====================================================================
Çeviriler 'diller/<kod>.json' dosyalarında tutulur (tr.json, en.json...).
Yeni bir dil eklemek için diller/ klasörüne yeni bir JSON koymak yeterlidir;
koda dokunmaya gerek yoktur.

Kullanım:
    import dil
    dil.yukle("en")
    dil.t("v_temiz")                      -> "CLEAN"
    dil.t("folder_summary", n=5, m=2)     -> biçimlendirilmiş metin
"""

from __future__ import annotations
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DILLER_DIR = os.path.join(_HERE, "diller")

_katalog: dict = {}
_kod: str = "tr"
# Dil adları (seçicide gösterilir). Listede olmayan kod, kodun kendisiyle görünür.
_ADLAR = {"tr": "Türkçe", "en": "English"}


def mevcut_diller():
    """diller/ klasöründeki dilleri [(kod, ad), ...] olarak döndürür."""
    sonuc = []
    try:
        for fn in sorted(os.listdir(_DILLER_DIR)):
            if fn.lower().endswith(".json"):
                kod = fn[:-5]
                sonuc.append((kod, _ADLAR.get(kod, kod)))
    except Exception:
        pass
    if not sonuc:
        sonuc = [("tr", "Türkçe")]
    return sonuc


def yukle(kod: str) -> None:
    """Bir dili yükler. Dosya yoksa Türkçeye düşer."""
    global _katalog, _kod
    yol = os.path.join(_DILLER_DIR, f"{kod}.json")
    if not os.path.isfile(yol):
        kod = "tr"
        yol = os.path.join(_DILLER_DIR, "tr.json")
    try:
        with open(yol, "r", encoding="utf-8") as f:
            _katalog = json.load(f)
        _kod = kod
    except Exception:
        _katalog = {}
        _kod = "tr"


def gecerli_kod() -> str:
    return _kod


def t(anahtar: str, **kw) -> str:
    """Anahtarın çevirisini döndürür; yoksa anahtarın kendisini. kw ile biçimlendirir."""
    s = _katalog.get(anahtar, anahtar)
    if kw:
        try:
            return s.format(**kw)
        except Exception:
            return s
    return s


def var_mi(anahtar: str) -> bool:
    return anahtar in _katalog


# İlk içe aktarmada varsayılan dili yükle.
yukle("tr")
