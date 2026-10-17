# Gemini MCP: düzeltme ve canlı doğrulama

16 Ekim 2026 | Kanıt saati: 16.10.2026 22:25:36 UTC+3 | Kanonik kod: tools/orchestrator_mcp

**Sonuç:** Mevcut MCP kullanılabilir bir görev yürütücüsüne çevrildi ve kuruldu. Kota 15/15 hesapta okunuyor. Kurulu girişten 15 ayrı hesapla 15 kod görevi ve bağımlı entegrasyon görevi tamamlandı; 16 gerçek kabul komutunun tamamı 0 döndü. Bu küçük görevler için olumlu kanıttır; büyük projede kusursuzluk garantisi değildir.

## Kota neden okunamıyordu?

İlk ölçümde 15 hesabın diskteki erişim tokenı yaklaşık 5 saat önce dolmuştu. Doğrudan kota isteği 15/15 hesapta HTTP 401 UNAUTHENTICATED döndü. Eski okuyucu OAuth yenilemesi yapmıyor, hatayı gizleyip bilinmeyen sonuç üretiyordu. Refresh tokenların bulunması tek başına yenilemenin gerçekleştiği anlamına gelmiyordu.

Yeni yol, yerel CPA yönetim API'sinde auth_index ve api-call üzerinden Bearer $TOKEN$ kullanıyor. Token yenilemesini CPA yapıyor. Kısa dönem ve haftalık Gemini kovalarının en düşük kalan oranı seçiliyor. Hata ve ölçüm zamanı saklanıyor; bilinmeyen kota dolu sayılmıyor. Anahtar veya OAuth tokenı bu rapora, MCP çıktısına ya da yeni kaynaklara yazılmadı.

## Orkestrasyonda giderilen sorunlar

- Görev sahipliği SQLite atomik claim ve süreli kira ile tutuluyor. Ayrı süreçler aynı hesabı aynı anda alamıyor; işlem çökünce işletim sistemi kilidi serbest kalıyor.
- Kod başarısı çağıranın exit_code beyanından çıkarılmıyor. Önceden belirlenen kabul komutu sunucuda çalışıyor; gerçek log, çıkış kodu ve dosya hashleri kaydediliyor.
- Bağımlılık, yinelenen görev/sonuç, toplam deneme sınırı, iptal ve sıfırlama doğrulanıyor. Başarısız bağımlılığın alt görevleri atlanıyor.
- İşçiler yalnız açık dosya kapsamını görüyor; çıktılar ayrı çalışma alanında kalıyor. Uygulama, kaynak hash kontrolü ve yedekle yapılıyor; kullanıcı değişikliği korunuyor.
- Başarısız testin logu sonraki sınırlı denemeye aktarılıyor. 429/auth hataları hesap bekleme süresi oluşturuyor. Uygun hesap kalmazsa WAITING_CAPACITY ile iş ve deneme bütçesi korunuyor.
- İstemci kapanınca ayrık çalıştırıcı sürüyor; ikinci başlatma yeni süreç açmıyor. Çöken çalıştırıcının görevi yeni açık başlatmada geri alınabiliyor.

## Ölçüm özeti

| Kontrol | Gerçek sonuç | Kapsam |
|---|---|---|
| Otomatik regresyon | 33/33; komut çıkışı 0 | Yarış, kira, çökme, kota hatası, test reddi, retry, dosya çakışması, MCP stdio |
| İlk canlı tur | 16/16; 25.25 saniye | Yeni kaynak kodu, 15 farklı hesap ve entegrasyon |
| Kurulu MCP canlı tur | 16/16; 21.45 saniye | 15 farklı hesap, her görev ilk denemede, bütün kabul komutları 0 |
| Kurulu MCP sağlık | 14 araç; 15/15 kota | Mevcut MCP JSON ayarı, üretim kota önbelleği |
| Sır taraması | 0 bulgu; komut çıkışı 0 | Yeni kaynaklar ve çalışma kanıtları; dış doğrulama kapalı |

<!-- PAGEBREAK -->

# Hesaplar, kurulum ve kullanım

