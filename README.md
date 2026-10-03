"""CineStream AI / KinoBot

CineStream AI - Telegram kino boti, PostgreSQL, Redis va AI Reels worker.

## Talablar

- Docker Desktop va Docker Compose v2
- Telegram bot tokeni
- PostgreSQL va Redis uchun lokal Docker resurslari
- AIMLAPI key; FFmpeg va Whisper worker image ichida o‘rnatiladi

## `.env` sozlash

`.env.example` faylidan `.env` yarating. Kamida `BOT_TOKEN`, `ADMIN_IDS`, `REELS_CHANNEL_ID`, `POSTGRES_PASSWORD` va `AIMLAPI_KEYS` qiymatlarini to‘ldiring. Secretlar faqat `.env` yoki deployment Variables orqali beriladi.

Docker Compose `DATABASE_URL` va `REDIS_URL` ni avtomatik ravishda `postgres` va `redis` service nomlariga moslaydi. Windows’da Docker’siz ishlaganda PostgreSQL uchun `localhost` ishlating.

## Docker orqali ishga tushirish

```powershell
Copy-Item .env.example .env
# .env ichidagi secret va ID qiymatlarini to‘ldiring
docker compose up --build
```

`bot` va `worker` containerlari ishga tushishidan oldin `alembic upgrade head` bajaradi. Migrationlar mavjud ma’lumotlarni o‘chirmaydi.

Servislar:

- `bot` - Telegram polling va `http://localhost:8080/` health endpoint
- `worker` - AI, Whisper, FFmpeg va Telegram Reels publishing
- `postgres` - persistent `cinestream_pg` volume bilan PostgreSQL
- `redis` - queue uchun Redis

Loglar, holat va to‘xtatish:

```powershell
docker compose ps
docker compose logs -f bot
docker compose logs -f worker
docker compose stop
```

PostgreSQL va Redis health tekshiruvi:

```powershell
docker compose exec postgres pg_isready -U postgres -d cinestream
docker compose exec redis redis-cli ping
```

Qayta build qilish:

```powershell
docker compose build --no-cache
docker compose up
```

`docker compose down -v` ishlatmang: bu PostgreSQL volume’ini o‘chiradi.

## Kino qo‘shish va Reels: yangi funksiyalar

Admin panel orqali kino qo‘shishning uchta usuli bor: forward, serverga video yoki ochiq URL.

- **URL yuklash** (`app/video/downloader.py`): faqat `http/https`, private/local host va embedded credential rad etiladi, hajm 5 GB cheklov; oddiy MP4 `httpx`, HLS/M3U8 va video sahifalar `yt-dlp` bilan olinadi. 50 MB gacha Telegram’ga yuklanib `file_id` saqlanadi, kattasi uchun `source_url` saqlanib worker keyinroq yuklab oladi.
- **Main channel post**: kino saqlangach `MAIN_CHANNEL_ID` ga poster + nom + kod + tavsif post qilinadi va `main_channel_message_id` yoziladi; kanal sozlanmagan bo‘lsa kino baribir saqlanib qoladi.
- **Xabar yuborish** (`app/handlers/admin_broadcast.py`): foydalanuvchilar / 1-kanal (main) / 2-kanal (reels) / hammasi / maxsus ID’lar; FloodWait bilan qayta urinish, 0.05 s pauza, muvaffaqiyatsiz ID’lar logga yoziladi.
- **Reels strategiyasi** (`app/video/moments.py`): `REEL_MOMENT_STRATEGY` = `auto`/`metadata`/`transcript`/`heuristic`. `auto` da AI ishlamasa to‘liq mahalliy heuristic’ga o‘tadi — AI o‘lsa ham job bajariladi. Qisqa filmlarda (≤ `REEL_TRANSCRIPT_MAX_DURATION`, default 1200 s) transcript-avval yo‘l ishlatiladi.
- **Yuz kuzatuvi** (`app/video/framing.py`): `REEL_FACE_TRACKING=true` bo‘lsa har sahnada yuz markaziga siljigan 9:16 crop; default `false` — statik markaz crop.
- **AIMLAPI fallback**: har bir xatolik (401/429/5xx/timeout) alohida log qilinadi, har kalitda 3 marta exponential retry, barcha kalitlar tugasa `AIMLAPI_FALLBACK_MODEL` siniladi va adminga sababli xabar boradi (`AIMLAPI_KEY_4` gacha qo‘llab-quvvatlanadi).

Test: `python -m pytest -q` (97+ test).

## Local Docker’siz ishlatish

```powershell
pip install -r requirements.txt
alembic upgrade head
python -m app.bot
# boshqa terminalda:
python -m app.workers.reels
```

## Docker'siz Railway deployment

Bu loyiha Railway’da Docker Desktop yoki Docker commandlarisiz Nixpacks orqali ishlaydi. `railway.toml` bot service uchun Nixpacks builder, healthcheck va deploy oldidan migration commandini belgilaydi.

### Bot service

Repository’ni Railway’ga ulang va quyidagi start command’dan foydalaning:

```text
python -m app.bot
```

### Worker service

Shu repository’dan ikkinchi Railway service yarating. Worker service uchun start command:

```text
python -m app.workers.reels
```

Worker Telegram bot service’dan alohida process bo‘lishi kerak. Worker service’da ham bir xil production environment variables bo‘lsin. Migrationni bir vaqtning o‘zida ikki service bajarib yubormasligi uchun `alembic upgrade head` ni Bot service deploy pre-command sifatida qoldiring; worker service’da migrationni alohida avtomatik command qilib qo‘ymang.

### PostgreSQL va Redis

Railway PostgreSQL service/plugin’ini ulang va Railway bergan `DATABASE_URL` ni Bot hamda Worker service’lariga Variables orqali qo‘ying. Redis service/plugin’idan berilgan URL’ni `REDIS_URL` ga qo‘ying. Railway URL’lari Docker’dagi `postgres`, `redis` yoki Windows’dagi `localhost` hostname’lariga almashtirilmaydi.

Majburiy production Variables:

- `BOT_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`
- `ADMIN_IDS`
- `MAIN_CHANNEL_ID` (masalan `-1003231515720`)
- `REELS_CHANNEL_ID`
- `AIMLAPI_KEYS` yoki `AIMLAPI_KEY_1` (ixtiyoriy: `AIMLAPI_KEY_2/3/4`)
- `AIMLAPI_FALLBACK_MODEL` (ixtiyoriy: asosiy model ishlamasa zaxira model)
- `REEL_MOMENT_STRATEGY` (default `auto`; `metadata`/`transcript`/`heuristic`)
- `REEL_TRANSCRIPT_MAX_DURATION` (default `1200`)
- `REEL_FACE_TRACKING` (default `false`)
- `CARD_NUMBER`
- `CARD_OWNER`
- `PREMIUM_WEEK_PRICE`
- `PREMIUM_MONTH_PRICE`
- `SUBSCRIBER_100_PRICE`
- `SUBSCRIBER_500_PRICE`
- `SUBSCRIBER_1000_PRICE`
- `ADMIN_USERNAME`

Reels worker uchun `FFMPEG_BINARY=ffmpeg`, `FFPROBE_BINARY=ffprobe`, `VIDEO_WORK_DIR=/tmp/cinestream-work`, `WHISPER_MODEL`, `REEL_JOB_MAX_ATTEMPTS`, `WORKER_CONCURRENCY`, `WORKER_RETRY_BACKOFF_SECONDS` va `WORKER_RETRY_BACKOFF_MAX_SECONDS` ni ham qo‘ying. `nixpacks.toml` FFmpeg’ni build muhitiga qo‘shadi.

### Health va migration

Railway `PORT` variable’ini berganda bot mavjud health serverini shu portda ishga tushiradi. Health endpoint PostgreSQL’ga `SELECT 1` orqali readiness tekshiradi.

Migration command:

```text
alembic upgrade head
```

Bu command faqat mavjud migrationlarni qo‘llaydi; database reset yoki ma’lumot o‘chirish commandlari yo‘q. Railway deploy holati, bot loglari va worker loglarini Railway dashboard’dan tekshiring.

Railway deployment hali bu lokal Windows muhitida real deploy sifatida tasdiqlanmagan. Keyingi amaliy qadam Railway’da PostgreSQL va Redis service’larini ulab, Bot va Worker uchun Variables hamda yuqoridagi alohida start commandlarni saqlashdir.
