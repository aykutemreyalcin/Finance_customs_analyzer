# NeXa Sağlık Raporu — 22 Eylül 2026

Kapsam: `app.py`, `core/*.py`, `data/finance_customs.db` (canlı veritabanının **kopyası** üzerinde, salt-okunur).
Kontroller Linux üzerinde pandas 2.3.3 ile çalıştırıldı; sizin venv'inizde pandas 3.0.5 var — tarih bulgusu (C-1) aynı kurala dayanıyor ama sizin ortamınızda ayrıca **doğrulanmalı**.

Terimler: **Tespit edildi** = veride/kodda görüldü · **Düzeltildi** = kod değişti ve test edildi · **Öneri** = onayınızı bekliyor.

---

## Özet

| # | Seviye | Bulgu | Etki | Durum |
|---|---|---|---|---|
| C-1 | Kritik | Karışık tarih formatları | 741 kutu ($17.057 gelir) tarih filtrelerinde görünmüyordu | **Düzeltildi** (kod + veritabanı, 22.09.2026 onaylı) |
| C-2 | Kritik | Aynı takip numarasıyla 24 kutu tekrarlanmış (53 satır) | $3.698,70 gelir / $2.141,88 FedEx maliyeti çift sayılıyor olabilir | Öneri (inceleme) |
| H-1 | Yüksek | Hiçbir kovaya girmeyen FedEx fatura satırları | 541 satır, $10.177,46 | Öneri (inceleme) |
| H-2 | Yüksek | Multi grupta 2+ gümrük (duty) faturası | 4 grup, $167,98 kayboluyor | Öneri |
| H-3 | Yüksek | Müşteri faturası var ama kutu "faturasız" sayılıyor | 33 kutu, $5.697,20 gelir hariç | Öneri (veri düzeltme) |
| H-4 | Yüksek | Bozuk PDF yüklemesi sayfayı çökertiyor / fatura no'suz PDF tekrar kayıt üretiyor | — | **Düzeltildi** |
| M-1 | Orta | PDF'ten oluşan kutular sonraki kutu importuyla hiç tamamlanmıyor | 361 kutuda müşteri, 746'da şirket, 478'de ülke boş | Öneri |
| M-2 | Orta | Düzeltilmiş FedEx faturası tekrar yüklenince kutu tutarı güncellenmiyor | — | Öneri |
| M-3 | Orta | Uygulama yerel ağdaki herkese açık olabilir (şifre yok) | Aynı Wi-Fi'daki biri NeXa'yı açıp değişiklik yapabilir | Öneri |
| M-4 | Orta | Refund silme onaysızdı | Refunds tablosu şu an boş (0 kayıt) | **Düzeltildi** |
| M-5 | Orta | Data Quality ekranında tarih/ülke serbest metin | C-1'i besliyor | Öneri |
| M-6 | Orta | 10 fatura "Unknown" tipinde $0 olarak kayıtlı | Gerçek tutarları olabilir | İnceleme |
| L-1 | Düşük | `requirements.txt` eksik (jinja2) ve sürümsüz | Yeni kurulumda "All Shipment Charges" açılmıyor | jinja2 **eklendi**; sürüm sabitleme Öneri |
| L-2 | Düşük | Otomatik test yoktu | — | **Eklendi** (21 test) |
| L-3 | Düşük | `app.py` 2.850 satır tek dosya; iki finans modeli yan yana | Bakım zorluğu | Yol haritası |
| L-4 | Düşük | Başarı mesajları `st.rerun` yüzünden hemen kayboluyor | UX | Öneri |

Genel tablo: çekirdek finans kuralları (faturasız kutu = 0, FedEx bekleyen kutu = maliyet 0, 14 gün yalnız etiket değiştirir) **testle doğrulandı ve doğru çalışıyor**. Sorunlar kuralların kendisinde değil, **verinin kurala nasıl ulaştığında** (tarih formatı, tekrar eden kayıt, eşleşmeyen satır).

---

## Kritik

