# ======================================================
# 🍕 DAY 7: FOOD & GROCERY ORDERING AGENT (SQLite DB)
# ======================================================

import logging
import os
import sqlite3
import json
from datetime import datetime
from typing import Annotated
from dataclasses import dataclass

print("\n" + "🛒" * 50)
print("🚀 F R E S H K A R T  —  Smart Grocery Engine")
print("📚 TASKS: Add Items -> Recipes -> Place Order -> DB Store")
print("🛒" * 50 + "\n")

from dotenv import load_dotenv
from pydantic import Field
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    function_tool,
    RunContext,
)

from livekit.plugins import murf, silero, google, deepgram, noise_cancellation
from livekit.plugins.turn_detector.multilingual import MultilingualModel

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# ======================================================
# 📦 1. DATABASE SETUP (SQLite)
# ======================================================

DB_FILE = "grocery.db"

def get_db_path():
    return os.path.join(os.path.dirname(__file__), DB_FILE)

def get_conn():
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def seed_db():
    print("📦 Seeding Grocery SQLite DB...")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS catalog_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            category TEXT,
            price REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            price REAL,
            quantity INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT,
            items TEXT,
            total REAL,
            status TEXT DEFAULT 'received',
            timestamp TEXT
        )
    """)

    cur.execute("SELECT COUNT(*) FROM catalog_items")
    if cur.fetchone()[0] == 0:
        sample_data = [
            # Groceries
            ('Bread', 'Groceries', 40), ('Milk (1L)', 'Groceries', 60), ('Eggs (6 pack)', 'Groceries', 55),
            ('Butter', 'Groceries', 75), ('Peanut Butter', 'Groceries', 180), ('Sugar (1kg)', 'Groceries', 45),
            ('Salt (1kg)', 'Groceries', 25), ('Rice (1kg)', 'Groceries', 60), ('Wheat Flour (1kg)', 'Groceries', 50),
            ('Cooking Oil (1L)', 'Groceries', 120), ('Tea Powder (250g)', 'Groceries', 85),
            ('Coffee (200g)', 'Groceries', 150), ('Toor Dal (1kg)', 'Groceries', 110), ('Chana Dal (1kg)', 'Groceries', 95),
            ('Besan (1kg)', 'Groceries', 75),

            # Snacks
            ('Chips', 'Snacks', 25), ('Nachos', 'Snacks', 40), ('Popcorn', 'Snacks', 35),
            ('Chocolate Bar', 'Snacks', 50), ('Cookies', 'Snacks', 60), ('Masala Peanuts', 'Snacks', 45),
            ('Khakhra', 'Snacks', 30), ('Samosa (2 pc)', 'Snacks', 30), ('Veg Puffs (2 pc)', 'Snacks', 40),

            # Beverages
            ('Coca-Cola (500ml)', 'Beverages', 40), ('Sprite (500ml)', 'Beverages', 40),
            ('Frooti (300ml)', 'Beverages', 30), ('Lassi (200ml)', 'Beverages', 25), ('Cold Coffee Can', 'Beverages', 55),
            ('Juice Pack (1L)', 'Beverages', 110),

            # Fruits
            ('Banana (6 pc)', 'Fruits', 40), ('Apple (1kg)', 'Fruits', 120), ('Mango (1kg)', 'Fruits', 180),
            ('Orange (1kg)', 'Fruits', 100), ('Grapes (500g)', 'Fruits', 70), ('Pomegranate (1kg)', 'Fruits', 170),
            ('Strawberries (200g)', 'Fruits', 90),

            # Vegetables
            ('Tomato (1kg)', 'Vegetables', 30), ('Potato (1kg)', 'Vegetables', 28), ('Onion (1kg)', 'Vegetables', 35),
            ('Cabbage (1 pc)', 'Vegetables', 25), ('Cauliflower (1 pc)', 'Vegetables', 40),
            ('Spinach (1 bunch)', 'Vegetables', 25), ('Carrot (500g)', 'Vegetables', 30),
            ('Ladyfinger (500g)', 'Vegetables', 35),

            # Prepared Food
            ('Veg Pizza', 'Prepared Food', 250), ('Chicken Burger', 'Prepared Food', 199),
            ('Pasta', 'Prepared Food', 80), ('Pasta Sauce', 'Prepared Food', 120),
            ('Chicken Biryani', 'Prepared Food', 180), ('Paneer Wrap', 'Prepared Food', 120),
            ('Egg Roll', 'Prepared Food', 60), ('Maggi Noodles Bowl', 'Prepared Food', 40),
        ]
        cur.executemany(
            "INSERT INTO catalog_items (name, category, price) VALUES (?, ?, ?)",
            sample_data
        )
        print("🍽 Catalog seeded successfully with 58 items!")

    conn.commit()
    conn.close()

seed_db()

# ======================================================
# 🧠 2. INTENT → CART STATE
# ======================================================

@dataclass
class Userdata:
    name: str = None

RECIPES = {
    "peanut butter sandwich": ["Bread", "Peanut Butter"],
    "sandwich": ["Bread", "Butter"],
    "pasta": ["Pasta", "Pasta Sauce"],
    "maggi": ["Maggi Noodles Bowl"],
}

# ======================================================
# 🛠️ 3. TOOLS (SQLite Actions)
# ======================================================
@function_tool
async def list_catalog(ctx: RunContext[Userdata]) -> str:
    """List all available grocery items from catalog."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT name, category, price FROM catalog_items ORDER BY category, name")
    rows = cur.fetchall()

    if not rows:
        return "No items available in the catalog."

    msg = "🛒 Available Groceries:\n"
    current_cat = None
    for r in rows:
        if r["category"] != current_cat:
            current_cat = r["category"]
            msg += f"\n📂 {current_cat}:\n"
        msg += f"• {r['name']} — ₹{r['price']}\n"

    return msg

