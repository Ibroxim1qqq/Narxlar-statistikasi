# O'zbekiston yangi uylar narxlari dashboardi

Bu loyiha hozirgi bozor snapshotini yig'adi va dashboardga chiqaradi.

[Renderga deploy qilish](https://dashboard.render.com/blueprint/new?repo=https%3A%2F%2Fgithub.com%2FIbroxim1qqq%2FNarxlar-statistikasi)

## Ishga tushirish

```powershell
& "C:\Users\Aslanbek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scrape_prices.py
& "C:\Users\Aslanbek\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m streamlit run dashboard.py
```

Oddiy Python muhitida:

```bash
pip install -r requirements.txt
python daily_update.py
streamlit run dashboard.py
```

## Chiqadigan fayllar

- `data/processed/projects.csv` - turar-joy komplekslari bo'yicha normalizatsiya qilingan jadval.
- `data/processed/room_prices.csv` - xona/maydon/min narx kesimidagi jadval.
- `data/processed/summary.json` - snapshot bo'yicha qisqa statistika.
- `data/housing_prices.sqlite` - tarixiy SQLite baza. Dashboard eng oxirgi snapshotni shu bazadan o'qiydi.
- `data/raw/` - API/HTMLdan kelgan raw javoblar. Bu papka scraper ishga tushganda qayta hosil bo'ladi va GitHubga kiritilmaydi.

## Database

SQLite baza:

```text
data/housing_prices.sqlite
```

Asosiy jadvallar:

```sql
SELECT * FROM snapshots ORDER BY snapshot_utc DESC;
SELECT * FROM projects_history;
SELECT * FROM room_prices_history;
```

Doim eng oxirgi joriy ma'lumotni ko'rsatadigan viewlar:

```sql
SELECT * FROM latest_projects;
SELECT * FROM latest_room_prices;
```

Terminaldan tez tekshirish:

```bash
python inspect_database.py
```

PostgreSQL yoqish uchun `.env` ichida DSN turadi:

```text
POSTGRES_DSN=postgresql+psycopg://narxlar_app:...@localhost:5432/narxlar_statistikasi
```

Mahalliy kompyuterda PostgreSQL va pgAdmin o'rnatish:

```powershell
.\scripts\install_postgres_pgadmin.ps1
.\scripts\setup_postgres_database.ps1
python daily_update.py
```

pgAdmin orqali ulanish:

```text
Host: localhost
Port: 5432
Database: narxlar_statistikasi
Username: narxlar_app
Password: .env ichidagi POSTGRES_APP_PASSWORD
```

PostgreSQL sozlangan bo'lsa, scraper snapshotni SQLite bilan birga PostgreSQL'ga ham yozadi. Dashboard esa birinchi PostgreSQL'dan o'qiydi, ulanish bo'lmasa SQLite fallback ishlaydi.

Dashboard ichidagi `Database` tabda `snapshots`, `latest_projects`, `latest_room_prices`, `projects_history` va `room_prices_history` jadvallarini ko'rish hamda CSV qilib yuklab olish mumkin.

`daily_update.py` bir kunda bitta snapshot saqlaydi: o'sha Asia/Tashkent sanasida qayta ishga tushsa, shu kun yozuvini yangilaydi. Windows Task Scheduler har kuni soat 10:00 da `daily_update.py`ni ishga tushirib, bazaga yangi snapshot qo'shadi. Kompyuterning o'zida qayta o'rnatish uchun:

```powershell
.\scripts\install_daily_task.ps1
```

Task nomi: `Narxlar Statistikasi Daily Update`. Loglar `data/logs/` ichida saqlanadi. Task data o'zgarsa `data/housing_prices.sqlite` va `data/processed/` fayllarini commit qilib GitHubga push ham qiladi.

## Dashboard bo'limlari

- `Umumiy` - KPI, eng qimmat/arzon hududlar, tuman reytingi va xarita.
- `Shaharlar` - shahar/viloyat bo'yicha median m2 narx va volume.
- `Tumanlar` - premium/value zonalar va narx-volume matritsasi.
- `Xonalar` - xona soni bo'yicha ticket size, maydon va m2 dispersiyasi.
- `Xarita` - latitude/longitude bor loyihalarni xaritada ko'rish.
- `Loyihalar` - loyiha-level jadval, sort, search va CSV export.
- `Data quality` - manba coverage, missing fields va caveatlar.
- `Database` - SQLite snapshotlar, latest viewlar va jadval preview.

## Manbalar

- Uysot: `https://uysot.uz/uz/uzbekistan/novostroyki`
- Salomuy: `https://salomuy.uz/`
- Yangiuylar: `https://yangiuylar.uz/objects/building`
- Domtut: `https://domtut.uz/uz/catalog-nedvijimosty`

## Eski data qayerdan olinadi?

1. O'z scraperimizni har kuni/haftada ishga tushirib, `snapshot_utc` bilan arxiv qilish.
2. Domtut sahifalaridagi bozor statistikasi bloklari, chunki u yerda oy va foiz o'zgarishlari ko'rinadi.
3. Wayback Machine sahifa snapshotlari, ayniqsa katalog va loyiha sahifalari uchun.
4. Markaziy bank kurslari va rasmiy statistika manbalari bilan narxlarni real/valyuta kesimida deflyatsiya qilish.
5. Quruvchilarning rasmiy price-listlari va Telegram/Instagram postlari. Buni alohida media-scraper bilan yig'ish kerak.

## GitHub / Streamlit Cloud

Repo GitHubga qo'yilgandan keyin Streamlit Cloud uchun entrypoint:

```text
dashboard.py
```

Data yangilash kerak bo'lsa, lokalda yoki scheduled runnerda `python daily_update.py` ishga tushiriladi va `data/housing_prices.sqlite` hamda `data/processed/` snapshotlari commit qilinadi.
