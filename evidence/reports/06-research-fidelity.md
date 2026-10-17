# Kaynak sadakati araştırma testi: Sonnet tek vs Gemini MCP + sonda orkestratör kontrolü

Tarih: 2026-10-17. Karar (Enes): site/oyun/uygulama işi orkestratörün kendisinde kalır, Gemini'ye gitmez; kaynak sadakati kritik araştırma Gemini MCP ile denenir ve en son orkestratör kontrol eder. Bu rapor yalnız ikinci kısmı ölçer.

## Düzenek

Konu: serbest iş parçacıklı (free-threaded) Python. Altı kaynak yerel metin olarak donduruldu (PEP 703, PEP 779, PEP 684, free-threading HOWTO, 3.13 ve 3.14 What's New). İki kol aynı görevi aldı: 12 iddia, her biri en çok 30 kelimelik birebir alıntı ve kaynak kimliği; ilk 8 iddia sabit konulara bağlı.

- Kol A: Sonnet 5.5 tek başına okur ve yazar.
- Kol B: Sonnet 5.5 orkestratör; altı Gemini işçisi (kaynak başına bir) iddia ve alıntı çıkarır; orkestratör alıntıları `quote_check.py` ile kaynakta mekanik doğrular, geçmeyeni atar, raporu kurar.

Puanlama: (1) alıntı kaynakta birebir var mı, mekanik ve bağımsız betikle; (2) kör Opus hakem, rastgele X/Y etiketi, iddia alıntı tarafından destekleniyor mu ve 8 konu kapsandı mı.

## Sonuç

| Ölçü | Sonnet tek (A) | Gemini MCP + kontrol (B) |
|---|---|---|
| Alıntı kaynakta birebir (mekanik) | 12/12 | 12/12 |
| Hakem: destekli / kısmi / desteksiz | 11 / 1 / 0 | 11 / 1 / 0 |
| Zorunlu 8 konudan kapsanan | 8/8 | 7/8 (PEP 703'ün ne önerdiği yok) |
| Sonnet token (ham) | 102.510 | 99.888 |
| Sonnet token (74.498 taban çıkarılmış) | 28.012 | 25.390 |
| Süre | 46,7 sn | 67,8 sn |
| Gemini token (ek) | 0 | 115.736 |

Gemini işçilerinin ürettiği 60 alıntının 2'si kontrolü geçemedi (biri 30 kelimeyi aştı, biri kaynakta yok); orkestratör ikisini de kullanmadı. Kontrol olmasaydı B raporunda uydurma alıntı olabilirdi.

## Yorum

- Sadakat: iki kol eşit. B'nin güvencesi sondaki mekanik kontrol; işçi ham çıktısı tek başına güvenilmez (60 alıntıda 2 hata, %3,3).
- Maliyet: Claude tokenı neredeyse aynı (ham -%2,6). Altı kaynak küçük olduğu için A grep ile hızlı okudu; orkestrasyon kazancı büyük kaynak setinde beklenir, burada ölçülmedi.
- Hız: B 1,45 kat yavaş.
- Kalite ayrıntısı: B'nin raporunda bir iddia alıntısından fazlasını söylüyor, bir iddia (PEP 779 bellek yüzdesi) yazıldığı tarihteki durumu güncel gibi sunuyor; A'da bir iddia alıntıdan azını destekliyor.

Karar önerisi: kaynak sadakati kritik işte Gemini işçi kullanılabilir, ama yalnız mekanik alıntı kontrolü ve orkestratör gözden geçirmesiyle; bu testte token veya hız avantajı göstermedi, yalnız yük dağıtımı. Kaynak seti büyüdükçe fark değişebilir.

## Sınırlar

- Tek koşu (n=1), tek konu, altı kaynak.
- Kendi seçtiğim konu ve konu listesi; hakem tek Opus ve X konumu yanlılığı olabilir.
- Mekanik kontrol alıntının varlığını doğrular, anlamını değil; anlam için hakem var.
- B kolu MCP stdio yerine aynı kütüphaneyi `orch_cli.py` ile kullandı.
- Gemini token son deneme sayımıdır.

## Dosyalar

`res/task.md`, `res/quote_check.py`, `res/score_res.py`, `res/sources/*`, `run/A_res/report.*`, `run/B_res/report.*`, `judge_res/verdict.json`, `judge_res_map.json`.
