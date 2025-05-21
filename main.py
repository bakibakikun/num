import logging
import sys
import uuid
import psycopg2
import hashlib
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web, ClientSession
from urllib.parse import urlencode
import asyncio
import os
from config import fetch_bot_settings
import qrcode
import io
from PIL import Image

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
log = logging.getLogger(__name__)
log.info("Starting subscription bot")

# Define endpoints and database
PAYMENT_STORE = "/store_payment"
YOOMONEY_HOOK = "/yoomoney_hook"
CRYPTO_HOOK = "/crypto_hook"
TON_HOOK = "/ton_hook"
HEALTH_CHECK = "/status"
WEBHOOK_BASE = "/bot_hook"
DB_URL = "postgresql://postgres.iylthyqzwovudjcyfubg:Alex4382!@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
BASE_URL = os.getenv("HOST_URL", "https://short-blinnie-bakibakikun-a88f041b.koyeb.app")
CRYPTOCLOUD_KEY = os.getenv("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1dWlkIjoiTlRVM056WT0iLCJ0eXBlIjoicHJvamVjdCIsInYiOiI3MGQ2YmMwYzM2ODE5MzExMzRmMGNjNDA1MTVlZmViYjI3ZjA2MjQ0ODVkOWM1MzQ4ZjE3NzcwYTU2NGVkNDQzIiwiZXhwIjo4ODE0NzY0MzkwMn0.P8MAez009Fv0AF8XUTUBVGZ0C7rvddJWeHZI1KtDSdU")
CRYPTOCLOUD_SHOP = os.getenv("qPPr3ZALOPIZ402t")

# Validate environment variables
if not CRYPTOCLOUD_KEY or not CRYPTOCLOUD_SHOP:
    log.error("Missing CRYPTOCLOUD_API_KEY or CRYPTOCLOUD_SHOP_ID")
    sys.exit(1)

# Environment
ENV = "koyeb"
log.info(f"Platform: {ENV}")

# Load bot configurations
SETTINGS = fetch_bot_settings()
log.info(f"Configuring {len(SETTINGS)} bots")
bot_instances = {}
dispatchers = {}

for bot_key, cfg in SETTINGS.items():
    try:
        log.info(f"Initializing bot {bot_key}")
        bot_instances[bot_key] = Bot(token=cfg["TOKEN"])
        dispatchers[bot_key] = Dispatcher(bot_instances[bot_key])
        log.info(f"Bot {bot_key} initialized")
    except Exception as e:
        log.error(f"Bot {bot_key} initialization failed: {e}")
        sys.exit(1)

# Database initialization
def setup_database():
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        for bot_key in SETTINGS:
            # Create table if not exists
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS payments_{bot_key} "
                "(label TEXT PRIMARY KEY, user_id TEXT, status TEXT, payment_type TEXT)"
            )
            # Add payment_type column if missing
            cursor.execute(
                f"ALTER TABLE payments_{bot_key} ADD COLUMN IF NOT EXISTS payment_type TEXT"
            )
        conn.commit()
        conn.close()
        log.info("Database initialized and schema updated")
    except Exception as e:
        log.error(f"Database error: {e}")
        sys.exit(1)

setup_database()

# Payment buttons
def create_payment_buttons(user_id, price):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("YooMoney", callback_data=f"yoomoney_{user_id}"))
    keyboard.add(InlineKeyboardButton("Cryptocurrency", callback_data=f"crypto_{user_id}"))
    keyboard.add(InlineKeyboardButton("TON Wallet", callback_data=f"ton_{user_id}"))
    return keyboard

