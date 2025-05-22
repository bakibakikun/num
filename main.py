import logging
import sys
import uuid
import psycopg2
import hashlib
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
from urllib.parse import urlencode
import asyncio
import os
from config import fetch_bot_settings

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
log = logging.getLogger(__name__)
log.info("Запуск бота подписки")

# Определение путей и базы данных
PAYMENT_STORE = "/store_payment"
YOOMONEY_HOOK = "/yoomoney_hook"
COINREMITTER_HOOK = "/coinremitter_hook"
HEALTH_CHECK = "/status"
WEBHOOK_BASE = "/bot_hook"
DB_URL = "postgresql://postgres.iylthyqzwovudjcyfubg:Alex4382!@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
BASE_URL = os.getenv("HOST_URL", "https://short-blinnie-bakibakikun-a88f041b.koyeb.app")
COINREMITTER_API_KEY_TCN = os.getenv("wkey_pyCGnCVlrawGdKl")
COINREMITTER_PASSWORD_TCN = os.getenv("Lemon333")

# Окружение
ENV = "koyeb"
log.info(f"Платформа: {ENV}")

# Загрузка конфигураций ботов
SETTINGS = fetch_bot_settings()
log.info(f"Настройка {len(SETTINGS)} ботов")
bot_instances = {}
dispatchers = {}

for bot_key, cfg in SETTINGS.items():
    try:
        log.info(f"Инициализация бота {bot_key}")
        bot_instances[bot_key] = Bot(token=cfg["TOKEN"])
        dispatchers[bot_key] = Dispatcher(bot_instances[bot_key])
        log.info(f"Бот {bot_key} инициализирован")
    except Exception as e:
        log.error(f"Ошибка инициализации бота {bot_key}: {e}")
        sys.exit(1)

# Инициализация базы данных
def setup_database():
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        for bot_key in SETTINGS:
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS payments_{bot_key} "
                "(label TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL, payment_type TEXT)"
            )
            cursor.execute(
                f"ALTER TABLE payments_{bot_key} ADD COLUMN IF NOT EXISTS payment_type TEXT"
            )
        conn.commit()
        conn.close()
        log.info("База данных настроена и схема обновлена")
    except Exception as e:
        log.error(f"Ошибка базы данных: {e}")
        sys.exit(1)

setup_database()

# Кнопки оплаты
def create_payment_buttons(user_id, price):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("ЮMoney", callback_data=f"yoomoney_{user_id}"))
    keyboard.add(InlineKeyboardButton("Coinremitter", callback_data=f"coinremitter_{user_id}"))
    return keyboard

