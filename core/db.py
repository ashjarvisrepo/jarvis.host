import aiosqlite, os, json, secrets, string, datetime, sqlite3

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users(
 user_id INTEGER PRIMARY KEY, joined_at TEXT NOT NULL, points INTEGER NOT NULL DEFAULT 0,
 store_credit INTEGER NOT NULL DEFAULT 0, banned INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products(
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT NOT NULL,
 category TEXT NOT NULL DEFAULT 'General', price INTEGER NOT NULL CHECK(price>=0),
 stock INTEGER NOT NULL DEFAULT -1, active INTEGER NOT NULL DEFAULT 1,
 delivery_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS carts(
 user_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), PRIMARY KEY(user_id,product_id)
);
CREATE TABLE IF NOT EXISTS wishlists(
 user_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id),
 added_at TEXT NOT NULL, PRIMARY KEY(user_id,product_id)
);
CREATE TABLE IF NOT EXISTS orders(
 id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL,
 total INTEGER NOT NULL, status TEXT NOT NULL, payment_ref TEXT, payment_status TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items(
 order_id INTEGER NOT NULL REFERENCES orders(id), product_id INTEGER NOT NULL,
 product_name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price INTEGER NOT NULL,
 delivery_status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS tickets(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, channel_id INTEGER,
 status TEXT NOT NULL DEFAULT 'open', subject TEXT NOT NULL, assigned_to INTEGER,
 created_at TEXT NOT NULL, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER NOT NULL, action TEXT NOT NULL,
 details TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coupons(
 code TEXT PRIMARY KEY, percent INTEGER NOT NULL, uses_left INTEGER NOT NULL DEFAULT -1,
 expires_at TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dm_preferences(
 user_id INTEGER PRIMARY KEY, promotional_opt_in INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dm_campaigns(
 id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, created_by INTEGER NOT NULL,
 audience TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending_approval',
 approved_by INTEGER, embed_enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 sent_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dm_campaign_deliveries(
 campaign_id INTEGER NOT NULL REFERENCES dm_campaigns(id), user_id INTEGER NOT NULL,
 status TEXT NOT NULL, reason TEXT, attempted_at TEXT NOT NULL,
 PRIMARY KEY(campaign_id,user_id)
);
CREATE TABLE IF NOT EXISTS verify_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
 target_key TEXT NOT NULL, result TEXT NOT NULL, ip_hash TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verify_pending_roles(
 user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL, target_key TEXT NOT NULL,
 role_id INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, PRIMARY KEY(user_id,guild_id,target_key)
);
CREATE TABLE IF NOT EXISTS verify_recovery_grants(
 user_id INTEGER NOT NULL, source_guild_id INTEGER NOT NULL, target_key TEXT NOT NULL,
 token_ciphertext TEXT NOT NULL, granted_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(user_id,source_guild_id,target_key)
);
CREATE TABLE IF NOT EXISTS invite_campaigns(
 code TEXT PRIMARY KEY, guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
 campaign TEXT NOT NULL, created_by INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invite_attributions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
 invite_code TEXT, campaign TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sellauth_events(
 event_key TEXT PRIMARY KEY, event TEXT NOT NULL, invoice_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL UNIQUE, received_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
);
"""

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

class Database:
    def __init__(self, path): self.path = path
    async def connect(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        # Remove IP hashes written by earlier verification builds; JARVIS no
        # longer persists any IP-derived verification data.
        await self.conn.execute("UPDATE verify_events SET ip_hash=NULL WHERE ip_hash IS NOT NULL")
        # Additive migrations keep existing v0.4.0 databases intact.
        await self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        cur = await self.conn.execute("PRAGMA table_info(dm_campaigns)")
        campaign_columns = {row["name"] for row in await cur.fetchall()}
        if "embed_enabled" not in campaign_columns:
            await self.conn.execute("ALTER TABLE dm_campaigns ADD COLUMN embed_enabled INTEGER NOT NULL DEFAULT 0")
        cur = await self.conn.execute("PRAGMA table_info(orders)")
        order_columns = {row["name"] for row in await cur.fetchall()}
        if "coupon_code" not in order_columns:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN coupon_code TEXT")
        if "discount" not in order_columns:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN discount INTEGER NOT NULL DEFAULT 0")
        cur = await self.conn.execute("PRAGMA table_info(verify_pending_roles)")
        verify_role_columns = {row["name"] for row in await cur.fetchall()}
        if "role_id" not in verify_role_columns:
            await self.conn.execute("ALTER TABLE verify_pending_roles ADD COLUMN role_id INTEGER NOT NULL DEFAULT 0")
        await self.conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,?)", (now(),))
        await self.conn.execute("INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(2,?)", (now(),))
        await self.conn.commit()
    async def close(self): await self.conn.close()
    async def create_backup(self, backup_dir):
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"jarvis_shop_{stamp}.sqlite3"
        final_path = os.path.join(backup_dir, name)
        temporary_path = final_path + ".tmp"
        target = sqlite3.connect(temporary_path)
        try:
            await self.conn.backup(target)
            target.commit()
        except Exception:
            target.close()
            try: os.remove(temporary_path)
            except OSError: pass
            raise
        target.close()
        os.replace(temporary_path, final_path)
        return name
    def list_backups(self, backup_dir):
        if not os.path.isdir(backup_dir): return []
        results = []
        for name in os.listdir(backup_dir):
            if name.startswith("jarvis_shop_") and name.endswith(".sqlite3"):
                path = os.path.join(backup_dir, name)
                if os.path.isfile(path): results.append((name, os.path.getsize(path), os.path.getmtime(path)))
        return sorted(results, key=lambda row: row[2], reverse=True)
    def verify_backup(self, backup_dir, name):
        if os.path.basename(name) != name or not name.startswith("jarvis_shop_") or not name.endswith(".sqlite3"):
            raise ValueError("Choose a JARVIS backup filename from `$backup list`.")
        path = os.path.join(backup_dir, name)
        if not os.path.isfile(path): raise ValueError("Backup file not found.")
        source = sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)
        try:
            integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"products", "orders", "order_items", "tickets"}
            missing = sorted(required - tables)
            return integrity == "ok" and not missing, integrity if not missing else f"Missing tables: {', '.join(missing)}"
        finally:
            source.close()
    async def audit(self, actor, action, details=""):
        await self.conn.execute("INSERT INTO audit(actor_id,action,details,created_at) VALUES(?,?,?,?)",
                                (actor, action, details[:1500], now()))
        await self.conn.commit()
    async def ensure_user(self, user_id):
        await self.conn.execute("INSERT OR IGNORE INTO users(user_id,joined_at) VALUES(?,?)",(user_id,now()))
        await self.conn.commit()
    async def products(self, active=True):
        q = "SELECT * FROM products" + (" WHERE active=1" if active else "") + " ORDER BY id DESC"
        cur = await self.conn.execute(q); return await cur.fetchall()
    async def search_products(self, query="", category="", sort="newest"):
        clauses = ["active=1"]
        args = []
        if query.strip():
            clauses.append("(name LIKE ? OR description LIKE ?)")
            term = f"%{query.strip()[:80]}%"
            args.extend((term, term))
        if category.strip():
            clauses.append("category = ?")
            args.append(category.strip()[:80])
        order_by = {"newest": "id DESC", "price_low": "price ASC, id DESC", "price_high": "price DESC, id DESC", "name": "name COLLATE NOCASE ASC"}.get(sort, "id DESC")
        cur = await self.conn.execute(f"SELECT * FROM products WHERE {' AND '.join(clauses)} ORDER BY {order_by} LIMIT 25", args)
        return await cur.fetchall()
    async def add_product(self, name, desc, category, price, stock, delivery):
        cur = await self.conn.execute("""INSERT INTO products(name,description,category,price,stock,delivery_text,created_at)
          VALUES(?,?,?,?,?,?,?)""",(name,desc,category,price,stock,delivery,now()))
        await self.conn.commit(); return cur.lastrowid
    async def update_product(self, product_id, *, name=None, description=None, category=None, price=None, stock=None):
        updates = {"name": name, "description": description, "category": category, "price": price, "stock": stock}
        updates = {key: value for key, value in updates.items() if value is not None}
        if not updates:
            raise ValueError("Provide at least one product field to update.")
        if "name" in updates and not str(updates["name"]).strip():
            raise ValueError("Product name cannot be empty.")
        if "price" in updates and updates["price"] < 0:
            raise ValueError("Price cannot be negative.")
        if "stock" in updates and updates["stock"] < -1:
            raise ValueError("Stock must be -1 (unlimited) or greater.")
        assignments = ",".join(f"{column}=?" for column in updates)
        cur = await self.conn.execute(f"UPDATE products SET {assignments} WHERE id=? AND active=1", (*updates.values(), product_id))
        if cur.rowcount == 0:
            await self.conn.rollback()
            raise ValueError("Product not found or inactive.")
        await self.conn.commit()
        return True
    async def duplicate_product(self, product_id):
        cur = await self.conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,))
        p = await cur.fetchone()
        if not p:
            raise ValueError("Product not found or inactive.")
        return await self.add_product(p["name"][:94] + " (copy)", p["description"], p["category"], p["price"], p["stock"], p["delivery_text"])
    async def adjust_stock(self, product_id, delta):
        cur = await self.conn.execute("SELECT stock FROM products WHERE id=? AND active=1", (product_id,))
        row = await cur.fetchone()
        if not row:
            raise ValueError("Product not found or inactive.")
        if row["stock"] < 0:
            raise ValueError("Unlimited stock does not need adjustment.")
        new_stock = row["stock"] + delta
        if new_stock < 0:
            raise ValueError("Stock cannot become negative.")
        await self.conn.execute("UPDATE products SET stock=? WHERE id=?", (new_stock, product_id))
        await self.conn.commit()
        return new_stock
    async def cart_add(self, user, product, qty, max_qty):
        await self.ensure_user(user)
        cur = await self.conn.execute("SELECT * FROM products WHERE id=? AND active=1",(product,))
        p = await cur.fetchone()
        if not p: raise ValueError("Product not found or inactive.")
        if p["stock"] >= 0 and p["stock"] < qty: raise ValueError("Not enough stock.")
        cur = await self.conn.execute("SELECT quantity FROM carts WHERE user_id=? AND product_id=?",(user,product))
        old = await cur.fetchone(); total = qty + (old["quantity"] if old else 0)
        if total > max_qty: raise ValueError(f"Cart quantity limit is {max_qty}.")
        if p["stock"] >= 0 and total > p["stock"]: raise ValueError("Cart quantity exceeds available stock.")
        await self.conn.execute("""INSERT INTO carts(user_id,product_id,quantity) VALUES(?,?,?)
          ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=excluded.quantity""",(user,product,total))
        await self.conn.commit()
    async def cart(self, user):
        cur = await self.conn.execute("""SELECT c.quantity,p.id,p.name,p.price,p.stock
          FROM carts c JOIN products p ON p.id=c.product_id WHERE c.user_id=? AND p.active=1""",(user,))
        return await cur.fetchall()
    async def cart_remove(self, user, product):
        cur = await self.conn.execute("DELETE FROM carts WHERE user_id=? AND product_id=?", (user, product))
        await self.conn.commit()
        return cur.rowcount > 0
    async def cart_clear(self, user):
        await self.conn.execute("DELETE FROM carts WHERE user_id=?", (user,))
        await self.conn.commit()
    async def wishlist(self, user):
        cur = await self.conn.execute("SELECT p.* FROM wishlists w JOIN products p ON p.id=w.product_id WHERE w.user_id=? AND p.active=1 ORDER BY w.added_at DESC", (user,))
        return await cur.fetchall()
    async def wishlist_add(self, user, product):
        cur = await self.conn.execute("SELECT id FROM products WHERE id=? AND active=1", (product,))
        if not await cur.fetchone():
            raise ValueError("Product not found or inactive.")
        await self.conn.execute("INSERT OR IGNORE INTO wishlists(user_id,product_id,added_at) VALUES(?,?,?)", (user, product, now()))
        await self.conn.commit()
    async def wishlist_remove(self, user, product):
        cur = await self.conn.execute("DELETE FROM wishlists WHERE user_id=? AND product_id=?", (user, product))
        await self.conn.commit()
        return cur.rowcount > 0
    async def checkout(self, user, prefix, coupon_code=None):
        # Atomic stock deduction and order creation.
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self.conn.execute("""SELECT c.quantity,p.* FROM carts c JOIN products p ON p.id=c.product_id
              WHERE c.user_id=? AND p.active=1""",(user,))
            rows = await cur.fetchall()
            if not rows: raise ValueError("Your cart is empty.")
            subtotal = sum(r["quantity"]*r["price"] for r in rows)
            discount = 0
            normalized_coupon = None
            if coupon_code:
                normalized_coupon = coupon_code.strip().upper()[:32]
                cur = await self.conn.execute("SELECT * FROM coupons WHERE code=? AND active=1", (normalized_coupon,))
                coupon = await cur.fetchone()
                if not coupon or (coupon["uses_left"] == 0):
                    raise ValueError("That coupon is invalid, inactive, or used up.")
                if coupon["expires_at"]:
                    try:
                        expires = datetime.datetime.fromisoformat(coupon["expires_at"].replace("Z", "+00:00"))
                        if expires.tzinfo is None: expires = expires.replace(tzinfo=datetime.timezone.utc)
                        if expires <= datetime.datetime.now(datetime.timezone.utc):
                            raise ValueError("That coupon has expired.")
                    except ValueError as exc:
                        if str(exc) == "That coupon has expired.": raise
                        raise ValueError("Coupon expiry is invalid; ask staff to update it.")
                discount = (subtotal * coupon["percent"]) // 100
                total = subtotal - discount
            else:
                total = subtotal
            for r in rows:
                if r["stock"] >= 0 and r["stock"] < r["quantity"]:
                    raise ValueError(f"Insufficient stock for {r['name']}.")
            public_id = prefix + "-" + ''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(8))
            cur = await self.conn.execute("""INSERT INTO orders(public_id,user_id,total,status,payment_status,created_at,updated_at)
              VALUES(?,?,?,'awaiting_payment','unpaid',?,?)""",(public_id,user,total,now(),now()))
            oid = cur.lastrowid
            if normalized_coupon:
                await self.conn.execute("UPDATE orders SET coupon_code=?,discount=? WHERE id=?", (normalized_coupon, discount, oid))
                await self.conn.execute("UPDATE coupons SET uses_left=uses_left-1 WHERE code=? AND uses_left>0", (normalized_coupon,))
            for r in rows:
                await self.conn.execute("""INSERT INTO order_items(order_id,product_id,product_name,quantity,unit_price)
                  VALUES(?,?,?,?,?)""",(oid,r["id"],r["name"],r["quantity"],r["price"]))
                if r["stock"] >= 0:
                    await self.conn.execute("UPDATE products SET stock=stock-? WHERE id=?",(r["quantity"],r["id"]))
            await self.conn.execute("DELETE FROM carts WHERE user_id=?",(user,))
            await self.conn.commit()
            return public_id,total
        except Exception:
            await self.conn.rollback(); raise
    async def order(self, public_id, user=None):
        q="SELECT * FROM orders WHERE public_id=?"; args=[public_id]
        if user is not None: q+=" AND user_id=?"; args.append(user)
        cur=await self.conn.execute(q,args); return await cur.fetchone()
    async def order_items(self, oid):
        cur=await self.conn.execute("SELECT * FROM order_items WHERE order_id=?",(oid,)); return await cur.fetchall()
    async def cancel_unpaid_order(self, public_id, user):
        await self.conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await self.conn.execute("SELECT * FROM orders WHERE public_id=? AND user_id=?", (public_id, user))
            order = await cur.fetchone()
            if not order:
                raise ValueError("Order not found.")
            if order["status"] != "awaiting_payment" or order["payment_status"] != "unpaid":
                raise ValueError("Only unpaid orders awaiting payment can be cancelled.")
            items = await self.order_items(order["id"])
            for item in items:
                if item["product_id"]:
                    await self.conn.execute("UPDATE products SET stock=stock+? WHERE id=? AND stock>=0", (item["quantity"], item["product_id"]))
            await self.conn.execute("UPDATE orders SET status='cancelled',updated_at=? WHERE id=? AND status='awaiting_payment' AND payment_status='unpaid'", (now(), order["id"]))
            await self.conn.commit()
            return True
        except Exception:
            await self.conn.rollback()
            raise
