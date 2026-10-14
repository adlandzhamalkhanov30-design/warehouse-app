import sqlite3
import os
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
from datetime import datetime, timedelta

import hashlib

# Секретный ключ для генерации/проверки активационных кодов
_SECRET_KEY = "wh_2026_sec_a1"

def scan_barcode(callback):
    """Заглушка сканера. Пока показывает сообщение.
    Позже здесь будет подключаться реальный сканер штрихкодов."""
    from kivy.uix.popup import Popup
    from kivy.uix.label import Label
    from kivy.uix.boxlayout import BoxLayout

    content = BoxLayout(orientation='vertical', padding=dp(20))
    lbl = Label(
        text="[b]Сканер временно отключён[/b]\n\n"
             "Введите штрихкод вручную в поле поиска.",
        markup=True, halign='center', valign='middle'
    )
    lbl.bind(size=lbl.setter('text_size'))
    btn = Button(text="OK", size_hint_y=None, height=dp(50))
    popup = Popup(
        title="Сканер",
        content=content,
        size_hint=(None, None),
        size=(dp(320), dp(220))
    )
    btn.bind(on_press=popup.dismiss)
    content.add_widget(lbl)
    content.add_widget(btn)
    popup.open()
    # callback вызывать не нужно — реального штрихкода нет


def validate_activation_code(code):
    """
    Проверяет активационный код.
    Формат: XXXX-XXXX-XXXX (12 символов)
    Первые 8 символов — тело, последние 4 — контрольная сумма (md5 от тела + секретного ключа).
    """
    code = code.strip().upper().replace("-", "").replace(" ", "")
    if len(code) != 12:
        return False
    body = code[:8]
    checksum = code[8:]
    expected = hashlib.md5((body + _SECRET_KEY).encode()).hexdigest()[:4].upper()
    return checksum == expected

def is_premium_active():
    """Проверяет, активирована ли премиум-подписка"""
    return get_setting('premium', '0') == '1'

def activate_premium(code):
    """Проверяет код и, если верный, активирует премиум в базе"""
    if validate_activation_code(code):
        set_setting('premium', '1')
        return True
    return False
# Архивация — встроена прямо в этот файл

# --- Функция для правильного пути к БД (универсально для Android) ---
def get_db_path():
    from kivy.app import App
    app = App.get_running_app()
    return os.path.join(app.user_data_dir, "business.db")

def get_archive_path():
    from kivy.app import App
    app = App.get_running_app()
    return os.path.join(app.user_data_dir, "archive.db")

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
def init_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            barcode TEXT DEFAULT '',
            purchase_price REAL DEFAULT 0,
            sale_price REAL DEFAULT 0,
            quantity INTEGER DEFAULT 0,
            shelf_life INTEGER DEFAULT 7,
            lead_time_days INTEGER DEFAULT 3
        )
    """)

    # Если таблица уже существует без lead_time_days — добавляем колонку
    try:
        c.execute("ALTER TABLE products ADD COLUMN lead_time_days INTEGER DEFAULT 3")
    except:
        pass  # колонка уже есть

    c.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL DEFAULT 0,
            date TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS open_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            added_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_archive_date', ?)",
              (datetime.now().strftime("%Y-%m-%d"),))
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('premium', '0')")

    conn.commit()
    conn.close()

def auto_archive():
    """Переносит операции старше 3 месяцев в archive.db"""
    db_path = get_db_path()
    archive_path = get_archive_path()

    conn_main = sqlite3.connect(db_path)
    c_main = conn_main.cursor()

    c_main.execute("SELECT value FROM settings WHERE key = 'last_archive_date'")
    row = c_main.fetchone()
    if not row:
        conn_main.close()
        return

    last_date = datetime.strptime(row[0], "%Y-%m-%d")
    if (datetime.now() - last_date).days < 90:
        conn_main.close()
        return

    # Создаём архивную базу
    conn_arch = sqlite3.connect(archive_path)
    c_arch = conn_arch.cursor()
    c_arch.execute("""
        CREATE TABLE IF NOT EXISTS operations_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL,
            date TEXT NOT NULL
        )
    """)

    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")

    c_main.execute("SELECT product_id, type, quantity, price, date FROM operations WHERE date < ?", (cutoff,))
    old_ops = c_main.fetchall()

    if old_ops:
        c_arch.executemany(
            "INSERT INTO operations_archive (product_id, type, quantity, price, date) VALUES (?, ?, ?, ?, ?)",
            old_ops
        )
        c_main.execute("DELETE FROM operations WHERE date < ?", (cutoff,))
        conn_arch.commit()
        conn_main.commit()
        c_main.execute("UPDATE settings SET value = ? WHERE key = 'last_archive_date'",
                      (datetime.now().strftime("%Y-%m-%d"),))
        conn_main.commit()
        print(f"Архивация: перенесено {len(old_ops)} операций")
    else:
        c_main.execute("UPDATE settings SET value = ? WHERE key = 'last_archive_date'",
                      (datetime.now().strftime("%Y-%m-%d"),))
        conn_main.commit()

    conn_main.close()
    conn_arch.close()

def get_setting(key, default="0"):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key, value):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def get_all_products():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Добавляем lead_time_days в выборку
    c.execute("SELECT id, name, quantity, purchase_price, sale_price, shelf_life, lead_time_days FROM products ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return rows
    
def search_products(query):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    q = query.strip().lower()
    if not q:
        c.execute("""
            SELECT id, name, quantity, purchase_price, sale_price, shelf_life, lead_time_days
            FROM products ORDER BY name
        """)
        rows = c.fetchall()
        conn.close()
        return rows

    # Берём ВСЕ товары из БД
    c.execute("""
        SELECT id, name, barcode, quantity, purchase_price, sale_price, shelf_life, lead_time_days
        FROM products ORDER BY name
    """)
    all_rows = c.fetchall()
    conn.close()

    # Фильтруем в Python — .lower() корректно работает с кириллицей
    results = []
    for row in all_rows:
        name_lower = row[1].lower() if row[1] else ''
        barcode_lower = row[2].lower() if row[2] else ''
        if q in name_lower or q in barcode_lower:
            # Возвращаем без barcode, чтобы формат совпадал
            results.append((row[0], row[1], row[3], row[4], row[5], row[6], row[7]))
    return results
    
def search_products_by_barcode(barcode):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT id, name, quantity, purchase_price, sale_price, shelf_life, lead_time_days "
        "FROM products WHERE barcode = ?",
        (barcode,)
    )
    rows = c.fetchall()
    conn.close()
    return rows
    
def get_product_by_barcode(barcode):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, name FROM products WHERE barcode = ?", (barcode,))
    row = c.fetchone()
    conn.close()
    return row

def get_last_supply_date(product_id):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT date FROM operations
        WHERE product_id = ? AND type = 'in'
        ORDER BY id DESC
        LIMIT 1
    """, (product_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def add_operation(product_id, op_type, qty, price, op_date=None):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    if op_date is None:
        op_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute(
        "INSERT INTO operations (product_id, type, quantity, price, date) VALUES (?, ?, ?, ?, ?)",
        (product_id, op_type, qty, price, op_date)
    )

    if op_type in ("out", "defect"):
        c.execute("UPDATE products SET quantity = quantity - ? WHERE id = ?", (qty, product_id))
    elif op_type == "in":
        c.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (qty, product_id))

    conn.commit()
    conn.close()

