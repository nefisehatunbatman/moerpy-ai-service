# AI servis işletimi

## Yerel demo ve container

`python scripts/configure_demo.py` yalnız AI servisinin `.env` ve yeni v2 SQLite dosyasını yapılandırır. Eski `ai_service.db` yerinde kalır. Büyük dataset DB'si `data/business_24m.db` altında salt okunur kullanılır. Kaynak business CSV'leri ve MOERPY DB'si değiştirilmez.

Üretim için `docker compose -p moerpy-ai -f compose.yaml config --quiet`, ardından `docker compose -p moerpy-ai -f compose.yaml up --build -d` kullanılır. Bu tanım `ERP_DATABASE_URL` ile gerçek PostgreSQL okuma kaynağı ister. Sentetik veri için ayrı `compose.demo.yaml` kullanılır. Host portu `127.0.0.1:8001`, container portu 8000'dir. Container non-root çalışır; root filesystem salt okunur, AI karar DB'si ayrı `ai_state` volume'dur. Demo verisi readonly mount, demo state'i `demo_ai_state` volume'dur. `AI_SERVICE_INTERNAL_TOKEN` en az 32 karakter olmalıdır. Production ayarı fake ERP'yi reddeder. Offline model moduna izin verilmesi, model kalitesinin veya canlı sağlayıcının doğrulandığı anlamına gelmez; kart generator alanı bu modu belirtir.

Yerel Linux container build, üretim imajıyla HTTP smoke ve ayrı PostgreSQL 16 üzerinde adapter/lifecycle testleri doğrulanmıştır; uzak production dağıtımı yapılmamıştır. İlk deployment'ta CPU/RAM/volume, TLS, ağ erişimi ve gerçek provider hesabı ayrıca doğrulanır. Tek worker varsayılandır. Eşzamanlılık sınırı worker başınadır; birden fazla replica için gateway kotası gerekir.

## DB upgrade, backup, rollback

1. AI API'yi durdurun; hedef `AI_SERVICE_DATABASE_URL` değerinin yalnız AI DB'si olduğundan emin olun.
2. SQLite için `python -m app.db.migrate` otomatik backup alır ve eklemeli v2 kolonlarını ekler. Postgres AI DB için önce platform snapshot/backup alın; aynı migration sonra çalıştırılır. `ERP_DATABASE_URL` bu migration'da kullanılmaz.
3. Legacy tenant'sız karar/anomali/politika kayıtları `legacy-unscoped` olarak kalır; yetkili API'ye açılmaz. Anomaliler yeniden analiz edilmelidir. Generic KB şablonları global kalır; eski embedding'ler açık reindex gerektirir.
4. `/ready`, imzalı KPI/analysis ve negatif scope testi yapılmadan trafiği açmayın.
5. Rollback gerekiyorsa API'yi durdurup önceki uygulama sürümü ile onun backup'ını birlikte geri alın. Yeni şema DB'sini eski binary ile otomatik downgrade etmeyin.

Yeni v2 kurulumu eski DB'yi dönüştürmeye gerek duymaz; `data/service_v2.db` oluşturur. DB backup restore ve storage failure için üretim ortamındaki RPO/RTO ayrıca belirlenir.

Mevcut v2 veritabanında global şablona kaydedilmiş şirket öğrenmeleri varsa aynı migration v3 veri düzeltmesini uygular. Receipt ve kararın tenant/company bilgisi kullanılarak özel KB kaydı oluşturulur; global özel aktivite alanları temizlenir. Sahibi belirlenemeyen receipt varsa işlem durur; kapsam uydurulmaz. Migration tekrar çalıştırıldığında onay sayısı tekrar artmaz. Bu bakım, eski kararların evidence/RAG snapshot'larını yeniden yazmaz.

## RAG ve provider geçişi

Model anahtarlarını source control'e koymayın. Live LLM açıkça `LLM_MODE=live`; live embedding `EMBEDDING_MODE=live` ile seçilir. Sağlayıcı kimlikleri ve model isimleri yapılandırmadan gelir. `scripts/reindex.py`, seçili embedding sağlayıcısıyla tüm KB vektörlerini önce hazırlar, ardından tek transaction'da değiştirir. API worker'ları bu işlem boyunca kapalı tutulur; başarıdan sonra yeni provider ayarıyla yeniden başlatılır. Aynı boyutta farklı modeller de uyumsuz kabul edilir.

Startup KB seed'ini hazırlar, model/indeks uyumunu kontrol eder. İstek sırasında tutarsız boyutlar 0 benzerlik gibi yorumlanmaz. Sağlayıcı çağrıları sınırlı tekrar ve zaman bütçesiyle yapılır; 429, geçici sunucu hataları ve ağ timeout'ları kontrollü hataya dönüşür. Uydurma nicel anlatım doğrulamadan geçmez; otomatik tahmini sayı üreten fallback yoktur.

## İzleme ve öğrenme kurtarma

`/health` süreç liveness; `/ready` AI DB, auth yapılandırması ve ERP şirket erişimini kontrol eder. `/api/v1/metrics` imzalı yönetici erişimiyle süreç içi istek/hata/meşgul/gecikme sayaçlarını verir. Restart sayaçları sıfırlar; merkezi Prometheus/OTel exporteri veya dashboard bağlı olduğu iddia edilmez. JSON loglarda request ID, güvenli bağlam alanları ve model token kullanım bilgisi bulunur. Provider fiyatlandırması sabit kodlanmaz; token kullanımından parasal maliyet hesabı deployment ekibinin güncel fiyat kaynağına bağlanmalıdır.

Onay kalıcı olduktan sonra embedding başarısızsa `learning_status=failed` olur. Finance yetkisiyle retry endpoint'i çağrılır. Processing lease beş dakika sonra tekrar alınabilir; worker kesintisinden sonra aynı onay için receipt, ikinci KB artışını önler. Bu endpoint ayrıca scheduler/queue worker'a bağlanabilir; uzak scheduler bu teslimde kurulmamıştır.

## Kalite kapıları ve sınırlar

`python scripts/check.py --full`, fixture/security/concurrency/provider hata testlerini ve büyük verinin 24 aylık doğrulamasını çalıştırır. Test raporları `data/` altındadır. CI şablonu `ci/github-actions.yml` içindedir; repository kök workflow'una yerleştirilmesi başka ekibin entegrasyon görevidir.

Canlı Postgres şema uyumu, read-only DB rolünün gerçekten provision edilmesi ve gerçek LLM/embedding hesaplarının kabul testi bu yerel ortam testlerinden çıkarılamaz. Postgres adapter'ı read-only transaction ve statement timeout ister; gerçek role yalnız gerekli canonical/fact SELECT izinlerini DBA vermelidir. Şirket verisi dış modele gönderilecekse hangi alanların gönderildiği (kompakt kanıt ve uygun KB örnekleri) ürün sahibiyle netleştirilmelidir. Private oracle modele gönderilmez.
