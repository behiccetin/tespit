# -*- coding: utf-8 -*-
"""
ml_classifier.py  --  Katman 5 ML sınıflandırıcı (YALNIZCA TAHMİN / predict-only)
=====================================================================
Bu, Tespit (dedektör) açık kaynak sürümüdür: önceden eğitilmiş modeli
(model.json) yükler ve Temiz/Şüpheli tahmini verir. Model EĞİTİMİ ve sahte
belge/veri ÜRETİMİ bu dosyada yoktur (onlar özel araştırma sürümünde kalır).
"""

from __future__ import annotations

import json
import numpy as np

from deep_detector import FEATURE_NAMES, DeepForensicDetector

CLASSES = ["Temiz", "Şüpheli"]  # 0 = Temiz, 1 = Şüpheli


class ForensicMLClassifier:
    """İkili (Temiz/Şüpheli) softmax sınıflandırıcı; yalnızca yükleme + tahmin."""

    def __init__(self, W=None, mean=None, std=None, classes=None, feature_names=None):
        self.W = W
        self.mean = mean
        self.std = std
        self.classes = classes or CLASSES
        self.feature_names = feature_names or FEATURE_NAMES

    def _forward(self, X):
        Xs = (X - self.mean) / self.std
        Xb = np.hstack([Xs, np.ones((Xs.shape[0], 1))])
        logits = Xb @ self.W
        logits -= logits.max(axis=1, keepdims=True)
        e = np.exp(logits)
        return e / e.sum(axis=1, keepdims=True)

    def predict(self, docx_path):
        row = np.array([DeepForensicDetector.feature_row(docx_path)], dtype=float)
        P = self._forward(row)[0]
        i = int(P.argmax())
        olas = {self.classes[j]: round(float(P[j]), 4) for j in range(len(self.classes))}
        return self.classes[i], float(P[i]), olas

    def predict_features(self, feats):
        P = self._forward(np.array([feats], dtype=float))[0]
        i = int(P.argmax())
        return self.classes[i], float(P[i])

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            o = json.load(f)
        return cls(
            W=np.array(o["W"], dtype=float),
            mean=np.array(o["mean"], dtype=float),
            std=np.array(o["std"], dtype=float),
            classes=o["classes"],
            feature_names=o["feature_names"],
        )
