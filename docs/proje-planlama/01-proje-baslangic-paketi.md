# Enretag Finans Platformu — Proje Başlangıç Paketi

Hazırlanma tarihi: 22.09.2026 · Sürüm: 1.0

> **[VARSAYIM]** Proje adı geçici olarak "Enretag Finans Platformu" verilmiştir; kullanıcı isterse değiştirebilir. Bu isim, mevcut NeXa sisteminde faturalandırma yapılan iki işletme varlığından biri olan ENRETAG'a atıfla seçilmiştir.

## Yönetici Özeti

Enretag Finans Platformu, ENRETAG ve LOGIWIX adına yürütülen FedEx/gümrük komisyonculuğu operasyonunun finansal tarafını (kâr/zarar, mutabakat, itiraz/iade takibi) elle yönetilen `Enretag_Kar_Zarar_Dashboard_v4.xlsx` formül tablosundan kurumsal, veritabanı destekli bir uygulamaya taşır. Sistem, mevcut operasyonel uygulama **NeXa**'nın ürettiği veriyi (kutu/sevkiyat, FedEx fatura, müşteri faturası, ürün/gümrük verisi) kaynak olarak kullanır ama NeXa'nın devamı değildir — ayrı bir veritabanı, ayrı bir kod tabanı ve ayrı bir sorumluluk alanına sahiptir. 22.09.2026 tarihinde NeXa'nın SQLite veritabanından salt-okunur bir RAW DATA anlık görüntüsü (`data/raw/nexa/2026-09-22_13-53-26/`) çıkarılmış, 9 tablo (68.916 kayıt) doğrulanmış ve bu paket o veri üzerine kuruludur.

Hedef kullanıcı tek kişi (Çağla Arslan) ve dahili kullanım olduğundan, plan kurumsal titizliği korurken bürokrasiyi asgaride tutacak şekilde ölçeklendirilmiştir.

En büyük 3 risk:
1. Kaynak veride zaten tespit edilmiş kalite sorunları (bkz. 6.3) — özellikle `boxes.profit_loss` alanındaki 1.171 "Bekliyor" metin değeri — hesaplama motoruna hatalı sıfır/NULL olarak sızabilir.
2. Kutu ↔ ana takip numarası (master tracking) ve müşteri adı eşleştirmesi hâlâ NeXa tarafında da tam çözülmemiş bir alan; bu platform bu eşleştirmeye dayanan mutabakat/kârlılık hesaplarını devralıyor.
3. Tek geliştiricili proje — devamlılık riski (belgeleme ve otomasyon olmadan bilgi kaybı).

Önerilen ilk adım: Sprint 1'de RAW→Staging aktarım hattını (Bölüm 3/6) kurup, mevcut Excel'in "Ortalamalar"/"Ortalama Üzeri Faturalar"/"Veri Kontrolü" mantığını yeni şemada yeniden üretip Excel'in (stale olmayan, yeniden hesaplanmış) çıktılarıyla satır satır karşılaştırmak.

## Proje Künyesi

