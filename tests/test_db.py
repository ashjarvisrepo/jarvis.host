import pytest
import aiosqlite
from core.db import Database

@pytest.mark.asyncio
async def test_product_cart_checkout(tmp_path):
    db=Database(str(tmp_path/"test.sqlite3")); await db.connect()
    pid=await db.add_product("Test","desc","General",19900,5,"")
    await db.cart_add(123,pid,2,20)
    cart=await db.cart(123); assert cart[0]["quantity"]==2
    public,total=await db.checkout(123,"JX")
    assert public.startswith("JX-") and total==39800
    cur=await db.conn.execute("SELECT stock FROM products WHERE id=?",(pid,))
    assert (await cur.fetchone())["stock"]==3
    assert await db.order(public,123)
    await db.close()

@pytest.mark.asyncio
async def test_coupon_applies_atomically_and_consumes_use(tmp_path):
    db=Database(str(tmp_path/"coupon.sqlite3")); await db.connect()
    pid=await db.add_product("Test","desc","General",1000,5,"")
    await db.cart_add(123,pid,2,20)
    await db.conn.execute("INSERT INTO coupons(code,percent,uses_left) VALUES('SAVE10',10,1)")
    await db.conn.commit()
    public,total=await db.checkout(123,"JX","save10")
    assert total==1800
    order=await db.order(public,123)
    assert order["coupon_code"]=="SAVE10" and order["discount"]==200
    cur=await db.conn.execute("SELECT uses_left FROM coupons WHERE code='SAVE10'")
    assert (await cur.fetchone())["uses_left"]==0
    await db.close()

@pytest.mark.asyncio
async def test_invalid_coupon_keeps_cart_and_stock(tmp_path):
    db=Database(str(tmp_path/"invalid_coupon.sqlite3")); await db.connect()
    pid=await db.add_product("Test","desc","General",1000,5,"")
    await db.cart_add(123,pid,2,20)
    with pytest.raises(ValueError,match="invalid"):
        await db.checkout(123,"JX","NOPE")
    assert len(await db.cart(123))==1
    cur=await db.conn.execute("SELECT stock FROM products WHERE id=?",(pid,))
    assert (await cur.fetchone())["stock"]==5
    await db.close()

@pytest.mark.asyncio
async def test_catalog_search_sort_and_stock_adjust(tmp_path):
    db=Database(str(tmp_path/"catalog.sqlite3")); await db.connect()
    first=await db.add_product("Alpha","gold service","Services",2000,2,"")
    await db.add_product("Beta","silver item","Digital",1000,4,"")
    assert [r["name"] for r in await db.search_products("",sort="price_low")] == ["Beta","Alpha"]
    assert [r["id"] for r in await db.search_products("gold","Services")] == [first]
    assert await db.adjust_stock(first,3)==5
    with pytest.raises(ValueError,match="negative"):
        await db.adjust_stock(first,-6)
    await db.close()

@pytest.mark.asyncio
async def test_additive_migration_upgrades_existing_orders_table(tmp_path):
    path=tmp_path/"legacy.sqlite3"
    legacy=await aiosqlite.connect(path)
    await legacy.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL, payment_ref TEXT, payment_status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    await legacy.commit(); await legacy.close()
    db=Database(str(path)); await db.connect()
    cur=await db.conn.execute("PRAGMA table_info(orders)")
    columns={row["name"] for row in await cur.fetchall()}
    assert {"coupon_code","discount"} <= columns
    await db.close()

@pytest.mark.asyncio
async def test_product_edit_duplicate_wishlist_and_cart_tools(tmp_path):
    db=Database(str(tmp_path/"product_tools.sqlite3")); await db.connect()
    pid=await db.add_product("Alpha","desc","General",1000,4,"")
    await db.update_product(pid,name="Beta",price=1250)
    copy_id=await db.duplicate_product(pid)
    products=await db.search_products("",sort="name")
    assert [p["name"] for p in products]==["Beta","Beta (copy)"]
    await db.wishlist_add(7,pid)
    assert (await db.wishlist(7))[0]["id"]==pid
    assert await db.wishlist_remove(7,pid)
    await db.cart_add(7,pid,1,20)
    assert await db.cart_remove(7,pid)
    await db.cart_add(7,pid,1,20)
    await db.cart_clear(7)
    assert await db.cart(7)==[]
    await db.close()

@pytest.mark.asyncio
async def test_cancelling_unpaid_order_returns_stock_only_once(tmp_path):
    db=Database(str(tmp_path/"cancel.sqlite3")); await db.connect()
    pid=await db.add_product("Limited","desc","General",1000,3,"")
    await db.cart_add(7,pid,2,20)
    public,_=await db.checkout(7,"JX")
    await db.cancel_unpaid_order(public,7)
    cur=await db.conn.execute("SELECT stock FROM products WHERE id=?",(pid,))
    assert (await cur.fetchone())["stock"]==3
    with pytest.raises(ValueError,match="Only unpaid"):
        await db.cancel_unpaid_order(public,7)
    await db.close()

@pytest.mark.asyncio
async def test_backup_creation_and_integrity_verification(tmp_path):
    db=Database(str(tmp_path/"backup_source.sqlite3")); await db.connect()
    await db.add_product("Backup test","desc","General",100,1,"")
    backup_dir=tmp_path/"backups"
    name=await db.create_backup(str(backup_dir))
    assert name.startswith("jarvis_shop_") and name.endswith(".sqlite3")
    valid, result=db.verify_backup(str(backup_dir),name)
    assert valid and result=="ok"
    assert len(db.list_backups(str(backup_dir)))==1
    await db.close()

@pytest.mark.asyncio
async def test_dm_optin_and_campaign_tables_are_additive(tmp_path):
    db=Database(str(tmp_path/"dm_campaign.sqlite3")); await db.connect()
    await db.conn.execute("INSERT INTO dm_preferences(user_id,promotional_opt_in,updated_at) VALUES(7,1,'now')")
    cur=await db.conn.execute("INSERT INTO dm_campaigns(guild_id,created_by,audience,message,status,embed_enabled,created_at) VALUES(1,2,'opted_in_customers','hello {username}','pending_approval',1,'now')")
    campaign_id=cur.lastrowid
    await db.conn.execute("INSERT INTO dm_campaign_deliveries(campaign_id,user_id,status,attempted_at) VALUES(?,7,'sent','now')",(campaign_id,))
    await db.conn.commit()
    cur=await db.conn.execute("SELECT promotional_opt_in FROM dm_preferences WHERE user_id=7")
    assert (await cur.fetchone())["promotional_opt_in"]==1
    cur=await db.conn.execute("SELECT embed_enabled FROM dm_campaigns WHERE id=?",(campaign_id,))
    assert (await cur.fetchone())["embed_enabled"]==1
    cur=await db.conn.execute("SELECT status FROM dm_campaign_deliveries WHERE campaign_id=? AND user_id=7",(campaign_id,))
    assert (await cur.fetchone())["status"]=="sent"
    await db.close()