# Command handlers
for bot_key, dp in dispatchers.items():
    @dp.message_handler(commands=["start"])
    async def initiate_payment(msg: types.Message, bot_key=bot_key):
        try:
            user_id = str(msg.from_user.id)
            chat_id = msg.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            log.info(f"[{bot_key}] /start from user {user_id}")

            keyboard = create_payment_buttons(user_id, cfg["PRICE"])
            welcome_msg = cfg["DESCRIPTION"].format(price=cfg["PRICE"])
            await bot.send_message(
                chat_id,
                f"{welcome_msg}\n\nSelect payment method for {cfg['PRICE']} RUB:",
                reply_markup=keyboard
            )
            log.info(f"[{bot_key}] Sent payment options to user {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] /start error: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Error. Try again.")

    @dp.callback_query_handler(lambda c: c.data.startswith("yoomoney_"))
    async def handle_yoomoney_choice(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] YooMoney chosen by user {user_id}")

            payment_id = str(uuid.uuid4())
            payment_data = {
                "quickpay-form": "shop",
                "paymentType": "AC",
                "targets": f"Subscription user {user_id}",
                "sum": cfg["PRICE"],
                "label": payment_id,
                "receiver": cfg["YOOMONEY_WALLET"],
                "successURL": f"https://t.me/{(await bot.get_me()).username}"
            }
            payment_link = f"https://yoomoney.ru/quickpay/confirm.xml?{urlencode(payment_data)}"

            # Save payment
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", "yoomoney")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Stored payment {payment_id} for user {user_id}")

            # Send payment link
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("Pay Now", url=payment_link))
            await bot.send_message(chat_id, "Proceed with YooMoney payment:", reply_markup=keyboard)
            log.info(f"[{bot_key}] YooMoney link sent to user {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] YooMoney error: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Payment error. Try again.")

    @dp.callback_query_handler(lambda c: c.data.startswith("crypto_") and not c.data.startswith(("crypto_usdt_", "crypto_btc_", "crypto_ton_")))
    async def handle_crypto_choice(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] Crypto chosen by user {user_id}")

            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("USDT", callback_data=f"crypto_usdt_{user_id}"))
            keyboard.add(InlineKeyboardButton("BTC", callback_data=f"crypto_btc_{user_id}"))
            keyboard.add(InlineKeyboardButton("TON", callback_data=f"crypto_ton_{user_id}"))
            await bot.send_message(chat_id, "Choose cryptocurrency:", reply_markup=keyboard)
            log.info(f"[{bot_key}] Sent crypto options to user {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] Crypto selection error: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Crypto error. Try again.")

    @dp.callback_query_handler(lambda c: c.data.startswith(("crypto_usdt_", "crypto_btc_", "crypto_ton_")))
    async def process_crypto_payment(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            parts = cb.data.split("_")
            currency = parts[1].upper()
            user_id = parts[2]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] Chose {currency} for user {user_id}")

            payment_id = str(uuid.uuid4())
            amount = cfg["PRICE"] / 80  # RUB to USD (approximate)
            log.debug(f"[{bot_key}] Creating CryptoCloud invoice: amount={amount}, currency=USD, order_id={payment_id}")
            async with ClientSession() as session:
                headers = {"Authorization": f"Token {CRYPTOCLOUD_KEY}"}
                data = {
                    "shop_id": CRYPTOCLOUD_SHOP,
                    "amount": amount,
                    "currency": "USD",
                    "order_id": payment_id,
                    "email": f"user_{user_id}@example.com",
                    "callback_url": f"{BASE_URL}{CRYPTO_HOOK}/{bot_key}"
                }
                async with session.post("https://api.cryptocloud.plus/v2/invoice/create", headers=headers, json=data) as resp:
                    result = await resp.json()
                    log.debug(f"[{bot_key}] CryptoCloud response: {result}")
                    if result.get("status") != "success":
                        log.error(f"[{bot_key}] Crypto invoice failed: {result}")
                        await bot.send_message(chat_id, "Unable to create crypto payment. Try again.")
                        return
                    address = result["result"]["address"]
                    pay_url = result["result"]["link"]

            # Save payment
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", f"crypto_{currency.lower()}")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Stored crypto payment {payment_id} for user {user_id}")

            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(f"{currency.lower()}:{address}?amount={amount}")
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")

            # Send payment details
            await bot.send_photo(
                chat_id,
                photo=buffer.getvalue(),
                caption=(
                    f"Send {amount:.4f} {currency} to:\n`{address}`\n\n"
                    f"Or use [payment link]({pay_url})\n"
                    "Payment will be confirmed automatically."
                ),
                parse_mode="Markdown"
            )
            log.info(f"[{bot_key}] Sent crypto details to user {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] Crypto payment error: {e}")
            await bot_instances[bot_key].send_message(chat_id, "Crypto payment error. Try again.")

    @dp.callback_query_handler(lambda c: c.data.startswith("ton_"))
    async def handle_ton_payment(cb: types.CallbackQuery, bot_key=bot_key):
        try:
            user_id = cb.data.split("_")[1]
            chat_id = cb.message.chat.id
            bot = bot_instances[bot_key]
            cfg = SETTINGS[bot_key]
            await bot.answer_callback_query(cb.id)
            log.info(f"[{bot_key}] TON Wallet chosen by user {user_id}")

            if not cfg.get("TON_API_TOKEN") or not cfg.get("TON_MERCHANT_ID"):
                log.error(f"[{bot_key}] Missing TON credentials")
                await bot.send_message(chat_id, "TON Wallet is not configured. Try another method.")
                return

            payment_id = str(uuid.uuid4())
            amount = cfg["PRICE"] / 400  # RUB to TON (approximate)
            async with ClientSession() as session:
                headers = {"Authorization": f"Bearer {cfg['TON_API_TOKEN']}"}
                data = {
                    "merchant_id": cfg["TON_MERCHANT_ID"],
                    "amount": amount,
                    "currency": "TON",
                    "order_id": payment_id,
                    "description": f"Subscription user {user_id}",
                    "callback_url": f"{BASE_URL}{TON_HOOK}/{bot_key}"
                }
                async with session.post("https://api.wallet.tg/v1/invoice/create", headers=headers, json=data) as resp:
                    result = await resp.json()
                    log.debug(f"[{bot_key}] TON Wallet response: {result}")
                    if result.get("status") != "success":
                        log.error(f"[{bot_key}] TON invoice failed: {result}")
                        await bot.send_message(chat_id, "Unable to create TON payment. Try again.")
                        return
                    pay_url = result["result"]["payment_url"]

            # Save payment
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
                "VALUES (%s, %s, %s, %s)",
                (payment_id, user_id, "pending", "ton")
            )
            conn.commit()
            conn.close()
            log.info(f"[{bot_key}] Stored TON payment {payment_id} for user {user_id}")

            # Send payment link
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("Pay via TON", url=pay_url))
            await bot.send_message(
               April 11, 2025 at 10:03 AM                chat_id,
                f"Pay {amount:.4f} TON via Telegram Wallet:",
                reply_markup=keyboard
            )
            log.info(f"[{bot_key}] Sent TON payment link to user {user_id}")
        except Exception as e:
            log.error(f"[{bot_key}] TON payment error: {e}")
            await bot_instances[bot_key].send_message(chat_id, "TON payment error. Try again.")