| Alan | Değer |
|---|---|
| Ad | Enretag Finans Platformu **[VARSAYIM]** |
| Amaç | NeXa operasyonel verisini temel alarak müşteri bazlı kârlılık, fatura mutabakatı, gelir/gider ve finansman açığı/fazlası hesaplamalarını otomatikleştiren, `Enretag_Kar_Zarar_Dashboard_v4.xlsx`'in yerini alacak sistem |
| Hedef kullanıcı | Çağla Arslan (finans/operasyon), tek kullanıcı **[VARSAYIM: ekip büyümesi olursa çok kullanıcılı erişim v2'ye ertelenir]** |
| Kullanım senaryosu | Kutu/sevkiyat maliyeti + müşteri faturası + gümrük verisini birleştirip kârlılık, mutabakatsızlık, itiraz ve iade takibi yapmak |
| Platform | Python tabanlı yerel uygulama (masaüstünde `.bat` ile başlatılan web arayüzü — NeXa ile aynı aile) **[VARSAYIM]** |
| Veri tabanı | Ayrı, yeni bir SQLite dosyası (NeXa'nınkinden bağımsız) **[VARSAYIM]** |
| Hedef süre | 12 hafta (MVP) **[VARSAYIM]** |
| Kısıtlar | Tek geliştirici (kullanıcı + AI asistan iş birliği), bütçe yok/dahili proje, zorunlu teknoloji: Python + SQLite (mevcut yatırımla tutarlılık) |
| Veri kaynakları | NeXa RAW DATA anlık görüntüsü (`data/raw/nexa/2026-09-22_13-53-26/`), `Enretag_Kar_Zarar_Dashboard_v4.xlsx` (mantık referansı) |
| Kapsam dışı (v1.0) | PDF fatura okuma (NeXa'da zaten var — bu platform onu tekrar etmez), çoklu kullanıcı yetkilendirme, Pay Stub/bordro entegrasyonu **[VARSAYIM]** |

---

## 1. Proje Yönetimi (Proje Yöneticisi)

### 1.1 Proje Beratı

**Amaç:** Elle yürütülen, formülleri "donmuş" (stale) kalabilen Excel tabanlı kâr/zarar sürecini, NeXa'nın ürettiği güncel veriyi doğrudan tüketen, otomatik yeniden hesaplanan bir finans platformuna dönüştürmek.

**Başarı kriterleri:**
- Yeni sistemin "Ortalamalar", "Ortalama Üzeri Faturalar" ve "Veri Kontrolü" çıktıları, Excel'in güncel (stale olmayan) haliyle satır bazında %100 eşleşir.
- Müşteri bazlı kârlılık raporu, 45 müşterinin tamamı için `customer_invoices` ↔ `boxes` eşleşmesiyle üretilir.
- Kaynak veri kalite sorunları (Bölüm 6.3) kullanıcıya UI üzerinde açıkça raporlanır, sessizce göz ardı edilmez.
- Sistem NeXa'ya hiçbir yazma işlemi yapmaz (tek yönlü, salt-okunur bağımlılık).

**Sponsor / karar verici:** Çağla Arslan.

### 1.2 Kilometre Taşları

| # | Kilometre Taşı | Hedef Hafta | Tamamlanma Kriteri |
|---|---|---|---|
| M1 | Staging şeması ve RAW→Staging aktarımı hazır | H2 sonu | 9 RAW tablo, doğrulama kontrolleriyle staging'e yüklendi |
| M2 | Finansal şema (fin_*) tasarlandı ve migration çalıştı | H4 sonu | DBA şema taslağı onaylı, staging→fin_* dönüşümü çalışıyor |
| M3 | Hesaplama motoru (P&L/benchmark/above-average/veri kontrolü) | H7 sonu | Excel referans çıktılarıyla satır bazlı doğrulama geçti |
| M4 | Mutabakat + itiraz/iade modülü | H9 sonu | customer_invoices↔boxes eşleşmesi + disputed_items/refunds akışı çalışıyor |
| M5 | Dashboard/raporlama arayüzü | H11 sonu | Aylık/şirket/ülke/sevkiyat tipi filtreli özet ekranı hazır |
| M6 | Sürüm 1.0 | H12 sonu | QA kabul kontrol listesi geçti, runbook teslim edildi |

### 1.3 Risk Kaydı

| No | Risk | Olasılık (D/O/Y) | Etki (D/O/Y) | Azaltma Aksiyonu | Sahibi |
|---|---|---|---|---|---|
| R1 | `boxes.profit_loss`/`fedex_total_cost` alanındaki "Bekliyor" metin değerleri (1.171 kayıt) hesaplama motorunda sessizce 0/NULL'a dönüşür, kârlılık yanlış görünür | Y | Y | Staging katmanında "Bekliyor" değerini ayrı bir `status` alanına taşı, sayısal alanı NULL bırak; UI'da "Faturası Bekleniyor" olarak göster | Dev Manager |
| R2 | Kutu↔ana takip numarası ve müşteri adı eşleştirmesi eksik/belirsiz (NeXa tarafında da tam çözülmedi) | Y | Y | Mutabakat modülünü "kesin eşleşme" ve "eşleşmedi — manuel inceleme" olarak iki kademeli tasarla; eşleşmeyenleri gizleme | BA + Dev Manager |
| R3 | `invoice_review` tablosunda 7.575/7.577 kayıtta `invoice_no` NULL — bu tablo mevcut haliyle finansal karara temel oluşturamaz | O | O | Bu tabloyu v1.0 kapsamına dahil etme; sadece NeXa'nın kendi iç iş akışı olarak bırak | PM |
| R4 | `customer_invoices` içindeki 1.543 kayıtta farklı tarih formatı (`11-May-26`) | O | D | Staging'de tarih normalizasyon kuralı (çoklu format parse) + başarısız satırları veri kalitesi kuyruğuna düşür | Dev Manager |
| R5 | Tek geliştiricili proje — bilgi/süreklilik riski | O | Y | Her modül için ADR ve runbook belgeleme zorunlu (Bölüm 4.1, 9.2) | PM |
| R6 | NeXa'nın kendi verisi değişmeye devam ediyor (canlı operasyon); yeni platform eski bir anlık görüntüyle çalışıyor olabilir | Y | O | Extraction script'i (`scripts/data_migration/extract_nexa_raw.py`) periyodik/istek üzerine tekrar çalıştırılabilir tasarlandı; her import'ta `extraction_timestamp` kayıtlarla birlikte saklanır | Dev Manager + DBA |

### 1.4 RACI Matrisi

| İş Kalemi | PM | PO | TPM | Dev Mgr | Scrum M. | BA | QA | DevOps | Ops | Security | DBA |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Kapsam/önceliklendirme | A | R | C | C | I | C | I | I | I | I | I |
| Şema/veri modeli | I | I | C | C | I | C | I | I | I | C | R/A |
| Hesaplama motoru | I | C | C | R/A | I | R | C | I | I | I | C |
| Mutabakat mantığı | I | C | I | C | I | R/A | C | I | I | I | C |
| Test stratejisi | I | I | I | C | I | C | R/A | I | I | C | I |
| Sürüm çıkarma | I | I | C | C | I | I | C | R/A | I | I | I |
| Güvenlik/KVKK | I | I | I | C | I | I | I | I | I | R/A | C |
| Destek/runbook | C | I | I | C | I | I | I | C | R/A | I | C |

*(R=Responsible, A=Accountable, C=Consulted, I=Informed)*

---

## 2. Ürün (Ürün Yöneticisi)

### 2.1 Vizyon ve Değer Önerisi

"Çağla, ay sonunda hangi müşterinin kârlı hangi müşterinin zararlı olduğunu, hangi faturaların ortalamanın üstünde geldiğini ve hangi kutuların hâlâ mutabakat beklediğini, Excel formüllerinin bayatlamasından (stale cache) endişe etmeden, tek ekrandan görsün."

### 2.2 Personalar

| Persona | Tanım | İhtiyaç |
|---|---|---|
| Finans Sorumlusu (birincil) | Çağla — non-teknik, terminal desteğine ihtiyaç duyuyor, gümrük/FedEx alan bilgisi güçlü | Sade arayüz, Türkçe etiketler, güvenilir/doğrulanmış rakamlar |
| **[VARSAYIM]** Muhasebe/Denetim (ikincil, gelecekte) | Dışarıdan bir mali müşavir veya denetçi | Dışa aktarılabilir, izlenebilir (audit trail) raporlar |

### 2.3 Özellik Önceliklendirme (MoSCoW)

| Özellik | Açıklama | MoSCoW | MVP'de mi? | Gerekçe |
|---|---|---|---|---|
| RAW→Staging aktarımı | NeXa anlık görüntüsünü doğrulanmış şekilde platforma alma | Must | Evet | Her şeyin temeli |
| P&L/Benchmark motoru | Excel'in Ortalamalar/Ortalama Üzeri mantığının kod karşılığı | Must | Evet | Ana değer önerisi |
| Veri kalitesi paneli | "Bekliyor", NULL PK, format sorunlarını görünür kılma | Must | Evet | R1/R3/R4 risklerinin azaltılması |
| Müşteri bazlı kârlılık | `customer_invoices`↔`boxes` eşleşmesiyle 45 müşteri kırılımı | Must | Evet | Excel'in "Enretag Invoice" sheet'inin doğal devamı |
| İtiraz/iade (dispute/refund) resmi kaydı | `disputed_items`/`refunds`'ın finansal muhasebeye bağlanması | Should | Evet | NeXa'da operasyonel var, finansal karşılığı eksik |
| Aylık/şirket/ülke dashboard | Excel "Dashboard" sheet'inin dijital karşılığı | Should | Evet | Yönetici görünürlüğü |
| Excel'e dışa aktarım | Rapor çıktısını `.xlsx` olarak alabilme | Could | Hayır (v1.1) | Geçiş dönemi kolaylığı, MVP'yi geciktirmesin |
| E-posta/bildirim (yüksek fatura uyarısı) | `HIGH_INVOICE_WARNING_USD` eşiği aşıldığında bildirim | Could | Hayır (v1.1) | Güzel ama kritik değil |
| Çoklu kullanıcı yetkilendirme | Rol bazlı erişim | Won't | Hayır | Tek kullanıcı senaryosu — [VARSAYIM] |
| PDF'den doğrudan fatura okuma | Bu platformun kendi PDF parser'ı olması | Won't | Hayır | NeXa'da zaten var, tekrar mühendislik gereksiz |
| Pay Stub/bordro entegrasyonu | Personel maaş verisiyle birleşik P&L | Won't | Hayır | Farklı bir iş alanı, ayrı sistemde kalmalı |

### 2.4 MVP Kapsam Sınırı

MVP'de **olmayacaklar**: çoklu kullanıcı, kendi PDF okuma motoru, otomatik e-posta bildirimleri, Excel dışa aktarım, bordro entegrasyonu, gerçek zamanlı NeXa senkronizasyonu (aktarım manuel/istek üzerine tetiklenir, otomatik değil — **[VARSAYIM]**).

### 2.5 Yol Haritası

- **v1.0 (H12):** Staging + finansal şema + hesaplama motoru + mutabakat + dashboard.
- **v1.1:** Excel dışa aktarım, yüksek fatura e-posta uyarısı, satır bazlı Duty allocation'ın (Master Tracking → kutu dağılımı) tam otomasyonu.
- **v1.2+ [VARSAYIM]:** Çoklu kullanıcı, NeXa ile otomatik/zamanlanmış senkronizasyon, dış muhasebe sistemi entegrasyonu.

### 2.6 Başarı Metrikleri (KPI)

| Metrik | Hedef |
|---|---|
| Excel'e karşı hesaplama doğruluğu | %100 eşleşme (Ortalamalar/Ortalama Üzeri/Veri Kontrolü) |
| Mutabakatı yapılmış kutu oranı | v1.0 sonunda ≥ %90 (kalan %10 bilinen eşleştirme boşluğu — R2) |
| Veri kalitesi kuyruğunda bekleyen kayıt | Her ay gözden geçiriliyor, sıfıra indirilmesi hedeflenmiyor (bazıları kaynaktan kaynaklanıyor) ama görünür ve raporlanıyor |

---

## 3. Teknik Planlama (Teknik Proje Yöneticisi)

### 3.1 Epic Listesi ve Efor Tahmini

| Epic | Açıklama | Efor (hafta) |
|---|---|---|
| E1 — Aktarım & Staging | RAW CSV → staging tabloları, doğrulama, tekrar-çalıştırılabilirlik | 2 |
| E2 — Finansal Şema & Migration | `fin_*` şeması, staging→fin_* dönüşüm/temizleme kuralları | 2 |
| E3 — Hesaplama Motoru | Benchmark, above-average, veri kontrolü, P&L | 3 |
| E4 — Mutabakat Modülü | `customer_invoices`↔`boxes`↔`invoices` çapraz kontrol | 2 |
| E5 — İtiraz/İade Yönetimi | `disputed_items`/`refunds` finansal kayda bağlama | 1 |
| E6 — Raporlama/Dashboard UI | Excel "Dashboard" karşılığı, filtreli özet | 1,5 |
| E7 — Güvenlik & Yedekleme | Tehdit modeli uygulaması, yedekleme otomasyonu | paralel (0,5 ayrık) |
| E8 — Test & Sürüm | Test senaryoları, kabul kontrol listesi, ilk sürüm | 1 |
| **Toplam** | | **~12 hafta** (E7 paralel yürüdüğü için toplamda ayrıca eklenmedi) |

### 3.2 Bağımlılıklar ve Kritik Yol

```
E1 (Aktarım & Staging)
   └──> E2 (Finansal Şema & Migration)
           └──> E3 (Hesaplama Motoru)
                   ├──> E4 (Mutabakat Modülü)
                   │       └──> E6 (Dashboard) ──> E8 (Test & Sürüm)
                   └──> E5 (İtiraz/İade)  ───────> E6
E7 (Güvenlik & Yedekleme): E1 başladığı andan itibaren paralel, E8'de son kontrol
```

**Kritik yol:** E1 → E2 → E3 → E4 → E6 → E8. E5 kritik yolun dışında ama E6'dan önce bitmesi gerekiyor (dashboard itiraz/iade verisini de gösteriyor).

### 3.3 Teknik Riskler

| Risk | Açıklama | Önlem |
|---|---|---|
| Şema kararlılığı | NeXa'nın kaynak şeması (`core/database.py`) zaman içinde `ALTER TABLE` ile değişebilir (zaten `_ensure_columns` ile büyüyor) | Her aktarımda `schema_version` etiketi kaydet, şema değişikliğini algılayan bir kontrol ekle |
| Performans | `customer_invoices` (35.059 satır) ve `legacy_fedex_invoice_raw` (11.072 satır) gibi tablolarda birleştirme (join) maliyeti | SQLite üzerinde uygun indeksler (`tracking_id`, `invoice_number`) E2'de oluşturulacak |
| Dış bağımlılık yok | Üçüncü parti API/lisans bağımlılığı tespit edilmedi | — |

---

## 4. Mimari ve Geliştirme (Yazılım Geliştirme Müdürü)

### 4.1 Mimari Karar Kaydı (ADR)

**ADR-001: Genel Mimari**
- **Bağlam:** Kullanıcı non-teknik, terminal desteğine ihtiyaç duyuyor, NeXa ile aynı Python/Streamlit/SQLite yatırımına sahip.
- **Karar:** Yeni platform da Python + Streamlit (yerel web arayüzü, `.bat` ile başlatma) + SQLite kullanacak, NeXa'dan tamamen ayrı bir proje klasöründe.
- **Gerekçe:** Öğrenme eğrisi sıfır, mevcut altyapı (venv, requirements.txt kalıpları) yeniden kullanılabilir, kullanıcı zaten bu arayüze aşina.
- **Sonuçlar:** NeXa'nın Streamlit sınırlamaları (widget-key-per-record-id kuralı, tekil instance ihtiyacı — bkz. NeXa hafızası) burada da geçerli olacak, en baştan tasarıma dahil edilmeli.

**ADR-002: Veri Ayrımı**
- **Bağlam:** Talimat NeXa'ya hiçbir yazma yapılmamasını, ayrı bir finansal veritabanı kurulmasını şart koşuyor.
- **Karar:** Yeni, bağımsız bir SQLite dosyası (`data/finans_platform.db` **[VARSAYIM isim]**), üç katmanlı şema: `raw_*` (RAW CSV'lerin birebir yüklendiği, hiç değiştirilmeyen katman) → `stg_*` (tip dönüşümü, tarih normalizasyonu yapılmış ama iş kuralı uygulanmamış katman) → `fin_*` (iş kuralları, hesaplamalar, mutabakat sonuçları).
- **Sonuçlar:** Her katman ayrı ayrı denetlenebilir; kaynak veri hiçbir zaman kaybolmaz.

**ADR-003: NeXa Senkronizasyonu**
- **Karar:** v1.0'da senkronizasyon manuel/istek üzerine (`extract_nexa_raw.py` script'inin yeniden çalıştırılması). Otomatik/zamanlanmış senkronizasyon v1.2+'ya ertelendi. **[VARSAYIM]**
- **Gerekçe:** NeXa canlı operasyonel sistem; otomatik senkronizasyonun ne sıklıkla/ne zaman güvenli olduğu henüz netleşmedi.

### 4.2 Teknoloji Yığını

| Katman | Seçim | Alternatif ve neden elendi |
|---|---|---|
| Dil | Python 3.14 | NeXa ile tutarlılık |
| Arayüz | Streamlit | Electron/React elendi — ek karmaşıklık, non-teknik kullanıcıya fayda sağlamıyor |
| Veri tabanı | SQLite | PostgreSQL/MySQL elendi — tek kullanıcı, sunucu kurulumu gereksiz karmaşıklık |
| Tablo/ızgara | `streamlit-aggrid` | NeXa'da kanıtlanmış, tutarlılık için aynısı kullanılacak |
| Test | `pytest` | Standart, hafif |

### 4.3 Modül Yapısı (taslak)

```
enretag-finans-platformu/
├── app.py                        # Streamlit giriş noktası
├── core/
│   ├── database.py                # Bağlantı + şema (raw_*/stg_*/fin_*)
│   ├── ingest_from_nexa.py        # RAW CSV → raw_* tabloları (bu paketin snapshot'ını okur)
│   ├── staging.py                  # raw_* → stg_* (tip/tarih normalizasyonu)
│   ├── calc_engine.py              # Excel mantığının kod karşılığı: benchmark, above-average, data quality
│   ├── reconciliation.py           # customer_invoices ↔ boxes ↔ invoices eşleştirme
│   ├── disputes_refunds.py         # itiraz/iade finansal kayıt mantığı
│   └── config.py                   # Excel "Ayarlar" sheet karşılığı (eşikler, ülke kuralları)
├── data/
│   ├── finans_platform.db
│   └── backups/
├── tests/
└── docs/proje-planlama/            # bu paket
```

### 4.4 Kodlama Standartları

- Fonksiyon/değişken adları İngilizce (NeXa ile tutarlı), UI metinleri Türkçe.
- Her hesaplama fonksiyonu, girdisini ve çıktısını Excel'in ilgili sheet'iyle karşılaştırılabilir şekilde dokümante eder (docstring'de "bkz. Ayarlar/Ortalamalar sheet").
- Kaynak veriye (raw_*) hiçbir zaman UPDATE/DELETE yapılmaz — sadece `stg_*`/`fin_*` katmanları yeniden hesaplanır.
- Git ile versiyon kontrolü **[VARSAYIM: proje henüz git deposu değil — Sprint 1'de `git init` önerilir]**.

---

## 5. Çevik Süreç (Scrum Master)

### 5.1 Sprint Takvimi

| Sprint | Tarih Aralığı (varsayımsal, H1 = proje başlangıcı) | Hedef | Ana İşler |
|---|---|---|---|
| S1 | H1–H2 | Aktarım hattı çalışır durumda | E1: raw_* şeması, CSV yükleme, satır sayısı doğrulama |
| S2 | H3–H4 | Finansal şema hazır | E2: stg_*/fin_* şeması, tarih/format normalizasyonu, "Bekliyor" ayrıştırma |
| S3 | H5–H6 | Benchmark motoru Excel ile eşleşiyor | E3 (kısım 1): Ortalamalar + Ortalama Üzeri Faturalar |
| S4 | H7–H8 | Veri kontrolü + mutabakat başlangıcı | E3 (kısım 2): Veri Kontrolü; E4 başlangıç |
| S5 | H9–H10 | Mutabakat + itiraz/iade tamam | E4 tamam, E5 tamam |
| S6 | H11–H12 | Dashboard + sürüm | E6, E7 son kontrol, E8, sürüm 1.0 |

### 5.2 Definition of Done

- [ ] Kod çalışıyor ve `pytest` testleri geçiyor.
- [ ] İlgili hesaplama, Excel referans çıktısıyla karşılaştırıldı (mümkünse otomatik test olarak).
- [ ] UI değişikliği varsa ekran görüntüsüyle doğrulandı.
- [ ] Kaynak veriye (raw_*) yazma yapılmadığı teyit edildi.
- [ ] Kısa bir not (`docs/proje-planlama/degisiklik-notlari.md` **[VARSAYIM dosya]**) güncellendi.

### 5.3 Seremoniler (sadeleştirilmiş — tek kişilik proje)

- **Sprint Planlama:** Her sprint başında 15 dakikalık kendi kendine gözden geçirme + AI asistanla kapsam teyidi.
- **Günlük:** Ayrı bir toplantı yok; her oturum başında "kaldığımız yer" özeti.
- **Sprint Gözden Geçirme:** Sprint sonunda çalışan özelliğin canlı gösterimi (NeXa'daki "run" alışkanlığıyla tutarlı).
- **Retrospektif:** Sprint sonunda 3 soru: Ne iyi gitti? Ne yavaşlattı? Bir sonrakinde ne değişecek?

---

## 6. Analiz ve İş Süreçleri (BA)

### 6.1 Kullanıcı Hikâyeleri ve Kabul Kriterleri

| # | Kullanıcı Hikâyesi | Kabul Kriterleri |
|---|---|---|
| U1 | Finans sorumlusu olarak, NeXa'nın en güncel verisini platforma aktarabilmek istiyorum ki hesaplamalar güncel kalsın. | Aktarım script'i çalıştırıldığında satır sayıları kaynakla eşleşiyor; uyuşmazlık varsa açıkça raporlanıyor, sessizce geçilmiyor. |
| U2 | Finans sorumlusu olarak, ülke/sevkiyat tipi bazlı ortalama Shipping/Duty/Total tutarları görmek istiyorum. | `MINIMUM_SAMPLE_SIZE_FOR_AVERAGE` (3) altındaki gruplarda "Yeterli Veri Yok" gösteriliyor; üzeri gruplarda ortalama Excel'in "Ortalamalar" sheet'iyle eşleşiyor. |
| U3 | Finans sorumlusu olarak, ortalamanın %20 üzerinde gelen faturaları görmek istiyorum. | `ABOVE_AVERAGE_THRESHOLD_PERCENT` (0,20) eşiği uygulanıyor; sonuç Excel'in "Ortalama Üzeri Faturalar" sheet'iyle eşleşiyor. |
| U4 | Finans sorumlusu olarak, US/AU sevkiyatlarında Duty'nin otomatik "-" görünmesini istiyorum çünkü bu ülkelerde Duty hiç kesilmez. | `NO_DUTY_COUNTRIES = {US, AU}` kuralı uygulanıyor; bu ülkelerde Duty alanı boş değil, açıkça "-" gösteriliyor. |
| U5 | Finans sorumlusu olarak, çoklu kutulu (Multi) sevkiyatlarda Duty'nin ana takip numarası üzerinden kesilip kutulara eşit bölündüğünü görmek istiyorum. | Aynı `multi_no` grubundaki kutularda toplam Duty korunuyor, kutu sayısına bölünüyor; ham `boxes` tablosu değişmiyor (sadece görüntüleme/hesaplama katmanında). |
| U6 | Finans sorumlusu olarak, hâlâ FedEx faturası gelmemiş kutuları "Faturası Bekleniyor" olarak, asla fatura gelmeyecekleri (US/AU Duty veya süresi dolmuş bekleme) "-" olarak ayırt etmek istiyorum. | `INVOICE_WAITING_PERIOD_DAYS` (14) kuralı ve iki durum stringi ("-" / "Bekliyor") doğru uygulanıyor. |
| U7 | Finans sorumlusu olarak, bir müşterinin (`customer_invoices.customer`) toplam faturalandığı tutar ile ona ait kutuların gerçek maliyetini karşılaştırıp kârlılığını görmek istiyorum. | `tracking_id` üzerinden eşleşen kayıtlar birleştiriliyor; eşleşmeyenler ayrı bir "eşleşmedi" listesinde gösteriliyor, gizlenmiyor. |
| U8 | Finans sorumlusu olarak, bir faturaya itiraz ettiğimde bunun finansal kayda (gelir/gider tahmininden düşülecek şekilde) yansımasını istiyorum. | `disputed_items` kaydı `fin_*` katmanında "beklemede" statüsüyle işaretleniyor, onaylanana kadar kesin zarar/gelir hesabına dahil edilmiyor. |
| U9 | Finans sorumlusu olarak, eksik/tutarsız veri (NULL şirket/ülke, beklenmedik Duty, eksik ana takip no) taşıyan kutuları ayrı bir "Veri Kontrolü" listesinde görmek istiyorum. | Excel'in "Veri Kontrolü" kuralları (5 kural) birebir uygulanıyor; ek olarak bu paket kapsamında bulunan "Bekliyor" metin/sayısal karışıklığı da bu listeye ekleniyor. |

### 6.2 İş Süreç Akışları

**Akış A — Aktarım ve Yeniden Hesaplama**
```
Başla → NeXa RAW snapshot script'i çalıştırılır
      → Satır sayısı kaynakla karşılaştırılır
      → Karar: Eşleşiyor mu?
            Evet → raw_* tablolarına yüklenir
            Hayır → Aktarım durur, hata raporlanır, kullanıcıya bildirilir
      → stg_* dönüşümü (tip/tarih normalizasyonu, "Bekliyor" ayrıştırma)
      → fin_* hesaplamaları (benchmark, above-average, veri kontrolü, mutabakat)
      → Dashboard güncellenir
Bitir
```

**Akış B — İtiraz (Dispute) Yaşam Döngüsü**
```
Başla → Kutu/fatura "itiraz" olarak işaretlenir (NeXa'daki mevcut mekanizma)
      → Bu platform disputed_items'ı okur, fin_* katmanında "beklemede" statüsü açar
      → Karar: İtiraz sonuçlandı mı?
            Onaylandı (iade/kredi) → refunds tablosuna/finansal kayda işlenir
            Reddedildi → normal maliyet olarak fin_* hesabına geri döner
      → Dashboard güncellenir
Bitir
```

### 6.3 İş Kuralları (mevcut Excel/NeXa mantığından devralınan + bu paket kapsamında tespit edilen)

| Kural | Kaynak | Bu platforma etkisi |
|---|---|---|
| US ve AU'da Duty hiç kesilmez → "-" | `core/config.py NO_DUTY_COUNTRIES` | Aynen uygulanır |
| Diğer tüm ülkelerde (Kanada dahil) Duty, ana takip numarası üzerinden kesilir, kutulara eşit bölünür | Excel "Ayarlar" + NeXa `analytics.py` | Aynen uygulanır, ham veri değişmez |
| Fatura bekleme süresi 14 gün | `INVOICE_WAITING_PERIOD_DAYS` | Aynen uygulanır |
| Ortalama üstü eşik %20 (+ sabit $0) | `ABOVE_AVERAGE_THRESHOLD_PERCENT/FIXED` | Aynen uygulanır |
| Yüksek fatura uyarı eşiği $750 | `HIGH_INVOICE_WARNING_USD` | Aynen uygulanır |
| Ortalama için minimum örneklem 3 | `MINIMUM_SAMPLE_SIZE_FOR_AVERAGE` | Aynen uygulanır |
| **[Bu pakette bulundu]** `boxes.fedex_total_cost`/`profit_loss` içinde 1.171 "Bekliyor" metin değeri | RAW veri kalite kontrolü (22.09.2026) | Yeni kural: bu değerler `stg_*`'ta ayrı bir durum alanına (`cost_status='pending'`) taşınır, sayısal alan NULL bırakılır — asla 0 olarak yorumlanmaz |
| **[Bu pakette bulundu]** `invoice_review` tablosunun %99,97'sinde `invoice_no` NULL | RAW veri kalite kontrolü | Bu tablo finansal hesaplamalara girdi olarak kullanılmaz (kapsam dışı) |
| **[Bu pakette bulundu]** `customer_invoices` içinde 1.543 kayıt farklı tarih formatında (`11-May-26`) | RAW veri kalite kontrolü | `stg_*` normalizasyonu çoklu format destekler, parse edilemeyen satır veri kalitesi kuyruğuna düşer |

### 6.4 Ekran Envanteri

| Ekran | Amaç |
|---|---|
| Aktarım / Senkronizasyon | RAW snapshot'ı yükle, sonucu (satır sayısı, hata) göster |
| Dashboard | Ay + şirket/ülke/sevkiyat tipi filtreli özet (Excel "Dashboard" karşılığı) |
| Ortalamalar | Ülke+sevkiyat tipi bazlı Shipping/Duty/Total ortalaması |
| Ortalama Üzeri Faturalar | Eşik üstü kutular |
| Müşteri Kârlılığı | 45 müşteri bazlı fatura vs. maliyet karşılaştırması |
| Mutabakat / Eşleşmeyenler | `tracking_id` bazlı eşleşen ve eşleşmeyen kayıtlar |
| İtiraz ve İadeler | `disputed_items`/`refunds` finansal durumu |
| Veri Kalitesi | Tüm kural ihlalleri (Excel'in 5 kuralı + bu pakette bulunan 3 yeni bulgu) |

---

## 7. Test ve Kalite (QA Müdürü)

### 7.1 Test Stratejisi

- **Birim testleri (pytest):** her hesaplama fonksiyonu (benchmark, above-average, veri kontrolü, Duty allocation) için, Excel'in doğrulanmış (stale olmayan, yeniden hesaplanmış) referans değerleriyle karşılaştırma.
- **Entegrasyon testleri:** RAW→staging→fin_* uçtan uca akış, satır sayısı ve checksum doğrulaması (extraction script'indeki yaklaşımın devamı).
- **Görsel doğrulama:** Dashboard ekran görüntüsü, Excel "Dashboard" sheet'iyle yan yana karşılaştırma (kullanıcının çalışma tarzına uygun).
- **Manuel kabul testi:** Çağla'nın gerçek ay sonu kapanışında paralel çalıştırması (Excel ve yeni sistem aynı anda, sonuçlar karşılaştırılır).

### 7.2 Test Senaryo Matrisi (öne çıkan 12 senaryo)

| No | Senaryo | Ön Koşul | Adımlar | Beklenen Sonuç | Öncelik |
|---|---|---|---|---|---|
| T1 | RAW aktarım satır sayısı doğrulama | Snapshot mevcut | Aktarımı çalıştır | raw_* satır sayısı = CSV satır sayısı | Yüksek |
| T2 | US ülkesinde Duty otomatik "-" | US kutusu, Duty tutarı boş | Hesaplama motorunu çalıştır | Duty alanı "-" | Yüksek |
| T3 | Multi kutu Duty bölünmesi | Aynı multi_no'lu 4 kutu, tek Duty tutarı | Hesaplama motorunu çalıştır | Her kutuya eşit pay, toplam korunuyor | Yüksek |
| T4 | "Bekliyor" metin değeri sayısal alana sızmıyor | `fedex_total_cost='Bekliyor'` olan kutu | Staging dönüşümünü çalıştır | `cost_status='pending'`, sayısal alan NULL | Yüksek |
| T5 | Ortalama altı örneklem (n<3) | Bir ülke+tip grubunda 2 kutu | Ortalamalar hesapla | "Yeterli Veri Yok" gösterilir | Orta |
| T6 | Ortalama üstü %20 eşik | Ortalamanın %25 üstü bir kutu | Above-average hesapla | Kutu listede görünür | Yüksek |
| T7 | Farklı tarih formatı parse | `11-May-26` formatlı kayıt | Staging normalizasyonu | Doğru tarihe dönüşür veya kuyruğa düşer, asla sessizce atılmaz | Orta |
| T8 | Müşteri kârlılığı eşleşme | Bilinen `tracking_id` | Mutabakat çalıştır | Fatura + maliyet doğru eşleşir | Yüksek |
| T9 | Eşleşmeyen tracking_id | Bilinmeyen `tracking_id` | Mutabakat çalıştır | "Eşleşmedi" listesinde görünür, gizlenmez | Yüksek |
| T10 | İtiraz beklemede statüsü | `disputed_items`'ta yeni kayıt | Dispute akışını çalıştır | fin_* kayıtta "beklemede", kesin zarara dahil değil | Orta |
| T11 | Boş veri (0 satırlı tablo) | `refunds` tablosu boş | Aktarımı çalıştır | Hata vermeden "0 kayıt" olarak işlenir | Düşük |
| T12 | Kaynağa yazma yapılmadığının doğrulanması | NeXa DB dosya zaman damgası | Tüm akışı çalıştır | NeXa DB dosyasının `mtime` değişmiyor | Yüksek |

### 7.3 Sürüm Kabul Kontrol Listesi (v1.0)

- [ ] Tüm "Yüksek" öncelikli test senaryoları geçti.
- [ ] Excel referans çıktılarıyla karşılaştırma raporu var ve fark yok (veya farklar açıklanabilir).
- [ ] NeXa veritabanına hiçbir yazma yapılmadığı doğrulandı.
- [ ] Yedekleme planı (Bölüm 11.3) en az bir kez test edildi (yedekten geri yükleme denendi).
- [ ] Runbook (Bölüm 9.2) güncel.

---

## 8. DevOps ve Sürüm (Release Manager)

### 8.1 Ortamlar

| Ortam | Açıklama |
|---|---|
| Geliştirme | Aynı makine, ayrı proje klasörü, ayrı SQLite dosyası |
| Üretim | Aynı makine (tek kullanıcı, sunucu yok) — geliştirme ile aynı, sadece veri klasörü ayrı tutulur **[VARSAYIM]** |

### 8.2 Sürüm Süreci

1. Sprint sonunda DoD kontrol edilir.
2. `tests/` çalıştırılır, hepsi geçmeli.
3. Veritabanı yedeklenir (Bölüm 11.3).
4. Sürüm klasörü/etiketi oluşturulur (örn. `v1.0.0`).
5. `Start Enretag Finans.bat` **[VARSAYIM dosya adı]** ile canlıya alınır.

### 8.3 Sürüm Notu Şablonu

```markdown
## vX.Y.Z — GG.AA.YYYY
### Eklenenler
### Düzeltilenler
### Bilinen Sorunlar
### Veri Kalitesi Notları (varsa yeni bulgular)
```

### 8.4 Geri Dönüş Planı

Her sürümden önce alınan yedek (Bölüm 11.3) korunur; sorun çıkarsa bir önceki yedek dosya üzerine geri dönülür, kod tarafı da bir önceki sürüm klasörüne alınır. **[VARSAYIM: git kullanılmıyorsa klasör bazlı versiyonlama; git kullanılacaksa `git revert` tercih edilir]**

---

## 9. Destek ve Operasyon (Ops Yöneticisi)

### 9.1 Destek Planı

Tek kullanıcı olduğundan resmi bir SLA yok; destek kanalı doğrudan AI asistan oturumu. **[VARSAYIM]**

### 9.2 Runbook İskeleti

- **Kurulum:** venv oluştur, `requirements.txt` yükle, `.bat` ile başlat (NeXa deseniyle aynı).
- **Yeni NeXa verisi alma:** `scripts/data_migration/extract_nexa_raw.py`'yi tekrar çalıştır → yeni snapshot klasörünü bu platformun aktarım ekranından seç.
- **Sık hata: "Bekliyor" görünüyor:** Bu beklenen bir durumdur (FedEx faturası henüz kesilmedi), hata değildir — bkz. Bölüm 6.3.
- **Sık hata: satır sayısı uyuşmuyor:** Aktarımı durdur, `logs/data_extraction/` altındaki log dosyasını incele.

### 9.3 Geri Bildirim Döngüsü

Kullanıcı bir hesaplama farkı fark ederse, önce Excel'in "stale cache" olasılığı kontrol edilir (bkz. NeXa hafızasındaki bilinen sorun), sonra kod tarafı incelenir. Bulgular bu paketin Bölüm 6.3'üne yeni bir "bu pakette bulundu" satırı olarak eklenir.

---

## 10. Siber Güvenlik (Security Yöneticisi)

### 10.1 Varlık Envanteri

| Varlık | Hassasiyet |
|---|---|
| Müşteri adları (`customer_invoices.customer`, 45 firma) | Orta — ticari bilgi, çoğunlukla şirket unvanı |
| Fatura tutarları, kâr/zarar rakamları | Yüksek — şirketin finansal performansı |
| `customer_code` alanında zaman zaman şahıs adı görünmesi (NeXa'da tespit edilmiş, örn. "IRFAN OZHAN") | Orta-Yüksek — kişisel veri olabilir, KVKK kapsamına girebilir |

### 10.2 Tehdit Modeli

| Tehdit | Giriş Noktası | Etki | Olasılık | Önlem |
|---|---|---|---|---|
| Yedek dosyasının şifresiz taşınması (USB/bulut) | Manuel yedekleme | Finansal veri sızıntısı | Orta | Yedekleri şifreli bir arşive koy veya erişimi kısıtlı bir klasörde tut |
| Yerel dosyaya yetkisiz erişim (paylaşımlı bilgisayar) | İşletim sistemi kullanıcı hesabı | Veri görüntüleme/değiştirme | Düşük | Windows kullanıcı hesabı ayrımı, veri klasörünü paylaşılan konumlara koyma |
| RAW veriye yanlışlıkla yazma (kod hatası) | `core/ingest_from_nexa.py` | Kaynağın bütünlüğü bozulur | Düşük | `raw_*` tablolarına sadece INSERT izinli bağlantı, kod incelemesinde kontrol |
| NeXa DB dosyasına yanlışlıkla bağlanıp yazma | Yanlış dosya yolu | NeXa operasyonel verisi bozulur | Düşük | Bu platform NeXa DB dosyasına asla doğrudan bağlanmaz, sadece dışa aktarılmış CSV/snapshot okur |

### 10.3 Güvenlik Kontrol Listesi

- [ ] SQL sorguları parametreli (string birleştirme ile SQL enjeksiyonu riski yok).
- [ ] Dosya yolları kullanıcı girdisinden değil, sabit yapılandırmadan geliyor.
- [ ] Bağımlılıklar (`requirements.txt`) düzenli güncelleniyor.
- [ ] Yedek dosyaları erişim kısıtlı bir klasörde.

### 10.4 Veri Koruma / KVKK

`customer_code`/`customer` alanlarında şahıs adı geçme ihtimali olduğundan, bu alanlar sadece iş amaçlı (mutabakat/kârlılık) kullanılmalı, dışa aktarımlarda gereksiz yere paylaşılmamalı. **[VARSAYIM: şirket şu an KVKK'ya tabi resmi bir süreç işletmiyor; ölçek büyürse resmi bir değerlendirme önerilir.]**

---

## 11. Veri Yönetimi (DBA)

### 11.1 Veri Modeli (kavramsal, metin ER özeti)

```
Invoice (NeXa'dan) 1 ── N ShipmentCharge
Invoice 1 ── N Product
Box (multi_no ile gruplanır) N ── 1 MasterTracking (mantıksal, ayrı tablo değil)
CustomerInvoiceLine N ── 1 Box (tracking_id üzerinden, bazen eşleşmez)
Box 1 ── N DisputedItem
Box 1 ── N Refund
```

### 11.2 Şema Taslağı (üç katmanlı)

**`raw_*` katmanı** — bu paketin CSV çıktısıyla birebir aynı, 9 tablo (invoices, shipment_charges, customer_invoices, boxes, products, refunds, disputed_items, invoice_review, legacy_fedex_invoice_raw), hiç değiştirilmez.

**`stg_*` katmanı (örnek — boxes)**

| Alan | Tip | Not |
|---|---|---|
| id | INTEGER | raw_boxes.id ile aynı |
| ship_date | DATE | normalize edilmiş |
| customer_code | TEXT | |
| country | TEXT | büyük harf normalize |
| tracking_id | TEXT | |
| multi_no | TEXT | |
| customer_total_invoice | REAL NULL | |
| fedex_total_cost | REAL NULL | "Bekliyor" ise NULL |
| cost_status | TEXT | 'known' / 'pending' / 'no_duty_expected' |
| profit_loss | REAL NULL | cost_status='pending' ise NULL |

**`fin_*` katmanı (örnek — fin_customer_profitability)**

| Alan | Tip | Not |
|---|---|---|
| customer | TEXT | |
| period | TEXT (YYYY-MM) | |
| total_billed | REAL | customer_invoices toplamı |
| total_cost | REAL | eşleşen boxes toplamı |
| finansman_farki | REAL | total_billed - total_cost ("Kâr/Zarar" yerine bu terim kullanılır) |
| matched_box_count | INTEGER | |
| unmatched_tracking_count | INTEGER | mutabakat kalitesi göstergesi |

### 11.3 Yedekleme Planı

- **Sıklık:** Her sürüm öncesi + haftalık otomatik (dosya kopyası). **[VARSAYIM]**
- **Konum:** `data/backups/YYYY-MM-DD_HH-MM-SS/` (extraction script'indeki zaman damgalı klasör deseniyle tutarlı).
- **Doğrulama:** SHA-256 checksum (bu pakette zaten uygulanan yönteme benzer şekilde).
- **Geri yükleme testi:** Her sürümde en az bir kez, yedekten geri yükleyip uygulamanın açıldığı doğrulanır.

### 11.4 Migration Stratejisi

- Şema değiştiğinde (`fin_*` katmanına yeni alan eklendiğinde), `stg_*→fin_*` dönüşümü yeniden çalıştırılabilir olmalı (idempotent) — mevcut `raw_*`/`stg_*` verisi kaybolmadan.
- Kaynak (NeXa) şeması değişirse (`_ensure_columns` ile yeni kolon eklenmesi gibi), bu paketin aktarım script'i yeni kolonları algılayıp `raw_*`'a otomatik ekleyecek şekilde tasarlanmalı **[VARSAYIM — Sprint 1'de teknik karar netleştirilecek]**.
- Türkçe yerel ayar: veritabanında tarih ISO (`YYYY-MM-DD`) formatında saklanır, sayılar nokta ondalık ayraçla saklanır; UI'da görüntülenirken Türkçe biçime (GG.AA.YYYY, virgül ondalık) çevrilir.

---

## Açık Kararlar ve Sonraki Adımlar

**Kullanıcının karar vermesi gereken maddeler:**
1. Proje adı ve klasör konumu onayı ("Enretag Finans Platformu" ismi ve nereye kurulacağı — aynı bilgisayarda ayrı bir klasör mü, farklı bir konum mu).
2. Arayüz teknolojisi olarak Streamlit'in devamı onayı (ADR-001), yoksa farklı bir teknoloji tercihi var mı.
3. NeXa senkronizasyon sıklığı: manuel mi kalsın, yoksa zamanlanmış görev (scheduled task, NeXa'daki Pay Stub otomasyonuna benzer) mi kurulsun.
4. `invoice_review` tablosundaki NULL `invoice_no` sorununun NeXa tarafında mı düzeltileceği, yoksa bu platformun onu hiç kullanmaması mı tercih edildiği.
5. KVKK/veri koruma için resmi bir sürece ihtiyaç olup olmadığı (Bölüm 10.4).

**İlk sprintin ilk 3 işi:**
1. Proje klasörünü oluştur, `git init`, temel `requirements.txt` ve `.bat` başlatıcıyı NeXa deseninden uyarla.
2. `raw_*` şemasını oluştur, bu paketteki 9 CSV dosyasını (`data/raw/nexa/2026-09-22_13-53-26/`) satır sayısı doğrulamasıyla yükle.
3. `stg_boxes` dönüşümünü yaz ve "Bekliyor" metin değerlerini `cost_status='pending'` olarak ayrıştıran testi geçir (T4).
