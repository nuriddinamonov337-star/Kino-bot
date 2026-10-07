# 🧹 CineStream AI — Loyihani Tozalash Qo'llanmasi (PowerShell)

> **Muhim:** Barcha buyruqlar **PowerShell** uchun. Loyiha papkasida turing:
> ```powershell
> cd C:\Users\HP\Desktop\Kino-bot
> ```

---

## 📊 Hozirgi holat (tekshirilgan)

| Ko'rsatkich | Qiymat |
|---|---|
| Umumiy hajm | **0.78 MB** |
| Umumiy fayllar | **284** |
| Python fayllar | **94** |
| Python kod qatorlari | **7 859** |
| Test fayllar | **25** |

> ✅ Loyiha allaqachon toza. `.venv`, `node_modules`, `__pycache__` mavjud emas.

---

## 1️⃣ Yangi `.gitignore` mazmuni

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
.coverage.*
htmlcov/
.venv/
venv/
env/
ENV/
*.egg-info/
.eggs/
build/
develop-eggs/
.installed.cfg

# Environment and secrets
.env
.env.*
!.env.example
railway.env

# Local runtime data and temporary video files
data/
logs/
tmp/
*.mp4
*.mkv
*.avi
*.mov
*.srt
*.log

# IDE and OS
.idea/
.vscode/
.DS_Store
Thumbs.db

# Legacy frontend dependencies (not used by the Python bot)
node_modules/
dist/

chat_*.md
```

---

## 2️⃣ Tozalash buyruqlari (PowerShell)

### 2.1. Keraksiz papkalarni o'chirish

```powershell
# Asosiy keraksiz papkalar
Remove-Item -Recurse -Force .venv, venv, node_modules, .pytest_cache, .mypy_cache, .ruff_cache -ErrorAction SilentlyContinue
```

### 2.2. Barcha `__pycache__` papkalarni topib o'chirish

```powershell
# Barcha __pycache__ papkalarni rekursiv topib o'chirish
Get-ChildItem -Recurse -Force -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# Qolgan .pyc fayllarni o'chirish
Get-ChildItem -Recurse -Force -File -Include *.pyc, *.pyo -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
```

### 2.3. Python virtual muhitni qayta yaratish

```powershell
# Eski muhitni o'chirish (agar mavjud bo'lsa)
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue

# Yangi virtual muhit yaratish
python -m venv .venv

# Faollashtirish
.\.venv\Scripts\Activate.ps1

# Agar "execution policy" xatosi chiqsa:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2.4. Kerakli paketlarni qayta o'rnatish

```powershell
# pip ni yangilash
python -m pip install --upgrade pip

# Loyiha paketlarini o'rnatish
pip install -r requirements.txt
```

---

## 3️⃣ Loyiha hajmini tekshirish buyruqlari (PowerShell)

### 3.1. Umumiy papka hajmi

```powershell
$size = (Get-ChildItem -Recurse -Force -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
"Umumiy hajm: {0:N2} MB" -f ($size / 1MB)
```

### 3.2. Python fayllar soni

```powershell
(Get-ChildItem -Recurse -Force -File -Filter *.py -ErrorAction SilentlyContinue).Count
```

### 3.3. Testlar soni

```powershell
# Test fayllar soni
(Get-ChildItem -Recurse -Force -File -Filter "test_*.py" -ErrorAction SilentlyContinue).Count

# Yoki pytest orqali aniq test soni
python -m pytest --collect-only -q
```

### 3.4. Kod qatorlari soni

```powershell
$lines = 0
Get-ChildItem -Recurse -Force -File -Filter *.py -ErrorAction SilentlyContinue | ForEach-Object {
    $lines += (Get-Content -LiteralPath $_.FullName -ErrorAction SilentlyContinue | Measure-Object -Line).Lines
}
"Python kod qatorlari: $lines"
```

### 3.5. Eng katta papkalar (top 10)

```powershell
Get-ChildItem -Force -Directory | ForEach-Object {
    $s = (Get-ChildItem -Recurse -Force -File $_.FullName -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    [PSCustomObject]@{ Papka = $_.Name; MB = [math]::Round($s / 1MB, 2) }
} | Sort-Object MB -Descending | Select-Object -First 10 | Format-Table -AutoSize
```

---

## 4️⃣ Qadamma-qadam ko'rsatma

### 🗑️ Nima o'chirish kerak?

| O'chirish | Sabab |
|---|---|
| `.venv/`, `venv/` | Virtual muhit — qayta yaratiladi |
| `node_modules/` | Frontend deps — bot uchun kerak emas |
| `__pycache__/`, `*.pyc` | Python kesh — avtomatik qayta yaratiladi |
| `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/` | Vosita keshlari |
| `data/`, `logs/`, `tmp/` | Runtime ma'lumotlar |
| `*.mp4`, `*.mkv`, `*.log` | Vaqtinchalik video/log fayllar |
| `chat_*.md` | Chat eksport fayllari |

### 💾 Nima saqlash kerak?

| Saqlash | Sabab |
|---|---|
| `app/`, `tests/`, `migrations/`, `src/`, `public/` | Asosiy kod |
| `requirements.txt`, `package.json` | Bog'liqliklar ro'yxati |
| `Dockerfile`, `docker-compose.yml`, `railway.toml`, `railway.worker.toml`, `nixpacks.toml` | Deploy konfiguratsiyasi |
| `.env.example` | Namuna konfiguratsiya (`.env` EMAS!) |
| `.gitignore`, `.dockerignore` | Ignore qoidalari |
| `alembic.ini`, `pytest.ini`, `README.md` | Konfiguratsiya va hujjat |

### 🚀 Railway'ga push qilish

```powershell
# 1. Holatni tekshirish
git status

# 2. Keraksiz fayllar kuzatilmayotganiga ishonch hosil qilish
git ls-files | Select-String -Pattern "\.venv|node_modules|__pycache__|\.pytest_cache"

# 3. O'zgarishlarni qo'shish
git add .gitignore
git add -A

# 4. Commit qilish
git commit -m "chore: clean up project and harden .gitignore"

# 5. Push qilish (Railway avtomatik deploy qiladi)
git push origin main
```

> ⚠️ **Diqqat:** `.env` faylini HECH QACHON commit qilmang! U `.gitignore` da.

### ✅ Tozalashdan keyin loyiha ishlashini tekshirish

```powershell
# 1. Virtual muhitni faollashtirish
.\.venv\Scripts\Activate.ps1

# 2. Importlar to'g'riligini tekshirish
python -c "import app.bot; print('Import OK')"

# 3. Barcha testlarni ishga tushirish
python -m pytest -q

# 4. Botni ishga tushirish (test rejimida)
python -m app.bot
```

---

## ⚠️ Muhim eslatmalar

1. **Mavjud kodni BUZMANG** — faqat keraksiz fayllarni o'chiring.
2. **`.env` faylini saqlang** — u maxfiy ma'lumotlarni o'z ichiga oladi.
3. **`git rm --cached`** — agar biror keraksiz fayl allaqachon kuzatilayotgan bo'lsa:
   ```powershell
   git rm -r --cached .venv node_modules
   git commit -m "chore: stop tracking build artifacts"
   ```
4. **Railway** — push qilgandan so'ng avtomatik deploy boshlanadi. Loglarni Railway dashboard'da kuzating.