# Validate YooMoney webhook
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
        log.debug(f"[{bot_key}] YooMoney hash: {computed_hash}, received: {data.get('sha1_hash')}")
        return computed_hash == data.get("sha1_hash")
    except Exception as e:
        log.error(f"[{bot_key}] YooMoney validation error: {e}")
        return False

# Generate channel invite
async def generate_channel_invite(bot_key, user_id):
    try:
        cfg = SETTINGS[bot_key]
        bot = bot_instances[bot_key]
        bot_member = await bot.get_chat_member(chat_id=cfg["PRIVATE_CHANNEL_ID"], user_id=(await bot.get_me()).id)
        if not bot_member.can_invite_users:
            log.error(f"[{bot_key}] Bot lacks invite permission for channel {cfg['PRIVATE_CHANNEL_ID']}")
            return None

        for _ in range(3):
            try:
                invite = await bot.create_chat_invite_link(
                    chat_id=cfg["PRIVATE_CHANNEL_ID"],
                    member_limit=1,
                    name=f"user_{user_id}_access"
                )
                log.info(f"[{bot_key}] Created invite for user {user_id}: {invite.invite_link}")
                return invite.invite_link
            except Exception as e:
                log.warning(f"[{bot_key}] Invite attempt failed: {e}")
                await asyncio.sleep(1)
        log.error(f"[{bot_key}] Failed to create invite for user {user_id}")
        return None
    except Exception as e:
        log.error(f"[{bot_key}] Invite error: {e}")
        return None