### C-1 · Karışık tarih formatları kutuları filtrelerden düşürüyor
- **Kanıt:** `boxes.ship_date` üç formatta: `2026-01-02 00:00:00` (8.941), `Sep 08, 2026` (470 — PDF'ten gelenler), `2026-09-08` (271). `pd.to_datetime(..., errors="coerce")` formatı ilk satırdan tahmin ediyor, diğerlerini sessizce boş (NaT) yapıyor → **741 kutu** tarihsiz kalıyor.
- **Etki:** Bu kutular ($17.057,28 gelir, $11.871,27 kâr) Dashboard'daki "Current Month / Previous Month / YTD / Custom" filtrelerinde ve Customer Profitability ay filtresinde **görünmüyor**. Örnek: Eylül 2026'da 560 kutu var, uygulama 548 görüyor (−$442,74 gelir). "All Time" toplamları doğru. Ayrıca FedEx'i bekleyen bu kutular tarihsiz olduğu için her zaman "Invoice Overdue" etiketi alıyor.
- **Öneri:** Tek bir ortak tarih çözümleyici (`format="mixed"`) yazıp tüm `pd.to_datetime(ship_date)` çağrılarında kullanmak. Veritabanındaki tarihlere dokunmaz; sadece okuma düzelir. Kopya üzerinde denendi: 0 kutu tarihsiz kalıyor. Para hesabını değiştirmez ama filtreli ekranlardaki toplamları değiştirir → **onayınız gerekiyor**.
- **Test:** `test_mixed_ship_date_formats_all_parse` (şu an bilinçli olarak "beklenen hata" olarak işaretli).

### C-2 · Tekrar eden takip numaraları
- **Kanıt:** 24 takip numarası `boxes` tablosunda 2+ kez var (toplam 53 satır). Fazla 29 satırın geliri $3.698,70, FedEx maliyeti $2.141,88, kârı $1.556,82. Satırların bir kısmı birebir aynı, bir kısmı farklı.
- **Etki:** Bu tutarlar Dashboard / Reconciliation / Customer Profitability'de çift sayılıyor olabilir. Ayrıca PDF eşleştirmesi bu numaralarda yalnızca ilk satırı güncelliyor.
- **Öneri:** Önce 24 numaranın satır satır listesini size çıkarayım; hangisinin gerçek tekrar olduğuna siz karar verin. Silme/birleştirme **yalnızca onayınızla**.

## Yüksek

### H-1 · Hiçbir kovaya girmeyen FedEx satırları ($10.177,46)
- **Kanıt:** 485 Duty satırı ($9.921,64) + 56 Shipping satırı ($255,82), takip numarası bir kutuyla eşleşiyor ama o kutuda **başka bir** fatura numarası kayıtlı. `_sync_box` bilinçli olarak üzerine yazmıyor (doğru), ama bu para ne "Included", ne "Excluded", ne "Unallocated" kovasında.
- **Neden fark edilmedi:** `compute_fedex_reconciliation` toplamı üç kovanın toplamı olarak hesaplıyor; yani kimlik (identity) tanım gereği hep tutuyor, gerçek fatura satırlarıyla hiç karşılaştırılmıyor.
- **Öneri:** (1) Reconciliation'a "kutuya bağlanamamış ikinci fatura" satırı ekleyip bu parayı görünür yapmak; (2) bu satırların FedEx düzeltme/yeniden faturalama mı, eski (legacy) numara farkı mı olduğunu birlikte incelemek. **NEEDS INVESTIGATION.**

### H-2 · Multi grupta birden fazla duty faturası ($167,98)
- **Kanıt:** `enrich_boxes_for_display` bir Multi grupta duty taşıyan ilk kutunun tutarını bütün gruba bölüyor; ikinci duty kutusunun tutarı kayboluyor. 4 grupta $167,98.
- **Öneri:** Gruptaki tüm duty tutarlarını toplayıp bölmek. Para hesabı → **onay gerekiyor**.

### H-3 · Faturası olduğu halde "Not Invoiced" sayılan kutular ($5.697,20)
- **Kanıt:** 25 kutunun ücret alanları boş ama `customer_invoices` tablosunda $3.670,80 tutarında satırları var (kutu, müşteri faturası importundan *sonra* oluşmuş; senkron sadece import anında çalışıyor). 8 kutunun ücretleri `0.0` ama $2.026,40 faturası var (senkron `0.0`'ı "dolu" sayıp atlıyor).
- **Öneri:** Mevcut `sync_customer_fees_from_invoices` fonksiyonunu tüm kutular için bir kez çalıştırmak (25 kutu, sadece boş alanları doldurur); 8 adet `0.0` kutu için ayrı karar. Veri değişikliği → **onay gerekiyor**.

### H-4 · PDF yükleme hataları — **DÜZELTİLDİ**
- **Önce:** Okunamayan bir PDF tüm sayfayı hata ekranıyla çökertiyor, aynı partideki diğer dosyalar yüklenmiyordu. Fatura numarası bulunamayan bir PDF satırları `NULL` numarayla kaydediyordu; her tekrar yüklemede kayıtlar çoğalıyordu.
- **Şimdi:** Her dosya ayrı deneniyor; hatalı dosya adıyla birlikte kırmızı mesaj gösteriliyor, diğerleri yükleniyor. Fatura numarası yoksa hiçbir şey yazılmadan reddediliyor. Bir paket PDF'te hata olursa o dosyanın hiçbir faturası yarım kalmıyor (hepsi ya da hiçbiri).
- **Dosyalar:** `app.py` (Upload Data bölümü), `core/ingest.py`.

## Orta

- **M-1** `box_import.import_boxes` var olan takip numarasını tamamen atlıyor; PDF'ten önce oluşmuş "yarım" kutunun müşteri/ülke/şirket alanları hiç dolmuyor. Öneri: yalnızca **boş** alanları dolduran birleştirme (mevcut değerlerin üzerine asla yazmadan).
- **M-2** Aynı fatura numarası düzeltilmiş tutarla yeniden yüklenirse `shipment_charges` güncelleniyor ama kutudaki tutar eski kalıyor. Öneri: aynı fatura numarasıysa tutarı güncellemek (farklı numarada yine dokunmamak).
- **M-3** Streamlit varsayılan olarak tüm ağ arayüzlerini dinliyor; NeXa'da şifre yok. Öneri: `.streamlit/config.toml` içine `address = "localhost"`. (NeXa'yı başka bir cihazdan açıyorsanız söyleyin, o zaman farklı çözüm gerekir.)
- **M-4** Refund silme artık "Confirm delete (adet / $tutar)" kutucuğu işaretlenmeden çalışmıyor — **DÜZELTİLDİ**.
- **M-5** Data Quality'deki tarih ve ülke kutuları serbest metin; yeni bir tarih formatı girilebiliyor. Öneri: tarih seçici + ülke kodunu büyük harfe çevirme.
- **M-6** 10 FedEx faturası "Unknown" tipinde ve $0 (ör. 9-323-07969, 9-332-67876). Gerçek tutarı olan faturalar olabilir; PDF'lerine bakılmalı.
- Performans: tablolarda `tracking_id` / `invoice_no` indeksi yok; şu anki veri boyutunda (≈10 bin kutu) sayfalar sorunsuz açılıyor, ölçülmüş bir yavaşlık yok → şimdilik gerek yok.

## Düşük

- **L-1** `requirements.txt`'e `jinja2` eklendi (All Shipment Charges sayfası buna ihtiyaç duyuyor; sizin venv'inizde zaten kurulu). Öneri: çalışan sürümleri sabitlemek (pandas 3.0.5, streamlit 1.63.0 …) — güncelleme bir gün uygulamayı bozmasın.
- **L-2** `tests/` klasörü eklendi (aşağıda).
- **L-3** `app.py` tek dosyada 13 sayfa; eski (`Bekliyor`) ve yeni (Actual) finans modelleri yan yana. Şu an çalışıyor; büyümeye devam ederse sayfalara bölünmeli (Tip D — ayrıca onay).
- **L-4** Başarı mesajları hemen kayboluyor (`st.rerun`). Yükleme hataları için çözüldü; diğerleri için aynı yöntem uygulanabilir.
- `legacy_import.py` fonksiyonları tabloları tamamen silip yeniden yazıyor; arayüzden erişilemiyor (iyi). Canlı veride çalıştırılmamalı — CLAUDE.md'ye not edildi.

