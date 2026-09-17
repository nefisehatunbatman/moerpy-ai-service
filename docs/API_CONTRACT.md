# AI Service v2 — MOERPY ekibine entegrasyon sözleşmesi

Bu belge servis teslimatıdır; MOERPY kodu bu değişiklikte düzenlenmemiştir. Mevcut `ai-financial-decisions` Edge Function yalnız `X-Internal-Token` gönderdiği için v2'de 401 alır. Kapsamı göndermeden ID bazlı erişime izin veren bir uyumluluk modu yoktur.

## Güven sınırı

### Finansal bağlam güncellemesi (2026-09-17)

Karar türü artık analyzer tarafından sabitlenmez; canlı LLM mevcut taksonomiden önerir. Kart yanıtına `assessment_status`, `financial_areas`, `information_gaps` eklenmiştir. Bilinmeyen finansal bağlam `review_required`, `FINANCIAL_RISK` ve boş `expected_impact` ile incelemeye yönlendirilir. Çevrimdışı mod genel inceleme önerir. `observed_impact`, beklenen kazanç değildir. Ayrıntı: [FINANCIAL_CONTEXT.md](FINANCIAL_CONTEXT.md). Yeni prompt sürümü `v3-financial-context`; frontend entegrasyonu bu güncellemenin kapsamında değildir.

İmzayı yalnız güvenilir backend üretir. Backend Supabase oturumunu, kullanıcının approved durumunu, ürün erişimini, tenant/company üyeliğini ve gerçek rolünü doğrular. Kullanıcıdan gelen `company_id`, `tenant_id`, `actor` veya `roles` doğrudan imzalanmaz. Secret browser'a verilmez. TLS ve servis ağı erişim kuralları deployment sorumlusunca uygulanır.

Her `/api/v1` isteği şu başlıkları taşır:

- `X-Internal-Token`: backend ve AI servisine özel ortak secret.
- `X-AI-Context`: aşağıdaki JSON'un UTF-8 → URL-safe base64 kodlaması (padding kabul edilir).
- `X-AI-Signature`: context başlığının **aynen gönderilen ASCII metni** üzerinde secret ile HMAC-SHA256, küçük harf hex.

```json
{
  "tenant_id": "server-resolved tenant",
  "company_id": "server-resolved company",
  "actor": "server-resolved user ID",
  "roles": ["finance"],
  "ts": 1789250000,
  "method": "POST",
  "path": "/api/v1/analysis/run",
  "body_sha256": "sha256 hex of the exact HTTP body bytes"
}
```

`ts` güncel Unix saniyesidir; örnek tarih kopyalanmaz. Varsayılan kabul penceresi ±120 saniyedir. `path`, yüzde kodlaması ve varsa query string dahil tam request target'tır. İmzalamadan sonra query parametre sırası veya JSON boşlukları değiştirilmez. Gövdesiz isteğin hash'i boş byte dizisinin SHA-256 değeridir. JSON anahtar sırası zorunlu değildir; imza başlıktaki metnin kendisine uygulanır.

Python referans uygulaması: `app/api/security.py::signed_headers`. Çalışan CLI örneği: `scripts/request.py`. Backend için algoritma:

```javascript
// Runs only in a trusted backend after authorization; never in frontend code.
const body = JSON.stringify(authorizedPayload);
const encoder = new TextEncoder();
const hex = bytes => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, "0")).join("");
const contextPayload = {
  tenant_id: scope.tenant_id, company_id: scope.company_id,
  actor: authorizedUser.id, roles: authorizedRoles,
  ts: Math.floor(Date.now() / 1000), method: "POST", path: "/api/v1/analysis/run",
  body_sha256: hex(await crypto.subtle.digest("SHA-256", encoder.encode(body)))
};
const bytes = encoder.encode(JSON.stringify(contextPayload));
const context = btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_");
const key = await crypto.subtle.importKey("raw", encoder.encode(internalSecret), {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
const signature = hex(await crypto.subtle.sign("HMAC", key, encoder.encode(context)));
// Send the exact body, target and context used above.
```

## Endpoint davranışları

Mevcut URL yapısı korunmuştur. Şirket parametresi her zaman imzalı kapsamla karşılaştırılır; tek kayıt endpoint'leri hem tenant hem company kontrol eder. Yanlış kapsam 404 döner. Onay/red/eşik değişikliği/öğrenme retry için `admin`, `owner`, `executive`, `finance` rollerinden en az biri gerekir; salt okuma rolü yeterli değildir. Request body içindeki `actor` uyumluluk için kabul edilebilir ama kullanılmaz; kayda imzalı kullanıcı yazılır.

