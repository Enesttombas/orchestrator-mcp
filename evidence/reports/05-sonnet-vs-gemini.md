# Sonnet 5.5 tek başına vs Gemini orkestrasyon MCP — karşılaştırma raporu

Tarih: 2026-10-17. Soru: aynı işi (a) yalnız Sonnet 5.5 yapınca ve (b) Sonnet 5.5 orkestratör, Gemini 3.8 flash-high işçiler yapınca hız, Claude kotası (token) ve çıktı kalitesi nasıl değişiyor?

## Düzenek

Her test iki kolda koştu; kol A = Sonnet 5.5 alt ajanı tek başına, kol B = Sonnet 5.5 alt ajanı yalnızca orkestratörü (`orch_cli.py`, MCP ile aynı kütüphane) kullanır, işi Gemini işçiler yapar.

| Test | İş | Puanlama |
|---|---|---|
| 1. Video | 5 YouTube videosunun transkriptinden özet (PDF'e çevrildi) | Kör Opus hakem, rastgele X/Y etiketi; kapsam /40, kaynaksız iddia, anlaşılırlık /5 |
| 2. Bug | 6 modül: 3 orta (slugify, csvparse, bizdays), 3 zor (eventbus, toposort, wrap); görünür + gizli testler | Orijinal görünür test + mühürlü gizli test; test dosyası kurcalama kontrolü |
| 3. Bağlam | 14 dosya sorusu (koddan) + 5 web sorusu (internetten) | Regex anahtar; web'de alıntı, belirtilen URL'de gerçekten var mı diye çekilip doğrulandı |

Genişletmeler (istenenin ötesinde): bağlam toplama testi için mühürlü soru anahtarı; no-op Sonnet alt ajanının sabit maliyeti ölçüldü (taban 74.498 token) ve net sütun eklendi; hakem kör ve haritası mühürlü.

## Sonuçlar

### Hız (saniye)

| Test | Sonnet tek (A) | Gemini MCP (B) | B/A |
|---|---|---|---|
| Video | 115,7 | 86,1 | 0,74 |
| Bug | 214,8 | 135,3 | 0,63 |
| Bağlam | 47,4 | 76,9 | 1,62 |
| Toplam | 377,9 | 298,3 | 0,79 |

### Claude kotası: Sonnet 5.5 `subagent_tokens`

| Test | A | B | B/A |
|---|---|---|---|
| Video | 117.585 | 89.189 | 0,76 |
| Bug | 97.793 | 86.005 | 0,88 |
| Bağlam | 96.777 | 92.449 | 0,96 |
| Toplam ham | 312.155 | 267.643 | 0,86 |
| Taban çıkarılmış net (3 × 74.498) | 88.661 | 44.149 | 0,50 |

Taban: hiçbir iş yapmayan Sonnet alt ajanı bile 74.498 token yakıyor (sistem istemi, araç şemaları). Ham toplam bu yüzden yanıltıcı biçimde yakın; işe özgü maliyet yaklaşık yarıya iniyor.

### Gemini tarafı (B kolu, ek maliyet; Claude kotasından değil)

| Test | Gemini token |
|---|---|
| Video | ≈ 41.069 |
| Bug | ≈ 13.874 |
| Bağlam | ≈ 51.198 |
| Toplam | ≈ 106.141 |

### Kalite

| Test | A (Sonnet tek) | B (Gemini MCP) |
|---|---|---|
| Bug, orta | 3/3 | 3/3 |
| Bug, zor | 3/3 | 3/3 |
| Bağlam, dosya | 14/14 | 14/14 |
| Bağlam, web (anahtar / alıntı doğrulandı) | 5/5 / 5/5 | 5/5 / 5/5 |
| Video kapsam (/40, 5 video toplamı) | 39 | 39 |
| Video kaynaksız iddia | 0 | 2 |
| Video anlaşılırlık (/5 ort.) | 5,0 | 3,8 |

Yorum: kodda ve bilgi toplamada fark yok. Videoda kapsam eşit ama Gemini özetleri daha az okunaklı ve 2 kaynaksız iddia içeriyor. Anlatım kalitesi gereken işte Sonnet önde.

## Dürüst notlar ve sınırlar

- Her test tek koşu (n=1); kazanç/kayıp sıralaması istatistiksel kanıt değil, işaret.
- Gemini token sayıları yalnız son deneme; yeniden denenen görevlerde eksik sayılmış olabilir.
- B kolu, MCP stdio yolunu değil aynı kütüphaneyi `orch_cli.py` ile kullandı; stdio yolu DX-001'de ayrıca kanıtlandı.
- Orkestratörün kendi yükü `subagent_tokens` içinde; taban 74.498 çıkarılırken orkestratör sabit yükü de yarı yarıya taban sayılmış olabilir.
- Hakem Opus; X konumu yanlılığı olabilir. Haritada V5'te A/B yer değiştirdi, hakem aynı sonuç ailesini verdi, yine de tam çözülmüş sayılmaz.
- Bağlam web puanı regex anahtar + alıntının sayfada varlığıdır; anlam doğrulaması değil.
- A kolu web için WebFetch kullandı (model özeti döner, ham metin değil).
- Bug işi modül başına bölünebilir olduğu için orkestrasyona uygun; bölünemeyen işte kazanç beklenmemeli.
- Bağlam testinde orkestrasyon hem yavaş (1,6×) hem Claude tokenında neredeyse eşit: küçük, tek sorgulu işte orkestrasyon değmiyor.

## Sonuç

| Boyut | Kazanan | Kanıt |
|---|---|---|
| Claude kotası (net) | Gemini MCP, yaklaşık yarı | 44.149 vs 88.661 |
| Hız | Gemini MCP (video, bug); Sonnet (bağlam) | toplam 298 sn vs 378 sn |
| Kod doğruluğu | Berabere | 6/6 ve 6/6 |
| Bilgi toplama | Berabere | 19/19 ve 19/19 |
| Yazı kalitesi | Sonnet | anlaşılırlık 5,0 vs 3,8, 0 vs 2 kaynaksız iddia |

Öneri: kod/test ve çok parçalı toplu işi Gemini MCP'ye ver, nihai özet/anlatım metnini Sonnet'e bırak. Küçük tek-sorgu işlerde doğrudan Sonnet.

## Dosyalar

`Video-Ozetleri-Sonnet-5.5.pdf`, `Video-Ozetleri-Gemini-Orkestrasyon.pdf` (+ .md); `run/{A,B}_{video,bugs,ctx}`; `score_bugs.py`, `score_ctx.py`, `ctx_questions.py`, `orch_cli.py`, `build_bugs.py`; `judge_map.json`.
