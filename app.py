import os, sqlite3
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).with_name("food_ordering.db"))))
STATUSES = ["Placed", "Confirmed", "Preparing", "Packed", "Out for Delivery", "Delivered", "Cancelled"]

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def add_column_if_missing(db, table, column, definition):
    cols = [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
          is_admin INTEGER NOT NULL DEFAULT 0, points INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS foods (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', price REAL NOT NULL CHECK(price>=0),
          category TEXT NOT NULL DEFAULT 'Main Course', image_url TEXT NOT NULL DEFAULT '',
          available INTEGER NOT NULL DEFAULT 1, tags TEXT NOT NULL DEFAULT '',
          is_veg INTEGER NOT NULL DEFAULT 1, spice_level INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
          customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL,
          total REAL NOT NULL, status TEXT NOT NULL DEFAULT 'Placed',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          coupon TEXT NOT NULL DEFAULT '', discount REAL NOT NULL DEFAULT 0,
          points_earned INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS order_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
          food_id INTEGER, food_name TEXT NOT NULL, price REAL NOT NULL,
          quantity INTEGER NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
          FOREIGN KEY(food_id) REFERENCES foods(id) ON DELETE SET NULL
        );
        """)
        for t, c, d in [
            ("users","points","INTEGER NOT NULL DEFAULT 0"),
            ("foods","tags","TEXT NOT NULL DEFAULT ''"),
            ("foods","is_veg","INTEGER NOT NULL DEFAULT 1"),
            ("foods","spice_level","INTEGER NOT NULL DEFAULT 1"),
            ("orders","coupon","TEXT NOT NULL DEFAULT ''"),
            ("orders","discount","REAL NOT NULL DEFAULT 0"),
            ("orders","points_earned","INTEGER NOT NULL DEFAULT 0")]:
            add_column_if_missing(db,t,c,d)
        if db.execute("SELECT COUNT(*) FROM foods").fetchone()[0] == 0:
            foods = [
             ("Chicken Biryani","Aromatic biryani with onion raita.",160,"Biryani","https://images.unsplash.com/photo-1563379091339-03246963d96c?w=900","spicy,hearty,lunch",0,3),
             ("Veg Fried Rice","Wok-tossed rice with fresh vegetables.",110,"Rice","https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=900","vegetarian,quick,lunch",1,1),
             ("Masala Dosa","Crispy dosa with potato masala and chutneys.",75,"South Indian","https://images.unsplash.com/photo-1668236543090-82eba5ee5976?w=900","vegetarian,comfort,breakfast",1,1),
             ("Paneer Butter Masala","Paneer in a rich tomato gravy.",180,"Curry","https://images.unsplash.com/photo-1631452180519-c014fe946bc7?w=900","vegetarian,creamy,hearty",1,1),
             ("Veg Burger","Veg patty, lettuce and house sauce.",90,"Fast Food","https://images.unsplash.com/photo-1520072959219-c595dc870360?w=900","vegetarian,quick,snack",1,2),
             ("French Fries","Golden crispy potato fries.",65,"Sides","https://images.unsplash.com/photo-1573080496219-bb080dd4f877?w=900","vegetarian,snack,quick",1,1),
             ("Chocolate Brownie","Rich chocolate brownie.",80,"Dessert","https://images.unsplash.com/photo-1606313564200-e75d5e30476c?w=900","sweet,dessert,comfort",1,1),
             ("Fresh Lime Juice","Refreshing lime drink.",45,"Drinks","https://images.unsplash.com/photo-1513558161293-cd6d2f2a4f0b?w=900","drink,refreshing,light",1,1),
             ("Chicken Noodles","Street-style chicken noodles.",140,"Noodles","https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=900","spicy,quick,hearty",0,3),
             ("Idli Sambar","Soft idlis with hot sambar.",55,"South Indian","https://images.unsplash.com/photo-1589301760014-d929f3979dbc?w=900","vegetarian,comfort,breakfast",1,1),
             ("Mushroom Pizza","Mushroom and cheese pizza.",190,"Pizza","https://images.unsplash.com/photo-1513104890138-7c749659a591?w=900","vegetarian,cheesy,snack",1,1),
             ("Grilled Chicken Bowl","Grilled chicken, rice and vegetables.",175,"Healthy","https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=900","protein,healthy,hearty",0,1)
            ]
            db.executemany("INSERT INTO foods(name,description,price,category,image_url,tags,is_veg,spice_level) VALUES(?,?,?,?,?,?,?,?)",foods)
        if not db.execute("SELECT id FROM users WHERE email=?",("admin@foodie.local",)).fetchone():
            db.execute("INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,1)",
                       ("Administrator","admin@foodie.local",generate_password_hash(os.environ.get("ADMIN_PASSWORD","Admin@123"))))
        db.commit()

def login_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get("user_id"):
            flash("Please sign in to continue.","info")
            return redirect(url_for("login", next=request.path))
        return fn(*a,**kw)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*a,**kw):
        if not session.get("is_admin"):
            flash("Administrator access required.","error")
            return redirect(url_for("index"))
        return fn(*a,**kw)
    return wrapped

@app.context_processor
def globals_for_templates():
    cart = session.get("cart", {})
    return {"cart_count":sum(int(v) for v in cart.values()), "current_user":session.get("user_name")}

@app.route("/")
def index():
    q=request.args.get("q","").strip()
    category=request.args.get("category","").strip()
    with get_db() as db:
        cats=[r["category"] for r in db.execute("SELECT DISTINCT category FROM foods WHERE available=1 ORDER BY category")]
        sql="SELECT * FROM foods WHERE available=1"; args=[]
        if q:
            sql+=" AND (name LIKE ? OR description LIKE ? OR tags LIKE ?)"; args += [f"%{q}%"]*3
        if category:
            sql+=" AND category=?"; args.append(category)
        foods=db.execute(sql+" ORDER BY id DESC",args).fetchall()
        recommended=db.execute("SELECT * FROM foods WHERE available=1 ORDER BY RANDOM() LIMIT 4").fetchall()
    return render_template("index.html",foods=foods,categories=cats,search=q,selected_category=category,recommended=recommended)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip().lower(); password=request.form.get("password","")
        if not name or "@" not in email or len(password)<6:
            flash("Enter a name, valid email, and password with at least 6 characters.","error")
        else:
            try:
                with get_db() as db:
                    db.execute("INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",(name,email,generate_password_hash(password))); db.commit()
                flash("Account created. Please sign in.","success"); return redirect(url_for("login"))
            except sqlite3.IntegrityError: flash("That email is already registered.","error")
    return render_template("auth.html",mode="register")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email","").strip().lower(); password=request.form.get("password","")
        with get_db() as db: user=db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if user and check_password_hash(user["password_hash"],password):
            session.clear(); session["user_id"]=user["id"]; session["user_name"]=user["name"]; session["is_admin"]=bool(user["is_admin"]); session["cart"]={}
            flash("Welcome back, "+user["name"]+"!","success")
            return redirect(url_for("admin_dashboard") if user["is_admin"] else url_for("index"))
        flash("Incorrect email or password.","error")
    return render_template("auth.html",mode="login")

@app.route("/logout")
def logout():
    session.clear(); flash("Signed out.","info"); return redirect(url_for("index"))

@app.route("/cart/add/<int:food_id>",methods=["POST"])
def add_to_cart(food_id):
    with get_db() as db: food=db.execute("SELECT id FROM foods WHERE id=? AND available=1",(food_id,)).fetchone()
    if not food: flash("Food is unavailable.","error")
    else:
        cart=session.get("cart",{}); key=str(food_id); cart[key]=min(int(cart.get(key,0))+1,99); session["cart"]=cart; flash("Added to cart.","success")
    return redirect(request.referrer or url_for("index"))

@app.route("/cart")
def cart():
    items=[]; subtotal=0
    with get_db() as db:
        for fid,qty in session.get("cart",{}).items():
            f=db.execute("SELECT * FROM foods WHERE id=? AND available=1",(int(fid),)).fetchone()
            if f:
                line=f["price"]*int(qty); subtotal+=line; items.append({"food":f,"qty":int(qty),"line":line})
    return render_template("cart.html",items=items,subtotal=subtotal)

@app.route("/cart/update",methods=["POST"])
def update_cart():
    cart={}
    for k,v in request.form.items():
        if k.startswith("qty_"):
            try:
                fid=int(k[4:]); qty=max(0,min(99,int(v)))
                if qty: cart[str(fid)]=qty
            except ValueError: pass
    session["cart"]=cart; flash("Cart updated.","success"); return redirect(url_for("cart"))

@app.route("/recommendations",methods=["GET","POST"])
def recommendations():
    mood=request.values.get("mood","comfort"); diet=request.values.get("diet","any"); spice=request.values.get("spice","any")
    with get_db() as db:
        foods=db.execute("SELECT * FROM foods WHERE available=1").fetchall()
    def score(f):
        tags=f["tags"].lower()
        points=2 if mood in tags else 0
        if mood=="comfort" and ("comfort" in tags or "hearty" in tags): points+=2
        if mood=="energy" and ("protein" in tags or "hearty" in tags): points+=2
        if diet=="veg": points += 3 if f["is_veg"] else -20
        if diet=="nonveg": points += 3 if not f["is_veg"] else -20
        if spice=="mild": points += 2 if f["spice_level"]<=1 else -1
        if spice=="spicy": points += 2 if f["spice_level"]>=2 else 0
        return points
    foods=sorted(foods,key=score,reverse=True)[:6]
    return render_template("recommendations.html",foods=foods,mood=mood,diet=diet,spice=spice)

@app.route("/budget",methods=["GET","POST"])
def budget():
    amount=request.values.get("amount","150")
    try: amount=max(1,min(10000,float(amount)))
    except ValueError: amount=150
    with get_db() as db: foods=db.execute("SELECT * FROM foods WHERE available=1 AND price<=? ORDER BY price",(amount,)).fetchall()
    # A simple, transparent budget finder: individual options and low-cost combos.
    combos=[]
    for f in foods:
        if f["price"]<=amount: combos.append({"items":[f],"total":f["price"]})
    for i,a in enumerate(foods):
        for b in foods[i+1:]:
            total=a["price"]+b["price"]
            if total<=amount: combos.append({"items":[a,b],"total":total})
    combos=sorted(combos,key=lambda x:(-len(x["items"]),x["total"]))[:8]
    return render_template("budget.html",amount=int(amount),foods=foods,combos=combos)

@app.route("/checkout",methods=["GET","POST"])
@login_required
def checkout():
    items=[]; subtotal=0
    with get_db() as db:
        for fid,qty in session.get("cart",{}).items():
            f=db.execute("SELECT * FROM foods WHERE id=? AND available=1",(int(fid),)).fetchone()
            if f:
                line=f["price"]*int(qty); subtotal+=line; items.append({"food":f,"qty":int(qty),"line":line})
    if not items: flash("Your cart is empty.","info"); return redirect(url_for("index"))
    if request.method=="POST":
        name=request.form.get("name","").strip(); phone=request.form.get("phone","").strip(); address=request.form.get("address","").strip()
        coupon=request.form.get("coupon","").strip().upper()
        if not name or not phone or not address:
            flash("Please complete all delivery details.","error")
        else:
            discount=0
            if coupon=="WELCOME10": discount=round(subtotal*0.10,2)
            elif coupon=="FOOD5": discount=5.0 if subtotal>=100 else 0
            elif coupon: flash("Coupon not recognised or minimum order not met.","error")
            discount=min(discount,subtotal); total=round(subtotal-discount,2); earned=int(total//10)
            with get_db() as db:
                cur=db.execute("INSERT INTO orders(user_id,customer_name,phone,address,total,status,coupon,discount,points_earned) VALUES(?,?,?,?,?,'Placed',?,?,?)",
                    (session["user_id"],name,phone,address,total,coupon if discount else "",discount,earned))
                oid=cur.lastrowid
                for item in items:
                    f=item["food"]; db.execute("INSERT INTO order_items(order_id,food_id,food_name,price,quantity) VALUES(?,?,?,?,?)",(oid,f["id"],f["name"],f["price"],item["qty"]))
                db.execute("UPDATE users SET points=points+? WHERE id=?",(earned,session["user_id"]))
                db.commit()
            session["cart"]={}; flash(f"Order #{oid} placed! You earned {earned} reward points.","success"); return redirect(url_for("order_detail",order_id=oid))
    return render_template("checkout.html",items=items,subtotal=subtotal)

@app.route("/orders")
@login_required
def orders():
    with get_db() as db:
        rows=db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY id DESC",(session["user_id"],)).fetchall()
    return render_template("orders.html",orders=rows)

@app.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    with get_db() as db:
        order=db.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(order_id,session["user_id"])).fetchone()
        if not order: flash("Order not found.","error"); return redirect(url_for("orders"))
        items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    return render_template("order_detail.html",order=order,items=items,statuses=STATUSES)

@app.route("/orders/<int:order_id>/invoice")
@login_required
def invoice(order_id):
    with get_db() as db:
        order=db.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(order_id,session["user_id"])).fetchone()
        if not order: return "Invoice not found",404
        items=db.execute("SELECT * FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    return render_template("invoice.html",order=order,items=items)

@app.route("/rewards")
@login_required
def rewards():
    with get_db() as db:
        user=db.execute("SELECT points FROM users WHERE id=?",(session["user_id"],)).fetchone()
        history=db.execute("SELECT id,created_at,total,points_earned FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10",(session["user_id"],)).fetchall()
    return render_template("rewards.html",points=user["points"],history=history)

@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    with get_db() as db:
        stats={
          "orders":db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
          "revenue":db.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status!='Cancelled'").fetchone()[0],
          "customers":db.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0],
          "foods":db.execute("SELECT COUNT(*) FROM foods").fetchone()[0],
        }
        orders=db.execute("SELECT o.*,u.email FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC LIMIT 30").fetchall()
        foods=db.execute("SELECT * FROM foods ORDER BY id DESC").fetchall()
        popular=db.execute("SELECT food_name,SUM(quantity) qty,SUM(price*quantity) sales FROM order_items GROUP BY food_name ORDER BY qty DESC LIMIT 5").fetchall()
        daily=db.execute("SELECT substr(created_at,1,10) day, SUM(total) revenue FROM orders WHERE status!='Cancelled' GROUP BY day ORDER BY day DESC LIMIT 7").fetchall()
    return render_template("admin.html",stats=stats,orders=orders,foods=foods,popular=popular,daily=list(reversed(daily)),statuses=STATUSES)

@app.route("/admin/food",methods=["POST"])
@login_required
@admin_required
def admin_add_food():
    name=request.form.get("name","").strip(); description=request.form.get("description","").strip()
    try: price=float(request.form.get("price","0")); spice=max(1,min(3,int(request.form.get("spice_level","1"))))
    except ValueError: price=0; spice=1
    category=request.form.get("category","Main Course").strip() or "Main Course"
    image_url=request.form.get("image_url","").strip(); tags=request.form.get("tags","").strip(); is_veg=1 if request.form.get("is_veg")=="on" else 0
    if name and price>=0:
        with get_db() as db:
            db.execute("INSERT INTO foods(name,description,price,category,image_url,tags,is_veg,spice_level) VALUES(?,?,?,?,?,?,?,?)",(name,description,price,category,image_url,tags,is_veg,spice)); db.commit()
        flash("Food item added.","success")
    else: flash("Enter a food name and valid price.","error")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/food/<int:food_id>/toggle",methods=["POST"])
@login_required
@admin_required
def admin_toggle_food(food_id):
    with get_db() as db:
        db.execute("UPDATE foods SET available=CASE available WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(food_id,)); db.commit()
    flash("Food availability updated.","success"); return redirect(url_for("admin_dashboard"))

@app.route("/admin/order/<int:order_id>",methods=["POST"])
@login_required
@admin_required
def admin_update_order(order_id):
    status=request.form.get("status","Placed")
    if status not in STATUSES: status="Placed"
    with get_db() as db:
        db.execute("UPDATE orders SET status=? WHERE id=?",(status,order_id)); db.commit()
    flash(f"Order #{order_id} updated to {status}.","success"); return redirect(url_for("admin_dashboard"))

@app.errorhandler(404)
def not_found(_): return render_template("404.html"),404

# IMPORTANT: initialize schema on import too, so Render/Gunicorn gets tables.
init_db()

if __name__=="__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG")=="1", host="0.0.0.0", port=int(os.environ.get("PORT",5000)))
