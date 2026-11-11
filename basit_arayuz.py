# -*- coding: utf-8 -*-
"""
basit_arayuz.py  --  TESPİT (sade belge doğrulama arayüzü, çok dilli)
=====================================================================
Tek ekranlı belge doğrulama. Kullanıcı bir Word/Excel/PowerPoint dosyası
seçer; program TEMİZ / ŞÜPHELİ sonucunu büyük ve renkli gösterir. Arayüz
metinleri diller/<kod>.json dosyalarından gelir (TR/EN hazır; yeni dil
eklemek için diller/ klasörüne JSON koymak yeterlidir).

Çalıştırma:  python basit_arayuz.py
"""

from __future__ import annotations

import os
import threading
from tkinter import filedialog

import customtkinter as ctk

import dil
from deep_detector import DeepForensicDetector
import batch_analyze
import karar

_HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_HERE, "model.json")
LOGO_PNG = os.path.join(_HERE, "tespit.png")   # mavi: sadece dedektör
LOGO_ICO = os.path.join(_HERE, "tespit.ico")
DIL_CONF = os.path.join(_HERE, "dil_secimi.txt")
BELGE_TURLERI = [("Office", "*.docx *.xlsx *.pptx"), ("*", "*.*")]


def _logo_image(boyut):
    try:
        from PIL import Image
        im = Image.open(LOGO_PNG)
        return ctk.CTkImage(light_image=im, dark_image=im, size=(boyut, boyut))
    except Exception:
        return None


def _pencere_simgesi(win):
    try:
        if os.path.isfile(LOGO_ICO):
            win.after(300, lambda: win.iconbitmap(LOGO_ICO))
    except Exception:
        pass


def _dil_oku() -> str:
    try:
        with open(DIL_CONF, "r", encoding="utf-8") as f:
            return (f.read().strip() or "tr")
    except Exception:
        return "tr"


def _dil_yaz(kod: str) -> None:
    try:
        with open(DIL_CONF, "w", encoding="utf-8") as f:
            f.write(kod)
    except Exception:
        pass


