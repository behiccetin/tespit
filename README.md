<p align="center">
  <img src="tespit.png" width="96" alt="Tespit">
</p>

<h1 align="center">Tespit</h1>

<p align="center">
  <b>Belge bütünlüğü denetçisi · Document integrity checker</b><br>
  Word (.docx), Excel (.xlsx), PowerPoint (.pptx)
</p>

---

## English

**Tespit** checks whether an Office document (Word, Excel, PowerPoint) has been
tampered with. It does not read the visible text; instead it inspects the hidden
**metadata** inside the file (editing traces / RSIDs, creation and modification
dates, the creating application, word/time counters, packaging) and looks for
**inconsistencies** that normal, hand-authored documents do not have.

It reports a clear verdict:

- 🟢 **CLEAN** – the document appears normally authored.
- 🔴 **SUSPICIOUS** – the document shows tampering/processing traces; review it.
- 🟠 **WARNING** – the document seems produced by a tool, or written in an
  implausibly short time (content likely **pasted**, possible **AI text**).
  This is a hint for manual review, not a verdict.

It can also **scan a whole folder** and export an Excel-friendly **CSV report**.

### Why this exists / Motivation

Tespit was developed in the context of **academic journal editing**, to help
editors, reviewers and institutions assess the **integrity of submitted
documents** (for example, spotting documents whose editing history or dates were
manipulated, or whose text was pasted in rather than written). It is a **triage
aid**, not a court-grade forensic verdict.

> **Important:** The result is a strong indicator, **not definitive proof**.
> A "Clean" result does **not** prove that no AI was used: if someone writes the
> text elsewhere and pastes it into Word, the file can look perfectly clean.
> Always review flagged documents manually, and never accuse anyone based on
> this tool alone.

### Install

Requires **Python 3.9+**.

```bash
pip install -r requirements.txt
```

On Linux you may also need Tk:

```bash
sudo apt install python3-tk      # Debian/Ubuntu
```

### Run

- **Windows:** double-click `Tespit.bat` (or `python basit_arayuz.py`)
- **Linux / macOS:** `./Tespit.sh` (or `python3 basit_arayuz.py`)

### Languages / Adding a language

The interface is multilingual. Translations live in the `diller/` folder as
JSON files (`tr.json`, `en.json`). To add a new language:

1. Copy `diller/en.json` to `diller/<code>.json` (e.g. `fr.json`).
2. Translate the **values** (keep the keys unchanged).
3. Optionally add the display name to `_ADLAR` in `dil.py`.

Your language then appears in the in-app language selector automatically. Pull
requests with new languages are welcome.

### How it works (short)

Rule-based layers inspect OOXML structure (ZIP timestamps, OPC ordering, XML
serialization, RSID editing traces, run fragmentation, date consistency, the
creating application, and time/word plausibility). A small, self-contained
machine-learning layer (binary: clean vs. suspicious, no external services)
gives an independent second opinion and can be retrained.

---

## Türkçe

**Tespit**, bir Office belgesinin (Word, Excel, PowerPoint) üzerinde oynanıp
oynanmadığını denetler. Belgenin görünür metnini okumaz; içindeki gizli **üst
verileri** (düzenleme izleri / RSID, oluşturma ve değiştirme tarihleri,
oluşturan uygulama, kelime/süre sayaçları, paketleme) inceler ve normal, elle
yazılmış belgelerde bulunmayan **tutarsızlıkları** arar.

Sonucu net gösterir:

- 🟢 **TEMİZ** – belge normal yazılmış görünüyor.
- 🔴 **ŞÜPHELİ** – belgede oynama/işlem izleri var; inceleyin.
- 🟠 **UYARI** – belge bir araçla üretilmiş ya da imkânsız denecek kadar kısa
  sürede yazılmış görünüyor (içerik büyük olasılıkla **yapıştırılmış**, olası
  **yapay zekâ metni**). Bu bir yargı değil, elle inceleme ipucudur.

Bir **klasörün tamamını tarayıp** Excel uyumlu bir **CSV rapor** da üretebilir.

### Neden yapıldı / Amaç

Tespit, **akademik dergi editörlüğü** bağlamında; editörlere, hakemlere ve
kurumlara gelen belgelerin **bütünlüğünü** değerlendirmede yardımcı olmak için
geliştirildi (örneğin düzenleme geçmişi veya tarihleri oynanmış, ya da metni
yazılmak yerine yapıştırılmış belgeleri fark etmek). Bu bir **ön eleme
aracıdır**, adli kesinlikte bir hüküm değildir.

> **Önemli:** Sonuç güçlü bir göstergedir, **kesin kanıt değildir.** "Temiz"
> çıkması yapay zekâ kullanılmadığını kanıtlamaz: biri metni başka yerde yazıp
> Word'e yapıştırdıysa dosya tertemiz görünebilir. Şüpheli çıkanları mutlaka elle
> inceleyin ve kimseyi yalnızca bu araca dayanarak suçlamayın.

### Kurulum

**Python 3.9+** gerekir.

```bash
pip install -r requirements.txt
```

Linux'ta ayrıca Tk gerekebilir:

```bash
sudo apt install python3-tk
```

### Çalıştırma

- **Windows:** `Tespit.bat` dosyasına çift tıklayın (ya da `python basit_arayuz.py`)
- **Linux / macOS:** `./Tespit.sh` (ya da `python3 basit_arayuz.py`)

### Diller / Yeni dil ekleme

Arayüz çok dillidir. Çeviriler `diller/` klasöründe JSON olarak durur
(`tr.json`, `en.json`). Yeni dil eklemek için:

1. `diller/en.json`'ı `diller/<kod>.json` olarak kopyalayın (ör. `fr.json`).
2. Yalnızca **değerleri** çevirin (anahtarları değiştirmeyin).
3. İsterseniz `dil.py` içindeki `_ADLAR`'a görünen adı ekleyin.

Diliniz uygulamadaki dil seçicide otomatik görünür. Yeni dil katkıları
memnuniyetle karşılanır.

---

## Katkı / Yapay zekâ notu · AI note

Bu araç **Öğr. Gör. Dr. Behiç Çetin** tarafından tasarlanıp geliştirilmiştir;
tasarım, yöntem ve kararlar kendisine aittir. **Kodlama sürecinde yapay zekâ
(Claude) desteği alınmıştır.**

This tool was designed and developed by **Behiç Çetin**; the design, method and
decisions are his. **AI (Claude) assistance was used during the coding.**

**Yazar · Author:** Öğr. Gör. Dr. Behiç Çetin — Burdur Mehmet Akif Ersoy
Üniversitesi (MAKÜ). Oğuzhan Sosyal Bilimler Dergisi editörü.

## License

MIT License — see [LICENSE](LICENSE). Serbestçe kullanabilir, değiştirebilir ve
dağıtabilirsiniz.
