# Orkestrasyon MCP — alan matrisi raporu

Tarih: 2026-10-17. Model: gemini-3.8-flash-high, 15 hesaplık havuz. Her görev, modelin değil **yerel betiğin** kararıyla puanlanır.
Doğrulama: kabul betiği, uygulanmış (applied) ağaçta bağımsız yeniden çalıştırılır. Analiz/araştırma cevapları yerelde hesaplanmış gerçek değerle karşılaştırılır.

## Sonuç özeti

- **Son koşu (düzeltme sonrası, 9 alan × 2 tekrar): 44/46 geçti (%96).** Tek başarısız görev ANA-2 (2/2 tekrarda); aynı soru açık yazılınca (ANA-3) 3/3 geçti.
- 23 görevden 21'i ilk denemede geçti; ANA-2 geçemedi; X-IMPOSSIBLE kasıtlı imkansız olduğu için 2 denemede başarısız oldu (beklenen).
- Testin kendisi doğrulandı: her kabul betiği dokunulmamış sandbox'ta **başarısız**, bilinen doğru çözümle **geçiyor** (`test_matrix.py`, 4 test).
- Sistem testleri: 87 test geçti (`test_plan_overlap.py` yeni).

## Alan bazlı sonuçlar (ham: `live-matrix-final.json`)

| Alan | Görev | Tür | Geçti | İlk deneme | Ort. deneme | Ort. token | Ort. model sn |
|---|---|---|---|---|---|---|---|
| bugfix | BUG-1 | code | 2/2 | 2/2 | 1 | 522.5 | 2.2 |
| bugfix | BUG-2 | code | 2/2 | 2/2 | 1 | 853.5 | 4.4 |
| bugfix | BUG-3 | code | 2/2 | 2/2 | 1 | 1790.5 | 9.2 |
| cleaning | CLEAN-1 | code | 2/2 | 2/2 | 1 | 1769 | 7.8 |
| cleaning | CLEAN-2 | code | 2/2 | 2/2 | 1 | 2323 | 9.1 |
| analysis | ANA-1 | answer | 2/2 | 2/2 | 1 | 851 | 4.8 |
| analysis | ANA-2 | answer | 0/2 | 0/2 | 1 | 1271.5 | 8.4 |
| research | RES-1 | answer | 2/2 | 2/2 | 1 | 630 | 4.9 |
| research | RES-2 | answer | 2/2 | 2/2 | 1 | 450.5 | 3.1 |
| dag | A | code | 2/2 | 2/2 | 1 | 361.5 | 2.4 |
| dag | B | code | 2/2 | 2/2 | 1 | 489.5 | 3.7 |
| dag | C | code | 2/2 | 2/2 | 1 | 482.5 | 2.9 |
| dag | D | code | 2/2 | 2/2 | 1 | 422.5 | 2.1 |
| dag | X-IMPOSSIBLE | expected-failure | 2/2 | 0/2 | 2 | - | - |
| dag | Y-AFTER-X | expected-blocked | 2/2 | 2/2 | 0 | - | - |
| video | VID-1 | code | 2/2 | 2/2 | 1 | 1099 | 4.9 |
| video | VID-2 | code | 2/2 | 2/2 | 1 | 1171 | 4.6 |
| bigfile | BIG-1 | code | 2/2 | 2/2 | 1 | 2903.5 | 3.2 |
| bigfile | BIG-2 | code | 2/2 | 2/2 | 1 | 3068 | 4.2 |
| multifile | MULTI-1 | code | 2/2 | 2/2 | 1 | 687 | 2.6 |
| multifile | MULTI-2 | code | 2/2 | 2/2 | 1 | 634.5 | 6.0 |
| secrets | SEC-1 | secret-must-not-land | 2/2 | 2/2 | 1 | 430.5 | 2.5 |
| secrets | SEC-2 | code | 2/2 | 2/2 | 1 | 556 | 1.8 |

| Alan | Geçen / toplam |
|---|---|
| bugfix | 6/6 (100%) |
| cleaning | 4/4 (100%) |
| analysis | 2/4 (50%) |
| research | 4/4 (100%) |
| dag | 12/12 (100%) |
| video | 4/4 (100%) |
| bigfile | 4/4 (100%) |
| multifile | 4/4 (100%) |
| secrets | 4/4 (100%) |
| **Toplam** | **44/46 (96%)** |

Toplam token (model çağrıları, kaydedilen): 45534; çağrı sayısı ≥ 42

## Bulgular ve kök neden sınıflandırması

