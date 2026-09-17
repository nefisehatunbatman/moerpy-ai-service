# MOERPY AI Service

**Bu repo, MOERPY monorepo'sundaki `ai-service/` bileşeninin bağımsız bir aynasıdır** — sadece bu servisin kaynak kodunu içerir, MOERPY frontend/Edge Function/Supabase migration'ları burada yer almaz (onlar ayrı, ana MOERPY reposunda geliştiriliyor). Komutlar ve dosya yolları bu README'de repo **kökünden** verilmiştir.

Güncel değişiklikler: [15 Eylül inceleme düzeltmeleri ve test sonuçları](docs/REVIEW_FIXES.md). Analiz ve karar üretimi finansal rol gerektirir; raporlama saat dilimi `REPORTING_TIMEZONE` ile belirlenir (varsayılan `Europe/Istanbul`).

**AI Decision Layer for Business — bağımsız finansal karar servisi**

Servis, doğrulanmış işletme verisinden deterministik KPI ve anomali üretir; sayısal kanıtları kodla oluşturur, LLM'yi yalnız nitel yönetici önerileri için kullanır. Karar taslakları insan onayına sunulur. Confidence, doğruluk olasılığı değil, açıklanabilir kanıt yeterlilik skorudur.

MOERPY'nin mevcut frontend/Edge Function entegrasyonu ayrı repoda geliştiriliyor, ancak **v2'nin zorunlu imzalı kapsam sözleşmesine henüz uyarlanmış değil**. Eski proxy'nin yalnız internal token taşıyan çağrıları reddedilir. Entegrasyon sorumlusu [API sözleşmesini](docs/API_CONTRACT.md) uygulamalıdır.

## Büyük veriyle yerel kullanım

