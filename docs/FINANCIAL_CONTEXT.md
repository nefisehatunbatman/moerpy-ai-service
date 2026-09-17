# Finansal bağlam ve karar üretimi

Güncelleme: 2026-09-17. Bu doküman eski rehberlerdeki sabit karar eşleştirmesi açıklamasının yerini alır.

`financial_impact/analyzer.py` artık karar türünü zorunlu seçmez. Bilinen metrikler için ilgili finansal alanlar, geçici değerlendirme hedefi, destek departmanları, bilgi eksikleri ve doğrulanmış parasal gösterge sağlar. Marj farkı maliyet farkı veya bütçe yeniden dağıtımı olarak varsayılmaz. Nedensellik iddiaları kaldırılmıştır.

`decision_type` eski snapshot uyumluluğu için bağlam modellerinde nullable tutulur; yeni analyzer çıktısında null'dır. LLM mevcut karar kategorilerinden seçim yapar. Kategori Pydantic ile doğrulanır; departman kapsamı kodla korunur. KPI, eşik ve önem hesapları değişmedi. Kanıt policy'si ayrı ve sürümlüdür; policy yoksa tamlık bilinmez ve güven puanı bunu tam kabul etmez.

## Bilinmeyen metrik

Tespit edilmiş fakat finansal eşleştirmesi olmayan metrik `review_required` üretir. Kendi doğrulanmış KPI sinyali varsa RAG/LLM akışı çalışır; final öneri güvenli bir finansal inceleme talebine sınırlandırılır, karar kategorisi FINANCIAL_RISK ve beklenen etki listesi boştur. Kanıt yoksa model çağrılmaz. Bu değişiklik yeni anomali tespit yöntemleri eklemez.

## Sayısal alanlar

Gözlenen tutar veya senaryo etkisi, aynı tenant/şirket/varlık/dönem kapsamındaki geçerli TRY KPI'ından gelir. Tasarruf olarak yorumlanmaz. LLM anlatısındaki sayılar reddedilir. Beklenen etkiler yalnızca gönderilen sinyaller için nitel olabilir; bilinmeyen metriğin azalması gerektiği varsayılmaz.

## Çevrimdışı ve canlı mod

Çevrimdışı istemci duruma özel karar veriyormuş gibi davranmaz: genel finansal inceleme önerir, beklenen kazanç üretmez. Canlı istemci bağlamla kategori ve koşullu öneri seçebilir. Prompt kuralları finansal doğruluğun garantisi değildir; uzman değerlendirmesi ve gerçek müşteri pilotu gereklidir.

Yeni kartlar `assessment_status`, `financial_areas`, `information_gaps` taşır. Bunlar evidence snapshot içinde saklanır; ayrı bir DB kolon migrasyonu gerekmez. Prompt sürümü `v3-financial-context`, idempotent karar kimliğinin de parçasıdır; eski kartlar otomatik yeniden yazılmaz. Frontend bağlantısı bu çalışmanın dışında bırakılmıştır.

## Yapılacaklar

Kart önerisi koşullu ve açık metin olarak, güven skoru ise kanıt yeterliliği ve gerekçeleriyle sunulur. Ayrıntı: [CONFIDENCE_AND_RECOMMENDATION.md](CONFIDENCE_AND_RECOMMENDATION.md).

Ana takip listesi: [roadmap.md](../../roadmap.md). Uzmanla mevcut bağlamları ve koşullu kuralları; gerekli veri, istisnalar, hesaplama varsayımları, inceleme koşulları ve doğru/yanlış örneklerle doğrula. Şirket hedefleri ve kısıtları henüz bu akışa sağlanmıyor.

## Kurallı bağlam seçimi — 2026-09-17

Bağlam seçimi `context-v1` ile yenilendi; güncel prompt sürümü `v4-context-selection` oldu. Ayrıntılar: [CONTEXT_SELECTION.md](CONTEXT_SELECTION.md). Eski snapshot'lara bağlam eklemek için analiz yeniden çalıştırılır. Kart sinyalleri artık entity_type, entity_id, scope_relation ve selection_reason içerir.
