# سِعرك (Sa'rak) — Egyptian Price Tracker

مشروع متكامل لمتابعة أسعار المنتجات في المتاجر المصرية (**Amazon.eg** و **Noon.com**) وإرسال تنبيهات فورية عبر **Telegram** عند وصول السعر إلى الحد المستهدف.

## طريقة التشغيل السريع (Local Development)

1. انسخ ملف الإعدادات البيئية:
   ```bash
   cp .env.example .env
   ```
2. شغّل جميع الخدمات باستخدام Docker Compose:
   ```bash
   docker compose up --build -d
   ```
3. افتح الموقع في المتصفح:
   - **الواجهة العربية (Frontend):** `http://localhost:8080`
   - **توثيق الـ API (Swagger UI):** `http://localhost:8000/docs`
   - **Prometheus Metrics:** `http://localhost:8080/metrics`

> **ملاحظة:** يمكنك أيضاً فتح ملف `frontend/index.html` مباشرة في المتصفح بدون تشغيل الباك إند، وسيعمل تلقائياً في **وضع التجربة (Demo Mode)** مع رسوم بيانية تفاعلية.
