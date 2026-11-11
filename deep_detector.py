# -*- coding: utf-8 -*-
"""
deep_detector.py
=====================================================================
Derin Adli Analiz Motoru (Deep Forensic Detector)
---------------------------------------------------------------------

Bir Office belgesinin üst verisindeki tutarsızlıkları dört katmanlı
analizle arar: hem basit iz-silici/otomasyon araçlarının (mat2,
python-docx vb.) bıraktığı izleri, hem de belgeyi elle yazılmış gibi
göstermeye çalışan daha gelişmiş müdahaleleri yakalamayı hedefler.

KATMANLAR:
  Katman 1 - Temel İmza:
      ZIP 1980 zaman damgası, OPC sıralaması, XML tırnak yapısı,
      w14:paraId 0x7FFFFFFF sınırı, RSID yokluğu, app.xml sayaç çapraz
      doğrulaması.
  Katman 2 - Dilbilimsel Run-Splitting:
      Biçimlendirme (w:rPr) değişmediği hâlde metnin noktalama/regex
      sınırlarından bölünme oranı: "Unjustified Run Fragmentation Index"
      (UFRI) + rPr yokluğu oranı.
  Katman 3 - RSID Geçiş Matrisi + Entropi + TotalTime:
      settings.xml ile document.xml arasındaki RSID tutarlılığı, RSID
      kullanım dağılımının Shannon entropisi, geçiş matrisi öz-geçiş
      (self-transition) oranı, Benford tarzı basamak dağılımı ve
      TotalTime / kelime korelasyonu.
  Katman 4 - Diferansiyel Profil Karşılaştırma:
      Toplanan sinyalleri bilinen araç profilleriyle (Orijinal Word,
      mat2/python-docx, Basit Script, Gelişmiş Simülatör) karşılaştırıp
      en olası kaynağı yüzdesel olarak raporlar.

ÖNEMLİ YORUM (bilimsel dürüstlük):
    Katman 1 sinyalleri YÜKSEK güvenilirliktedir (kesin spesifikasyon
    ihlalleri). Katman 2-3 sinyalleri İSTATİSTİKSEL göstergelerdir;
    tek başlarına "kesin kanıt" değil, "şüphe artırıcı" olarak
    yorumlanmalıdır. Benford analizi bu alanda zayıf bir sinyaldir ve
    yalnızca yardımcı gösterge olarak işaretlenir. Nihai karar, birden
    çok katmanın birikimli ağırlığına göre verilir.
"""

from __future__ import annotations

import math
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}

MS_WORD_DATE = (1980, 1, 1, 0, 0, 0)
PARAID_LIMIT = 0x80000000  # Bu değer ve üstü MS-DOCX spesifikasyonu ihlalidir.

# Sinyal ağırlıkları (şüphe puanına katkı). Katman 1 ihlalleri ağır basar.
SEVERITY = {"kesin": 40, "yuksek": 25, "orta": 12, "dusuk": 5, "bilgi": 0}

# Katman 5 (ML) için sabit sıralı sayısal özellik adları.
# extract_features() bu sırayla değer üretir; ml_classifier bu sırayı kullanır.
FEATURE_NAMES = [
    "rsid_run_count",         # document.xml run'larındaki rsidR adedi
    "rsid_unique",            # benzersiz rsidR adedi
    "shannon_norm",           # RSID dağılımı normalize entropi (0-1)
    "self_transition",        # ardışık run'larda öz-geçiş oranı (0-1)
    "rpr_missing_ratio",      # çoklu-run paragraflarda rPr yokluk oranı (0-1)
    "punct_aligned_ratio",    # noktalama-hizalı bölünme oranı (0-1)
    "ufri",                   # gerekçesiz run bölünme indeksi (0-1)
    "rsidp_eq_default_ratio", # rsidP == rsidRDefault oranı (0-1)
    "benford_chi2",           # run uzunlukları Benford sapması
    "words_per_min",          # kelime / TotalTime (yoksa 0)
    "declared_rsid",          # settings.xml'de bildirilen RSID adedi
    "used_rsid",              # document.xml'de kullanılan benzersiz RSID
    "declared_minus_used",    # bildirilen - kullanılan
    "zip_bad_date",           # ZIP tarihi 1980 değil (0/1)
    "xml_single_quote",       # XML bildirimi tek tırnak (0/1)
    "paraid_violation",       # w14:paraId > 0x7FFFFFFF (0/1)
    "wordcount_mismatch",     # |app.xml - gerçek| / gerçek
    "multi_run_paras",        # çoklu-run paragraf adedi
    "total_runs",             # çoklu-run paragraflardaki toplam run
    "no_rsid_flag",           # hiç rsidR yok (0/1)
]


# ---------------------------------------------------------------------------
# Veri yapıları
# ---------------------------------------------------------------------------
@dataclass
class Anomaly:
    layer: int
    code: str
    severity: str          # kesin | yuksek | orta | dusuk | bilgi
    message: str
    params: dict = field(default_factory=dict)  # çeviri için biçimlendirme değerleri

    def __str__(self) -> str:
        etiket = {
            1: "Katman-1 İmza",
            2: "Katman-2 Run-Splitting",
            3: "Katman-3 İstatistik",
            4: "Katman-4 Diferansiyel",
        }.get(self.layer, f"Katman-{self.layer}")
        return f"[{etiket} / {self.severity.upper()}] {self.message}"


