# Orkestrasyon MCP v4 cilası — Ralph turu raporu

Tarih: 2026-10-17. Kapsam: `tools/orchestrator_mcp`. Commit'ler push edilmedi.

## Ne değişti

| Story | Değişiklik | Kanıt |
|---|---|---|
| US-001/002 | Çevrimdışı + canlı benchmark harness (`evals/bench.py`), GitHub/arXiv araştırması (`ARASTIRMA.md/.pdf`) | `test_bench.py` 3 test |
| US-003 | Aider tarzı SEARCH/REPLACE edit formatı; büyük dosyada tam metin yerine yalnız değişen blok | `test_edits.py` 10 test; sentetik büyük dosyada yanıt ≥%95 küçük |
| US-004 | `Model output token limit reached` artık yeniden denenir, bütçe ikiye katlanır (üst sınır 16384); düzyazıya sarılı/kesik çitli JSON çıkarılır; kapsam dışı dosyada açıklayıcı geri bildirim; `ORCHESTRATOR_RETRY_CONTEXT=full\|clean` | `test_adaptive.py` |
| US-005 | Hesap başına kimlik/proje cache'i (TTL 600 sn, 401/403'te düşer, hatalı listeleme cache'lenmez). 3 üretimde `auth-files` çağrısı 3 → 1 | `test_speed.py` 5 test |
| US-007 | `apply` aşamasında yeni eklenen API anahtarı / özel anahtar / bearer token reddedilir; hata mesajı sırrı içermez | `test_secrets.py` 6 test; reviewer düzeltmeleri: kapsam hatası dosya adını verir, mevcut dosyadaki sır yeni sırrı gizleyemez, 401 ile yarışan listeleme önbelleğe yazılmaz |

Test durumu: 84 test geçti (test_secrets, test_speed, test_adaptive, test_edits, test_bench, test_orchestrator, test_robustness), `omc ralph verify` rc=0.

## Canlı önce/sonra (6 görev × 2 tekrar, gemini-3.8-flash-high, 15 hesaplık havuz)

| Metrik | Önce (fdaf7c12) | Sonra, retry=full | Sonra, retry=clean |
|---|---|---|---|
| Geçme oranı | 1,00 | 1,00 | 1,00 |
| İlk denemede geçme | 1,00 | 1,00 | 1,00 |
| Süre (ort. sn / koşu) | 5,59 | 6,12 | 5,12 |
| Toplam token / koşu | 1410 | 1776 | 1798 |
| Çıktı token / koşu | 384 | 402 | 425 |

Ham veri: `live-bench-before.json`, `live-bench-full.json`, `live-bench-clean.json`.

## Kötüleşen metrik (açıkça)

- **Token +%26.** Neden: SYSTEM istemine edit formatı talimatı eklendi (~60 token/çağrı). Bu görev setinde dosyalar küçük (<60 satır), edit formatı hiç tetiklenmedi; kazancı yalnız büyük dosyada görülür (sentetik testte ≥%95 yanıt küçülmesi). Canlı ölçümde kazancı **kanıtlanmadı**.
- Süre farkı (5,1–6,1 sn) 2 tekrarda gürültü sınırında; iyileşme ya da kötüleşme iddia edilmez.

## Ölçülemeyen / açık

- **Retry bağlamı A/B (full vs clean) sonuçsuz.** Dört canlı koşuda hiç yeniden deneme olmadı (ilk denemede geçme 1,00); iki kolu ayıracak veri çıkmadı. Varsayılan `full` kaldı (davranış değişmedi). Ayırıcı bir ölçüm için ilk denemede başarısız olması muhtemel görevler gerekir.
- Edit formatının canlı token kazancı: büyük dosyalı görev seti gerekir.
- 18 araçlı sunucunun gerçek bir MCP istemcisinde (Antigravity) yeniden bağlanması test edilmedi.
- `feedbackCommands` yeni test dosyalarını içermiyor; bunlar elle koşuldu.

## Kota harcaması

Canlı: 3 benchmark koşu kümesi × 2 tekrar × 6 görev = 36 üretim çağrısı. Bench `total_tokens_mean` koşu başına (6 görev) değerdir; toplam ≈ 2 × (1410 + 1776 + 1798) ≈ **10k token**. Gemini yalnız bu MCP'nin testleri için kullanıldı.
