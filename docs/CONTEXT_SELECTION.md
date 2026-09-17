# Kurallı ve dinamik kanıt seçimi

2026-09-17 — seçim sürümü `context-v2-policy`, prompt sürümü `v4-context-selection`.

## Akış

1. Anomali tespitinde aynı şirket/kiracı/dönemdeki yerel KPI'lar snapshot'a alınır. Ürün-şube anomalisi için aynı şubenin göstergeleri de saklanır. Başka şubeler, kardeş ürünler ve tüm şirket verisi eklenmez.
2. `evidence/selection.py` ana sinyali doğrular. Değeri anomaliyle eşleşmeyen, eksik veya tekrarlı ana sinyalde paket boş kalır; LLM çağrılmaz.
3. Hesap bileşenleri önce seçilir. Örneğin marj için gelir ve COGS; stok gün sayısı için stok değeri ve COGS. Bunlar aynı varlıkta bulunmalıdır; üst şube değeri ürünün eksik bileşenini tamamlamaz.
4. Kalan adaylar ortak kaynak kayıtlarına ve ilgili finansal alanlara göre sıralanır. Yerel kapsam, kaynak ortaklığı, veri kapsamı, sorun sayısı ve sabit kimlik sırası kullanılır. Sonuç giriş sırasından bağımsızdır.
5. Ana sinyal dahil en fazla sekiz gösterge seçilir. Sığmayan ilgili aday sayısı, eksik temel göstergeler ve geçersiz adayların dışlanma nedenleri kaydedilir.

## Policy ve katalog ayrımı

`evidence/policies.py` metrik başına sürümlü kanıt politikasını taşır: ana metrik, zorunlu bileşenler, izin verilen kapsamlar ve sinyal bütçesi. Policy kimliği ve sürüm hash'i evidence snapshot'a yazılır. Policy olmayan metrikte tamlık `unknown` ve güven faktörü sıfırdır; ana sinyalin bulunması yeterli kabul edilmez. Eski `problem_type` bazlı sabit sinyal sayısı fallback'i kaldırılmıştır.

Katalog göstergelerin finansal alanını ve birimini tanımlar. Policy zorunlu bileşenleri belirler; katalog adayların finansal ilişkisini açıklamaya yardım eder. Kataloğa eklenmemiş gösterge gerçek kaynak kayıtları ortaksa bağlama girebilir, fakat policy yerine geçmez. Ortak kaynak veya tanımlı ilişki yoksa sistem ilişki uydurmaz. LLM veri seçmez.

## İzlenebilirlik

Her sinyal `entity_type`, `entity_id`, `scope_relation` ve `selection_reason` taşır. Bunlar kanıt snapshot'ında ve kartın sinyallerinde korunur. Şube bağlamı ürünün kendi sayısı gibi yorumlanmaması için prompt'ta ve sayısal özette açıkça ayrılır. Aynı metriğin üst şube değeri, ürün için beklenen etki kaynağı olamaz.

Paketin kaynak yükleme listesi yalnız seçilmiş sinyallerden türetilir. `missing_context:<metric>`, `context_limit_reached`, `context_exclusions` eksikleri görünür kılar. Hatalı durum, boş değer, sıfır veri kapsamı, yinelenen metrik, yanlış birim, gelecekteki/eski stok fotoğrafı seçilmez. Parasal etki de seçim doğrulamasından geçmeyen KPI'a dayanamaz.

Güven motorunun veri tamlığı ve kanıt kapsamı, toplam sinyal sayısı yerine gerekli bileşenlerin bulunma oranını kullanır. Çok sayıda opsiyonel sinyal eksik COGS'u gizlemez. Bu oran başarı olasılığı veya tüm iş bağlamının eksiksiz olduğu iddiası değildir.

## Sınırlar ve geçiş

- Ortak kaynak ilişki gösterir; bağımsız kanıt veya nedensellik değildir.
- Üst kapsam erişimi şu anda yalnız hesap motorunun ürettiği `branch-code:product-code` kimliğinden ilgili şubeye yapılır. Diğer hiyerarşiler ayrıca tanımlanmalıdır.
- Finansal karşılığı bilinmeyen metrik bağlam bulsa bile inceleme gerektiren akışta kalır.
- Geçmiş anomalilerin snapshot'ları değiştirilmez. Üst şube bağlamı için analiz yeniden çalıştırılmalıdır. Seçim sürümü run kimliğine, yeni prompt sürümü karar kimliğine katılır.
- Şirket hedefleri ve kısıtlarının entegrasyonu, uzman doğrulaması ve frontend çalışması ayrı görevlerdir.