@dataclass
class ForensicReport:
    dosya: str
    anomaliler: List[Anomaly] = field(default_factory=list)
    metrikler: Dict[str, object] = field(default_factory=dict)
    profil_skorlari: Dict[str, float] = field(default_factory=dict)
    en_olasi_profil: str = "Orijinal MS Word"
    supphe_puani: int = 0            # 0..100 arası normalize edilmiş
    karar: str = "Temiz"
    # Katman 5 (ML) alanları; model yüklüyse doldurulur.
    ml_tahmin: str = ""
    ml_guven: float = 0.0
    ml_olasiliklar: Dict[str, float] = field(default_factory=dict)

    def ekle(self, a: Anomaly) -> None:
        self.anomaliler.append(a)

    def to_text(self) -> str:
        satirlar = []
        satirlar.append("=" * 70)
        satirlar.append(f"ADLİ ANALİZ RAPORU : {self.dosya}")
        satirlar.append("=" * 70)
        satirlar.append(f"ŞÜPHE PUANI   : {self.supphe_puani}/100")
        satirlar.append(f"KARAR         : {self.karar}")
        satirlar.append(f"EN OLASI KAYNAK: {self.en_olasi_profil}")
        if self.ml_tahmin:
            satirlar.append(f"KATMAN-5 ML   : {self.ml_tahmin}  (güven %{self.ml_guven*100:.1f})")
        satirlar.append("")
        satirlar.append("PROFİL GÜVENİ (diferansiyel, bağımsız %):")
        for ad, skor in sorted(self.profil_skorlari.items(),
                               key=lambda x: x[1], reverse=True):
            bar = "#" * int(skor / 5)
            satirlar.append(f"  {ad:<34} %{skor:5.1f}  {bar}")
        satirlar.append("")
        if self.anomaliler:
            satirlar.append(f"TESPİT EDİLEN ANOMALİLER ({len(self.anomaliler)}):")
            for a in self.anomaliler:
                satirlar.append(f"  - {a}")
        else:
            satirlar.append("Anomali tespit edilmedi (Katman 1-3 temiz).")
        satirlar.append("")
        satirlar.append("ÖLÇÜLEN METRİKLER:")
        for k, v in self.metrikler.items():
            satirlar.append(f"  {k:<32}: {v}")
        satirlar.append("=" * 70)
        return "\n".join(satirlar)


