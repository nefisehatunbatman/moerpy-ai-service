# Öneri ve güven seviyesi

Karar kartındaki öneri bir uygulama emri değil, mevcut kanıta göre yönetimin değerlendireceği koşullu adımdır. Örneğin stok bulgusunda sistem yeni satın alma taahhütlerini ve yavaş hareket eden ürünleri incelemeyi; sipariş zamanını talep ve tedarikçi koşulları kontrol edildikten sonra yeniden değerlendirmeyi söyleyebilir. Nedeni doğrulanmadan “satın almayı durdur” veya “şu kadar tasarruf edilir” demez.

`confidence.score` 0–100 arası deterministik bir **kanıt yeterliliği** puanıdır. Önerinin uygulanınca başarılı olma olasılığı değildir. Kart artık `confidence.reasons` ile puanın neden sınırlı olduğunu taşır: zorunlu bağlam eksikliği, veri kapsamı, benzer onaylı karar desteği ve güncellik gibi nedenler ayrı görülebilir.

Önerinin açıklanması için kartta şu ayrım korunur:

- `observed_impact`: Veride gözlenen parasal büyüklük; beklenen tasarruf değildir.
- `expected_impact`: Kanıt destekliyorsa nitel yön; bilinmiyorsa boş bırakılır.
- `recommended_decision`: Koşullu yönetim değerlendirmesi.
- `confidence`: Kanıtın yeterlilik seviyesi ve gerekçeleri.

Çevrimdışı LLM istemcisi artık finansal alanlara göre anlaşılır bir taslak öneri verir. Canlı LLM aynı sözleşmeye uyar; önerinin iş uygunluğu uzman doğrulaması ve pilot sonuçlarıyla ölçülmelidir.