# Обработчики команд
for bot_key, dp in dispatchers.items():
    @dp.message_handler(commands=["start"])
    async def initiate_payment(msg: types.Message, bot_key=bot_key):
        try:
            user_id = str(msg.from_user.id)
            chat_id = msg.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            log.info(f"[{bot_key}] Команда /start от пользователя {user_id}")

            keyboard = create_payment_buttons(user_id, cfg["PRICE"])
            welcome_msg = cfg["DESCRIPTION"].format(price=cfg["PRICE"])
            await bot.send_message(
                chat_id,
                f"{welcome_msg}\n\nВыберите способ оплаты для {cfg['PRICE']} RUB:",
                reply_markup=keyboard
            )
            log.info(f"[{bot_key}] Отправлены варианты оплаты пользователю {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка /start: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Ошибка. Попробуйте снова.")

    @dp.callback_query_handler(lambda c: c.data.startswith("yoomoney_"))
    async def handle_yoomoney_choice(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] Выбран ЮMoney пользователем {user_id}")

            payment_id = str(uuid.uuid4())
            payment_data = {
                "quickpay-form": "shop",
                "paymentType": "AC",
                "targets": f"Подписка пользователя {user_id}",
                "sum": cfg["PRICE"],
                "label": payment_id,
                "receiver": cfg["YOOMONEY_WALLET"],
                "successURL": f"https://t.me/{(await bot.get_me()).username}"
            }
            payment_link = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(payment_data)}"

            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", "yoomoney")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Сохранен платеж {payment_id} для пользователя {user_id}")

            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("Оплатить сейчас", url=payment_link))
            await bot.send_message(chat_id, "Перейдите для оплаты через ЮMoney:", reply_markup=keyboard)
            log.info(f"[{bot_key}] Ссылка ЮMoney отправлена пользователю {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка ЮMoney: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Ошибка оплаты. Попробуйте снова.")

    @dp.callback_query_handler(lambda c: c.data.startswith("coinremitter_"))
    async def handle_coinremitter_payment(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] Выбран Coinremitter (TCN) пользователем {user_id}")

            if not COINREMITTER_API_KEY_TCN or not COINREMITTER_PASSWORD_TCN:
                log.error(f"[{bot_key}] Отсутствуют ключи Coinremitter")
                await bot.send_message(chat_id, "Coinremitter не настроен. Выберите другой способ.")
                return

            payment_id = str(uuid.uuid4())
            amount = cfg["PRICE"]
            log.info(f"[{bot_key}] Создание Coinremitter инвойса: amount={amount}, currency=RUB, coin=TCN")

            headers = {"Accept": "application/json"}
            payload = {
                "api_key": COINREMITTER_API_KEY_TCN,
                "password": COINREMITTER_PASSWORD_TCN,
                "amount": amount,
                "fiat_currency": "RUB",
                "currency": "TCN",
                "notify_url": f"{BASE_URL}{COINREMITTER_HOOK}/{bot_key}",
                "name": f"Подписка пользователя {user_id}",
                "custom_data1": payment_id,
                "expire_time_in_minutes": 30
            }
            response = requests.post(
                "https://coinremitter.com/api/v3/TCN/create-invoice",
                headers=headers,
                data=payload
            )
            result = response.json()
            if result.get("flag") != 1:
                log.error(f"[{bot_key}] Ошибка создания инвойса: {result}")
                await bot.send_message(chat_id, "Ошибка создания платежа. Попробуйте снова.")
                return

            invoice_url = result["data"]["url"]
            log.info(f"[{bot_key}] Инвойс создан: {invoice_url}")

            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", "coinremitter_tcn")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Сохранен Coinremitter платеж {payment_id} для пользователя {user_id}")

            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("Оплатить через криптовалюту", url=invoice_url))
            await bot.send_message(
                chat_id,
                "Оплатите через криптовалюту (TCN для теста):\nПлатеж будет подтвержден автоматически.",
                reply_markup=keyboard
            )
            log.info(f"[{bot_key}] Отправлена ссылка Coinremitter (TCN) пользователю {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка Coinremitter платежа: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Ошибка оплаты. Попробуйте снова.")

# Временный обработчик корневого пути
async def handle_root(req):
    log.info(f"[{ENV}] Запрос на корневой путь")
    return web.Response(status=200, text="OK")

# Проверка вебхука ЮMoney
def check_yoomoney_webhook(data, bot_key):
    try:
        cfg = SETTINGS[bot_key]
        params = [
            data.get("notification_type", ""),
            data.get("operation_id", ""),
            data.get("amount", ""),
            data.get("currency", ""),
            data.get("datetime", ""),
            data.get("sender", ""),
            data.get("codepro", ""),
            cfg["NOTIFICATION_SECRET"],
            data.get("label", "")
        ]
        computed_hash = hashlib.sha1("&".join(params).encode()).hexdigest()
        log.debug(f"[{bot_key}] Хэш ЮMoney: {computed_hash}, получено: {data.get('sha1_hash')}")
        return computed_hash == data.get("sha1_hash")
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка проверки ЮMoney: {e}")
        return False

# Генерация приглашения в канал
async def generate_channel_invite(bot_key, user_id):
    try:
        cfg = SETTINGS[bot_key]
        bot = bot_instances[bot_key]
        bot_member = await bot.get_chat_member(chat_id=cfg["PRIVATE_CHANNEL_ID"], user_id=(await bot.get_me()).id)
        if not bot_member.can_invite_users:
            log.error(f"[{bot_key}] У бота нет прав на создание приглашений для канала {cfg['PRIVATE_CHANNEL_ID']}")
            return None

        for _ in range(3):
            try:
                invite = await bot.create_chat_invite_link(
                    chat_id=cfg["PRIVATE_CHANNEL_ID"],
                    member_limit=1,
                    name=f"пользователь_{user_id}_доступ"
                )
                log.info(f"[{bot_key}] Создано приглашение для пользователя {user_id}: {invite.invite_link}")
                return invite.invite_link
            except Exception as e:
                log.warning(f"[{bot_key}] Не удалось создать приглашение: {e}")
                await asyncio.sleep(1)
        log.error(f"[{bot_key}] Не удалось создать приглашение для пользователя {user_id}")
        return None
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка создания приглашения: {e}")
        return None