**Kota ölçümü:** 16.10.2026 22:25:36 UTC+3. Oranlar gözlem anına aittir; kısa dönem/haftalık en düşük değer gösterilir. Yeniden okumak için orchestrator_refresh_quotas çağrılır. Kota okuma model üretimi yapmaz; eksik yerel CPA süreçlerini açabilir.

| Hesap | Kalan kota | Durum |
|---|---|---|
| h01 | %89.73 | Okundu; CPA çevrimiçi |
| h02 | %92.49 | Okundu; CPA çevrimiçi |
| h03 | %99.03 | Okundu; CPA çevrimiçi |
| h04 | %99.97 | Okundu; CPA çevrimiçi |
| h05 | %95.07 | Okundu; CPA çevrimiçi |
| h06 | %99.97 | Okundu; CPA çevrimiçi |
| h07 | %99.98 | Okundu; CPA çevrimiçi |
| h08 | %99.97 | Okundu; CPA çevrimiçi |
| h09 | %99.98 | Okundu; CPA çevrimiçi |
| h10 | %99.97 | Okundu; CPA çevrimiçi |
| h11 | %99.97 | Okundu; CPA çevrimiçi |
| h12 | %99.97 | Okundu; CPA çevrimiçi |
| h13 | %99.98 | Okundu; CPA çevrimiçi |
| h14 | %99.97 | Okundu; CPA çevrimiçi |
| h15 | %99.97 | Okundu; CPA çevrimiçi |

## Kurulum ve kullanım

Mevcut Antigravity orchestrator/server.py girişi kanonik repo/tools/orchestrator_mcp koduna yönlendirildi. MCP JSON'unda yalnız bu sunucuya ORCHESTRATOR_GEMINI_ENABLED=1 verildi. Eski global kapatma işareti korunuyor; filo/AFK yolları açılmadı. Mevcut iki oturum SQLite geçişinde korundu. Kaynak, ayar ve veritabanı yedeği mevcut sunucunun backups/20261016-222433-313222 klasöründe.

Normal akış: refresh_quotas -> init(custom_dag) -> add_task -> configure_task -> run_session -> get_status -> incelenen çıktı için apply_task. Aynı dosyaya yazan işleri bağımlılık zincirine koy. Antigravity'de araç listesi eskiyse MCP bağlantısını yenile; keşifte 14 araç görünmeli. Ayrıntılar kanonik klasörün README.md dosyasında.

Kurulu tur oturumu: ses_9ffe415949e94368. Model: gemini-3.8-flash-high; sağlayıcı/model fallback yok. Bu turda 16 model çağrısı, API'nin bildirdiği toplam 17455 token kullanıldı; iki tur toplam 32 model çağrısı yaptı. Client yeniden bağlanması, yinelenen başlatmayı engelleme ve sentetik dosyaya uygulama da geçti.

## Pratik sınırlar

Kabul komutu ve üretilen kod kullanıcı yetkisiyle çalışır; ayrı dosya çalışma alanı bir OS güvenlik sandbox'ı değildir. İşçi açık kapsam içinde dosya önerir; sınırsız araç kullanan depo ajanı değildir. İptalde sürmekte olan HTTP isteğinin boşalması 120 saniye sürebilir. Büyük depo, saatlerce yük, makine yeniden başlatma ve uzun süre sonra OAuth süresinin tekrar dolması bu turda uçtan uca sınanmadı. Token yenileme yolu hem süresi dolmuş mevcut hesaplarda hem canlı kotada doğrulandı.

## Kanıtlar ve kaynak

Yerel kanıtlar: regression-output.txt; quota-diagnosis-before.json; installed-health.json; live-01/results.json; live-installed/results.json. Görev bazlı kabul logu, model kullanım bilgisi ve hash kanıtları ilgili results.json içindeki evidence_path yollarındadır. Önceki audit klasörü düzeltme öncesi tarihsel karşılaştırmadır.

CPA yöntemi: [resmi yönetim API'si](https://github.com/router-for-me/CLIProxyAPIDocs/blob/main/docs/en/management/api.md), kurulu sürüm kaynak kodu [api_tools.go / 61fdfc34](https://github.com/router-for-me/CLIProxyAPI/blob/61fdfc34/internal/api/handlers/management/api_tools.go).