def update_product_prices(product_id, purchase_price, sale_price):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "UPDATE products SET purchase_price = ?, sale_price = ? WHERE id = ?",
        (purchase_price, sale_price, product_id)
    )
    conn.commit()
    conn.close()

def add_new_product(name, shelf_life=7, barcode='', lead_time=3):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO products (name, purchase_price, sale_price, quantity, shelf_life, barcode, lead_time_days) "
        "VALUES (?, 0, 0, 0, ?, ?, ?)",
        (name, shelf_life, barcode, lead_time)
    )
    conn.commit()
    conn.close()

def delete_product(product_id):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM operations WHERE product_id = ?", (product_id,))
    c.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()

def get_auto_lead_time(product_id, default=3):
    """Считает средний интервал между поставками в днях"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "SELECT date FROM operations WHERE product_id = ? AND type = 'in' ORDER BY date ASC",
        (product_id,)
    )
    rows = c.fetchall()
    conn.close()

    if len(rows) < 2:
        return default

    intervals = []
    for i in range(1, len(rows)):
        d1 = datetime.strptime(rows[i-1][0], "%Y-%m-%d %H:%M:%S")
        d2 = datetime.strptime(rows[i][0], "%Y-%m-%d %H:%M:%S")
        diff = (d2 - d1).total_seconds() / 86400  # в днях
        if diff > 0:
            intervals.append(diff)

    if not intervals:
        return default

    return round(sum(intervals) / len(intervals))
    
def get_avg_daily_sales(product_id, days=30):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "SELECT SUM(quantity) FROM operations WHERE product_id=? AND type='out' AND date >= ?",
        (product_id, since)
    )
    row = c.fetchone()
    conn.close()
    total = row[0] if row and row[0] else 0
    if days <= 0:
        return 0.0
    return total / days
    
def add_to_open_check(product_id, qty, price):
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "INSERT INTO open_checks (product_id, quantity, price) VALUES (?, ?, ?)",
        (product_id, qty, price)
    )
    conn.commit()
    conn.close()

def get_open_check_items():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT oc.id, oc.product_id, p.name, oc.quantity, oc.price,
               (oc.quantity * oc.price) as total
        FROM open_checks oc
        JOIN products p ON oc.product_id = p.id
    """)
    rows = c.fetchall()
    conn.close()
    return rows

def clear_open_check():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM open_checks")
    conn.commit()
    conn.close()

# ============================================================
# АНАЛИТИКА (как у X5 Group)
# ============================================================

def analytics_revenue(period_days=30):
    """Суммарная выручка за период"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "SELECT SUM(quantity * price) FROM operations WHERE type='out' AND date >= ?",
        (since,)
    )
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else 0.0

def analytics_revenue_by_day(period_days=30):
    """Выручка по дням — для графика динамики"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    c.execute("""
        SELECT DATE(date) as day, SUM(quantity * price) as rev
        FROM operations WHERE type='out' AND date >= ?
        GROUP BY day ORDER BY day
    """, (since,))
    rows = c.fetchall()
    conn.close()
    return rows

def analytics_avg_check(period_days=30):
    """Средний чек: выручка / количество чеков (операций продаж)"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "SELECT SUM(quantity * price), COUNT(*) FROM operations WHERE type='out' AND date >= ?",
        (since,)
    )
    row = c.fetchone()
    conn.close()
    if not row or not row[1] or row[1] == 0:
        return 0.0
    return row[0] / row[1] if row[0] else 0.0

def analytics_losses(period_days=30):
    """Потери: брак и списания за период"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        SELECT p.name, SUM(o.quantity) as qty, SUM(o.quantity * o.price) as cost
        FROM operations o
        JOIN products p ON o.product_id = p.id
        WHERE o.type='defect' AND o.date >= ?
        GROUP BY p.id ORDER BY cost DESC
    """, (since,))
    rows = c.fetchall()
    conn.close()
    return rows

def analytics_losses_total(period_days=30):
    """Сумма потерь в деньгах"""
    rows = analytics_losses(period_days)
    return sum(r[2] for r in rows if r[2])

def analytics_abc(period_days=30):
    """ABC-анализ: A — 80% выручки, B — 15%, C — 5%"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    since = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        SELECT p.id, p.name, SUM(o.quantity * o.price) as revenue
        FROM operations o
        JOIN products p ON o.product_id = p.id
        WHERE o.type='out' AND o.date >= ?
        GROUP BY p.id ORDER BY revenue DESC
    """, (since,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return []

    total = sum(r[2] for r in rows if r[2])
    if total == 0:
        return []

    result = []
    cumulative = 0
    for pid, name, rev in rows:
        cumulative += rev if rev else 0
        pct = cumulative / total * 100
        if pct <= 80:
            group = 'A'
        elif pct <= 95:
            group = 'B'
        else:
            group = 'C'
        result.append((pid, name, rev or 0, group))
    return result

def analytics_lfl(period_days=30):
    """LFL (Like-for-Like): сравнение продаж текущего периода с предыдущим"""
    current = analytics_revenue(period_days)
    # Предыдущий период — столько же дней до текущего
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    prev_start = (datetime.now() - timedelta(days=period_days * 2)).strftime("%Y-%m-%d %H:%M:%S")
    prev_end = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "SELECT SUM(quantity * price) FROM operations WHERE type='out' AND date >= ? AND date < ?",
        (prev_start, prev_end)
    )
    row = c.fetchone()
    conn.close()
    prev = row[0] if row and row[0] else 0
    if prev == 0:
        return 0.0
    return round((current - prev) / prev * 100, 1)

def analytics_forecast(product_id, days_ahead=7):
    """Прогноз продаж на основе скользящего среднего за 30 дней"""
    avg = get_avg_daily_sales(product_id, days=30)
    return round(avg * days_ahead, 1)