## Güvenlik özeti (inceleme, tam güvenlik testi değil)
SQL sorguları parametreli; dinamik kolon adları yalnızca koddan geliyor (güvenli). Kodda şifre/anahtar yok. `allow_unsafe_jscode` sadece sabit biçimlendirme kodlarında kullanılıyor. Tek açık nokta M-3 (ağ erişimi, kimlik doğrulama yok). Veritabanı bütünlük kontrolü: `ok`.

---

## Bu turda yapılan değişiklikler

| Dosya | Değişiklik |
|---|---|
| `app.py` | PDF yüklemede dosya bazlı hata yakalama + görünür hata mesajı; refund silmede onay kutusu |
| `core/ingest.py` | Fatura numarası yoksa reddet; hata olursa rollback, bağlantı her durumda kapanıyor |
| `requirements.txt` | `jinja2` eklendi |
| `requirements-dev.txt` | Yeni (pytest) |
| `tests/` | Yeni: 21 test (`test_analytics.py`, `test_ingest.py`) |
| `CLAUDE.md` | Import davranışlarının gerçek hali, test bölümü, reconciliation kimliği notu |
| `backups/code_2026-09-22/` | Değişiklik öncesi `app.py`, `ingest.py`, `CLAUDE.md` kopyaları (geri almak için) |

**Veritabanına ve Excel dosyasına hiçbir şekilde yazılmadı.**

## Ne test edildi
- `pytest tests`: **18 geçti, 3 beklenen hata** (C-1, H-1, H-2'yi kanıtlayan testler; düzeltildiklerinde otomatik olarak uyarı verecekler). Canlı veritabanı testi salt-okunur modda çalıştı.
- Streamlit `AppTest` ile veritabanı kopyası üzerinde **13 sayfanın hepsi açıldı**; uygulama kodundan kaynaklı hata yok. (All Shipment Charges benim test ortamımda jinja2 eksikliğinden açılmadı; sizin venv'inizde jinja2 kurulu.)
- **Test edilmedi:** Gerçek bir bozuk PDF'in arayüzden yüklenmesi (birim testle doğrulandı), Windows'taki kendi venv'iniz. Lütfen NeXa'yı **tamamen kapatıp yeniden başlatın** (core dosyaları değişti).

## Önerilen sıra (onay bekleyenler)
1. **C-1** tarih çözümleyici (kod, veri değişmez) — en büyük etki, en düşük risk.
2. **C-2** tekrar eden kutuların listesini çıkarayım → siz karar verin.
3. **H-3** 25 kutunun ücretlerini müşteri faturalarından doldurma (önce tam liste + tutar).
4. **H-1** Reconciliation'da eşleşmeyen FedEx satırlarını görünür yapma + inceleme.
5. **H-2** Multi duty toplama düzeltmesi.
6. M-3 localhost, M-1, M-2, M-5, L-1 sürüm sabitleme.