# Поиск бота по ID платежа
def locate_bot_by_payment(payment_id):
    try:
        for bot_key in SETTINGS:
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(f"SELECT user_id FROM payments_{bot_key} WHERE label = %s", (payment_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                log.info(f"[{bot_key}] Найден платеж {payment_id}")
                return bot_key
        log.warning(f"Платеж {payment_id} не найден")
        return None
    except Exception as e:
        log.error(f"Ошибка поиска платежа: {e}")
        return None

# Обработчик вебхука ЮMoney
async def process_yoomoney_webhook(req):
    try:
        data = await req.post()
        log.info(f"[{ENV}] Вебхук ЮMoney: {dict(data)}")
        payment_id = data.get("label")
        if not payment_id:
            log.error(f"[{ENV}] Отсутствует ID платежа")
            return web.Response(status=400, text="Нет ID платежа")

        bot_key = locate_bot_by_payment(payment_id)
        if not bot_key:
            log.error(f"[{ENV}] Бот не найден для платежа {payment_id}")
            return web.Response(status=400, text="Бот не найден")

        if not check_yoomoney_webhook(data, bot_key):
            log.error(f"[{bot_key}] Неверный вебхук ЮMoney")
            return web.Response(status=400, text="Неверная подпись")

        if data.get("notification_type") in ["p2p-incoming", "card-incoming"]:
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(f"SELECT user_id FROM payments_{bot_key} WHERE label = %s", (payment_id,))
            result = cursor.fetchone()
            if result:
                user_id = result[0]
                cursor.execute(
                    f"UPDATE payments_{bot_key} SET status = %s WHERE label = %s",
                    ("success", payment_id)
                )
                conn.commit()
                bot = bot_instances[bot_key]
                await bot.send_message(user_id, "Платеж подтвержден!")
                invite = await generate_channel_invite(bot_key, user_id)
                if invite:
                    await bot.send_message(user_id, f"Присоединяйтесь к каналу: {invite}")
                    log.info(f"[{bot_key}] Обработан платеж {payment_id} для пользователя {user_id}")
                else:
                    await bot.send_message(user_id, "Ошибка приглашения. Свяжитесь с @YourSupportHandle.")
                    log.error(f"[{bot_key}] Не удалось создать приглашение для пользователя {user_id}")
            else:
                log.error(f"[{bot_key}] Платеж {payment_id} не найден")
            conn.close()
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{ENV}] Ошибка вебхука ЮMoney: {e}")
        return web.Response(status=500)

# Обработчик вебхука Coinremitter
async def process_coinremitter_webhook(req, bot_key=None):
    try:
        data = await req.json()
        log.info(f"[{bot_key or 'general'}] Вебхук Coinremitter: {data}")
        payment_id = data.get("custom_data1")
        status = data.get("status")
        currency = data.get("coin_short_name", "unknown").lower()
        if not payment_id or not status:
            log.error(f"[{bot_key or 'general'}] Отсутствуют данные Coinremitter")
            return web.Response(status=400, text="Отсутствуют данные")

        if not bot_key:
            bot_key = locate_bot_by_payment(payment_id)
            if not bot_key:
                log.error(f"[{bot_key or 'general'}] Бот не найден для платежа {payment_id}")
                return web.Response(status=400, text="Бот не найден")

        if status.lower() == "paid":
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(f"SELECT user_id FROM payments_{bot_key} WHERE label = %s", (payment_id,))
            result = cursor.fetchone()
            if result:
                user_id = result[0]
                cursor.execute(
                    f"UPDATE payments_{bot_key} SET status = %s WHERE label = %s",
                    ("success", payment_id)
                )
                conn.commit()
                bot = bot_instances[bot_key]
                await bot.send_message(user_id, f"Платеж Coinremitter ({currency.upper()}) подтвержден!")
                invite = await generate_channel_invite(bot_key, user_id)
                if invite:
                    await bot.send_message(user_id, f"Присоединяйтесь к каналу: {invite}")
                    log.info(f"[{bot_key}] Coinremitter платеж {payment_id} ({currency.upper()}) обработан для пользователя {user_id}")
                else:
                    await bot.send_message(user_id, "Ошибка приглашения. Свяжитесь с @YourSupportHandle.")
                    log.error(f"[{bot_key}] Не удалось создать приглашение для пользователя {user_id}")
            else:
                log.error(f"[{bot_key}] Платеж {payment_id} не найден")
            conn.close()
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key or 'general'}] Ошибка вебхука Coinremitter: {e}")
        return web.Response(status=200)  # Возвращаем 200 для валидации