@function_tool
async def add_to_cart(ctx: RunContext[Userdata], item_name: str, quantity: int = 1) -> str:
    conn = get_conn()
    cur = conn.cursor()

    # Recipe mapping
    name = item_name.lower().replace("ingredients for ", "").strip()
    if name in RECIPES:
        for i in RECIPES[name]:
            await add_to_cart(ctx, i, 1)
        return f"Added ingredients for {item_name}! 😄"

    cur.execute("SELECT * FROM catalog_items WHERE LOWER(name)=LOWER(?) LIMIT 1", (item_name,))
    row = cur.fetchone()
    if not row:
        return f"Item '{item_name}' not found."

    cur.execute("SELECT * FROM cart_items WHERE LOWER(name)=LOWER(?) LIMIT 1", (item_name,))
    exists = cur.fetchone()
    if exists:
        new_q = exists["quantity"] + quantity
        cur.execute("UPDATE cart_items SET quantity=? WHERE id=?", (new_q, exists["id"]))
    else:
        cur.execute("INSERT INTO cart_items (name, price, quantity) VALUES (?,?,?)",
                    (row["name"], row["price"], quantity))

    conn.commit()
    return f"Added {quantity} × {item_name} to cart! 🛒"


@function_tool
async def list_cart(ctx: RunContext[Userdata]) -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cart_items")
    items = cur.fetchall()

    if not items:
        return "Your cart is empty."

    total = 0
    msg = "🛍 Your cart:\n"
    for it in items:
        sub = it["price"] * it["quantity"]
        total += sub
        msg += f"- {it['name']} × {it['quantity']} = ₹{sub}\n"

    msg += f"💰 Total: ₹{total}"
    return msg