# Locate bot by payment ID
def locate_bot_by_payment(payment_id):
    try:
        for bot_key in SETTINGS:
            conn = psycopg2.connect(DB_URL)
            cursor = conn.cursor()
            cursor.execute(f"SELECT user_id FROM payments_{bot_key} WHERE label = %s", (payment_id,))
            result = cursor.fetchone()
            conn.close()
            if result:
                log.info(f"[{bot_key}] Found payment {payment_id}")
                return bot_key
        log.warning(f"Payment {payment_id} not found")
        return None
    except Exception as e:
        log.error(f"Payment lookup error: {e}")
        return None

# YooMoney webhook handler
async def process_yoomoney_webhook(req):
    try:
        data = await req.post()
        log.info(f"[{ENV}] YooMoney webhook: {dict(data)}")
        payment_id = data.get("label")
        if not payment_id:
            log.error(f"[{ENV}] Missing payment ID")
            return web.Response(status=400, text="No payment ID")

        bot_key = locate_bot_by_payment(payment_id)
        if not bot_key:
            log.error(f"[{ENV}] Bot not found for payment {payment_id}")
            return web.Response(status=400, text="Bot not found")

        if not check_yoomoney_webhook(data, bot_key):
            log.error(f"[{bot_key}] Invalid YooMoney webhook")
            return web.Response(status=400, text="Invalid signature")

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
                await bot.send_message(user_id, "Payment confirmed!")
                invite = await generate_channel_invite(bot_key, user_id)
                if invite:
                    await bot.send_message(user_id, f"Join channel: {invite}")
                    log.info(f"[{bot_key}] Processed payment {payment_id} for user {user_id}")
                else:
                    await bot.send_message(user_id, "Invite error. Contact @YourSupportHandle.")
                    log.error(f"[{bot_key}] Invite failed for user {user_id}")
            else:
                log.error(f"[{bot_key}] Payment {payment_id} not found")
            conn.close()
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{ENV}] YooMoney webhook error: {e}")
        return web.Response(status=500)

# CryptoCloud webhook handler
async def process_crypto_webhook(req, bot_key):
    try:
        data = await req.json()
        log.info(f"[{bot_key}] CryptoCloud webhook: {data}")
        payment_id = data.get("order_id")
        status = data.get("status")
        if not payment_id or not status:
            log.error(f"[{bot_key}] Missing CryptoCloud data")
            return web.Response(status=400, text="Missing data")

        if status == "success":
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
                await bot.send_message(user_id, "Crypto payment confirmed!")
                invite = await generate_channel_invite(bot_key, user_id)
                if invite:
                    await bot.send_message(user_id, f"Join channel: {invite}")
                    log.info(f"[{bot_key}] Crypto payment {payment_id} processed for user {user_id}")
                else:
                    await bot.send_message(user_id, "Invite error. Contact @YourSupportHandle.")
                    log.error(f"[{bot_key}] Crypto invite failed for user {user_id}")
            else:
                log.error(f"[{bot_key}] Payment {payment_id} not found")
            conn.close()
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] Crypto webhook error: {e}")
        return web.Response(status=500)

# TON Wallet webhook handler
async def process_ton_webhook(req, bot_key):
    try:
        data = await req.json()
        log.info(f"[{bot_key}] TON Wallet webhook: {data}")
        payment_id = data.get("order_id")
        status = data.get("status")
        if not payment_id or not status:
            log.error(f"[{bot_key}] Missing TON data")
            return web.Response(status=400, text="Missing data")

        if status == "success":
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
                await bot.send_message(user_id, "TON payment confirmed!")
                invite = await generate_channel_invite(bot_key, user_id)
                if invite:
                    await bot.send_message(user_id, f"Join channel: {invite}")
                    log.info(f"[{bot_key}] TON payment {payment_id} processed for user {user_id}")
                else:
                    await bot.send_message(user_id, "Invite error. Contact @YourSupportHandle.")
                    log.error(f"[{bot_key}] TON invite failed for user {user_id}")
            else:
                log.error(f"[{bot_key}] Payment {payment_id} not found")
            conn.close()
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] TON webhook error: {e}")
        return web.Response(status=500)