| # | Bulgu | Sınıf | Durum |
|---|---|---|---|
| 1 | ANA-2 (belirsiz istem): son koşuda 0/2, ek 3 tekrarda 1/3 geçti; başarısız cevaplar yalnız `db: 3` yazdı. Aynı veriyle açık istem (ANA-3: her servisi satır satır listele, sonra en kötüsünü söyle) 3/3 geçti (`live-matrix-analysis.json`). | **Model, istem biçimine duyarlı**: açık istemle sorun yok, kısa/belirsiz istemde çıktı eksik kalıyor | Kullanım kuralı: analiz isteminde çıktı biçimini ve kapsamı açıkça yaz |
| 2 | İlk koşuda BIG-2 ve MULTI-2 başarısız göründü: aynı dosyaya yazan iki bağımsız görev aynı oturumda koştu, ikinci apply "kaynak değişti" diye reddedildi. | **Sistem/kullanılabilirlik** (güvenli ama modelin işi boşa gitti) | **Düzeltildi:** `plan.submit` artık aralarında bağımlılık yolu olmayan iki görevin aynı çıktıyı yazmasını baştan reddediyor, net mesajla (`test_plan_overlap.py`). Matris bu iki alanı görev başına oturumla koşuyor; 8/8 geçti. |
| 3 | `.git/index.lock` artık kilidi commit'i engelledi. | Ortam | Süreç yok, 0 bayt, 3 dk eski → kaldırıldı |

## Önceki “kanıtlanmadı” maddelerinin durumu

- **Edit formatı canlıda çalışıyor.** 300 satırlık dosyada istem ≈2,6k token. Çıktı (completion) token'ları `edit-format-tokens.json` içinde: BIG-1 6 koşuda 296–331; BIG-2 4 koşuda 86–89, birinde 975, birinde 2229 (model dosyayı baştan yazmış; yine de doğru). Tam dosya yazımı ≈2,2k+ olurdu; tipik koşuda çıktı ~%85–96 küçülüyor, ama sapma var.
- **Sır taraması canlıda çalışıyor.** SEC-1 (modelden sahte anahtar literal'i istendi): 4/4 `apply` aşamasında reddedildi; dosyaya sızmadı. SEC-2 (64 karakter sha256 hex ve uzun kebab-case rota adı): 4/4 yanlış alarm yok, uygulandı.
- **Hata yayılımı doğru.** X-IMPOSSIBLE 2 denemede `FAILED`, bağımlısı Y-AFTER-X `SKIPPED`, hiçbir dosya yazılmadı (4/4). Elmas DAG (A→B,C→D, ata çıktılarının miras alınması) 8/8.
- **Araştırma dürüstlüğü:** var olmayan `itertools.chunked` sorusunda model 4/4 stdlib'de olmadığını söyledi (uydurmadı).

## Alan alan kullanım önerisi

| İş | Güvenle verilebilir mi | Not |
|---|---|---|
| Bug fix (küçük/orta, test yazılı) | Evet | 6/6, hepsi ilk denemede |
| Veri temizleme (betik yazdırma) | Evet | Veriyi değil temizleme betiğini yazıyor; 4/4 |
| Analiz (kısa veri bağlamda) | Dikkatli | 1 görev 2/2, diğeri 0/2 (eksik cevap). Sonuç sayıları ayrıca doğrula |
| Araştırma/bilgi | Sınırlı | Yalnız model bilgisi, web yok; uydurma tuzağı 4/4 geçti |
| Plan/DAG yürütme | Evet | Miras ve hata yayılımı doğru; aynı dosyaya yazan paralel görev artık baştan reddedilir |
| Video | Betik olarak evet | Gemini ffmpeg betiğini yazıyor, video yerelde üretiliyor; 4/4 biçim ve ilk/son kare parlaklığı doğrulandı. Görsel kaliteyi insan gözüyle bakmadım |
| Büyük dosya düzenleme | Evet | Edit formatı token'ı tipik koşuda ~%85–96 düşürüyor, sapma var |
| Çok dosyalı değişiklik | Evet | Çıktı listesinde olmayan dosyaya dokunamaz; listeyi doğru ver |
| Gizli bilgi sızıntısı | Korumalı | Apply aşaması reddediyor |

## Sınırlar (dürüstçe)

- Görevler küçük/orta; çok dosyalı büyük depo işi, uzun bağımlılık zinciri ve 15'ten fazla paralel görev matriste yok.
- Her görev 2 tekrar; oranlar küçük örnek (örn. %100, alt sınırı düşük). Bir modelin nadir hatasını yakalamaz.
- Analiz kalitesi istem biçimine duyarlı; yalnız iki veri setinde ölçüldü.
- MCP istemcisinden (Antigravity) gerçek yeniden bağlanma hâlâ denenmedi.

## Kota harcaması

Üç canlı koşu: ilk koşu 46 satır / 51,9k token, yeniden koşu (BIG/MULTI izole) 8 satır / 15,9k, son koşu 46 satır / 45,5k; ek analiz koşusu 9 satır / 8098 token; toplam ≈ **121440 token, ≥ 102 üretim çağrısı** (başarısız deneme tokenleri kayıtlı olmayanlar hariç). Gemini yalnız bu MCP'nin testi için kullanıldı.

## Dosyalar

`matrix/matrix.py` (görevler + doğrulayıcılar), `matrix/run_matrix.py` (canlı koşucu), `matrix/test_matrix.py` (testin testi), `matrix/live-matrix-run1.json`, `live-matrix-rerun.json`, `live-matrix-final.json` (ham veri).