| İşlem | Endpoint |
| --- | --- |
| KPI | `GET /companies/{company_id}/kpis?period_start=&period_end=` |
| Analiz | `POST /analysis/run` — company_id, period_start, period_end |
| Eşik listesi/değişikliği | `GET/PUT /companies/{company_id}/thresholds` |
| Aktif anomaliler | `GET /companies/{company_id}/anomalies?limit=100&offset=0` |
| Anomali | `GET /anomalies/{id}` |
| Karar üretimi | `POST /anomalies/{id}/generate-decision?language=tr` |
| Karar listesi | `GET /decisions?company_id=&status=&limit=100&offset=0` |
| Kart/kanıt/RAG/geçmiş | `GET /decisions/{id}` ve `/evidence`, `/rag-context`, `/lifecycle` |
| Onay/red | `POST /decisions/{id}/approve`, `/reject` |
| Öğrenme retry | `POST /decisions/{id}/retry-learning` |
| Servis metrikleri | `GET /metrics` — finans/yönetici rolü |

Tüm yollar `/api/v1` altında; `/health` ve `/ready` hariç. Sayfalama üst sınırı 500'dür. Dönem başlangıcı bitişten sonra olamaz; üst sınır üç yıldır. Pasif eşikler de yönetim GET'inde döner. Desteklenmeyen metrik/operator, yanlış risk yönü veya ters warning/critical sırası 422 döner. Body üst sınırı varsayılan 32 KiB'dır.

Gelecekteki dönem bitişi reddedilir; açık ay için gerçek kesim tarihi gönderilmelidir. Business sağlayıcısında dönem, doğrulanmış veri kümesinin tarih kapsamını da aşamaz. Servis ayın kalan günlerini tahminle doldurmaz. Liste sorgularında tenant/company filtresi sayfalamadan önce uygulanır.

Öğrenme yalnız ilgili tenant/company özel kaydını günceller; global RAG şablonlarına şirket aktivitesi yazılmaz. Eski global öğrenme kayıtları bulunan AI veritabanları için yedek alınarak `python -m app.db.migrate` çalıştırılmalıdır (şema/veri geçişi v3).

## Çıktıda değişen alanlar

KPI `value` artık `null` olabilir. `status`, `issues`, `coverage`, `source_count`, `source_digest`, sınırlı `source_ids`, `import_batch_ids`, `snapshot_date`, `tenant_id` taşır. UI `null` değerleri sıfıra çevirmemelidir.

Karar kartına `tenant_id`, `company_id`, `entity_id`, `entity_type`, `period`, `run_id`, `generator`, `model_version`, `prompt_version`, `language`, `learning_status`, `observed_impact` ve confidence faktörleri eklenmiştir. `expected_impact` nitel olur; stok değeri veya geçmiş zarar burada tasarruf olarak gösterilmez. `observed_impact.kind` `observed_exposure` veya `scenario_impact` olabilir. Confidence `interpretation` alanı doğruluk olasılığı olmadığını açıklar.

Aynı anomali sürümü ve dil için üretim tekrarları aynı kartı döndürür. Yeniden analiz yeni veri/eşik hash'iyle yeni sürüm üretir; önceki anomaliler superseded olur. Onay/red yarışında yalnız bir transition kazanır. İkinci onay 409'dur. Öğrenme başarısızlığında onay 200 ve `learning_status=failed` dönebilir; sonrasında retry endpoint'i kullanılır. Aynı karar için öğrenme receipt'i tekrar sayacı artırmayı engeller.

Hata sınıfları: 401 imza/auth, 403 rol, 404 bulunamadı/kapsam dışı, 409 eski sürüm veya transition çakışması, 413 body boyutu, 422 girdi/kanıt doğrulama, 429 yerel eşzamanlılık sınırı, 502 provider hatası, 503 hazır değil, 504 doğrudan upstream timeout. Provider'ın tekrar bütçesi tükendiğinde 502 döner. `X-Request-ID` normal yanıtlarda; middleware hata gövdesinde `request_id` bulunur. Ham model yanıtı ve secret hata detayına konmaz.

## Diğer ekibin kabul testleri

A şirketindeki kullanıcı B şirketinin kararını okuyamamalı/onaylayamamalı/reddedememeli, B anomalisiyle üretim yapamamalı. İmzalı query/body değiştirilirse çağrı reddedilmeli. Finance olmayan kullanıcı politikayı değiştirememeli. `null` KPI, offline generator ve başarısız öğrenme durumları istemcide doğru gösterilmeli. Bu belge ve servis testleri hazırdır; mevcut frontend/proxy üzerinde bu bağlantılar uygulanmamıştır.

### Kurallı bağlam seçimi

Prompt sürümü `v4-context-selection`. `signals` öğelerinde `entity_type`, `entity_id`, `scope_relation`, `selection_reason` alanları eklenmiştir; mevcut alanlar korunur. `parent_branch` sinyalleri üst şube bağlamıdır, ürünün kendi değeri değildir. Kanıt endpoint'i seçim sürümünü, gereken/mevcut bileşen sayılarını, dışlama nedenlerini ve sınır nedeniyle alınamayan aday sayısını içerir. Ayrıntı: [CONTEXT_SELECTION.md](CONTEXT_SELECTION.md).