# Payment storage handler
async def store_payment(req, bot_key):
    try:
        data = await req.json()
        payment_id = data.get("label")
        user_id = data.get("user_id")
        payment_type = data.get("payment_type", "unknown")
        log.info(f"[{bot_key}] Storing payment: {payment_id} for user {user_id}")
        if not payment_id or not user_id:
            log.error(f"[{bot_key}] Missing payment data")
            return web.Response(status=400, text="Incomplete data")

        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO payments_{bot_key} (label, user_id, status, payment_type) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (label) DO UPDATE SET user_id = %s, status = %s",
            (payment_id, user_id, "pending", payment_type, user_id, "pending")
        )
        conn.commit()
        conn.close()
        log.info(f"[{bot_key}] Stored payment: {payment_id}")
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] Payment storage error: {e}")
        return web.Response(status=500)

# Health check handler
async def check_status(req):
    log.info(f"[{ENV}] Status check")
    return web.Response(status=200, text=f"Active with {len(SETTINGS)} bots")

# Bot webhook handler
async def process_bot_webhook(req, bot_key):
    try:
        if bot_key not in dispatchers:
            log.error(f"[{bot_key}] Invalid bot key")
            return web.Response(status=400, text="Invalid bot")

        bot = bot_instances[bot_key]
        dp = dispatchers[bot_key]
        Bot.set_current(bot)
        dp.set_current(dp)

        update = await req.json()
        log.debug(f"[{bot_key}] Webhook data: {update}")
        update_obj = types.Update(**update)
        asyncio.create_task(dp.process_update(update_obj))
        return web.Response(status=200)
    except Exception as e:
        log.error(f"[{bot_key}] Webhook error: {e}")
        return web.Response(status=500)

# Configure webhooks
async def configure_webhooks():
    log.info(f"Configuring webhooks for {len(SETTINGS)} bots")
    for bot_key in bot_instances:
        try:
            bot = bot_instances[bot_key]
            hook_url = f"{BASE_URL}{WEBHOOK_BASE}/{bot_key}"
            await bot.delete_webhook(drop_pending_updates=True)
            await bot.set_webhook(hook_url)
            log.info(f"[{bot_key}] Webhook set: {hook_url}")
        except Exception as e:
            log.error(f"[{bot_key}] Webhook error: {e}")
            sys.exit(1)

# Initialize server
async def launch_server():
    try:
        await configure_webhooks()
        log.info("Starting server")
        app = web.Application()
        app.router.add_post(YOOMONEY_HOOK, process_yoomoney_webhook)
        app.router.add_get(HEALTH_CHECK, check_status)
        app.router.add_post(HEALTH_CHECK, check_status)
        for bot_key in SETTINGS:
            app.router.add_post(f"{YOOMONEY_HOOK}/{bot_key}", lambda req, bot_key=bot_key: process_yoomoney_webhook(req))
            app.router.add_post(f"{CRYPTO_HOOK}/{bot_key}", lambda req, bot_key=bot_key: process_crypto_webhook(req, bot_key))
            app.router.add_post(f"{TON_HOOK}/{bot_key}", lambda req, bot_key=bot_key: process_ton_webhook(req, bot_key))
            app.router.add_post(f"{PAYMENT_STORE}/{bot_key}", lambda req, bot_key=bot_key: store_payment(req, bot_key))
            app.router.add_post(f"{WEBHOOK_BASE}/{bot_key}", lambda req, bot_key=bot_key: process_bot_webhook(req, bot_key))
        log.info(f"Endpoints active: {HEALTH_CHECK}, {YOOMONEY_HOOK}, {CRYPTO_HOOK}, {TON_HOOK}, {PAYMENT_STORE}, {WEBHOOK_BASE}")

        port = int(os.getenv("PORT", 8000))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        log.info(f"Server running on port {port}")

        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        log.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(launch_server())