Python 3.11 gerekir. Komutlar repo kökünden çalıştırılır:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B scripts/configure_demo.py
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001
```

Yeni ortamda önce `python -m venv .venv` çalıştırılır. `configure_demo.py`, yalnız AI servisinin `.env` dosyasında büyük veri sağlayıcısını ve yeni `data/service_v2.db` yolunu seçer; yeterli uzunlukta internal secret oluşturur, mevcut model anahtarlarını korur ve ekrana yazmaz. Sunum için `LLM_MODE=offline`, `EMBEDDING_MODE=local` seçer. Bu modlarda dış model çağrısı yapılmaz; kartın `generator` alanı bunu açıkça gösterir.

Veri indeksi henüz yoksa, **ana business paketinin açılmış dizini** verilerek bir kez oluşturulur:

```powershell
.\.venv\Scripts\python.exe -B -m app.data.business --source '<moerpy_demo_business_24m_v1 dizini>' --target data/business_24m.db
```

Mevcut DB'nin üzerine yazılmaz. İndeks değiştirilirken yeni sürümlü bir hedef oluşturulur, doğrulanır ve sağlayıcı yolu kontrollü değiştirilir.

Ana paket `2024-09-01`–`2026-08-31` dönemine ait **57 tablo / 1.577.755 satırdır**. Mevcut finansal metriklerin kullandığı **8 tablonun 1.050.029 satırı** indekslenir: şirket, lokasyon, ürün, satış faturası, fatura satırı, maliyet geçmişi, günlük stok snapshot'ı ve stok hareketi. Diğer tabloların kullanıldığı iddia edilmez. CSV parçaları manifest SHA-256 ve satır sayısıyla doğrulanır; tenant/company ve ana satış referansları kontrol edilir. Private oracle/scenario etiketleri feature, RAG veya LLM girdisine alınmaz. Kaynak dosyalar değiştirilmez.

Bu corpus sentetiktir ve senaryo yoğunluğu yüksektir; sektör prevalansı veya model doğruluğu benchmark'ı değildir. AR/AP, CAPEX, üretim/OEE ve tüm özel senaryolar için yeni karar motorları bu düzeltmenin kapsamına dahil değildir.

## İstek örnekleri

`/health` liveness, `/ready` bağımlılık ve auth yapılandırması kontrolüdür. Swagger `/docs`, geliştirme ortamında mevcuttur. API çağrıları geliştirmede de imzalıdır.

```powershell
.\.venv\Scripts\python.exe scripts/request.py GET '/api/v1/companies/22222222-2222-4222-8222-222222222222/kpis?period_start=2026-08-01&period_end=2026-08-31'
.\.venv\Scripts\python.exe scripts/request.py POST /api/v1/analysis/run --body '{"company_id":"22222222-2222-4222-8222-222222222222","period_start":"2026-08-01","period_end":"2026-08-31"}'
.\.venv\Scripts\python.exe scripts/request.py GET '/api/v1/companies/22222222-2222-4222-8222-222222222222/anomalies'
```

Bir anomali için `POST /api/v1/anomalies/{id}/generate-decision` kullanılır; İngilizce çıktı için `?language=en` eklenir. Varsayılan Türkçedir. Aynı anomali sürümü ve dil aynı karar ID'sini verir. Eski/superseded anomaliyle yeni karar üretimi 409 döner.

## Doğruluk sözleşmesi

- Fatura satırında doğrulanmış COGS varsa aynen kullanılır. Açık satır maliyeti varsa satır bazında hesaplanır; mağaza/üründeki başka satışın maliyeti satırı ezmez.
- Satır maliyeti yoksa işlem tarihinde geçerli gözlenen Cost Upload kullanılır. Onaylı bütçe, eksik gerçekleşen maliyetin yerine geçmez; bütçe ve gerçekleşen maliyet ayrı çözülür. Aynı öncelikte çelişkili maliyet reddedilir. Stock Upload yalnız uygun tarihli, güncel ve çelişkisiz fallback'tir; gelecekteki snapshot eski satırı fiyatlandıramaz.
- Büyük corpusun `cogs_try`, `inventory_value_try`, `total_unit_cost_try` alanları TRY'ye dönüştürülmüş değerlerdir. Kaynak `currency` alanını okuyup yeniden FX çarpımı yapılmaz. Postgres'ten karışık/dönüştürülmemiş maliyet para birimleri reddedilir.
- Gözlenen tedarikçi maliyeti, onaylı bütçe değildir. Gerçek Postgres ve büyük business sağlayıcısında onaylı bütçe baseline'ı bulunmadığı için `unit_cost_variance_*` uydurulmaz; bu metriğin fixture testindeki bulunması gerçek veri desteği anlamına gelmez.
- Eksik maliyet, veri yokluğu ve sıfır/negatif payda sağlıklı `0` veya `%100` gibi gösterilmez: `value=null`, `status=insufficient_data`, `issues` ve kapsam bilgisi taşınır. Anomali motoru yalnız `status=ok` metrikleri değerlendirir.
- DIO, dönem sonu stok değerinden hesaplanan bir proxydir; ortalama günlük stokla hesaplanmış standart DIO veya gerçek nakde dönüşüm tahmini olarak sunulmaz.
- API gelecekteki dönem bitişini reddeder; açık ay için gerçek raporlama kesim tarihi gönderilir. Business sağlayıcısı doğrulanmış veri kümesi tarih aralığının dışına taşan dönemleri reddeder. Satış satırlarının bulunması günlük yükleme kapsamının tam olduğunu kanıtlamaz; Postgres kaynağının raporlama kapsamı upstream veri sözleşmesinin sorumluluğudur.
- Gelirin veri kalitesi maliyete, stok değerinin veri kalitesi satışa bağlanmaz. DIO, stok/gelir ve fire/gelir kaynak izleri payda ve çözülen maliyet kayıtlarını da içerir. Yinelenen kaynak ID'leri sessizce toplanmaz.
- `observed_impact` gözlenen risk tutarı veya açıkça etiketli senaryodur. `expected_impact` nitel tutulur. Stok tutarının tamamı beklenen tasarruf olarak gösterilmez.
- LLM'nin serbest anlatımındaki nicel iddialar reddedilir. Sayılar uygulamanın ürettiği `signals`, `summary`, `problem_signal` ve `observed_impact` alanlarında yer alır. Bu politika, modelin bütün nitel önerilerinin doğru olduğunu kanıtlamaz; öneriler insan incelemesine tabidir.
- Dönem, entity, tenant/company, run ID, kaynak sayısı/ID örnekleri/hash'i, import batch, model/prompt sürümü ve confidence faktörleri kaydedilir. Anomali üretiminden sonra verinin değişmesi eski kararın kanıtını değiştirmez.

## Onay ve RAG

Onay/red, koşullu DB update ve lifecycle olayıyla tek transaction'da kaydedilir. Onay sonrası öğrenmenin sonucu kartta `pending`, `processing`, `failed` veya `completed` olarak taşınır. Embedding hatası onayı geri almış gibi gösterilmez. `POST /decisions/{id}/retry-learning` yalnız finans yetkisiyle çağrılır. Süresi dolmuş processing lease tekrar alınabilir; receipt kaydı aynı onayın bilgi tabanı sayacını tekrar artırmasını önler.

RAG yalnız onaylı, ilgili problem tipindeki, aynı tenant/şirketin veya global şablonların kayıtlarını kullanır. Minimum benzerlik altında sonuç vermez. Şablonlar ölçülmüş geçmiş başarılar olarak değerlendirilmez. İndeks vektörlerinde embedding model kimliği ve boyutu tutulur. Sağlayıcı/model değişiminde uyumsuz indeksi sessizce kullanmak yerine açık hata verilir.

Şirket onayları global şablonu değiştirmez. İlk onay şirkete özel öğrenme kaydı oluşturur; sonraki benzer onaylar yalnız bu özel kaydı günceller. Önceki sürümde global şablonlara yazılan öğrenme kayıtları için `python -m app.db.migrate` v3 geçişi receipt'leri şirket kapsamına taşır. Global kayıtta eski özel aktivite bulunursa startup açık migration hatası verir.

Gerçek sağlayıcıyı seçmek için `LLM_MODE=live` ve `LLM_API_KEY`; gerçek embedding için `EMBEDDING_MODE=live` ve `EMBEDDING_API_KEY` gereklidir. Model/base URL ayrıca ayarlanır. **Anahtar bulunması tek başına live modu açmaz.** Embedding değişiminde API'yi durdurup `python scripts/reindex.py` çalıştırın, başarıdan sonra yeniden başlatın. Reindex bütün vektörler hazırlanmışsa tek transaction'da yayınlanır. Gerçek sağlayıcı doğrulaması bu yerel düzeltme sırasında harici çağrıyla yapılmadı; timeout/429/bozuk cevap davranışları mock transport testleriyle doğrulanır.

## Test ve işletim

```powershell
.\.venv\Scripts\python.exe -B scripts/check.py --full
```

Bu komut pytest sonuçlarını `data/test-results.txt` ve `data/test-results.xml` dosyalarına yazar. `--full`, indeksin varlığını zorunlu kılar ve 24 ayın tamamında fatura gelirleriyle reconciliation ve karar üretimi yapar; `data/business_validation.json` üretir. Unit testler kendi SQLite veritabanlarını kullanır; `.env` veya mevcut servis DB'sine bağımlı değildir. Büyük indeks yoksa dataset pytest testleri skip olur; `--full` doğrulaması ise başarı sayılmaz.

[CI şablonu](ci/github-actions.yml) hazırdır; `.github/workflows/` altına taşınıp etkinleştirilmesi gerekir — bu bağımsız repoda henüz aktif edilmedi, otomatik uzak CI çalıştığı iddia edilmez.

[İşletim rehberi](docs/OPERATIONS.md), DB upgrade/backup, container, readiness ve provider geçişini açıklar. Docker/Compose tanımları servisin içindedir. DB şeması eksikse startup upgrade ister; eski DB kullanılacaksa servis durdurulup `python -m app.db.migrate` çalıştırılır. SQLite upgrade otomatik backup alır. Eski tenant'sız kayıtlar `legacy-unscoped` olur ve normal API'de açılmaz; yeni analiz gerekir.

## Dağıtım ve bağımsız doğrulama

`compose.yaml` gerçek read-only PostgreSQL ERP kaynağına bağlanan üretim tanımıdır; `ERP_DATABASE_URL` ve `AI_SERVICE_INTERNAL_TOKEN` ister. AI yazma veritabanı ERP veritabanından ayrıdır. `compose.demo.yaml` yalnız sentetik business verisiyle çalışır. İki tanımın state volume'ları ayrıdır.

```powershell
# Üretim tanımı: yalnız gerekli ortam değişkenleri hazır olduğunda
docker compose -p moerpy-ai -f compose.yaml config --quiet
docker compose -p moerpy-ai -f compose.yaml up --build -d