# ---------------------------------------------------------------------------
# Dedektör
# ---------------------------------------------------------------------------
class DeepForensicDetector:
    """Dört katmanlı OOXML adli analiz motoru."""

    LINGUISTIC_BOUNDARY = (",", ".", ";", ":", "!", "?", "…")

    @staticmethod
    def _text_stats(doc_root) -> Tuple[int, int]:
        """
        Gerçek kelime/karakter sayısını paragraf bazında hesaplar.
        Her paragrafın w:t düğümleri ARALIKSIZ birleştirilir; aksi hâlde
        run-splitting sonrası düğümler arasına yapay boşluk girip sayım
        şişer (ölçüm artefaktı). Böylece app.xml karşılaştırması güvenilir olur.
        """
        words = 0
        chars = 0
        for p in doc_root.xpath("//w:p", namespaces=NS):
            metin = "".join(p.xpath(".//w:t/text()", namespaces=NS))
            words += len([w for w in metin.split() if w])
            chars += len(metin)
        return words, chars

    @staticmethod
    def extract_features(docx_path: str) -> "Dict[str, float]":
        """
        Belgeyi sayısal özellik vektörüne dönüştürür (Katman 5 / ML için).
        Eşik mantığından BAĞIMSIZDIR: tüm metrikleri her zaman hesaplar; böylece
        sınıflandırıcı ham sinyalleri görür. Sonuç, FEATURE_NAMES sırasına uyar.
        """
        import math as _math
        BOUND = DeepForensicDetector.LINGUISTIC_BOUNDARY
        f = {k: 0.0 for k in FEATURE_NAMES}

        with zipfile.ZipFile(docx_path, "r") as zf:
            names = zf.namelist()
            infolist = zf.infolist()
            raw_doc = zf.read("word/document.xml")
            doc_root = etree.fromstring(raw_doc)
            settings_root = (etree.fromstring(zf.read("word/settings.xml"))
                             if "word/settings.xml" in names else None)
            app_root = (etree.fromstring(zf.read("docProps/app.xml"))
                        if "docProps/app.xml" in names else None)

        # RSID temelli.
        run_rsids = [r.upper() for r in doc_root.xpath("//w:r/@w:rsidR", namespaces=NS)]
        f["rsid_run_count"] = float(len(run_rsids))
        uniq = set(run_rsids)
        f["rsid_unique"] = float(len(uniq))
        f["no_rsid_flag"] = 1.0 if len(run_rsids) == 0 else 0.0

        if run_rsids:
            sayac = Counter(run_rsids)
            toplam = sum(sayac.values())
            H = -sum((c / toplam) * _math.log2(c / toplam) for c in sayac.values())
            k = len(sayac)
            Hmax = _math.log2(k) if k > 1 else 1.0
            f["shannon_norm"] = (H / Hmax) if Hmax > 0 else 0.0
        if len(run_rsids) >= 2:
            oz = sum(1 for a, b in zip(run_rsids, run_rsids[1:]) if a == b)
            f["self_transition"] = oz / (len(run_rsids) - 1)

        # Paragraf / run yapısı.
        paras = doc_root.xpath("//w:p", namespaces=NS)
        multi = 0
        missing_rpr = 0
        punct_aligned = 0
        total_runs = 0
        unjustified = 0
        for p in paras:
            runs = p.xpath("./w:r", namespaces=NS)
            if len(runs) <= 1:
                continue
            multi += 1
            total_runs += len(runs)
            if not any(r.find(f"{{{NS['w']}}}rPr") is not None for r in runs):
                missing_rpr += 1
            pe = 0
            for r in runs:
                txt = "".join(r.xpath("./w:t/text()", namespaces=NS)).rstrip()
                if not txt:
                    continue
                if txt.endswith(BOUND):
                    pe += 1
                else:
                    unjustified += 1
            if runs and pe >= len(runs) * 0.6:
                punct_aligned += 1
        f["multi_run_paras"] = float(multi)
        f["total_runs"] = float(total_runs)
        if multi:
            f["rpr_missing_ratio"] = missing_rpr / multi
            f["punct_aligned_ratio"] = punct_aligned / multi
        if total_runs:
            f["ufri"] = unjustified / total_runs

        # rsidP == rsidRDefault.
        rp = doc_root.xpath("//w:p/@w:rsidP", namespaces=NS)
        rd = doc_root.xpath("//w:p/@w:rsidRDefault", namespaces=NS)
        if rp and rd:
            esit = sum(1 for a, b in zip(rp, rd) if a == b)
            f["rsidp_eq_default_ratio"] = esit / max(1, len(rp))

        # Benford (run uzunlukları).
        uz = []
        for r in doc_root.xpath("//w:r", namespaces=NS):
            t = "".join(r.xpath("./w:t/text()", namespaces=NS)).strip()
            if t:
                uz.append(len(t))
        if len(uz) >= 30:
            ilk = Counter(int(str(u)[0]) for u in uz if u > 0)
            tk = sum(ilk.values())
            chi = 0.0
            for d in range(1, 10):
                bek = _math.log10(1 + 1 / d)
                goz = ilk.get(d, 0) / tk
                chi += (goz - bek) ** 2 / bek
            f["benford_chi2"] = chi

        # RSID settings tutarlılığı.
        declared = set()
        if settings_root is not None:
            rsids_el = settings_root.find(f"{{{NS['w']}}}rsids")
            if rsids_el is not None:
                for el in rsids_el.findall(f"{{{NS['w']}}}rsid"):
                    v = el.get(f"{{{NS['w']}}}val")
                    if v:
                        declared.add(v.upper())
        f["declared_rsid"] = float(len(declared))
        f["used_rsid"] = float(len(uniq))
        f["declared_minus_used"] = float(len(declared) - len(uniq))

        # ZIP tarih / XML tırnak / paraId.
        f["zip_bad_date"] = 1.0 if any(i.date_time != MS_WORD_DATE for i in infolist) else 0.0
        f["xml_single_quote"] = 1.0 if b"version='1.0'" in raw_doc[:120] else 0.0
        pids = doc_root.xpath("//@w14:paraId", namespaces=NS)
        f["paraid_violation"] = 1.0 if any(
            len(pid) == 8 and int(pid, 16) >= PARAID_LIMIT for pid in pids) else 0.0

        # TotalTime / kelime, word mismatch.
        words, _ = DeepForensicDetector._text_stats(doc_root)
        total_time = None
        if app_root is not None:
            el = app_root.find(f"{{{NS['ep']}}}TotalTime")
            if el is not None and el.text and el.text.strip().isdigit():
                total_time = int(el.text.strip())
        if total_time is None and settings_root is not None:
            el = settings_root.find(f"{{{NS['w']}}}TotalTime")
            if el is not None and el.get(f"{{{NS['w']}}}val", "").isdigit():
                total_time = int(el.get(f"{{{NS['w']}}}val"))
        f["words_per_min"] = (words / total_time) if (total_time and total_time > 0) else 0.0

        recorded = 0
        if app_root is not None:
            wel = app_root.find(f"{{{NS['ep']}}}Words")
            if wel is not None and wel.text and wel.text.strip().isdigit():
                recorded = int(wel.text.strip())
        f["wordcount_mismatch"] = abs(recorded - words) / max(1, words)

        return f

    @staticmethod
    def feature_row(docx_path: str):
        """extract_features çıktısını FEATURE_NAMES sırasında düz listeye çevirir."""
        f = DeepForensicDetector.extract_features(docx_path)
        return [float(f[k]) for k in FEATURE_NAMES]

    @staticmethod
    def _ooxml_turu(namelist) -> str:
        if "word/document.xml" in namelist:
            return "docx"
        if "xl/workbook.xml" in namelist:
            return "xlsx"
        if "ppt/presentation.xml" in namelist:
            return "pptx"
        return "bilinmeyen"

    def analyze_docx(self, docx_path: str) -> ForensicReport:
        # Belge türünü belirle; Word değilse (Excel/PowerPoint) ortak OOXML analizi.
        with zipfile.ZipFile(docx_path, "r") as zf0:
            tur0 = self._ooxml_turu(zf0.namelist())
        if tur0 != "docx":
            return self._analyze_non_docx(docx_path, tur0)

        report = ForensicReport(dosya=docx_path)

        with zipfile.ZipFile(docx_path, "r") as zf:
            namelist = zf.namelist()
            infolist = zf.infolist()
            raw_doc = zf.read("word/document.xml")
            doc_root = etree.fromstring(raw_doc)
            settings_root = (
                etree.fromstring(zf.read("word/settings.xml"))
                if "word/settings.xml" in namelist else None
            )
            app_root = (
                etree.fromstring(zf.read("docProps/app.xml"))
                if "docProps/app.xml" in namelist else None
            )
            core_root = (
                etree.fromstring(zf.read("docProps/core.xml"))
                if "docProps/core.xml" in namelist else None
            )

            self._layer1_signatures(report, namelist, infolist, raw_doc,
                                    doc_root, app_root)
            self._layer2_run_splitting(report, doc_root)
            self._layer3_statistics(report, doc_root, settings_root, app_root)
            self._check_dates(report, core_root, app_root)
            _rsid_var = len(doc_root.xpath("//w:r/@w:rsidR", namespaces=NS)) > 0
            self._uretim_izi(report, app_root, core_root, docx_rsid_var=_rsid_var)

        report.metrikler["Belge türü"] = "Word (docx)"
        # Katman 4 toplanan tüm sinyalleri kullanır.
        self._layer4_differential(report)
        self._finalize(report)
        return report

    # =======================================================================
    # EXCEL / POWERPOINT (ortak OOXML analizi; RSID/run yok)
    # =======================================================================
    def _analyze_non_docx(self, path: str, tur: str) -> ForensicReport:
        report = ForensicReport(dosya=path)
        ad = {"xlsx": "Excel (xlsx)", "pptx": "PowerPoint (pptx)"}.get(tur, tur)
        report.metrikler["Belge türü"] = ad
        ana_parca = {"xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}.get(tur, "")

        with zipfile.ZipFile(path, "r") as zf:
            namelist = zf.namelist()
            infolist = zf.infolist()
            raw_main = zf.read(ana_parca) if ana_parca in namelist else b""
            app_root = (etree.fromstring(zf.read("docProps/app.xml"))
                        if "docProps/app.xml" in namelist else None)
            core_root = (etree.fromstring(zf.read("docProps/core.xml"))
                         if "docProps/core.xml" in namelist else None)

        # Ortak Katman-1 imzaları (Word'e özgü olmayanlar).
        if any(i.date_time != MS_WORD_DATE for i in infolist):
            report.ekle(Anomaly(1, "L1_ZIP_DATE", "orta",
                "ZIP iç tarihleri 1980-01-01 değil; harici araçla paketlenmiş."))
        else:
            report.metrikler["ZIP tarihleri"] = "Tümü 1980-01-01"
        if namelist and namelist[0] != "[Content_Types].xml":
            report.ekle(Anomaly(1, "L1_OPC_ORDER", "orta",
                "[Content_Types].xml ilk sırada değil (OPC sırası bozuk)."))
        if b"version='1.0'" in raw_main[:120]:
            report.ekle(Anomaly(1, "L1_XML_QUOTE", "yuksek",
                "XML bildiriminde tek tırnak var (lxml/Python serileştirme izi)."))

        # core.xml tarih tutarlılığı (ortak).
        self._check_dates(report, core_root, app_root)
        # Üretim izi (oluşturan uygulama / otomatik araç şüphesi).
        self._uretim_izi(report, app_root, core_root)

        # Diferansiyel ML/profil docx'e özgü; burada kural tabanlı kalır.
        report.profil_skorlari = {}
        self._finalize(report)
        if report.supphe_puani < 10:
            report.en_olasi_profil = f"Orijinal {ad}"
            report.karar = f"TEMİZ: {ad} için belirgin manipülasyon izi yok"
        else:
            report.en_olasi_profil = f"Şüpheli {ad}"
        return report

    # =======================================================================
    # KATMAN 1 : Temel İmza
    # =======================================================================
    def _layer1_signatures(self, report, namelist, infolist, raw_doc,
                           doc_root, app_root) -> None:
        # 1A. RSID yokluğu (mat2 / python-docx / Pandoc).
        rsids_in_doc = doc_root.xpath("//@w:rsidR", namespaces=NS)
        report.metrikler["document.xml RSID adedi"] = len(rsids_in_doc)
        if len(rsids_in_doc) == 0:
            report.ekle(Anomaly(
                1, "L1_NO_RSID", "yuksek",
                "Belgede hiç RSID yok (mat2, python-docx veya Pandoc izi)."
            ))

        # 1B. ZIP iç tarihleri 1980-01-01 değil (harici script paketlemesi).
        kotu_tarih = [i.filename for i in infolist if i.date_time != MS_WORD_DATE]
        if kotu_tarih:
            report.ekle(Anomaly(
                1, "L1_ZIP_DATE", "orta",
                f"ZIP iç tarihleri 1980-01-01 değil ({len(kotu_tarih)} dosya); "
                "harici araçla paketlenmiş."
            ))
        else:
            report.metrikler["ZIP tarihleri"] = "Tümü 1980-01-01 (Word standardı veya sahtecilik izi olabilir)"

        # 1C. OPC sıralaması: [Content_Types].xml ilk sırada mı?
        if namelist and namelist[0] != "[Content_Types].xml":
            report.ekle(Anomaly(
                1, "L1_OPC_ORDER", "orta",
                "[Content_Types].xml ZIP'in ilk girdisi değil (OPC sırası bozuk)."
            ))

        # 1D. XML bildirimi tek tırnak (lxml izi).
        bas = raw_doc[:120]
        if b"version='1.0'" in bas:
            report.ekle(Anomaly(
                1, "L1_XML_QUOTE", "yuksek",
                "XML bildiriminde tek tırnak var (lxml/Python serileştirme izi)."
            ))
        if b"standalone=" not in bas:
            report.ekle(Anomaly(
                1, "L1_XML_DECL", "dusuk",
                "XML bildiriminde standalone özniteliği yok (Word bunu yazar)."
            ))

        # 1E. w14:paraId 0x7FFFFFFF sınır ihlali (rastgele HEX üreteci).
        para_ids = doc_root.xpath("//@w14:paraId", namespaces=NS)
        ihlal = [pid for pid in para_ids if len(pid) == 8 and int(pid, 16) >= PARAID_LIMIT]
        if ihlal:
            report.ekle(Anomaly(
                1, "L1_PARAID_RANGE", "kesin",
                f"w14:paraId 0x7FFFFFFF sınırını aşıyor ({len(ihlal)} adet); "
                "rastgele HEX üreteci kesin izi."
            ))

        # 1F. app.xml kelime sayacı çapraz doğrulaması.
        if app_root is not None:
            words_el = app_root.find(f"{{{NS['ep']}}}Words")
            if words_el is not None and words_el.text and words_el.text.isdigit():
                kayitli = int(words_el.text)
                gercek, _ = self._text_stats(doc_root)
                report.metrikler["app.xml Words / gerçek"] = f"{kayitli} / {gercek}"
                tolerans = max(20, gercek * 0.25)
                if abs(kayitli - gercek) > tolerans:
                    report.ekle(Anomaly(
                        1, "L1_WORDCOUNT", "orta",
                        f"app.xml kelime sayısı ({kayitli}) ile gerçek metin "
                        f"({gercek}) uyuşmuyor."
                    ))

    # =======================================================================
    # KATMAN 2 : Dilbilimsel Run-Splitting (UFRI)
    # =======================================================================
    def _layer2_run_splitting(self, report, doc_root) -> None:
        paras = doc_root.xpath("//w:p", namespaces=NS)
        multi_run_paras = 0
        missing_rpr_paras = 0
        punct_aligned_paras = 0
        total_runs = 0
        unjustified_breaks = 0  # bir run'ın dilbilimsel sınırda bitmemesi

        for p in paras:
            runs = p.xpath("./w:r", namespaces=NS)
            if len(runs) <= 1:
                continue
            multi_run_paras += 1
            total_runs += len(runs)

            # rPr yokluğu: gerçek Word'de run'larda genelde rPr (font/dil) olur.
            has_any_rpr = any(r.find(f"{{{NS['w']}}}rPr") is not None for r in runs)
            if not has_any_rpr:
                missing_rpr_paras += 1

            # Her run'ın bitiş karakterine bak.
            punct_endings = 0
            for r in runs:
                txt = "".join(r.xpath("./w:t/text()", namespaces=NS)).rstrip()
                if not txt:
                    continue
                if txt.endswith(self.LINGUISTIC_BOUNDARY):
                    punct_endings += 1
                else:
                    unjustified_breaks += 1
            if runs and punct_endings >= len(runs) * 0.6:
                punct_aligned_paras += 1

        report.metrikler["Çoklu-run paragraf"] = multi_run_paras
        report.metrikler["Toplam run"] = total_runs

        if multi_run_paras == 0:
            return

        # rPr yokluğu oranı.
        rpr_missing_ratio = missing_rpr_paras / multi_run_paras
        report.metrikler["rPr-kayıp oranı"] = f"{rpr_missing_ratio:.2f}"
        if rpr_missing_ratio > 0.7:
            report.ekle(Anomaly(
                2, "L2_NO_RPR", "yuksek",
                f"Çoklu <w:r> bloklarının %{rpr_missing_ratio*100:.0f}'inde <w:rPr> "
                "(biçim/dil) alt etiketi yok; metin algoritmik olarak parçalanmış."
            ))

        # Noktalama hizalı bölünme oranı.
        punct_ratio = punct_aligned_paras / multi_run_paras
        report.metrikler["Noktalama-hizalı bölünme"] = f"{punct_ratio:.2f}"
        if punct_ratio > 0.5:
            report.ekle(Anomaly(
                2, "L2_PUNCT_SPLIT", "orta",
                f"<w:r> kırılmaları %{punct_ratio*100:.0f} oranında regex noktalama "
                "sınırlarıyla örtüşüyor (insan klavye duraksaması değil)."
            ))

        # UFRI: run'ların dilbilimsel sınırda bitme oranı.
        # Gerçek Word'de run sınırları biçim/imla değişimiyle oluşur ve çoğu run
        # dilbilimsel sınırda BİTMEZ. Simülatör ise bilerek noktalamada böler;
        # bu da "gerekçesiz parçalanma" oranını DÜŞÜRÜR (çok düzenli bölünme).
        if total_runs > 0:
            ufri = unjustified_breaks / total_runs
            report.metrikler["UFRI (gerekçesiz bölünme oranı)"] = f"{ufri:.2f}"
            # Çok düşük UFRI = bölünmeler fazla "temiz"/kurallı = yapay.
            if multi_run_paras >= 3 and ufri < 0.25:
                report.ekle(Anomaly(
                    2, "L2_UFRI_LOW", "orta",
                    f"UFRI çok düşük ({ufri:.2f}); run sınırları doğal düzenleme "
                    "yerine kurallı (regex) bölünme gösteriyor."
                ))

    # =======================================================================
    # KATMAN 3 : RSID Geçiş Matrisi + Entropi + TotalTime
    # =======================================================================
    def _layer3_statistics(self, report, doc_root, settings_root, app_root) -> None:
        run_rsids = doc_root.xpath("//w:r/@w:rsidR", namespaces=NS)
        para_rsidP = doc_root.xpath("//w:p/@w:rsidP", namespaces=NS)
        para_rsidRDef = doc_root.xpath("//w:p/@w:rsidRDefault", namespaces=NS)

        # 3A. settings vs document RSID tutarlılığı.
        declared = set()
        if settings_root is not None:
            rsids_el = settings_root.find(f"{{{NS['w']}}}rsids")
            if rsids_el is not None:
                for el in rsids_el.findall(f"{{{NS['w']}}}rsid"):
                    val = el.get(f"{{{NS['w']}}}val")
                    if val:
                        declared.add(val.upper())
        used = set(r.upper() for r in run_rsids)
        report.metrikler["Bildirilen RSID (settings)"] = len(declared)
        report.metrikler["Kullanılan RSID (document)"] = len(used)

        # python-docx / şablon izi: settings RSID bildirir ama body'de hiç
        # kullanılmaz. Gerçek Word'de bildirilen RSID'ler body'de karşılık bulur.
        if declared and len(used) == 0:
            report.ekle(Anomaly(
                3, "L3_RSID_UNUSED", "yuksek",
                f"settings.xml {len(declared)} RSID bildiriyor ama document.xml "
                "run'larında hiç kullanılmamış (python-docx/şablon üretimi izi)."
            ))

        if declared and used:
            # Gerçek Word'de settings genelde document'tan FAZLA RSID barındırır
            # (silinmiş/geçmiş oturumlar). Birebir eşitlik = sentetik üretim izi.
            kesisim = declared & used
            if declared == used and len(declared) <= 8:
                report.ekle(Anomaly(
                    3, "L3_RSID_EXACT", "orta",
                    f"settings.xml ve document.xml RSID kümeleri birebir aynı "
                    f"({len(declared)} adet); doğal düzenleme geçmişi yok."
                ))
            orphan = used - declared
            if orphan:
                report.ekle(Anomaly(
                    3, "L3_RSID_ORPHAN", "dusuk",
                    f"{len(orphan)} RSID document'ta var ama settings'te bildirilmemiş."
                ))

        # 3B. rsidP == rsidRDefault aşırı örtüşmesi (simülatör hepsini eşitler).
        if para_rsidP and para_rsidRDef:
            esit = sum(1 for a, b in zip(para_rsidP, para_rsidRDef) if a == b)
            oran = esit / max(1, len(para_rsidP))
            report.metrikler["rsidP==rsidRDefault oranı"] = f"{oran:.2f}"
            if len(para_rsidP) >= 4 and oran > 0.95:
                report.ekle(Anomaly(
                    3, "L3_RSID_UNIFORM", "orta",
                    f"Paragrafların %{oran*100:.0f}'inde rsidP == rsidRDefault; "
                    "Word'de paragraf işareti ve içerik oturumları genelde ayrışır."
                ))

        # 3C. Shannon entropisi (RSID kullanım dağılımı).
        if run_rsids:
            sayac = Counter(r.upper() for r in run_rsids)
            toplam = sum(sayac.values())
            H = -sum((c / toplam) * math.log2(c / toplam) for c in sayac.values())
            k = len(sayac)
            Hmax = math.log2(k) if k > 1 else 1.0
            norm = H / Hmax if Hmax > 0 else 0.0
            report.metrikler["RSID Shannon entropisi"] = f"{H:.3f} bit"
            report.metrikler["Normalize entropi (0-1)"] = f"{norm:.3f}"
            # Markov %85/%15 dağılımı belirgin bir orta-bant entropi üretir:
            # tek bir RSID baskın, kalanlar seyrek. Bunu bilgi olarak raporla.
            self._entropy_judgement(report, norm, k)

        # 3D. RSID geçiş matrisi: ardışık run'lar arası öz-geçiş oranı.
        if len(run_rsids) >= 4:
            gecis = defaultdict(int)
            oz_gecis = 0
            toplam_gecis = 0
            for a, b in zip(run_rsids, run_rsids[1:]):
                gecis[(a.upper(), b.upper())] += 1
                toplam_gecis += 1
                if a.upper() == b.upper():
                    oz_gecis += 1
            oz_oran = oz_gecis / max(1, toplam_gecis)
            report.metrikler["RSID öz-geçiş oranı"] = f"{oz_oran:.2f}"
            # Markov simülatörü ~0.85 öz-geçiş hedefler. 0.80-0.92 bandı +
            # tek baskın RSID, mühendislik ürünü kümelenmenin parmak izidir.
            if 0.78 <= oz_oran <= 0.93 and len(set(run_rsids)) <= 8:
                report.ekle(Anomaly(
                    3, "L3_MARKOV", "yuksek",
                    f"RSID öz-geçiş oranı ({oz_oran:.2f}) dar Markov bandında ve "
                    "oturum sayısı az; yapay 'kümelenmiş' RSID dağılımı işareti."
                ))

        # 3E. Benford tarzı basamak dağılımı (YARDIMCI/zayıf sinyal).
        self._benford_auxiliary(report, doc_root)

        # 3F. TotalTime / kelime korelasyonu.
        self._total_time_check(report, settings_root, app_root, doc_root)

    def _entropy_judgement(self, report, norm, k) -> None:
        # Not: Tek başına karar vermez; profil skorlamasına girdi olur.
        if k >= 2 and 0.15 <= norm <= 0.55:
            report.ekle(Anomaly(
                3, "L3_ENTROPY_BAND", "dusuk",
                f"RSID normalize entropisi ({norm:.2f}) tek-baskın-oturum bandında; "
                "yapay kümelenme ile uyumlu (zayıf sinyal)."
            ))

    def _benford_auxiliary(self, report, doc_root) -> None:
        """
        Benford yasası bu alanda ZAYIF bir sinyaldir ve yalnızca yardımcı
        gösterge olarak işaretlenir. Run metin uzunluklarının ilk basamak
        dağılımına bakarız; doğal metinde 1-2-3 baskınken, kurallı (noktalama)
        bölünmede dağılım bozulabilir. Kesin kanıt DEĞİLDİR.
        """
        uzunluklar = []
        for r in doc_root.xpath("//w:r", namespaces=NS):
            txt = "".join(r.xpath("./w:t/text()", namespaces=NS)).strip()
            if txt:
                uzunluklar.append(len(txt))
        if len(uzunluklar) < 30:
            return
        ilk = Counter(int(str(u)[0]) for u in uzunluklar if u > 0)
        toplam = sum(ilk.values())
        # Benford beklenen P(d) = log10(1 + 1/d)
        beklenen = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
        ki_kare = 0.0
        for d in range(1, 10):
            gozlenen = ilk.get(d, 0) / toplam
            ki_kare += (gozlenen - beklenen[d]) ** 2 / beklenen[d]
        report.metrikler["Benford χ² (run uzunlukları)"] = f"{ki_kare:.3f}"
        # Yüksek sapma = olası kurallı bölünme. Sadece 'bilgi' seviyesinde.
        if ki_kare > 0.30:
            report.ekle(Anomaly(
                3, "L3_BENFORD", "dusuk",
                f"Run uzunlukları Benford beklentisinden sapıyor (χ²={ki_kare:.2f}); "
                "yardımcı/zayıf gösterge, tek başına kanıt değildir."
            ))

    def _total_time_check(self, report, settings_root, app_root, doc_root) -> None:
        total_time = None
        # Önce app.xml, sonra settings.xml.
        if app_root is not None:
            el = app_root.find(f"{{{NS['ep']}}}TotalTime")
            if el is not None and el.text and el.text.strip().isdigit():
                total_time = int(el.text.strip())
        if total_time is None and settings_root is not None:
            el = settings_root.find(f"{{{NS['w']}}}TotalTime")
            if el is not None:
                val = el.get(f"{{{NS['w']}}}val")
                if val and val.isdigit():
                    total_time = int(val)

        kelime, _ = self._text_stats(doc_root)
        report.metrikler["TotalTime (dk)"] = total_time if total_time is not None else "yok"

        if total_time is None:
            return
        if kelime < 50:
            return
        # Kaba beklenti: ~15-40 kelime/dk yazım + düzenleme payı.
        # TotalTime == 0 veya kelime başına çok küçük => şüpheli.
        kelime_per_dk = kelime / max(1, total_time)
        report.metrikler["Kelime/dakika"] = f"{kelime_per_dk:.1f}"
        if total_time == 0 and kelime > 100:
            report.ekle(Anomaly(
                3, "L3_TIME_ZERO", "orta",
                f"TotalTime=0 ama {kelime} kelime var; düzenleme süresi sıfırlanmış.",
                params={"kelime": kelime}
            ))
        elif kelime >= 100 and kelime_per_dk > 120:
            report.ekle(Anomaly(
                3, "L3_HIZLI_YAZIM", "orta",
                f"Belge çok kısa sürede yazılmış görünüyor (TotalTime={total_time} dk, "
                f"{kelime} kelime; dakikada ~{kelime_per_dk:.0f} kelime). Bu hızda elle "
                "yazılamaz; içerik dışarıdan YAPIŞTIRILMIŞ olabilir (kopyala-yapıştır veya "
                "yapay zekâ metni). Kesin değildir, ELLE İNCELEYİN.",
                params={"dk": total_time, "kelime": kelime, "hiz": round(kelime_per_dk)}
            ))
        elif kelime_per_dk > 60:
            report.ekle(Anomaly(
                3, "L3_TIME_FAST", "dusuk",
                f"Kelime/dakika ({kelime_per_dk:.0f}) insan yazımı için yüksek; "
                "TotalTime gerçekçi değil."
            ))
        elif abs(kelime_per_dk - 33.3) < 0.5:
            # Simülatörün 100 kelime/3 dk = 33.3 kuralının parmak izi.
            report.ekle(Anomaly(
                3, "L3_TIME_SYNTHETIC", "orta",
                "Kelime/dakika oranı tam 33.3 civarında; formülle üretilmiş "
                "TotalTime işareti."
            ))

        # Aşırı YAVAŞ / şişirilmiş TotalTime: içeriğe göre imkânsız derecede uzun süre.
        if total_time and kelime >= 30 and (total_time / kelime) > 10:
            dk_kelime = total_time / kelime
            report.ekle(Anomaly(
                3, "L3_TIME_SLOW", "yuksek",
                f"Düzenleme süresi içeriğe göre aşırı yüksek (~{dk_kelime:.0f} dk/kelime, "
                f"{kelime} kelime için {total_time} dk); TotalTime elle şişirilmiş olabilir."
            ))

    # =======================================================================
    # TARİH TUTARLILIĞI (core.xml) - elle girilmiş tarihleri yakalar
    # =======================================================================
    def _check_dates(self, report, core_root, app_root) -> None:
        """core.xml oluşturma/değiştirme tarihlerinde mantık hatası arar.
        Elle (manuel) girilmiş tutarsız tarihleri bu katman yakalar."""
        from datetime import datetime, timezone

        def parse(tag):
            if core_root is None:
                return None
            el = core_root.find(f"{{{NS['dcterms']}}}{tag}")
            if el is None or not el.text:
                return None
            s = el.text.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                return None

        created = parse("created")
        modified = parse("modified")
        if created:
            report.metrikler["Belge oluşturma"] = created.strftime("%Y-%m-%d %H:%M")
        if modified:
            report.metrikler["Belge değiştirme"] = modified.strftime("%Y-%m-%d %H:%M")

        simdi = datetime.now(timezone.utc)

        # 1) değiştirme < oluşturma => imkânsız.
        if created and modified and modified < created:
            report.ekle(Anomaly(
                1, "L1_DATE_ORDER", "yuksek",
                "Değiştirme tarihi oluşturma tarihinden ÖNCE; tarih elle oynanmış."
            ))
        # 2) gelecek tarih.
        for ad, dt in [("oluşturma", created), ("değiştirme", modified)]:
            if dt and dt > simdi:
                report.ekle(Anomaly(
                    1, "L1_DATE_FUTURE", "orta",
                    f"Belge {ad} tarihi gelecekte ({dt.strftime('%Y-%m-%d')}); tutarsız."
                ))
        # 3) TotalTime, takvim aralığından büyük olamaz.
        total_time = None
        if app_root is not None:
            el = app_root.find(f"{{{NS['ep']}}}TotalTime")
            if el is not None and el.text and el.text.strip().isdigit():
                total_time = int(el.text.strip())
        if created and modified and total_time:
            span_dk = (modified - created).total_seconds() / 60.0
            if span_dk >= 0 and total_time > span_dk + 1:
                report.ekle(Anomaly(
                    3, "L3_TIME_SPAN", "orta",
                    f"Düzenleme süresi ({total_time} dk) takvim aralığından "
                    f"({span_dk:.0f} dk) büyük; süre/tarih çelişiyor."
                ))

    # =======================================================================
    # ÜRETİM İZİ (oluşturan uygulama / otomatik araç şüphesi)
    # =======================================================================
    # İnsanın elle yazdığı editörler (uyarı ÇIKMAZ):
    _EDITORLER = ["microsoft office word", "microsoft word", "microsoft macintosh word",
                  "libreoffice", "openoffice", "wps", "pages", "google", "polaris",
                  "onlyoffice", "calligra", "softmaker", "hancom"]
    # Programlama kütüphaneleri (insan elle yazmamış; otomatik/olası YZ üretimi):
    _KUTUPHANELER = ["python-docx", "aspose", "apache poi", "poi ", "docx4j",
                     "openxml", "open xml", "spire", "phpword", "gembox",
                     "syncfusion", "telerik", "jacob", "docxtemplater", "officegen"]

    def _uretim_izi(self, report, app_root, core_root, docx_rsid_var=None) -> None:
        """
        Oluşturan uygulamaya bakarak belgenin elle mi yazıldığını yoksa bir
        araçla/kütüphaneyle mi üretildiğini değerlendirir. 'YZ kesin kullanılmış'
        DEMEZ; yalnızca 'otomatik araçla üretilmiş olabilir, elle inceleyin' der.
        """
        def ep(root, tag):
            if root is None:
                return None
            el = root.find(f"{{{NS['ep']}}}{tag}")
            return el.text.strip() if (el is not None and el.text) else None

        app = ep(app_root, "Application")
        appver = ep(app_root, "AppVersion")
        company = ep(app_root, "Company")

        creator = lastmod = None
        if core_root is not None:
            c = core_root.find(f"{{{NS['dc']}}}creator")
            creator = c.text.strip() if (c is not None and c.text) else None
            m = core_root.find(f"{{{NS['cp']}}}lastModifiedBy")
            lastmod = m.text.strip() if (m is not None and m.text) else None

        report.metrikler["Oluşturan uygulama"] = app or "(belirtilmemiş)"
        if appver:
            report.metrikler["Uygulama sürümü"] = appver
        if company:
            report.metrikler["Şirket"] = company
        if creator:
            report.metrikler["Oluşturan"] = creator
        if lastmod:
            report.metrikler["Son değiştiren"] = lastmod

        a = (app or "").lower()
        if app:
            if any(k in a for k in self._KUTUPHANELER):
                report.ekle(Anomaly(
                    1, "L1_APP_LIB", "orta",
                    f"Belge bir programlama kütüphanesiyle üretilmiş görünüyor "
                    f"(uygulama: {app}); insan tarafından elle yazılmamış olabilir. "
                    "Otomatik / olası yapay zekâ üretimi açısından ELLE İNCELEYİN.",
                    params={"app": app}))
            elif not any(e in a for e in self._EDITORLER):
                report.ekle(Anomaly(
                    1, "L1_APP_BILINMEYEN", "dusuk",
                    f"Belge bilinen bir Office editörüyle üretilmemiş görünüyor "
                    f"(uygulama: {app}); elle inceleyin.",
                    params={"app": app}))
            elif docx_rsid_var is False:
                # Word olduğunu iddia ediyor ama hiç düzenleme izi (RSID) yok:
                # python-docx gibi araçlar şablonun 'Microsoft Word' etiketini taşır.
                report.ekle(Anomaly(
                    1, "L1_APP_SAHTE_WORD", "orta",
                    f"Uygulama '{app}' diyor ama belgede hiç düzenleme izi (RSID) yok; "
                    "Word'de elle yazılmamış, bir araçla üretilmiş olabilir. ELLE İNCELEYİN.",
                    params={"app": app}))
        else:
            report.ekle(Anomaly(
                1, "L1_APP_YOK", "dusuk",
                "Oluşturan uygulama bilgisi yok; belge standart bir editörle "
                "kaydedilmemiş olabilir, elle inceleyin."))

    # =======================================================================
    # KATMAN 4 : Diferansiyel Profil Karşılaştırma
    # =======================================================================
    # Hangi kod hangi araç ailesini işaret eder (şiddet ağırlığıyla puanlanır).
    # L1_* = yüzeysel imza (basit araçlar); L2_*/L3_* = derin istatistik
    # (gelişmiş simülatör, çünkü yüzeysel izleri kapatır ama bunları bırakır).
    _SIMPLE_L1 = ["L1_ZIP_DATE", "L1_XML_QUOTE", "L1_PARAID_RANGE",
                  "L1_OPC_ORDER", "L1_WORDCOUNT", "L1_XML_DECL"]
    _LIBRARY = ["L1_NO_RSID", "L2_NO_RPR", "L3_RSID_UNUSED"]
    _ADVANCED = ["L2_NO_RPR", "L2_PUNCT_SPLIT", "L2_UFRI_LOW",
                 "L3_MARKOV", "L3_RSID_EXACT", "L3_RSID_UNIFORM",
                 "L3_ENTROPY_BAND", "L3_TIME_SYNTHETIC", "L3_TIME_ZERO"]
    # Gelişmiş simülatöre özgü, basit araçlarda ASLA görülmeyen ayırt edici kodlar.
    _ADV_SIGNATURE = ["L3_MARKOV", "L3_RSID_EXACT", "L3_RSID_UNIFORM"]

    _SEV_W = {"kesin": 4, "yuksek": 3, "orta": 2, "dusuk": 1, "bilgi": 0}

    def _layer4_differential(self, report) -> None:
        """
        Toplanan anomali kodlarını, şiddet ağırlıklı ve BİRBİRİNDEN BAĞIMSIZ
        güven yüzdeleriyle bilinen araç profillerine eşler. Yüzdeler toplamı
        100'e zorlanmaz; her biri "bu aracın ürettiğine dair güven" olarak
        okunur (okunurluk için 0-100 aralığında).

        Aile ayrımı:
          - Yalnızca L1_* sinyalleri  -> basit araçlar (script / kütüphane).
          - L2_*/L3_* sinyalleri      -> gelişmiş simülatör (yüzeyi temiz).
          - Hiç sinyal yok            -> Orijinal MS Word.
        NOT: "mat2", "python-docx" ve "basit script" imza paylaştığından bu üçü
        arasındaki ayrım yaklaşıktır; aile düzeyi ayrım ise güçlüdür.
        """
        kodlar = {a.code: a.severity for a in report.anomaliler}

        def w(code: str) -> int:
            return self._SEV_W.get(kodlar.get(code, "bilgi"), 0) if code in kodlar else 0

        def puan(kod_listesi: List[str]) -> int:
            return sum(w(c) for c in kod_listesi)

        adv_pts = puan(self._ADVANCED)
        simple_pts = puan(self._SIMPLE_L1)
        lib_pts = puan(self._LIBRARY)
        adv_sig = puan(self._ADV_SIGNATURE)   # ayırt edici gelişmiş imza
        toplam_kanit = sum(self._SEV_W.get(s, 0) for s in kodlar.values())

        # Gelişmiş simülatör güveni: derin sinyaller; ayırt edici imza bonuslu.
        conf_adv = min(100.0, adv_pts * 11.0 + adv_sig * 6.0)

        # Basit script güveni: L1 imzaları.
        conf_simple = min(100.0, simple_pts * 15.0)

        # Kütüphane (mat2/python-docx): NO_RSID / NO_RPR / RSID_UNUSED.
        conf_lib = min(100.0, lib_pts * 16.0)
        # Ayırt edici gelişmiş imza varsa, bu bir kütüphane DEĞİLDİR (RSID yapısı var).
        if adv_sig > 0:
            conf_lib *= 0.25

        # Orijinal Word güveni: her kanıt tabanı düşürür.
        conf_word = max(0.0, 100.0 - toplam_kanit * 12.0)

        skorlar = {
            "Orijinal MS Word": round(conf_word, 1),
            "mat2 / python-docx (sentetik kütüphane)": round(conf_lib, 1),
            "Basit Manipülatör Script": round(conf_simple, 1),
            "Gelişmiş OOXML Simülatörü (Run-Splitter)": round(conf_adv, 1),
        }
        report.profil_skorlari = skorlar
        report.en_olasi_profil = max(skorlar, key=skorlar.get)

    # =======================================================================
    # Nihai karar
    # =======================================================================
    def _finalize(self, report) -> None:
        puan = sum(SEVERITY.get(a.severity, 0) for a in report.anomaliler)
        report.supphe_puani = min(100, puan)

        if report.supphe_puani >= 60:
            report.karar = "YÜKSEK ŞÜPHE: Manipülasyon güçlü biçimde muhtemel"
        elif report.supphe_puani >= 30:
            report.karar = "ORTA ŞÜPHE: Sentetik/manipüle izleri mevcut"
        elif report.supphe_puani >= 10:
            report.karar = "DÜŞÜK ŞÜPHE: Zayıf göstergeler var"
        else:
            report.karar = "TEMİZ: Belirgin manipülasyon izi yok"

        # Orijinal Word profili baskınsa kararı yumuşat.
        if (report.en_olasi_profil == "Orijinal MS Word"
                and report.supphe_puani < 10):
            report.karar = "TEMİZ: Orijinal MS Word profiliyle uyumlu"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        description="Tespit: Derin OOXML adli analiz motoru."
    )
    ap.add_argument("docx", help="Analiz edilecek .docx")
    ap.add_argument("--model", default="model.json",
                    help="Katman-5 ML model dosyası (varsa yüklenir)")
    args = ap.parse_args()
    det = DeepForensicDetector()
    rep = det.analyze_docx(args.docx)
    # Katman 5: model varsa ML tahminini ekle.
    try:
        import os as _os
        if _os.path.isfile(args.model):
            from ml_classifier import ForensicMLClassifier
            clf = ForensicMLClassifier.load(args.model)
            etiket, guven, olas = clf.predict(args.docx)
            rep.ml_tahmin, rep.ml_guven, rep.ml_olasiliklar = etiket, guven, olas
    except Exception as e:
        print(f"[not] ML katmanı atlandı: {e}")
    print(rep.to_text())


if __name__ == "__main__":
    _cli()
