# AI Service — İnceleme sonrası düzeltmeler

Tarih: 15 Eylül 2026. Bu not, aynı gün hazırlanan kod rehberinden sonra yapılan değişiklikleri kaydeder.

## Düzeltilen davranışlar

### Yetkilendirme

`POST /analysis/run` ve `POST /anomalies/{id}/generate-decision` artık mevcut finansal işlem rolünü kontrol eder: `admin`, `owner`, `executive` veya `finance`. Salt okuma rolüyle analiz kayıtları değiştirilemez veya karar üreticisi çağrılamaz. İmzalı tenant/şirket kontrolü korunur.

### İstek sınırı ve sağlık kontrolleri

HTTP middleware saf ASGI olarak düzenlendi. API gövdesi boyut sınırı içinde okunur ve imza doğrulaması ile endpoint'e ayrı receive fonksiyonları üzerinden aynı baytlar verilir; `request._body` kullanılmaz. Açıkça fazla Content-Length bildiren istek gövdesi okunmadan 413 alır. API öneki tam yol veya `/` sınırıyla eşleşir; `/api/v10`, `/api/v1` sayılmaz.

`/health` ve `/ready` iş isteği semaforundan ve iş metriklerinden ayrıldı. İş isteğinin slotu yanıt gövdesi tamamlanana kadar tutulur. Meşgul yanıtlarının süreleri de sayaç toplamına eklenir. Her HTTP yanıt başlangıcına `X-Request-ID` eklenir.

### Hata sözleşmesi ve loglar

- `CompanyNotFoundError` ve `DecisionNotFoundError` → 404.
- `InvalidPeriodError` ve FastAPI istek doğrulama hataları → 422, `error_code=invalid_request`, `detail=Invalid request`.
- `InvalidSourceDataError` → 422, `error_code=invalid_source_data`; kaynak satırı veya ham istisna mesajı yanıta eklenmez.
- Beklenmeyen `KeyError`, `IndexError`, `ValueError` ve diğer programlama hataları → 500.
- LLM doğrulama hataları 422, geçersiz karar geçişleri 409, dış servis hataları 502/504 olarak ayrılmaya devam eder.
- Beklenmeyen hata ve readiness hatalarında stack konumları loglanır. JSON formatter dosya/satır/fonksiyon bilgilerini yazar; istisna mesajı, kaynak kod satırı ve yerel değişkenleri eklemez.
- Bozuk embedding önce tür/boşluk, sonra boyut ve sonlu/sıfır olmayan sayılar açısından denetlenir. Hatalı kayıt kimliği loglanır; `len(None)` hatası oluşmaz.
- Başlangıç başarısız olsa veya lifespan istisnayla kapansa da AI engine `finally` içinde dispose edilir.

### Tarih ve ayarlar

`REPORTING_TIMEZONE=Europe/Istanbul` varsayılandır; analizdeki “bugün” ve confidence güncellik tarihi bu ayardan hesaplanır. `tzdata` bağımlılığı, işletim sisteminde IANA veritabanı bulunmadığında da saat dilimini sağlar.

Varsayılan `.env`, göreli SQLite dosyaları ve business dataset yolları `ai-service/` köküne bağlandı. Mutlak yollar korunur. AI durumu ile business verisinin aynı dosyaya yazılması reddedilir. Postgres kimlik kontrolü hostname harflerini ve bilinen loopback alternatiflerini normalleştirir. SQLite bellek biçimleri, sürücü ve URI seçenekleri dahil kontrol edilir.

Bozuk DB URL'leri kontrollü doğrulama hatasına çevrilir. Settings hata metinlerinde input gizlenir; anahtar/token/DB URL alanları model repr çıktısından çıkarılır. Ayar nesnesinin tamamını loglamak veya `model_dump()` çıktısını yayınlamak yine uygun değildir.

### Veri sözleşmeleri

Company ve fact dataclass'larında tenant zorunlu hale geldi; boş değerler reddedilir. KPI, anomali, evidence ve threshold çıktı modelleri ile ilgili ORM modellerindeki otomatik fixture tenant varsayılanları kaldırıldı. Örnek kiracı yalnız fixture sağlayıcısında açıkça atanır.

CostFact ters geçerlilik aralığını; WasteReturnFact tanımsız olay türünü reddeder. KPI motorunun negatif sayı, dönem, maliyet ve kaynak kapsamı kontrolleri korunur; beklenen hatalar açık kaynak veri hatası sınıfını kullanır.

Fake provider artık lineage, sales_date, cogs_amount, cost_basis_known, maliyet kapsamı/geçerlilik tarihleri/is_budget ve inventory_value alanlarını okur. Günlük satışlar satış tarihine göre süzülür. Günlük ayrıntısı olmayan aylık toplam için kısmi dönem sessizce boş sonuç vermek yerine hata üretir. Eksik birim maliyet, otomatik olarak “maliyet kesinlikle bilinemez” sayılmaz; doğrulanmış alternatif maliyet çözümü korunur.

## Doğrulama

Testler Docker içinde offline metin ve yerel embedding ile çalıştırıldı; canlı model çağrısı yapılmadı.

| Kontrol | Sonuç |
|---|---|
| Ana pytest koşusu | 141 geçti; ayrı ortam isteyen 29 test bu koşuda atlandı. |
| Büyük business dataset, salt okunur mount | Atlanan 26 business testi ayrıca geçti; 24 aylık gelir/COGS mutabakatı dahil. |
| Ayrı geçici PostgreSQL | Atlanan 3 Postgres testi ayrıca geçti. |
| Gerçek yerel HTTP smoke, fake provider | Başlangıç, imza, 8 anomali, idempotent karar, tenant izolasyonu, onay ve öğrenme başarılı. |

Toplam **170 test başarılı**; ayrıca HTTP smoke başarılı. Testler arasında bir Starlette/AnyIO deprecation uyarısı vardı; test başarısızlığı yoktu. Geçici PostgreSQL konteyneri ve ağı kaldırıldı.

Yeni regresyonlar `app/tests/test_review_fixes.py` içindedir. Mevcut sayısal testlerin hesap beklentileri değiştirilmedi; doğrudan oluşturulan örneklere açık tenant eklendi. Kısmi fixture döneminin beklenen sonucu yeni açık hata sözleşmesine uyarlandı.

## Kullanıma alma

Değişiklikler kaynak dosyalardadır; çalışan uygulamaya dağıtım yapılmadı. Yeni bağımlılık ve kod için ortamın yeniden kurulması veya container imajının yeniden build edilip servisin yeniden başlatılması gerekir. Normal uygulama başlangıcı var olan kayıtları yeniden yazmaz.

API istemcileri analiz/üretim için yetkili rol taşımalı ve yeni ortak 422 hata biçimini kullanmalıdır. Eski Supabase köprüsünün imza başlıklarını üretmemesi, önceki rehberde belirtilen ayrı entegrasyon sınırı olarak devam eder; bu çalışma AI service içindeki inceleme bulgularını düzeltir.
