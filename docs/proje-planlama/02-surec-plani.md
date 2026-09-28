# Enretag Finans Platformu — Süreç Planı

Hazırlanma tarihi: 22.09.2026 · İlgili paket: `01-proje-baslangic-paketi.md`

## Faz ve Kilometre Taşı Tablosu

| Faz | Süre | Sorumlu Roller | Teslimatlar | Tamamlanma Kriteri |
|---|---|---|---|---|
| Faz 1 — Aktarım & Staging (E1) | H1–H2 | Dev Manager, DBA | `raw_*` şeması, yükleme script'i | 9 tablo, satır sayısı kaynakla %100 eşleşiyor |
| Faz 2 — Finansal Şema (E2) | H3–H4 | DBA, Dev Manager | `stg_*`/`fin_*` şeması, normalizasyon kuralları | Migration idempotent çalışıyor, "Bekliyor" ayrıştırması test geçiyor |
| Faz 3 — Hesaplama Motoru (E3) | H5–H7 | Dev Manager, BA, QA | Benchmark, above-average, veri kontrolü modülleri | Excel referans çıktılarıyla satır bazlı eşleşme |
| Faz 4 — Mutabakat & İtiraz/İade (E4, E5) | H8–H9 | BA, Dev Manager | Mutabakat modülü, itiraz/iade finansal kaydı | `tracking_id` eşleşme oranı ölçülüyor, eşleşmeyenler görünür |
| Faz 5 — Dashboard & Sürüm (E6, E8) | H10–H12 | QA, DevOps, PM | Dashboard UI, kabul kontrol listesi, v1.0 sürümü | QA kabul kontrol listesi geçti, runbook teslim edildi |
| Güvenlik & Yedekleme (E7) | H1–H12 (paralel) | Security, DBA, DevOps | Tehdit modeli uygulaması, yedekleme otomasyonu | Her sürüm öncesi yedek alınıp doğrulanıyor |

## Sprint Takvimi

| Sprint | Tarih Aralığı | Hedef | Ana İşler | Bağımlılık |
|---|---|---|---|---|
| S1 | H1–H2 | Aktarım hattı çalışır durumda | `raw_*` şeması, CSV yükleme, satır sayısı doğrulama, git deposu kurulumu | Bu paketteki RAW snapshot (`data/raw/nexa/2026-09-22_13-53-26/`) |
| S2 | H3–H4 | Finansal şema hazır | `stg_*`/`fin_*` şeması, tarih normalizasyonu, "Bekliyor" ayrıştırma, indeksler | S1 tamamlanmış olmalı |
| S3 | H5–H6 | Benchmark motoru Excel ile eşleşiyor | Ortalamalar + Ortalama Üzeri Faturalar modülleri, birim testleri | S2 tamamlanmış olmalı |
| S4 | H7–H8 | Veri kontrolü + mutabakat başlangıcı | Veri Kontrolü modülü (Excel'in 5 kuralı + 3 yeni bulgu); mutabakat modülü başlangıç | S3 tamamlanmış olmalı |
| S5 | H9–H10 | Mutabakat + itiraz/iade tamam | Mutabakat modülü bitiş, itiraz/iade finansal akışı | S4 tamamlanmış olmalı |
| S6 | H11–H12 | Dashboard + sürüm | Dashboard UI, QA kabul kontrolü, yedekleme testi, v1.0 sürümü | S5 tamamlanmış olmalı |

## Zaman Çizelgesi (hafta bazlı)

| İş Paketi | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | H9 | H10 | H11 | H12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1 — Aktarım & Staging | █ | █ | | | | | | | | | | |
| E2 — Finansal Şema | | | █ | █ | | | | | | | | |
| E3 — Hesaplama Motoru | | | | | █ | █ | █ | | | | | |
| E4 — Mutabakat | | | | | | | █ | █ | █ | | | |
| E5 — İtiraz/İade | | | | | | | | █ | █ | | | |
| E6 — Dashboard/Raporlama | | | | | | | | | | █ | █ | |
| E7 — Güvenlik & Yedekleme | █ | █ | █ | █ | █ | █ | █ | █ | █ | █ | █ | █ |
| E8 — Test & Sürüm | | | | | | | | | | | █ | █ |

## Kritik Yol ve Bağımlılıklar

Sıralı kritik yol: **E1 (Aktarım & Staging) → E2 (Finansal Şema) → E3 (Hesaplama Motoru) → E4 (Mutabakat) → E6 (Dashboard) → E8 (Test & Sürüm)**.

- E1 gecikirse tüm proje aynı oranda kayar — RAW veri olmadan hiçbir hesaplama doğrulanamaz.
- E2'deki "Bekliyor" ayrıştırma kuralı (Bölüm 6.3, R1) E3'ün doğruluğunun ön koşulu; atlanırsa kârlılık rakamları sessizce yanlış çıkar.
- E5 (İtiraz/İade) kritik yolun dışında ama E6 (Dashboard) başlamadan bitmiş olmalı, çünkü dashboard itiraz/iade durumunu da gösteriyor.
- E7 (Güvenlik & Yedekleme) tüm proje boyunca paralel yürür; herhangi bir fazı geciktirmez ama E8'deki sürüm kabul kontrol listesinin bir parçasıdır (yedekleme testi olmadan sürüm çıkmaz).

## Kontrol Noktaları

| Faz Sonu | Devam/Duraklat Kararı İçin Sorular |
|---|---|
| Faz 1 (H2) | Satır sayıları kaynakla eşleşti mi? Şema NeXa'nın gerçek `core/database.py` yapısıyla tutarlı mı? |
| Faz 2 (H4) | "Bekliyor" ve NULL PK sorunları öngörülen şekilde ayrıştırıldı mı? Migration tekrar çalıştırılabilir mi (idempotent)? |
| Faz 3 (H7) | Benchmark/above-average/veri kontrolü sonuçları Excel'in güncel (stale olmayan) çıktısıyla satır satır eşleşiyor mu? Eşleşmiyorsa fark açıklanabilir mi? |
| Faz 4 (H9) | Mutabakat eşleşme oranı hedeflenen ≥%90'a yakın mı? Eşleşmeyenler kullanıcıya anlamlı şekilde gösteriliyor mu? |
| Faz 5 (H12) | QA kabul kontrol listesinin tamamı geçti mi? Yedekten geri yükleme denendi mi? Runbook güncel mi? |
