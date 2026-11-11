# -*- coding: utf-8 -*-
"""
batch_analyze.py
=====================================================================
Tespit  --  Toplu Analiz + CSV Rapor
---------------------------------------------------------------------
Bir klasördeki tüm .docx dosyalarını DeepForensicDetector (Katman 1-4) ve
varsa ForensicMLClassifier (Katman 5) ile analiz edip tek bir CSV raporu
üretir. CSV, Excel'de Türkçe karakterlerin düzgün görünmesi için utf-8-sig
(BOM) ile yazılır.

Kullanım:
    python batch_analyze.py "H:\\klasor" --out rapor.csv
    python batch_analyze.py "H:\\klasor" --recursive --model model.json
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from deep_detector import DeepForensicDetector, FEATURE_NAMES

CSV_BASLIKLAR = [
    "dosya", "supphe_puani", "karar", "en_olasi_profil",
    "ml_tahmin", "ml_guven",
    # Öne çıkan metrikler (hızlı gözden geçirme için):
    "no_rsid", "rpr_missing_ratio", "self_transition", "shannon_norm",
    "paraid_violation", "xml_single_quote", "zip_bad_date",
    "words_per_min", "multi_run_paras",
]


@dataclass
class BatchSonuc:
    satirlar: List[Dict[str, object]]
    toplam: int
    bayrakli: int        # orta+ şüphe (>=30)
    hata: int


def _docx_bul(klasor: str, recursive: bool) -> List[str]:
    bulunan = []
    uzantilar = (".docx", ".xlsx", ".pptx")
    if recursive:
        for kok, _dirs, files in os.walk(klasor):
            for fn in files:
                if fn.lower().endswith(uzantilar) and not fn.startswith(("~$", "_")):
                    bulunan.append(os.path.join(kok, fn))
    else:
        for fn in os.listdir(klasor):
            tam = os.path.join(klasor, fn)
            if os.path.isfile(tam) and fn.lower().endswith(uzantilar) \
                    and not fn.startswith(("~$", "_")):
                bulunan.append(tam)
    return sorted(bulunan)


def analyze_folder(
    klasor: str,
    out_csv: Optional[str] = None,
    model_path: Optional[str] = "model.json",
    recursive: bool = False,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> BatchSonuc:
    """Klasörü analiz eder; out_csv verilirse CSV yazar. progress(i, toplam, dosya)."""
    det = DeepForensicDetector()

    clf = None
    if model_path and os.path.isfile(model_path):
        try:
            from ml_classifier import ForensicMLClassifier
            clf = ForensicMLClassifier.load(model_path)
        except Exception:
            clf = None

    dosyalar = _docx_bul(klasor, recursive)
    satirlar: List[Dict[str, object]] = []
    bayrakli = hata = 0

    for i, path in enumerate(dosyalar, start=1):
        if progress:
            progress(i, len(dosyalar), os.path.basename(path))
        try:
            rep = det.analyze_docx(path)
            # Özellik vektörü ve ML yalnızca Word (docx) için anlamlıdır.
            try:
                feats = DeepForensicDetector.extract_features(path)
            except Exception:
                feats = {k: 0.0 for k in FEATURE_NAMES}
            ml_tahmin, ml_guven = "", ""
            if clf is not None:
                try:
                    etiket, guven, _ = clf.predict(path)
                    ml_tahmin, ml_guven = etiket, f"{guven:.3f}"
                except Exception:
                    pass
            satir = {
                "dosya": path,
                "supphe_puani": rep.supphe_puani,
                "karar": rep.karar,
                "en_olasi_profil": rep.en_olasi_profil,
                "ml_tahmin": ml_tahmin,
                "ml_guven": ml_guven,
                "no_rsid": int(feats["no_rsid_flag"]),
                "rpr_missing_ratio": round(feats["rpr_missing_ratio"], 3),
                "self_transition": round(feats["self_transition"], 3),
                "shannon_norm": round(feats["shannon_norm"], 3),
                "paraid_violation": int(feats["paraid_violation"]),
                "xml_single_quote": int(feats["xml_single_quote"]),
                "zip_bad_date": int(feats["zip_bad_date"]),
                "words_per_min": round(feats["words_per_min"], 1),
                "multi_run_paras": int(feats["multi_run_paras"]),
            }
            if rep.supphe_puani >= 30:
                bayrakli += 1
            satirlar.append(satir)
        except Exception as e:
            hata += 1
            satirlar.append({
                "dosya": path, "supphe_puani": "", "karar": f"HATA: {e}",
                "en_olasi_profil": "", "ml_tahmin": "", "ml_guven": "",
                "no_rsid": "", "rpr_missing_ratio": "", "self_transition": "",
                "shannon_norm": "", "paraid_violation": "", "xml_single_quote": "",
                "zip_bad_date": "", "words_per_min": "", "multi_run_paras": "",
            })

    if out_csv:
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            yazici = csv.DictWriter(f, fieldnames=CSV_BASLIKLAR)
            yazici.writeheader()
            for s in satirlar:
                yazici.writerow(s)

    return BatchSonuc(satirlar=satirlar, toplam=len(dosyalar),
                      bayrakli=bayrakli, hata=hata)


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Toplu .docx adli analiz + CSV rapor.")
    ap.add_argument("klasor", help="Taranacak klasör")
    ap.add_argument("--out", default="rapor.csv", help="CSV çıktı yolu")
    ap.add_argument("--model", default="model.json", help="Katman-5 ML modeli (ops.)")
    ap.add_argument("--recursive", action="store_true", help="Alt klasörleri de tara")
    args = ap.parse_args()

    def ilerle(i, n, ad):
        print(f"  [{i}/{n}] {ad}")

    sonuc = analyze_folder(args.klasor, out_csv=args.out, model_path=args.model,
                           recursive=args.recursive, progress=ilerle)
    print("-" * 60)
    print(f"Toplam dosya : {sonuc.toplam}")
    print(f"Bayraklı (>=30 şüphe): {sonuc.bayrakli}")
    print(f"Hatalı       : {sonuc.hata}")
    print(f"CSV raporu   : {args.out}")


if __name__ == "__main__":
    _cli()