def analytics_turnover(product_id):
    """Оборачиваемость: сколько дней запаса осталось"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT quantity FROM products WHERE id = ?", (product_id,))
    row = c.fetchone()
    conn.close()
    qty = row[0] if row else 0
    avg = get_avg_daily_sales(product_id, days=30)
    if avg <= 0:
        return 999
    return round(qty / avg, 1)

def generate_ai_recommendations():
    """
    ИИ-аналитик: формирует текстовые рекомендации
    на основе всех метрик — как аналитик в X5
    """
    recs = []
    products = get_all_products()
    abc = analytics_abc(30)
    losses = analytics_losses(30)
    lfl = analytics_lfl(30)

    # 1. LFL динамика
    if lfl > 0:
        recs.append(("📈", f"Продажи растут: +{lfl}% к прошлому периоду. Хороший момент для расширения ассортимента."))
    elif lfl < 0:
        recs.append(("📉", f"Продажи падают: {lfl}% к прошлому периоду. Проверьте цены и акции по топ-товарам."))

    # 2. Товары на исходе
    low_stock = []
    for pid, name, qty, pp, sp, sl, lt in products:
        avg = get_avg_daily_sales(pid, 30)
        lt = get_auto_lead_time(pid)  # <-- автоматически считаем срок поставки
        if avg > 0:
            days_left = qty / avg
            if days_left <= lt + 3:
                reorder = int(avg * (lt + 7) - qty) + 1
                low_stock.append((name, int(qty), reorder, round(days_left, 1)))
    if low_stock:
        recs.append(("⚠️", f"{len(low_stock)} товаров заканчиваются. Сформируйте заказ поставщику."))
        for name, qty, reorder, days in low_stock[:3]:
            recs.append(("  └", f"{name}: остаток {qty} шт, хватит на {days} дн. → заказать {reorder} шт."))

    # 3. Просрочка
    today = datetime.now()
    expiring = []
    for pid, name, qty, pp, sp, sl, lt in products:
        if sl and sl > 0:
            expiry = today + timedelta(days=sl)
            days_to = (expiry - today).days
            if days_to <= 3 and qty > 0:
                expiring.append((name, qty, days_to))
    if expiring:
        recs.append(("⏰", f"{len(expiring)} товаров с истекающим сроком. Уцените или спишите."))
        for name, qty, days in expiring[:3]:
            recs.append(("  └", f"{name}: {qty} шт, срок истекает через {days} дн."))

    # 4. Потери
    if losses:
        total_loss_cost = sum(r[2] for r in losses if r[2])
        recs.append(("❌", f"Потери за период: {total_loss_cost:.0f} руб. Топ-брак:"))
        for name, qty, cost in losses[:3]:
            recs.append(("  └", f"{name}: {qty} шт на {cost:.0f} руб."))

    # 5. ABC — фокус на группе A
    if abc:
        group_a = [r for r in abc if r[3] == 'A']
        group_c = [r for r in abc if r[3] == 'C']
        recs.append(("🎯", f"Группа A ({len(group_a)} товаров) даёт 80% выручки. Всегда держите их в наличии."))
        if group_c:
            recs.append(("📦", f"Группа C ({len(group_c)} товаров) — 5% выручки. Рассмотрите вывод части из ассортимента."))

    # 6. Нет продаж
    no_sales = []
    for pid, name, qty, pp, sp, sl, lt in products:
        avg = get_avg_daily_sales(pid, 30)
        if avg == 0 and qty > 0:
            no_sales.append(name)
    if no_sales:
        recs.append(("🚫", f"{len(no_sales)} товаров без продаж за 30 дней: {', '.join(no_sales[:3])}..."))

    if not recs:
        recs.append(("✅", "Все показатели в норме. Нарушений не обнаружено."))

    return recs

# ============================================================
# КАРТОЧКА ТОВАРА
# ============================================================
class ItemCard(BoxLayout):
    def __init__(self, product_id, name, initial_qty, purchase_price, sale_price, shelf_life, lead_time=3, **kwargs):
        super().__init__(**kwargs)
        self.lead_time = lead_time
        # --- Рисуем рамку вокруг карточки ---
        with self.canvas.before:
            Color(0.8, 0.8, 0.8, 1)
            self.rect = Rectangle(size=self.size, pos=self.pos)
                   
        # Чтобы рамка двигалась вместе с виджетом при изменении размера
        self.bind(size=self._update_rect, pos=self._update_rect)

        self.orientation = 'vertical'
        self.padding = dp(8)
        self.spacing = dp(4)
        self.size_hint_y = None
        self.height = dp(440)
        self.product_id = product_id
        self.name = name
        self.shelf_life_days = shelf_life

        title = Label(
            text=f"[b]{name}[/b]",
            markup=True,
            size_hint_y=None,
            height=dp(40),                # было 30 → стало 40 (хватит на 2 строки)
            font_size=dp(18),
            color=(0, 0, 0, 1),
            halign='left',
            valign='middle',
            padding=(dp(8), dp(4))       # отступ слева/справа и сверху/снизу
)
        title.bind(size=title.setter('text_size'))

        price_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(45), spacing=dp(5))


        self.purchase_price_input = TextInput(
            hint_text="Цена закупки", input_filter='float',
            size_hint_y=None, height=dp(45), font_size=dp(14),
            padding=[dp(5), dp(15), dp(5), dp(15)]
        )
        if purchase_price > 0:
            self.purchase_price_input.text = str(int(purchase_price))

        self.sale_price_input = TextInput(
            hint_text="Цена продажи", input_filter='float',
            size_hint_y=None, height=dp(45), font_size=dp(14),
            padding=[dp(5), dp(15), dp(5), dp(15)]
        )
        if sale_price > 0:
            self.sale_price_input.text = str(int(sale_price))

        price_row.add_widget(self.purchase_price_input)
        price_row.add_widget(self.sale_price_input)

        self.income_input = TextInput(
            hint_text="Приход (шт)", input_filter='float',
            size_hint_y=None, height=dp(45), font_size=dp(16),
            padding=[dp(10), dp(15), dp(10), dp(15)]
        )

        # Поле для ввода количества списания
        self.write_off_input = TextInput(
            hint_text="Списать шт", input_filter='int',
            size_hint_y=None, height=dp(45), font_size=dp(16),
            padding=[dp(10), dp(15), dp(10), dp(15)]
        )

        btn_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))

        save_btn = Button(text="Записать", background_color=(0.15, 0.15, 0.15, 1), font_size=dp(15), color=(1, 1, 1, 1))
        save_btn.bind(on_press=self.on_save)

        defect_btn = Button(text="Брак", background_color=(0.7, 0.4, 0.1, 1), font_size=dp(15), color=(1, 1, 1, 1))
        defect_btn.bind(on_press=self.open_defect_popup)

        del_btn = Button(text="Удалить", background_color=(0.8, 0.2, 0.2, 1), font_size=dp(15), color=(1, 1, 1, 1))
        del_btn.bind(on_press=self.on_delete)

        btn_row.add_widget(save_btn)
        btn_row.add_widget(defect_btn)
        btn_row.add_widget(del_btn)

        self.result_label = Label(
            text=f"Остаток: {initial_qty}",
            size_hint_y=None, height=dp(30),
            color=(0, 0.6, 0, 1), font_size=dp(18), halign='left'
        )
        self.result_label.bind(size=self.result_label.setter('text_size'))

        self.margin_label = Label(
            text="", size_hint_y=None, height=dp(25),
            color=(0, 0, 0.5, 1), font_size=dp(14), halign='left'
        )
        self.margin_label.bind(size=self.margin_label.setter('text_size'))

        self.date_label = Label(
            text="-", size_hint_y=None, height=dp(25),
            color=(0.5, 0.5, 0.5, 1), font_size=dp(14), halign='left'
        )
        self.date_label.bind(size=self.date_label.setter('text_size'))
        self.supply_date_label = Label(
            text="-",
            size_hint_y=None, height=dp(25),
            color=(0.5, 0.5, 0.5, 1),
            font_size=dp(14),
            halign='left'
        )
        self.supply_date_label.bind(size=self.supply_date_label.setter('text_size'))

        self.add_widget(title)
        self.add_widget(price_row)
        self.add_widget(self.income_input)
        self.add_widget(self.write_off_input)
        self.add_widget(btn_row)
        self.add_widget(self.result_label)
        self.add_widget(self.margin_label)
        self.add_widget(self.date_label)
        self.add_widget(self.supply_date_label)

        # Показываем дату поставки сразу при создании карточки
        supply_date = get_last_supply_date(self.product_id)
        if supply_date:
            self.supply_date_label.text = f"Дата последней поставки: {supply_date}"
            self.supply_date_label.color = (0, 0, 0, 1)
        else:
            self.supply_date_label.text = "Дата поставки: не зафиксирована"
            self.supply_date_label.color = (0.5, 0.5, 0.5, 1)
            
    def _update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def on_save(self, instance):
        inc_val = self.income_input.text.replace(" ", "").replace(",", ".")
        woff_val = self.write_off_input.text.replace(" ", "").replace(",", ".")

        if not inc_val and not woff_val:
            self.result_label.text = "Введите приход или списание!"
            self.result_label.color = (0.8, 0.5, 0, 1)
            return

        try:
            income = float(inc_val) if inc_val else 0.0
            write_off = float(woff_val) if woff_val else 0.0

            pp_val = self.purchase_price_input.text.replace(" ", "").replace(",", ".")
            sp_val = self.sale_price_input.text.replace(" ", "").replace(",", ".")
            purchase_price = float(pp_val) if pp_val else 0.0
            sale_price = float(sp_val) if sp_val else 0.0

            update_product_prices(self.product_id, purchase_price, sale_price)

            if income > 0:
                add_operation(self.product_id, "in", income, purchase_price)
                self.margin_label.text = ""

            if write_off > 0:
                db_path = get_db_path()
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                c.execute("SELECT quantity FROM products WHERE id = ?", (self.product_id,))
                current_qty = c.fetchone()[0]
                conn.close()

                if write_off > current_qty:
                    self.result_label.text = f"Не хватает! Есть: {int(current_qty)}, нужно: {int(write_off)}"
                    self.result_label.color = (1, 0, 0, 1)
                    return

                add_operation(self.product_id, "defect", write_off, purchase_price)

                self.margin_label.text = f"Списано по сроку: {int(write_off)} шт."

            self.refresh_qty_display()
            self.income_input.text = ""
            self.write_off_input.text = ""

        except ValueError:
            self.result_label.text = "Вводите только числа!"
            self.result_label.color = (1, 0, 0, 1)
        except Exception as e:
            self.result_label.text = f"Ошибка: {str(e)}"
            self.result_label.color = (1, 0, 0, 1)

    def open_defect_popup(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(12))

        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT quantity FROM products WHERE id = ?", (self.product_id,))
        current_qty = c.fetchone()[0]
        conn.close()

        info_label = Label(
            text=f"[b]{self.name}[/b]\nОстаток: {int(current_qty)} шт.\n\nСколько бракованных?",
            markup=True, font_size=dp(16), halign='center', valign='middle',
            size_hint_y=None, height=dp(90)
        )
        info_label.bind(size=info_label.setter('text_size'))

        defect_input = TextInput(
            hint_text="Количество брака",
            font_size=dp(18), multiline=False,
            size_hint_y=None, height=dp(50),
            padding=[dp(10), dp(15), dp(10), dp(15)]
        )

        btn_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(50), spacing=dp(10))
        confirm_btn = Button(text="Списать брак", background_color=(0.7, 0.4, 0.1, 1), font_size=dp(16), color=(1, 1, 1, 1))
        cancel_btn = Button(text="Отмена", background_color=(0.3, 0.3, 0.3, 1), font_size=dp(16), color=(1, 1, 1, 1))

        popup = Popup(title="Учёт брака", content=content, size_hint=(None, None), size=(dp(320), dp(300)), auto_dismiss=False)

        def on_confirm(btn):
            raw = defect_input.text.strip()
            if not raw:
                return
            try:
                defect_qty = int(raw)
            except ValueError:
                return
            if defect_qty <= 0:
                return
            if defect_qty > current_qty:
                info_label.text = f"[b]{self.name}[/b]\nОстаток: {int(current_qty)} шт.\n\n[color=FF0000]Брак больше остатка![/color]"
                return

            pp_val = self.purchase_price_input.text.replace(" ", "").replace(",", ".")
            purchase_price = float(pp_val) if pp_val else 0.0
            add_operation(self.product_id, "defect", defect_qty, purchase_price)
            popup.dismiss()
            self.refresh_qty_display()
            self.margin_label.text = ""
            App.get_running_app().update_total_value()

        confirm_btn.bind(on_press=on_confirm)
        cancel_btn.bind(on_press=lambda btn: popup.dismiss())
        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)

        content.add_widget(info_label)
        content.add_widget(defect_input)
        content.add_widget(btn_row)
        popup.open()

    def refresh_qty_display(self):
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT quantity, shelf_life FROM products WHERE id = ?", (self.product_id,))
        row = c.fetchone()
        new_qty = row[0]
        shelf_life = row[1]
        conn.close()

        self.result_label.text = f"Остаток: {int(new_qty)}"
        self.result_label.color = (0, 0.6, 0, 1)
        self.date_label.text = datetime.now().strftime("%d.%m.%Y %H:%M")

        # Получаем и показываем дату последней поставки
        supply_date = get_last_supply_date(self.product_id)
        if supply_date:
            self.supply_date_label.text = f"Дата последней поставки: {supply_date}"
            self.supply_date_label.color = (0, 0, 0, 1)
        else:
            self.supply_date_label.text = "Дата поставки: не зафиксирована"
            self.supply_date_label.color = (0.5, 0.5, 0.5, 1)

        App.get_running_app().update_total_value()

    def on_delete(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        msg = Label(
            text=f"Удалить товар:\n[b]{self.name}[/b]\nВсе операции будут удалены!",
            markup=True, font_size=dp(12), halign='center', valign='middle',
            size_hint_y=None, height=dp(30)
        )
        msg.bind(size=msg.setter('text_size'))

        yes_btn = Button(text="Да, удалить", size_hint_y=None, height=dp(50), background_color=(0.8, 0.2, 0.2, 1), font_size=dp(18), color=(1, 1, 1, 1))
        no_btn = Button(text="Отмена", size_hint_y=None, height=dp(50), background_color=(0.3, 0.3, 0.3, 1), font_size=dp(18), color=(1, 1, 1, 1))

        popup = Popup(title="Подтверждение", content=content, size_hint=(None, None), size=(dp(320), dp(240)), auto_dismiss=False)

        yes_btn.bind(on_press=lambda btn: [delete_product(self.product_id), App.get_running_app().populate_cards(), popup.dismiss()])
        no_btn.bind(on_press=lambda btn: popup.dismiss())

        content.add_widget(msg)
        content.add_widget(yes_btn)
        content.add_widget(no_btn)
        popup.open()

        content = BoxLayout(orientation='vertical')

# ============================================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# ============================================================
class WarehouseApp(App):    
    def build(self):
        print("3. Запуск build()")
        init_db()
        auto_archive()
        print("4. База инициализирована")
        Window.clearcolor = (1, 1, 1, 1)
        main_layout = BoxLayout(orientation='vertical')

        # --- Строка 1: Кнопки управления ---
        top_buttons = BoxLayout(
            size_hint_y=None, height=dp(45),
            padding=dp(6), spacing=dp(6)
        )

        add_btn = Button(text="+ Товар", background_color=(0.2, 0.6, 0.2, 1), font_size=dp(14), color=(1, 1, 1, 1))
        add_btn.bind(on_press=self.open_add_product_popup)

        sell_btn = Button(text="Продажа", background_color=(0.8, 0.4, 0.2, 1), font_size=dp(14), color=(1, 1, 1, 1))
        sell_btn.bind(on_press=self.open_sale_screen)

        # Кнопка аналитика / премиум
        if is_premium_active():
            analytics_btn = Button(text="📊 Аналитика", background_color=(0.5, 0.2, 0.7, 1), font_size=dp(14), color=(1, 1, 1, 1))
            analytics_btn.bind(on_press=self.open_analytics_popup)
        else:
            analytics_btn = Button(text="⭐ Premium", background_color=(0.9, 0.7, 0.1, 1), font_size=dp(14), color=(1, 1, 1, 1))
            analytics_btn.bind(on_press=self.open_premium_popup)

        top_buttons.add_widget(add_btn)
        top_buttons.add_widget(sell_btn)
        top_buttons.add_widget(analytics_btn)
        main_layout.add_widget(top_buttons)

        # --- Строка 2: Поле поиска + сканер + кнопка «Найти» ---
        search_row = BoxLayout(
            size_hint_y=None, height=dp(55),
            padding=dp(8), spacing=dp(6)
        )

        self.search_input = TextInput(hint_text="Название или штрихкод", size_hint_y=None, height=dp(50))
# ВАЖНО: Привязываем изменение текста к нашему обработчику
        self.search_input.bind(text=self.on_search_text) 

        scan_search_btn = Button(
            text="Сканер",
            size_hint_x=None, width=dp(55),
            background_color=(0.2, 0.5, 0.8, 1),
            font_size=dp(14), color=(1, 1, 1, 1)
        )

        search_btn = Button(
            text="Найти",
            size_hint_x=None, width=dp(50),
            background_color=(0.2, 0.6, 0.8, 1),
            font_size=dp(14), color=(1, 1, 1, 1)
        )
        search_btn.bind(on_press=self.perform_search)

        search_row.add_widget(self.search_input)
        search_row.add_widget(scan_search_btn)
        search_row.add_widget(search_btn)
        main_layout.add_widget(search_row)

        # Заголовок
        title = Label(
            text="[b]Склад: Учёт товаров[/b]",
            size_hint_y=None, height=dp(40),
            font_size=dp(20), color=(0, 0, 0, 1), markup=True, halign='center'
        )
        title.bind(size=title.setter('text_size'))
        main_layout.add_widget(title)

        # Итоговые показатели
        self.total_label = Label(text="Всего на складе: 0 шт.", size_hint_y=None, height=dp(35), font_size=dp(16), color=(0, 0.5, 0, 1), halign='center')
        self.total_label.bind(size=self.total_label.setter('text_size'))
        main_layout.add_widget(self.total_label)

        self.value_label = Label(text="Сумма товара: 0", size_hint_y=None, height=dp(35), font_size=dp(16), color=(0, 0, 0.5, 1), halign='center')
        main_layout.add_widget(self.value_label)

        # Область с карточками товаров (ScrollView + BoxLayout)
        scroll = ScrollView(size_hint=(1, 1))
        self.cards_container = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(50))
        self.cards_container.size_hint_y = None
        self.cards_container.bind(minimum_height=self.cards_container.setter('height'))
        scroll.add_widget(self.cards_container)
        main_layout.add_widget(scroll)

        # Первоначальная загрузка товаров и подсчёт итогов
        self.populate_cards()
        self.update_total_value()

        return main_layout

    def on_search_text(self, instance, value):
        """Вызывается при каждом изменении текста в поле поиска"""
        self.refresh_search(value)

    def refresh_search(self, query=""):
        """Очищает список и загружает товары согласно запросу поиска"""
        self.cards_container.clear_widgets()
        self.cards_container.height = 0
        
        # Используем функцию поиска из БД, а не get_all_products
        products = search_products(query)

        if not products:
            # Если поиск дал 0 результатов, показываем заглушку (опционально)
            # Или оставляем пустым, если хочешь, чтобы список просто исчезал
            empty_label = Label(
                text=f"[b]Ничего не найдено[/b]\n\nПопробуйте другой запрос.",
                markup=True, font_size=dp(18), color=(0.5, 0.5, 0.5, 1),
                halign='center', valign='middle', size_hint_y=None, height=dp(200)
            )
            empty_label.bind(size=empty_label.setter('text_size'))
            self.cards_container.add_widget(empty_label)
            self.cards_container.height = dp(200)
            self.update_total_value()
            return

        for pid, name, qty, pp, sp, shelf_life, lt in products:
            card = ItemCard(pid, name, qty, pp, sp, shelf_life, lt)
            self.cards_container.add_widget(card)

        # Минимальная высота контейнера должна учитывать все карточки
        self.cards_container.height = self.cards_container.minimum_height
        self.update_total_value()

        # --- Методы для поиска (обязательно должны быть в классе) ---

    def on_barcode_scanned(self, barcode):
        """Обрабатывает штрихкод, распознанный сканером"""
        # Если открыт экран продажи — добавляем товар в чек
        if hasattr(self, 'sale_popup') and self.sale_popup:
            self.sale_search_input.text = barcode
            self.process_sale_scan(self.sale_search_input)
        # Если открыто окно добавления товара — подставляем в поле штрихкода
        elif hasattr(self, 'barcode_input') and self.barcode_input:
            self.barcode_input.text = barcode
            self.on_barcode_scanned_in_add(barcode)
        # Иначе — ищем на главном экране
        else:
            self.search_input.text = barcode
            self.perform_search(None)

    def perform_search(self, instance):
        query = self.search_input.text.strip()

        if not query:
            products = get_all_products()
        elif len(query) in (8, 13) and query.isdigit():
            products = search_products_by_barcode(query)
        else:
            products = search_products(query)

        self.cards_container.clear_widgets()
        for row in products:
            pid, name, qty, pp, sp, sl, lt = row
            card = ItemCard(pid, name, qty, pp, sp, sl, lt)
            self.cards_container.add_widget(card)

        self.cards_container.height = self.cards_container.minimum_height
        self.update_total_value()

    def populate_cards(self):
        self.cards_container.clear_widgets()
        self.cards_container.height = 0
        products = get_all_products()

        if not products:
            empty_label = Label(
                text="[b]Список товаров пуст[/b]\n\nНажмите «+ Товар», чтобы добавить.",
                markup=True, font_size=dp(18), color=(0.5, 0.5, 0.5, 1),
                halign='center', valign='middle', size_hint_y=None, height=dp(200)
            )
            empty_label.bind(size=empty_label.setter('text_size'))
            self.cards_container.add_widget(empty_label)
            self.cards_container.height = dp(200)
            self.update_total_value()
            return

        for pid, name, qty, pp, sp, shelf_life, lt in products:
            card = ItemCard(pid, name, qty, pp, sp, shelf_life, lt)
            self.cards_container.add_widget(card)

        self.cards_container.height = self.cards_container.minimum_height
        self.update_total_value()

    def update_total_value(self):
        products = get_all_products()
        total_qty = 0
        total_value = 0.0
        for row in products:
            _, _, qty, pp, sp, _, _ = row
            total_qty += qty
            total_value += qty * sp
        self.total_label.text = f"Всего на складе: {total_qty} шт."
        self.value_label.text = f"Сумма товара: {total_value:.2f}"

    def save_new_product(self, instance):
        name = self.name_input.text.strip()
        shelf_str = self.shelf_input.text.strip()
        barcode = self.barcode_input.text.strip()

        if not name:
            # Можно показать всплывающее сообщение или просто вернуть
            return

        shelf_life = 7  # Значение по умолчанию
        if shelf_str.isdigit():
            shelf_life = int(shelf_str)

        # Вызываем существующую функцию добавления
        add_new_product(name, shelf_life=shelf_life, barcode=barcode)

        # Обновляем интерфейс
        self.populate_cards()
        self.update_total_value()

        # Закрываем попап
        if hasattr(self, 'add_product_popup') and self.add_product_popup:
            self.add_product_popup.dismiss()
       
    def open_add_product_popup(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(12))

        # Поле названия
        self.name_input = TextInput(
            hint_text="Название товара",
            size_hint_y=None, height=dp(45), font_size=dp(16)
        )

        # Поле штрихкода
        self.barcode_input = TextInput(
            hint_text="Штрихкод (опционально)",
            size_hint_y=None, height=dp(45), font_size=dp(16)
        )

        # Строка со сканером
        barcode_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        scan_btn = Button(text="🔍 Сканер", size_hint_x=None, width=dp(120),
                          background_color=(0.2, 0.5, 0.8, 1), font_size=dp(14), color=(1, 1, 1, 1))
        barcode_row.add_widget(self.barcode_input)
        barcode_row.add_widget(scan_btn)
        content.add_widget(barcode_row)

        # Срок годности
        self.shelf_input = TextInput(
            hint_text="Срок хранения (дни, по умолчанию 7)",
            input_filter='int',
            size_hint_y=None, height=dp(45), font_size=dp(16)
        )

        btn_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        save_btn = Button(text="Сохранить", background_color=(0.2, 0.6, 0.2, 1),
                          font_size=dp(16), color=(1, 1, 1, 1))
        cancel_btn = Button(text="Отмена", background_color=(0.3, 0.3, 0.3, 1),
                            font_size=dp(16), color=(1, 1, 1, 1))

        popup = Popup(title="Добавить товар", content=content, size_hint=(None, None),
                      size=(dp(340), dp(420)), auto_dismiss=False)

        def on_save(*args):
            name = self.name_input.text.strip()
            shelf_str = self.shelf_input.text.strip()
            barcode = self.barcode_input.text.strip()

            if not name:
                # Можно сделать Popup с ошибкой, но пока просто выходим
                return

            shelf_life = 7
            if shelf_str.isdigit():
                shelf_life = int(shelf_str)

            add_new_product(name, shelf_life=shelf_life, barcode=barcode)
            self.populate_cards()
            self.update_total_value()
            popup.dismiss()

        save_btn.bind(on_press=on_save)
        cancel_btn.bind(on_press=popup.dismiss)

        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)

        content.add_widget(self.name_input)
        content.add_widget(self.shelf_input)
        content.add_widget(btn_row)
        popup.open()

    def open_sale_screen(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(10))

        # 1. Поле для сканера / поиска
        self.sale_search_input = TextInput(
            hint_text="Штрихкод или название...",
            font_size=dp(18),
            padding=[dp(15), dp(15), dp(15), dp(15)],
            multiline=False,
        )
        self.sale_search_input.bind(on_text_validate=self.process_sale_scan)
        content.add_widget(self.sale_search_input)

        # 2. Список товаров в чеке (ScrollView)
        scroll = ScrollView(size_hint=(1, 1))

        # --- Светлый фон для области чека ---
        with scroll.canvas.before:
            Color(0.36, 0.36, 0.36, 1)
            self._sale_scroll_bg = Rectangle(size=scroll.size, pos=scroll.pos)
        scroll.bind(
            size=lambda inst, val: setattr(self._sale_scroll_bg, 'size', val),
            pos=lambda inst, val: setattr(self._sale_scroll_bg, 'pos', val)
        )
        # ------------------------------------

        self.sale_items_container = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(8))
        self.sale_items_container.size_hint_y = None
        self.sale_items_container.bind(minimum_height=self.sale_items_container.setter('height'))
        scroll.add_widget(self.sale_items_container)
        content.add_widget(scroll)

        # 3. Итого
        self.sale_total_label = Label(
            text="Итого: 0", size_hint_y=None, height=dp(40),
            font_size=dp(22), color=(0, 0.6, 0, 1), halign='right'
        )
        content.add_widget(self.sale_total_label)

        # 4. Кнопки действий
        actions_row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(10))
        
        cancel_btn = Button(text="Отмена", background_color=(0.3, 0.3, 0.3, 1), color=(1, 1, 1, 1))
        cancel_btn.bind(on_press=self.close_sale_popup)
        
        pay_btn = Button(text="Пробить чек", background_color=(0.2, 0.6, 0.2, 1), color=(1, 1, 1, 1))
        # ИСПРАВЛЕНО: привязываем к finalize_check, который мы реализуем ниже
        pay_btn.bind(on_press=self.finalize_check)
        
        scan_in_sale_btn = Button(
            text="📷 Сканер",
            background_color=(0.2, 0.5, 0.8, 1),
            color=(1, 1, 1, 1)
        )

        actions_row.add_widget(scan_in_sale_btn)
        actions_row.add_widget(cancel_btn)
        actions_row.add_widget(pay_btn)
        content.add_widget(actions_row)

        # Создаем и открываем Popup
        self.sale_popup = Popup(
            title="Продажа",
            content=content,
            size_hint=(None, None),
            size=(Window.width * 0.95, Window.height * 0.85),
            auto_dismiss=False
        )
        self.sale_popup.open()
        
        # Сразу ставим фокус на поле ввода
        self.sale_search_input.focus = True
        
        # ВАЖНО: сразу обновляем список, чтобы показать, если там что-то осталось с прошлого раза
        self.refresh_sale_items()
        
    def process_sale_scan(self, instance):
        query = instance.text.strip()
        if not query:
            return

        results = []
        # Логика поиска
        if len(query) in (8, 13) and query.isdigit():
            results = search_products_by_barcode(query)
        else:
            results = search_products(query)

        # --- ЗАМЕНИ СТРОКУ ВЫШЕ НА ЭТОТ БЛОК ---
        
        # 1. Проверяем, что список не пуст (на случай гонки условий, хотя выше уже есть проверка)
        if not results:
            self.show_popup_message("Товар не найден!", "Ошибка")
            instance.text = ""
            return

        # 2. Берем ПЕРВЫЙ найденный товар из списка. 
        # База данных всегда возвращает список, даже если товар всего один: [(id, name, ...)]
        product = results[0]

        # 3. Теперь распаковываем данные из конкретного товара, а не из всего списка
        pid, name, qty, pp, sp, sl, lt = product
        
        # -----------------------------------------

        if qty <= 0:
            self.show_popup_message("Нет на складе!", "Внимание")
            instance.text = ""
            return

        # Добавляем ровно 1 штуку. Дальше кассир сам поменяет количество в чеке
        add_to_open_check(pid, 1.0, sp)
        
        self.refresh_sale_items()
        
        # Очищаем поле поиска и возвращаем фокус
        instance.text = ""
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: setattr(instance, 'focus', True), 0.1)

    def refresh_sale_items(self):
        self.sale_items_container.clear_widgets()
        items = get_open_check_items()
        total = 0

        for item in items:
            check_id, pid, name, qty, price, line_total = item
            total += line_total

            row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))

            # 1. Название товара
            lbl_name = Label(text=name, size_hint_x=0.5, halign='left', font_size=dp(16), color=(0,0,0,1))
            lbl_name.bind(size=lbl_name.setter('text_size'))

            # 2. РЕДАКТИРУЕМОЕ ПОЛЕ КОЛИЧЕСТВА (Вместо статичного текста)
            qty_input = TextInput(
                text=str(int(qty)), 
                input_filter='int', 
                multiline=False,
                size_hint_x=0.2, 
                halign='center', 
                font_size=dp(16),
                padding=[dp(5), dp(15), dp(5), dp(15)],
                background_color=(1, 1, 1, 0.1) # Полупрозрачный фон, чтобы выглядело аккуратно
            )
            # Сохраняем данные прямо в виджете, чтобы знать, что обновлять
            qty_input.check_id = check_id
            qty_input.product_id = pid
            qty_input.price = price
            
            # При изменении текста сразу обновляем базу и сумму
            qty_input.bind(text=self.on_qty_changed)

            # Ссылка на лейбл суммы, чтобы обновлять его мгновенно без полного перерисовки
            # Мы передадим его позже, но для простоты пока будем пересчитывать итог полностью
            
            # 3. Сумма строки
            lbl_sum = Label(text=f"{int(line_total)} ₽", size_hint_x=0.2, halign='right', font_size=dp(16), color=(0,0.6,0,1))
            # Сохраняем ссылку на лейбл суммы внутри инпута, чтобы обновлять только его
            qty_input.sum_label = lbl_sum 

            # 4. Кнопка удаления
            del_btn = Button(text="X", size_hint_x=None, width=dp(40), background_color=(0.8,0.2,0.2,1), color=(1,1,1,1), font_size=dp(14))
            del_btn.check_id = check_id
            del_btn.bind(on_press=self.remove_from_sale)

            row.add_widget(lbl_name)
            row.add_widget(qty_input)
            row.add_widget(lbl_sum)
            row.add_widget(del_btn)
            self.sale_items_container.add_widget(row)

        self.sale_total_label.text = f"Итого: {int(total)} ₽"
        self.sale_items_container.height = self.sale_items_container.minimum_height
        
    def on_qty_changed(self, instance, value):
        try:
            new_qty = int(value) if value else 0
            check_id = instance.check_id
            price = instance.price

            # Обновляем БД
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("UPDATE open_checks SET quantity = ? WHERE id = ?", (new_qty, check_id))
            conn.commit()
            conn.close()

            # Обновляем сумму строки
            instance.sum_label.text = str(int(new_qty * price))

            # Пересчитываем ИТОГ без перерисовки (чтобы не было цикла)
            items = get_open_check_items()
            total = sum(item[5] for item in items)
            self.sale_total_label.text = f"Итого: {int(total)} ₽"

        except ValueError:
            pass

    def remove_from_sale(self, instance):
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("DELETE FROM open_checks WHERE id = ?", (instance.check_id,))
        conn.commit()
        conn.close()
        self.refresh_sale_items()

    def finalize_check(self, instance=None):
        """ИСПРАВЛЕНО: переименовано из finalize_sale и вынесено из другого метода"""
        items = get_open_check_items()
        if not items:
            self.show_popup_message("Чек пуст!", "Внимание")
            return

        for item in items:
            check_id, pid, name, qty, price, line_total = item
            add_operation(pid, "out", qty, price)

        clear_open_check()
        self.populate_cards()
        self.update_total_value()
        self.refresh_sale_items()
        self.show_popup_message("Чек пробит!", "Успех")
        self.close_sale_popup()

    def close_sale_popup(self, instance=None):
        """ИСПРАВЛЕНО: вынесено из finalize_sale, теперь это отдельный метод класса"""
        if hasattr(self, 'sale_popup') and self.sale_popup:
            self.sale_popup.dismiss()
            self.sale_popup = None

    def show_popup_message(self, message, title="Сообщение"):
        """ИСПРАВЛЕНО: вынесено из finalize_sale, теперь это отдельный метод класса"""
        popup_content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(15))
        lbl = Label(text=message, font_size=dp(18), halign='center', valign='middle', size_hint_y=None, height=dp(80), color=(1,1,1,1))
        lbl.bind(size=lbl.setter('text_size'))
        
        btn = Button(text="OK", size_hint_y=None, height=dp(50), background_color=(0.2, 0.6, 0.2, 1), color=(1,1,1,1))
        
        popup = Popup(title=title, content=popup_content, size_hint=(None, None), size=(dp(350), dp(250)), auto_dismiss=False)
        btn.bind(on_press=popup.dismiss)
        
        popup_content.add_widget(lbl)
        popup_content.add_widget(btn)
        popup.open()

    def open_premium_popup(self, instance):
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(25))

        info_label = Label(
            text="[b]Premium-аналитика[/b]\n\n"
                 "• Прогноз дефицита и рекомендация к заказу\n"
                 "• Топ проблемных позиций (брак, просрочка)\n"
                 "• Динамика продаж и средний чек\n"
                 "• ABC‑анализ и оборачиваемость товаров\n\n"
                 "Введите код активации:",
            markup=True, font_size=dp(16), halign='center', valign='middle',
            size_hint_y=None, height=dp(220), color=(0, 0, 0, 1)
        )
        info_label.bind(size=info_label.setter('text_size'))

        code_input = TextInput(
            hint_text="XXXX-XXXX-XXXX",
            font_size=dp(20), multiline=False,
            size_hint_y=None, height=dp(55),
            padding=[dp(15), dp(15), dp(15), dp(15)],
            halign='center',
            background_color=(1, 1, 1, 1),
            foreground_color=(0, 0, 0, 1),
            hint_text_color=(0.5, 0.5, 0.5, 1)
        )

        btn_row = BoxLayout(size_hint_y=None, height=dp(55), spacing=dp(10))

        cancel_btn = Button(text="Отмена", background_color=(0.3, 0.3, 0.3, 1), font_size=dp(16), color=(1, 1, 1, 1))
        activate_btn = Button(text="Активировать", background_color=(0.2, 0.6, 0.2, 1), font_size=dp(16), color=(1, 1, 1, 1))

        # Создаем Popup
        popup = Popup(title="Premium-подписка", content=content,
                      size_hint=(None, None), size=(dp(360), dp(420)), 
                      auto_dismiss=False)

        # === ГЛАВНОЕ ИЗМЕНЕНИЕ: Убираем картинку фона и красим в белый ===
        popup.background = ''  # Убираем стандартную серую картинку
        with popup.canvas.before:
            Color(1, 1, 1, 1)  # Чисто белый цвет (R, G, B, Alpha)
            self._rect_popup = Rectangle(pos=popup.pos, size=popup.size)
        
        # Привязываем перерисовку прямоугольника при изменении размера/позиции
        popup.bind(pos=lambda instance, value: setattr(self._rect_popup, 'pos', value),
                   size=lambda instance, value: setattr(self._rect_popup, 'size', value))
        # =================================================================

        def on_activate(btn):
            code = code_input.text.strip()
            if activate_premium(code):
                popup.dismiss()
                self.show_popup_message("Premium активирована! Перезапустите приложение.", "Успех!")
            else:
                code_input.text = ""
                self.show_popup_message("Неверный код. Проверьте ввод.", "Ошибка")

        cancel_btn.bind(on_press=lambda btn: popup.dismiss())
        activate_btn.bind(on_press=on_activate)

        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(activate_btn)

        content.add_widget(info_label)
        content.add_widget(code_input)
        content.add_widget(btn_row)
        popup.open()

    def open_analytics_popup(self, instance):
        if not is_premium_active():
            self.open_premium_popup(instance)
            return

        content = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(8))

        scroll = ScrollView(size_hint=(1, 1))
        report = BoxLayout(orientation='vertical', padding=dp(5), spacing=dp(15))
        report.size_hint_y = None
        report.bind(minimum_height=report.setter('height'))

        # === СВОДКА ===
        rev = analytics_revenue(30)
        avg_check = analytics_avg_check(30)
        losses_total = analytics_losses_total(30)
        lfl = analytics_lfl(30)
        stock_value = sum(row[2] * row[4] for row in get_all_products())

        lfl_text = f"+{lfl}%" if lfl >= 0 else f"{lfl}%"
        lfl_color = (0, 0.6, 0, 1) if lfl >= 0 else (0.8, 0.2, 0.2, 1)

        summary = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(170), padding=dp(10), spacing=dp(6))
        with summary.canvas.before:
            Color(0.93, 0.95, 1.0, 1)
            Rectangle(size=summary.size, pos=summary.pos)
        summary.bind(pos=lambda i, v: setattr(summary.canvas.children[0], 'pos', v),
                    size=lambda i, v: setattr(summary.canvas.children[0], 'size', v))

        lbl1 = Label(text=f"[b]Выручка (30 дн):[/b] {rev:.0f} руб.", markup=True, font_size=dp(15), color=(0, 0, 0.5, 1), size_hint_y=None, height=dp(30), halign='left')
        lbl1.bind(size=lbl1.setter('text_size'))

        lbl2 = Label(text=f"[b]Средний чек:[/b] {avg_check:.0f} руб.", markup=True, font_size=dp(15), color=(0, 0, 0.5, 1), size_hint_y=None, height=dp(30), halign='left')
        lbl2.bind(size=lbl2.setter('text_size'))

        lfl_str = f"[color={lfl_color[0]:.2f},{lfl_color[1]:.2f},{lfl_color[2]:.2f},1]{lfl_text}[/color]"
        lbl3 = Label(text=f"[b]LFL динамика:[/b] {lfl_str}", markup=True, font_size=dp(15), color=(0, 0, 0.5, 1), size_hint_y=None, height=dp(30), halign='left')
        lbl3.bind(size=lbl3.setter('text_size'))

        lbl4 = Label(text=f"[b]Потери (30 дн):[/b] {losses_total:.0f} руб.", markup=True, font_size=dp(15), color=(0.8, 0.2, 0.2, 1), size_hint_y=None, height=dp(30), halign='left')
        lbl4.bind(size=lbl4.setter('text_size'))

        lbl5 = Label(text=f"[b]Запас на складе:[/b] {stock_value:.0f} руб.", markup=True, font_size=dp(15), color=(0, 0.5, 0, 1), size_hint_y=None, height=dp(30), halign='left')
        lbl5.bind(size=lbl5.setter('text_size'))

        summary.add_widget(lbl1)
        summary.add_widget(lbl2)
        summary.add_widget(lbl3)
        summary.add_widget(lbl4)
        summary.add_widget(lbl5)
        report.add_widget(summary)

        # === ИИ-РЕКОМЕНДАЦИИ ===
        recs = generate_ai_recommendations()
        recs_header = Label(text="[b]Рекомендации ИИ-аналитика[/b]", markup=True, font_size=dp(16), color=(0.5, 0.2, 0.7, 1), size_hint_y=None, height=dp(30), halign='left')
        recs_header.bind(size=recs_header.setter('text_size'))
        report.add_widget(recs_header)

        for icon, text in recs:
            rec_label = Label(text=f"{icon} {text}", font_size=dp(13), color=(0.2, 0.2, 0.2, 1), size_hint_y=None, height=dp(28), halign='left', text_size=(dp(340), None))
            rec_label.bind(size=rec_label.setter('text_size'))
            report.add_widget(rec_label)

        # === ABC-АНАЛИЗ ===
        abc = analytics_abc(30)
        if abc:
            abc_header = Label(text="[b]ABC-анализ по выручке[/b]", markup=True, font_size=dp(16), color=(0, 0, 0.5, 1), size_hint_y=None, height=dp(30), halign='left')
            abc_header.bind(size=abc_header.setter('text_size'))
            report.add_widget(abc_header)

            for pid, name, rev_val, group in abc[:10]:
                gc = {'A': (0, 0.6, 0, 1), 'B': (0.8, 0.6, 0, 1), 'C': (0.8, 0.3, 0.3, 1)}.get(group, (0, 0, 0, 1))
                abc_row = Label(text=f"[{group}] {name} — {rev_val:.0f} руб.", markup=True, font_size=dp(13), color=gc, size_hint_y=None, height=dp(25), halign='left')
                abc_row.bind(size=abc_row.setter('text_size'))
                report.add_widget(abc_row)

        # === КАРТОЧКИ ТОВАРОВ ===
        cards_header = Label(text="[b]Детальный анализ товаров[/b]", markup=True, font_size=dp(16), color=(0, 0, 0.5, 1), size_hint_y=None, height=dp(30), halign='left')
        cards_header.bind(size=cards_header.setter('text_size'))
        report.add_widget(cards_header)

        for row in get_all_products():
            pid, name, qty, pp, sp, shelf_life, lead_time = row
            avg_daily = get_avg_daily_sales(pid, days=30)
            lead_time = get_auto_lead_time(pid)
            days_left = qty / avg_daily if avg_daily > 0 else 999
            forecast = analytics_forecast(pid, 7)
            turnover = analytics_turnover(pid)

            today = datetime.now()
            expiry_date = today + timedelta(days=shelf_life) if shelf_life else today
            days_to_expiry = (expiry_date - today).days

            status_parts = []
            status_color = (0, 0.6, 0, 1)

            if days_to_expiry <= 0 and qty > 0:
                status_parts.append("ПРОСРОЧЕНО")
                status_color = (1, 0.2, 0.2, 1)
            elif days_to_expiry <= 3 and qty > 0:
                status_parts.append(f"Срок ({days_to_expiry} дн.)")
                status_color = (1, 0.6, 0, 1)

            if avg_daily > 0 and days_left <= lead_time + 3:
                reorder = int(avg_daily * (lead_time + 7) - qty) + 1
                if reorder > 0:
                    status_parts.append(f"Заказать {reorder} шт.")
                    if status_color == (0, 0.6, 0, 1):
                        status_color = (1, 0.4, 0.2, 1)

            if avg_daily == 0 and qty > 0:
                status_parts.append("Нет продаж 30 дн.")
                status_color = (0.6, 0.6, 0.6, 1)

            if not status_parts:
                status_parts.append("В норме")

            status_text = " | ".join(status_parts)

            card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(100), padding=dp(8), spacing=dp(4))
            with card.canvas.before:
                Color(0.95, 0.95, 0.95, 1)
                Rectangle(size=card.size, pos=card.pos)
            card.bind(pos=lambda i, v, c=card: setattr(c.canvas.children[0], 'pos', v),
                      size=lambda i, v, c=card: setattr(c.canvas.children[0], 'size', v))

            nl = Label(text=f"[b]{name}[/b]", markup=True, font_size=dp(15), color=(0, 0, 0, 1), size_hint_y=None, height=dp(25), halign='left')
            nl.bind(size=nl.setter('text_size'))

            il = Label(text=f"Остаток: {qty} | Прод/день: {avg_daily:.1f} | Хватит: {turnover:.0f} дн.", font_size=dp(12), color=status_color, size_hint_y=None, height=dp(22), halign='left')
            il.bind(size=il.setter('text_size'))

            dl = Label(text=f"Прогноз 7 дн: {forecast:.0f} шт. | {status_text}", font_size=dp(12), color=(0.5, 0.5, 0.5, 1), size_hint_y=None, height=dp(22), halign='left')
            dl.bind(size=dl.setter('text_size'))

            card.add_widget(nl)
            card.add_widget(il)
            card.add_widget(dl)
            report.add_widget(card)

        scroll.add_widget(report)
        content.add_widget(scroll)

        close_btn = Button(text="Закрыть", size_hint_y=None, height=dp(50), background_color=(0.3, 0.3, 0.3, 1), font_size=dp(16), color=(1, 1, 1, 1))
        popup = Popup(title="ИИ-Аналитика склада", content=content, size_hint=(None, None), size=(dp(380), dp(600)), auto_dismiss=False)
        close_btn.bind(on_press=lambda btn: popup.dismiss())
        content.add_widget(close_btn)
        popup.open()

if __name__ == '__main__':
    WarehouseApp().run()