# Обработчик хранения платежей
async def store_payment(req, bot_key):
    try:
        data = await req.json()
        payment_id = data.get("label")
        user_id = data.get("user_id")
        payment_type = data.get("payment_type", "unknown")
        log.info(f"[{bot_key}] Сохранение платежа: {payment_id} для пользователя {user_id}")
        if not payment_id or not user_id:
            log.error(f"[{bot_key}] Неполные данные платежа")
            return web.Response(status=400, text="Неполные данные")

        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (label) DO UPDATE SET user_id = %s, status = %s",
            (payment_id, user_id, "pending", payment_type, user_id, "pending")
        )
        conn.commit()
        conn.close()
        log.info(f"[{bot_key}] Платеж сохранен: {payment_id}")
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка сохранения платежа: {e}")
        return web.Response(status=500)

# Проверка состояния
async def check_status(req):
    log.info(f"[{ENV}] Проверка состояния")
    return web.Response(status=200, text=f"Активно с {len(SETTINGS)} ботами")

# Обработчик вебхука бота
async def process_bot_webhook(req, bot_key):
    try:
        if bot_key not in dispatchers:
            log.error(f"[{bot_key}] Неверный ключ бота")
            return web.Response(status=400, text="Неверный бот")

        bot = bot_instances[bot_key]
        dp = dispatchers[bot_key]
        Bot.set_current(bot)
        dp.set_current(dp)

        update = await req.json()
        log.debug(f"[{bot_key}] Данные вебхука: {update}")
        update_obj = types.Update(**update)
        asyncio.create_task(dp.process_update(update_obj))
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] Ошибка вебхука: {e}")
        return web.Response(status=500)

# Настройка вебхуков
async def configure_webhooks():
    log.info(f"Настройка вебхуков для {len(SETTINGS)} ботов")
    for bot_key in bot_instances:
        try:
            bot = bot_instances[bot_key]
            hook_url = f"{BASE_URL}{WEBHOOK_BASE}/{bot_key}"
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(hook_url)
            log.info(f"[{bot_key}] Вебхук установлен: {hook_url}")
        except Exception as e:
            log.error(f"[{bot_key}] Ошибка вебхука: {e}")
            sys.exit(1)

# Запуск сервера
async def launch_server():
    try:
        await configure_webhooks()
        log.info("Запуск сервера")
        app = web.Application()
        app.router.add_post("/", handle_root)  # Временный маршрут для /
        app.router.add_post(YOOMONEY_HOOK, process_yoomoney_webhook)
        app.router.add_post(COINREMITTER_HOOK, process_coinremitter_webhook)
        app.router.add_get(HEALTH_CHECK, check_status)
        app.router.add_post(HEALTH_CHECK, check_status)
        for bot_key in SETTINGS:
            app.router.add_post(f"{YOOMONEY_HOOK}/{bot_key}", lambda req, bot_key=bot_key: process_yoomoney_webhook(req))
            app.router.add_post(f"{COINREMITTER_HOOK}/{bot_key}", lambda req, bot_key=bot_key: process_coinremitter_webhook(req, bot_key=bot_key))
            app.router.add_post(f"{PAYMENT_STORE}/{bot_key}", lambda req, bot_key=bot_key: store_payment(req, bot_key))
            app.router.add_post(f"{WEBHOOK_BASE}/{bot_key}", lambda req, bot_key=bot_key: process_bot_webhook(req, bot_key))
        log.info(f"Активные пути: {HEALTH_CHECK}, {YOOMONEY_HOOK}, {COINREMITTER_HOOK}, {PAYMENT_STORE}, {WEBHOOK_BASE}, /")

        port = int(os.getenv("PORT", 8000))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info(f"Сервер запущен на порту {port}")

        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        log.error(f"Ошибка сервера: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(launch_server())
