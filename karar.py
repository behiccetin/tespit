# -*- coding: utf-8 -*-
"""
karar.py  --  Ortak karar/görüntü yardımcıları (arayüzden bağımsız, çok dilli)
=====================================================================
Metinler dil.py üzerinden (diller/<kod>.json) gelir. tkinter'a bağımlı DEĞİLDİR.
"""

from __future__ import annotations
import dil


def karar_goruntu(puan: int):
    """Kural tabanlı şüphe puanına göre (etiket, arka_renk, yazi_renk, açıklama)."""
    if puan >= 60:
        return (dil.t("v_supheli"), "#c0392b", "#ffffff", dil.t("exp_supheli_strong"))
    if puan >= 30:
        return (dil.t("v_supheli"), "#e67e22", "#ffffff", dil.t("exp_supheli_mid"))
    if puan >= 10:
        return (dil.t("v_dikkat"), "#f1c40f", "#111111", dil.t("exp_dikkat"))
    return (dil.t("v_temiz"), "#27ae60", "#ffffff", dil.t("exp_temiz"))


# Teknik profil adını sade/yerelleştirilmiş metne çevirir.
_PROFIL_ANAHTAR = {
    "Orijinal MS Word": "src_word",
    "mat2 / python-docx (sentetik kütüphane)": "src_lib",
    "Basit Manipülatör Script": "src_basit",
    "Gelişmiş OOXML Simülatörü (Run-Splitter)": "src_gelismis",
}


def kaynak_sade(profil: str) -> str:
    anahtar = _PROFIL_ANAHTAR.get(profil)
    if anahtar:
        return dil.t(anahtar)
    # Excel/PowerPoint gibi "Orijinal Excel (xlsx)" türevleri olduğu gibi döner.
    return profil


# Uyarı anomali kodu -> dil anahtarı. Bunlar ana ekranda yerelleştirilmiş gösterilir.
_UYARI_ANAHTAR = {
    "L1_APP_LIB": "w_app_lib",
    "L1_APP_SAHTE_WORD": "w_app_sahte_word",
    "L1_APP_BILINMEYEN": "w_app_bilinmeyen",
    "L1_APP_YOK": "w_app_yok",
    "L3_HIZLI_YAZIM": "w_hizli_yazim",
    "L3_TIME_ZERO": "w_time_zero",
}


def uyari_metinleri(rep):
    """Belgedeki 'araç/yapıştırma/olası YZ' uyarılarını seçili dilde döndürür."""
    out = []
    for a in getattr(rep, "anomaliler", []):
        anahtar = _UYARI_ANAHTAR.get(a.code)
        if anahtar:
            out.append(dil.t(anahtar, **(a.params or {})))
    return out


def nihai_karar(rep, model=None):
    """
    Nihai 'TEMİZ/ŞÜPHELİ' kararı. İKİ kaynağı birleştirir (OR):
      * ML (ikili) 'Şüpheli' derse, VEYA
      * güçlü kural işaretleri (kesin/yüksek anomali ya da şüphe puanı >= 30).
    Döner: (etiket, arka_renk, yazi_renk, açıklama).
    """
    sert_kural = any(getattr(a, "severity", "") in ("kesin", "yuksek")
                     for a in getattr(rep, "anomaliler", []))
    kural_supheli = rep.supphe_puani >= 30 or sert_kural

    if model is None or not getattr(rep, "ml_tahmin", ""):
        return karar_goruntu(rep.supphe_puani)

    ml_supheli = (rep.ml_tahmin == "Şüpheli")
    if ml_supheli or kural_supheli:
        kirmizi = sert_kural or rep.supphe_puani >= 60 or (ml_supheli and rep.ml_guven >= 0.80)
        renk = "#c0392b" if kirmizi else "#e67e22"
        return (dil.t("v_supheli"), renk, "#ffffff", dil.t("exp_supheli"))
    return (dil.t("v_temiz"), "#27ae60", "#ffffff", dil.t("exp_temiz"))