class BasitArayuz(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.geometry("820x660")
        self.minsize(720, 600)
        _pencere_simgesi(self)

        dil.yukle(_dil_oku())
        self._son_rapor = None
        self._son_path = None
        self._model = self._load_model()
        self._logo_img = _logo_image(56)

        self.title(dil.t("app_title"))
        self._icerik = None
        self._build()

    # -- Arayüzü (yeniden) kur: dil değişince çağrılır -----------------------
    def _build(self):
        if self._icerik is not None:
            self._icerik.destroy()
        self._icerik = ctk.CTkFrame(self, fg_color="transparent")
        self._icerik.pack(fill="both", expand=True)
        p = self._icerik

        # Üst şerit: logo + ad + dil seçici.
        ust = ctk.CTkFrame(p, fg_color="transparent")
        ust.pack(fill="x", padx=20, pady=(16, 8))
        sol = ctk.CTkFrame(ust, fg_color="transparent")
        sol.pack(side="left")
        if self._logo_img is not None:
            ctk.CTkLabel(sol, image=self._logo_img, text="").grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(sol, text=dil.t("app_title"),
                     font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(sol, text=dil.t("app_subtitle"),
                     font=ctk.CTkFont(size=12), text_color="#555555",
                     wraplength=520, justify="left").grid(row=1, column=1, sticky="w")

        sag = ctk.CTkFrame(ust, fg_color="transparent")
        sag.pack(side="right")
        ctk.CTkLabel(sag, text=dil.t("lang_label") + ":", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 6))
        diller = dil.mevcut_diller()
        self._dil_ad_kod = {ad: kod for kod, ad in diller}
        gecerli_ad = next((ad for kod, ad in diller if kod == dil.gecerli_kod()), diller[0][1])
        self._dil_menu = ctk.CTkOptionMenu(sag, values=[ad for _, ad in diller], width=120,
                                           command=self._dil_degistir)
        self._dil_menu.set(gecerli_ad)
        self._dil_menu.pack(side="left")

        # Ana buton.
        self.sec_btn = ctk.CTkButton(p, text=dil.t("btn_pick"),
                                     font=ctk.CTkFont(size=18, weight="bold"), height=62,
                                     command=self._sec_ve_kontrol)
        self.sec_btn.pack(fill="x", padx=40, pady=(6, 6))
        self.secili_lbl = ctk.CTkLabel(p, text=dil.t("no_file"),
                                       font=ctk.CTkFont(size=12), text_color="#777777")
        self.secili_lbl.pack(pady=(0, 12))

        self.sonuc = ctk.CTkLabel(p, text=dil.t("result_placeholder"),
                                  font=ctk.CTkFont(size=38, weight="bold"),
                                  fg_color="#ecf0f1", text_color="#333333",
                                  corner_radius=14, height=116)
        self.sonuc.pack(fill="x", padx=40, pady=(0, 10))

        self.aciklama = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=16),
                                     wraplength=700, justify="center")
        self.aciklama.pack(padx=40, pady=(0, 6))
        self.kaynak_lbl = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=13), text_color="#555555")
        self.kaynak_lbl.pack(pady=(0, 6))
        self.uyari_lbl = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=14, weight="bold"),
                                      text_color="#b45309", wraplength=720, justify="center")
        self.uyari_lbl.pack(pady=(0, 12))

        alt = ctk.CTkFrame(p, fg_color="transparent")
        alt.pack(pady=(0, 8))
        ctk.CTkButton(alt, text=dil.t("btn_folder"), width=200, height=40,
                      fg_color="#5a6", command=self._klasor_tara).grid(row=0, column=0, padx=8)
        self.detay_btn = ctk.CTkButton(alt, text=dil.t("btn_tech"), width=150, height=40,
                                       fg_color="#888", state="disabled", command=self._teknik_rapor)
        self.detay_btn.grid(row=0, column=1, padx=8)
        ctk.CTkButton(alt, text=dil.t("btn_help"), width=110, height=40,
                      fg_color="#2563eb", command=self._yardim).grid(row=0, column=2, padx=8)

        self.durum = ctk.CTkLabel(p, text="", font=ctk.CTkFont(size=12), text_color="#999999")
        self.durum.pack(pady=(4, 0))

        # Dil değişiminde son sonucu yeni dilde geri göster.
        if self._son_rapor is not None:
            self.detay_btn.configure(state="normal")
            self._goster(self._son_rapor)

    def _dil_degistir(self, secili_ad):
        kod = self._dil_ad_kod.get(secili_ad, "tr")
        _dil_yaz(kod)
        dil.yukle(kod)
        self.title(dil.t("app_title"))
        self._build()

    def _load_model(self):
        if os.path.isfile(MODEL_PATH):
            try:
                from ml_classifier import ForensicMLClassifier
                return ForensicMLClassifier.load(MODEL_PATH)
            except Exception:
                return None
        return None

    # -- Tek dosya kontrol --------------------------------------------------
    def _sec_ve_kontrol(self):
        f = filedialog.askopenfilename(title=dil.t("pick_title"), filetypes=BELGE_TURLERI)
        if not f:
            return
        self._son_path = f
        self.secili_lbl.configure(text=os.path.basename(f))
        self.sec_btn.configure(state="disabled", text=dil.t("checking"))
        self.durum.configure(text=dil.t("analyzing_wait"))
        threading.Thread(target=self._kontrol_worker, args=(f,), daemon=True).start()

    def _kontrol_worker(self, path):
        try:
            rep = DeepForensicDetector().analyze_docx(path)
            if self._model is not None:
                try:
                    e, g, o = self._model.predict(path)
                    rep.ml_tahmin, rep.ml_guven, rep.ml_olasiliklar = e, g, o
                except Exception:
                    pass
            self.after(0, lambda: self._goster(rep))
        except Exception as e:
            self.after(0, lambda: self._hata(str(e)))
        finally:
            self.after(0, lambda: self.sec_btn.configure(state="normal", text=dil.t("btn_pick")))

    def _goster(self, rep):
        self._son_rapor = rep
        etiket, renk, yazi, aciklama = karar.nihai_karar(rep, self._model)
        self.sonuc.configure(text=etiket, fg_color=renk, text_color=yazi)
        self.aciklama.configure(text=aciklama)
        kaynak_txt = dil.t("source_label", kaynak=karar.kaynak_sade(rep.en_olasi_profil))
        uyg = rep.metrikler.get("Oluşturan uygulama")
        if uyg:
            kaynak_txt += "   ·   " + dil.t("app_label", app=uyg)
        self.kaynak_lbl.configure(text=kaynak_txt)
        uyarilar = karar.uyari_metinleri(rep)
        self.uyari_lbl.configure(text=("⚠ " + "\n⚠ ".join(uyarilar)) if uyarilar else "")
        self.detay_btn.configure(state="normal")
        self.durum.configure(text=f"{rep.supphe_puani}/100")

    def _hata(self, msg):
        self.sonuc.configure(text=dil.t("v_hata"), fg_color="#7f8c8d", text_color="#ffffff")
        self.aciklama.configure(text=dil.t("read_fail", msg=msg))
        self.kaynak_lbl.configure(text="")
        self.uyari_lbl.configure(text="")
        self.durum.configure(text="")

    def _teknik_rapor(self):
        if self._son_rapor is None:
            return
        pencere = ctk.CTkToplevel(self)
        pencere.title(dil.t("btn_tech"))
        pencere.geometry("760x600")
        _pencere_simgesi(pencere)
        kutu = ctk.CTkTextbox(pencere, font=ctk.CTkFont(family="Courier New", size=12))
        kutu.pack(fill="both", expand=True, padx=12, pady=12)
        kutu.insert("end", self._son_rapor.to_text())
        kutu.configure(state="disabled")

    # -- Klasör tarama ------------------------------------------------------
    def _klasor_tara(self):
        d = filedialog.askdirectory(title=dil.t("folder_title"))
        if not d:
            return
        out = os.path.join(d, "dogrulama_raporu.csv")
        self.durum.configure(text=dil.t("folder_scanning"))
        threading.Thread(target=self._klasor_worker, args=(d, out), daemon=True).start()

    def _klasor_worker(self, d, out):
        try:
            sonuc = batch_analyze.analyze_folder(d, out_csv=out, model_path=MODEL_PATH)
            renk = "#e67e22" if sonuc.bayrakli else "#27ae60"
            self.after(0, lambda: self.sonuc.configure(text=dil.t("folder_done"),
                                                       fg_color=renk, text_color="#ffffff"))
            self.after(0, lambda: self.aciklama.configure(
                text=dil.t("folder_summary", n=sonuc.toplam, m=sonuc.bayrakli)))
            self.after(0, lambda: self.kaynak_lbl.configure(text=dil.t("folder_report", path=out)))
            self.after(0, lambda: self.durum.configure(text=dil.t("folder_saved")))
            self.after(0, lambda: self.uyari_lbl.configure(text=""))
        except Exception as e:
            self.after(0, lambda: self._hata(str(e)))

    # -- Yardım -------------------------------------------------------------
    def _yardim(self):
        top = ctk.CTkToplevel(self)
        top.title(dil.t("help_title"))
        top.geometry("660x580")
        _pencere_simgesi(top)
        top.after(60, top.grab_set)
        kutu = ctk.CTkScrollableFrame(top)
        kutu.pack(fill="both", expand=True, padx=14, pady=14)

        def baslik(t):
            ctk.CTkLabel(kutu, text=t, font=ctk.CTkFont(size=15, weight="bold"),
                         anchor="w", justify="left", wraplength=580).pack(anchor="w", pady=(10, 2), fill="x")

        def yazi(t):
            ctk.CTkLabel(kutu, text=t, font=ctk.CTkFont(size=13),
                         anchor="w", justify="left", wraplength=600).pack(anchor="w", pady=(0, 4), fill="x")

        for h, pk in [("help_h1", "help_p1"), ("help_h2", "help_p2"), ("help_h3", "help_p3"),
                      ("help_h4", "help_p4"), ("help_h5", "help_p5")]:
            baslik(dil.t(h))
            yazi(dil.t(pk))
        ctk.CTkButton(top, text=dil.t("btn_close"), command=top.destroy).pack(pady=(0, 12))


def main():
    app = BasitArayuz()
    app.mainloop()


if __name__ == "__main__":
    main()