@function_tool
async def place_order(ctx: RunContext[Userdata], customer_name: str) -> str:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM cart_items")
    items = cur.fetchall()
    if not items:
        return "Cart empty!"

    total = sum(i["price"] * i["quantity"] for i in items)
    items_json = json.dumps([dict(i) for i in items])
    ts = datetime.now().isoformat()

    cur.execute("INSERT INTO orders_history (customer_name, items, total, timestamp) VALUES (?, ?, ?, ?)",
                (customer_name, items_json, total, ts))
    order_id = cur.lastrowid
    cur.execute("DELETE FROM cart_items")
    conn.commit()
    return f"🎉 Order #{order_id} placed! Current status: received 🚀"
@function_tool
@function_tool
async def track_order(ctx: RunContext[Userdata], order_id: int) -> str:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT status FROM orders_history WHERE id=?", (order_id,))
    row = cur.fetchone()
    if not row:
        return "Order not found!"

    curr = row["status"]
    next_stage = None

    if curr == "confirmed":
        next_stage = "being_prepared"
    elif curr == "being_prepared":
        next_stage = "out_for_delivery"
    elif curr == "out_for_delivery":
        next_stage = "delivered"

    if next_stage:
        cur.execute("UPDATE orders_history SET status=? WHERE id=?", (next_stage, order_id))
        conn.commit()
        curr = next_stage  # move to new status

    status_emojis = {
        "confirmed": "📦",
        "being_prepared": "👨‍🍳",
        "out_for_delivery": "🚚💨",
        "delivered": "🎉"
    }

    return f"{status_emojis.get(curr,'📦')} Order #{order_id} is currently: {curr}!"

ORDER_STAGES = [
    "received",
    "confirmed",
    "being_prepared",
    "out_for_delivery",
    "delivered"
]

@function_tool
async def progress_order_status(ctx: RunContext[Userdata], order_id: int) -> str:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT status FROM orders_history WHERE id=?", (order_id,))
    row = cur.fetchone()

    if not row:
        return "Order not found!"

    current_status = row["status"]
    stage_index = ORDER_STAGES.index(current_status)

    if stage_index < len(ORDER_STAGES) - 1:
        new_status = ORDER_STAGES[stage_index + 1]
        cur.execute("UPDATE orders_history SET status=? WHERE id=?", (new_status, order_id))
        conn.commit()
        return f"🚀 Order #{order_id} status updated: {new_status}"

    return f"🎉 Order #{order_id} already delivered!"


# ======================================================
# 🤖 4. AGENT DEFINITION
# ======================================================

class GroceryAgent(Agent):
    def __init__(self):
        super().__init__(
instructions="""
🥗 Welcome to F R E S H K A R T — Your Smart Food & Grocery Assistant! 😄

Your job:
- Help users shop faster with friendly guidance 🍎🛒
- Understand items, quantities & small details
- Easily add & update cart during conversation
- Suggest items when useful 🤓
- Handle recipes intelligently (e.g. “ingredients for pasta”) 🍝
- Always confirm what was added
- When user says they are done → place_order()
If user asks about delivery or status:
→ Ask for order_id
→ Call track_order()

If user asks 'Where is my order?':
→ Call track_order() for latest order

Voice Style:
✨ Polite
✨ Clear confirmations
✨ Shopping buddy vibes 😄

Remember:
User convenience comes first! 🚀
""",
tools=[add_to_cart, list_cart, place_order, list_catalog, track_order, progress_order_status],
)

# ======================================================
# 🎙️ 5. VOICE ENTRYPOINT (Same as Fraud Agent)
# ======================================================

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def entrypoint(ctx: JobContext):
    print("🎧 Starting Grocery Ordering Session...")
    userdata = Userdata()

    session = AgentSession(
        stt=deepgram.STT(model="nova-3"),
        llm=google.LLM(model="gemini-2.5-flash"),
        tts=murf.TTS(voice="en-US-marcus"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        userdata=userdata,
    )

    await session.start(
        agent=GroceryAgent(),
        room=ctx.room,
        room_input_options=RoomInputOptions(noise_cancellation=noise_cancellation.BVC()),
    )
    await ctx.connect()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