# Sentetik veri demosu
docker compose -p moerpy-ai-demo -f compose.demo.yaml up --build -d

# Bağımsız test imajı; MOERPY servislerine bağlanmaz
docker compose -p moerpy-ai-verify -f compose.test.yaml --profile postgres --profile smoke build
docker compose -p moerpy-ai-verify -f compose.test.yaml run --rm ai-tests
docker compose -p moerpy-ai-verify -f compose.test.yaml run --rm ai-postgres-tests
docker compose -p moerpy-ai-verify -f compose.test.yaml run --rm ai-smoke
docker compose -p moerpy-ai-verify -f compose.test.yaml --profile postgres --profile smoke down
```

Postgres testi kendi geçici `ai_service_test` veritabanına yazar; uygulamanın ERP veritabanını kullanmaz. Business smoke için `data/business_24m.db` gerekir. Testler ve pytest üretim imajından çıkarılır. Düz `docker build .` son `production` aşamasını üretir. `.env`, yerel DB, log ve cache dosyaları imaja alınmaz.

`python scripts/package.py`, yalnız AI servisi kaynakları ve her dosyanın SHA-256 manifest'ini içeren `dist/moerpy-ai-service-source.zip` üretir. Yerel veritabanları ve kimlik bilgileri pakete girmez. Güncel doğrulama kapsamı ve devir notları: [teslim notu](docs/HARDENING_HANDOFF.md).

## Dosya haritası

`app/data` sağlayıcılar ve indeksleme; `app/kpi/calculation.py` tek KPI otoritesi; `app/anomaly` snapshot/sürümleme; `app/evidence` kanıt; `app/llm` nitel anlatım; `app/rag` indeks ve öğrenme; `app/decisions` lifecycle; `app/api/routes/v2.py` kapsam kontrollü API; `scripts/` kurulum, test, imzalı istemci ve indeks geçişi.
