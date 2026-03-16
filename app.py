from __future__ import annotations

from datetime import datetime, date, time
import random

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from functools import wraps

app = Flask(__name__)

# MySQL connection
# Update username, password, host if needed
app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root:password@localhost/proj_db"
app.config["SECRET_KEY"] = "your-secret-key-here"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

bcrypt = Bcrypt(app)


# Models
class Users(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)
    role = db.Column(db.String(50), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CashAccount(db.Model):
    __tablename__ = "cash_accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    balance = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Stock(db.Model):
    __tablename__ = "stocks"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False)
    ticker = db.Column(db.String(10), unique=True, nullable=False)

    price = db.Column(db.Numeric(12, 2), nullable=False)
    volume = db.Column(db.Integer, nullable=False)

    open_price = db.Column(db.Numeric(12, 2), nullable=False)
    high_price = db.Column(db.Numeric(12, 2), nullable=False)
    low_price = db.Column(db.Numeric(12, 2), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Holding(db.Model):
    __tablename__ = "holdings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False)

    shares = db.Column(db.Integer, default=0, nullable=False)
    avg_cost = db.Column(db.Numeric(12, 2), default=0, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "stock_id", name="uniq_user_stock"),)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=False)

    side = db.Column(db.String(10), nullable=False)  # buy or sell
    shares = db.Column(db.Integer, nullable=False)

    price_at_submit = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, executed, canceled

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    executed_at = db.Column(db.DateTime, nullable=True)


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    txn_type = db.Column(db.String(20), nullable=False)  # buy, sell, deposit, withdraw
    amount = db.Column(db.Numeric(12, 2), nullable=False)

    stock_id = db.Column(db.Integer, db.ForeignKey("stocks.id"), nullable=True)
    shares = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Numeric(12, 2), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class MarketSettings(db.Model):
    __tablename__ = "market_settings"

    id = db.Column(db.Integer, primary_key=True)

    open_time = db.Column(db.String(5), default="09:30", nullable=False)
    close_time = db.Column(db.String(5), default="16:00", nullable=False)

    mon = db.Column(db.Boolean, default=True, nullable=False)
    tue = db.Column(db.Boolean, default=True, nullable=False)
    wed = db.Column(db.Boolean, default=True, nullable=False)
    thu = db.Column(db.Boolean, default=True, nullable=False)
    fri = db.Column(db.Boolean, default=True, nullable=False)
    sat = db.Column(db.Boolean, default=False, nullable=False)
    sun = db.Column(db.Boolean, default=False, nullable=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MarketHoliday(db.Model):
    __tablename__ = "market_holidays"

    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.Date, unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=True)


@login_manager.user_loader
def load_user(user_id: str):
    return Users.query.get(int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


def get_market_settings() -> MarketSettings:
    settings = MarketSettings.query.first()
    if settings:
        return settings

    settings = MarketSettings()
    db.session.add(settings)
    db.session.commit()
    return settings


def parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(hour=int(hh), minute=int(mm))
    except Exception:
        return time(9, 30)


def is_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    settings = get_market_settings()

    weekday = now.weekday()  # 0 Monday
    weekday_open = [settings.mon, settings.tue, settings.wed, settings.thu, settings.fri, settings.sat, settings.sun]
    if not weekday_open[weekday]:
        return False

    if MarketHoliday.query.filter_by(day=now.date()).first() is not None:
        return False

    open_t = parse_hhmm(settings.open_time)
    close_t = parse_hhmm(settings.close_time)
    now_t = now.time()

    return open_t <= now_t <= close_t


def ensure_cash_account(user_id: int) -> CashAccount:
    acct = CashAccount.query.filter_by(user_id=user_id).first()
    if acct:
        return acct

    acct = CashAccount(user_id=user_id, balance=0)
    db.session.add(acct)
    db.session.commit()
    return acct


def update_stock_prices():
    """Simple random price generator.
    Called on stock listing and on home page.

    It changes prices by a small random percent and updates high and low.
    """

    stocks = Stock.query.all()
    if not stocks:
        return

    for s in stocks:
        current = float(s.price)
        change = random.uniform(-0.012, 0.012)
        new_price = max(0.01, round(current * (1 + change), 2))

        s.price = new_price
        s.high_price = max(float(s.high_price), new_price)
        s.low_price = min(float(s.low_price), new_price)

    db.session.commit()


with app.app_context():
    db.create_all()

    # Create default admin if missing
    if Users.query.filter_by(username="admin").first() is None:
        admin = Users(
            full_name="System Admin",
            username="admin",
            email="admin@example.com",
            password=bcrypt.generate_password_hash("admin123").decode("utf-8"),
            role="admin",
        )
        db.session.add(admin)
        db.session.commit()
        ensure_cash_account(admin.id)


# Auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        if not full_name or not username or not email or not password:
            flash("Please fill out all fields.", "warning")
            return redirect(url_for("register"))

        if Users.query.filter_by(username=username).first() is not None:
            return redirect(url_for("register", error="exists"))

        if Users.query.filter_by(email=email).first() is not None:
            return redirect(url_for("register", error="email"))

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        user = Users(full_name=full_name, username=username, email=email, password=hashed_password, role="user")
        db.session.add(user)
        db.session.commit()

        ensure_cash_account(user.id)

        flash("Account created. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("sign_up.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = Users.query.filter_by(username=username).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for("home"))

        return redirect(url_for("login", error="invalid"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# Home
@app.route("/")
@login_required
def home():
    update_stock_prices()

    market_open = is_market_open()

    if current_user.role == "admin":
        users = Users.query.order_by(Users.id.asc()).all()
        settings = get_market_settings()
        holidays = MarketHoliday.query.order_by(MarketHoliday.day.asc()).all()
        return render_template(
            "home.html",
            market_open=market_open,
            users=users,
            settings=settings,
            holidays=holidays,
        )

    acct = ensure_cash_account(current_user.id)

    holdings = (
        db.session.query(Holding, Stock)
        .join(Stock, Holding.stock_id == Stock.id)
        .filter(Holding.user_id == current_user.id)
        .all()
    )

    portfolio_value = 0.0
    holdings_rows = []
    for h, s in holdings:
        value = float(s.price) * int(h.shares)
        portfolio_value += value
        holdings_rows.append(
            {
                "ticker": s.ticker,
                "shares": int(h.shares),
                "price": f"{float(s.price):.2f}",
                "value": f"{value:.2f}",
            }
        )

    open_orders_count = Order.query.filter_by(user_id=current_user.id, status="pending").count()

    stocks = Stock.query.order_by(Stock.ticker.asc()).limit(8).all()
    stocks_rows = []
    for s in stocks:
        market_cap = float(s.price) * int(s.volume)
        stocks_rows.append(
            {
                "ticker": s.ticker,
                "company_name": s.company_name,
                "price": f"{float(s.price):.2f}",
                "volume": int(s.volume),
                "market_cap": f"{market_cap:.2f}",
                "open_price": f"{float(s.open_price):.2f}",
                "high_price": f"{float(s.high_price):.2f}",
                "low_price": f"{float(s.low_price):.2f}",
            }
        )

    recent_txns = (
        Transaction.query.filter_by(user_id=current_user.id)
        .order_by(Transaction.created_at.desc())
        .limit(5)
        .all()
    )

    recent_rows = []
    for t in recent_txns:
        recent_rows.append(
            {
                "type": t.txn_type,
                "amount": f"{float(t.amount):.2f}",
                "timestamp": t.created_at.strftime("%m/%d/%Y %I:%M %p"),
            }
        )

    return render_template(
        "home.html",
        market_open=market_open,
        cash_balance=f"{float(acct.balance):.2f}",
        portfolio_value=f"{portfolio_value:.2f}",
        open_orders_count=open_orders_count,
        holdings=holdings_rows,
        stocks=stocks_rows,
        recent_transactions=recent_rows,
    )


# Customer pages
@app.route("/stocks")
@login_required
def stocks():
    update_stock_prices()
    market_open = is_market_open()

    rows = []
    for s in Stock.query.order_by(Stock.ticker.asc()).all():
        rows.append(
            {
                "ticker": s.ticker,
                "company_name": s.company_name,
                "price": f"{float(s.price):.2f}",
                "volume": int(s.volume),
                "market_cap": f"{float(s.price) * int(s.volume):.2f}",
                "open_price": f"{float(s.open_price):.2f}",
                "high_price": f"{float(s.high_price):.2f}",
                "low_price": f"{float(s.low_price):.2f}",
            }
        )

    return render_template("stocks.html", market_open=market_open, stocks=rows)


@app.route("/portfolio")
@login_required
def portfolio():
    acct = ensure_cash_account(current_user.id)

    holdings = (
        db.session.query(Holding, Stock)
        .join(Stock, Holding.stock_id == Stock.id)
        .filter(Holding.user_id == current_user.id)
        .all()
    )

    rows = []
    total = 0.0
    for h, s in holdings:
        value = float(s.price) * int(h.shares)
        total += value
        rows.append(
            {
                "ticker": s.ticker,
                "company_name": s.company_name,
                "shares": int(h.shares),
                "avg_cost": f"{float(h.avg_cost):.2f}",
                "price": f"{float(s.price):.2f}",
                "value": f"{value:.2f}",
            }
        )

    return render_template(
        "portfolio.html",
        cash_balance=f"{float(acct.balance):.2f}",
        portfolio_value=f"{total:.2f}",
        holdings=rows,
    )


@app.route("/transactions")
@login_required
def transactions():
    txns = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.created_at.desc()).all()

    rows = []
    for t in txns:
        rows.append(
            {
                "type": t.txn_type,
                "amount": f"{float(t.amount):.2f}",
                "details": "" if t.stock_id is None else f"Stock ID {t.stock_id}"
                if t.shares is None
                else f"{t.shares} shares",
                "timestamp": t.created_at.strftime("%m/%d/%Y %I:%M %p"),
            }
        )

    return render_template("transactions.html", transactions=rows)


@app.route("/deposit", methods=["GET", "POST"])
@login_required
def deposit():
    acct = ensure_cash_account(current_user.id)

    if request.method == "POST":
        amount_str = (request.form.get("amount") or "").strip()
        try:
            amount = round(float(amount_str), 2)
        except Exception:
            flash("Enter a valid amount.", "warning")
            return redirect(url_for("deposit"))

        if amount <= 0:
            flash("Amount must be greater than 0.", "warning")
            return redirect(url_for("deposit"))

        acct.balance = float(acct.balance) + amount
        db.session.add(Transaction(user_id=current_user.id, txn_type="deposit", amount=amount))
        db.session.commit()

        flash("Deposit completed.", "success")
        return redirect(url_for("portfolio"))

    return render_template("deposit.html", cash_balance=f"{float(acct.balance):.2f}")


@app.route("/withdraw", methods=["GET", "POST"])
@login_required
def withdraw():
    acct = ensure_cash_account(current_user.id)

    if request.method == "POST":
        amount_str = (request.form.get("amount") or "").strip()
        try:
            amount = round(float(amount_str), 2)
        except Exception:
            flash("Enter a valid amount.", "warning")
            return redirect(url_for("withdraw"))

        if amount <= 0:
            flash("Amount must be greater than 0.", "warning")
            return redirect(url_for("withdraw"))

        if float(acct.balance) < amount:
            flash("Insufficient funds in cash account.", "danger")
            return redirect(url_for("withdraw"))

        acct.balance = float(acct.balance) - amount
        db.session.add(Transaction(user_id=current_user.id, txn_type="withdraw", amount=amount))
        db.session.commit()

        flash("Withdrawal completed.", "success")
        return redirect(url_for("portfolio"))

    return render_template("withdraw.html", cash_balance=f"{float(acct.balance):.2f}")


@app.route("/buy/<ticker>", methods=["GET", "POST"])
@login_required
def buy(ticker: str):
    if not is_market_open():
        flash("Market is closed. Trades can only be placed during market hours.", "danger")
        return redirect(url_for("stocks"))

    stock = Stock.query.filter_by(ticker=ticker.upper()).first_or_404()
    acct = ensure_cash_account(current_user.id)

    if request.method == "POST":
        shares_str = (request.form.get("shares") or "").strip()
        try:
            shares = int(shares_str)
        except Exception:
            flash("Enter a valid number of shares.", "warning")
            return redirect(url_for("buy", ticker=ticker))

        if shares <= 0:
            flash("Shares must be greater than 0.", "warning")
            return redirect(url_for("buy", ticker=ticker))

        cost = float(stock.price) * shares
        if float(acct.balance) < cost:
            flash("Insufficient cash balance.", "danger")
            return redirect(url_for("buy", ticker=ticker))

        order = Order(
            user_id=current_user.id,
            stock_id=stock.id,
            side="buy",
            shares=shares,
            price_at_submit=stock.price,
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        flash("Order placed. You can cancel it before execution.", "success")
        return redirect(url_for("orders"))

    est_cost = float(stock.price)
    return render_template(
        "buy.html",
        stock={"ticker": stock.ticker, "company_name": stock.company_name, "price": f"{float(stock.price):.2f}"},
        cash_balance=f"{float(acct.balance):.2f}",
        est_cost=f"{est_cost:.2f}",
    )


@app.route("/sell/<ticker>", methods=["GET", "POST"])
@login_required
def sell(ticker: str):
    if not is_market_open():
        flash("Market is closed. Trades can only be placed during market hours.", "danger")
        return redirect(url_for("stocks"))

    stock = Stock.query.filter_by(ticker=ticker.upper()).first_or_404()

    holding = Holding.query.filter_by(user_id=current_user.id, stock_id=stock.id).first()
    owned = int(holding.shares) if holding else 0

    if request.method == "POST":
        shares_str = (request.form.get("shares") or "").strip()
        try:
            shares = int(shares_str)
        except Exception:
            flash("Enter a valid number of shares.", "warning")
            return redirect(url_for("sell", ticker=ticker))

        if shares <= 0:
            flash("Shares must be greater than 0.", "warning")
            return redirect(url_for("sell", ticker=ticker))

        if shares > owned:
            flash("You do not have enough shares to sell.", "danger")
            return redirect(url_for("sell", ticker=ticker))

        order = Order(
            user_id=current_user.id,
            stock_id=stock.id,
            side="sell",
            shares=shares,
            price_at_submit=stock.price,
            status="pending",
        )
        db.session.add(order)
        db.session.commit()

        flash("Sell order placed. You can cancel it before execution.", "success")
        return redirect(url_for("orders"))

    return render_template(
        "sell.html",
        stock={"ticker": stock.ticker, "company_name": stock.company_name, "price": f"{float(stock.price):.2f}"},
        owned=owned,
    )


@app.route("/orders")
@login_required
def orders():
    rows = (
        db.session.query(Order, Stock)
        .join(Stock, Order.stock_id == Stock.id)
        .filter(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )

    out = []
    for o, s in rows:
        out.append(
            {
                "id": o.id,
                "type": o.side,
                "ticker": s.ticker,
                "shares": int(o.shares),
                "price": f"{float(o.price_at_submit):.2f}",
                "status": o.status,
                "created_at": o.created_at.strftime("%m/%d/%Y %I:%M %p"),
            }
        )

    return render_template("orders.html", orders=out)


@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel_order(order_id: int):
    order = Order.query.filter_by(id=order_id, user_id=current_user.id).first_or_404()

    if order.status != "pending":
        flash("Only pending orders can be canceled.", "warning")
        return redirect(url_for("orders"))

    order.status = "canceled"
    db.session.commit()
    flash("Order canceled.", "success")
    return redirect(url_for("orders"))


# Admin executes pending orders to demonstrate cancel before execution
@app.route("/admin/orders/execute", methods=["POST"])
@login_required
@admin_required
def execute_orders_admin():
    if not is_market_open():
        flash("Market is closed. Cannot execute orders right now.", "danger")
        return redirect(url_for("home"))

    pending = Order.query.filter_by(status="pending").order_by(Order.created_at.asc()).all()
    if not pending:
        flash("No pending orders to execute.", "warning")
        return redirect(url_for("home"))

    executed_count = 0

    for order in pending:
        stock = Stock.query.get(order.stock_id)
        if stock is None:
            order.status = "canceled"
            continue

        user_acct = ensure_cash_account(order.user_id)
        holding = Holding.query.filter_by(user_id=order.user_id, stock_id=stock.id).first()

        market_price = float(stock.price)
        shares = int(order.shares)

        if order.side == "buy":
            cost = market_price * shares
            if float(user_acct.balance) < cost:
                order.status = "canceled"
                continue

            if stock.volume < shares:
                order.status = "canceled"
                continue

            user_acct.balance = float(user_acct.balance) - cost
            stock.volume = int(stock.volume) - shares

            if holding is None:
                holding = Holding(user_id=order.user_id, stock_id=stock.id, shares=shares, avg_cost=market_price)
                db.session.add(holding)
            else:
                prev_shares = int(holding.shares)
                prev_cost = float(holding.avg_cost)
                new_total_shares = prev_shares + shares
                new_avg = ((prev_shares * prev_cost) + (shares * market_price)) / new_total_shares
                holding.shares = new_total_shares
                holding.avg_cost = round(new_avg, 2)

            db.session.add(
                Transaction(
                    user_id=order.user_id,
                    txn_type="buy",
                    amount=round(cost, 2),
                    stock_id=stock.id,
                    shares=shares,
                    price=market_price,
                )
            )

        elif order.side == "sell":
            if holding is None or int(holding.shares) < shares:
                order.status = "canceled"
                continue

            proceeds = market_price * shares
            holding.shares = int(holding.shares) - shares
            if int(holding.shares) == 0:
                db.session.delete(holding)

            stock.volume = int(stock.volume) + shares
            user_acct.balance = float(user_acct.balance) + proceeds

            db.session.add(
                Transaction(
                    user_id=order.user_id,
                    txn_type="sell",
                    amount=round(proceeds, 2),
                    stock_id=stock.id,
                    shares=shares,
                    price=market_price,
                )
            )

        order.status = "executed"
        order.executed_at = datetime.utcnow()
        executed_count += 1

    db.session.commit()

    flash(f"Executed {executed_count} orders.", "success")
    return redirect(url_for("home"))


# Admin pages
@app.route("/admin/stocks/create", methods=["GET", "POST"])
@login_required
@admin_required
def create_stock():
    if request.method == "POST":
        company_name = (request.form.get("company_name") or "").strip()
        ticker = (request.form.get("ticker") or "").strip().upper()
        volume_str = (request.form.get("volume") or "").strip()
        price_str = (request.form.get("initial_price") or "").strip()

        if not company_name or not ticker or not volume_str or not price_str:
            flash("Please fill out all fields.", "warning")
            return redirect(url_for("create_stock"))

        if Stock.query.filter_by(ticker=ticker).first() is not None:
            flash("Ticker already exists.", "danger")
            return redirect(url_for("create_stock"))

        try:
            volume = int(volume_str)
            price = round(float(price_str), 2)
        except Exception:
            flash("Enter valid volume and price.", "warning")
            return redirect(url_for("create_stock"))

        if volume <= 0 or price <= 0:
            flash("Volume and price must be greater than 0.", "warning")
            return redirect(url_for("create_stock"))

        s = Stock(
            company_name=company_name,
            ticker=ticker,
            volume=volume,
            price=price,
            open_price=price,
            high_price=price,
            low_price=price,
        )
        db.session.add(s)
        db.session.commit()

        flash("Stock created.", "success")
        return redirect(url_for("stocks"))

    return render_template("admin_create_stock.html")


@app.route("/admin/market-hours", methods=["GET", "POST"])
@login_required
@admin_required
def market_hours():
    settings = get_market_settings()

    if request.method == "POST":
        open_time_val = (request.form.get("open_time") or "").strip()
        close_time_val = (request.form.get("close_time") or "").strip()

        if open_time_val:
            settings.open_time = open_time_val
        if close_time_val:
            settings.close_time = close_time_val

        db.session.commit()
        flash("Market hours updated.", "success")
        return redirect(url_for("home"))

    return render_template("admin_market_hours.html", settings=settings)


@app.route("/admin/market-schedule", methods=["GET", "POST"])
@login_required
@admin_required
def market_schedule():
    settings = get_market_settings()

    if request.method == "POST":
        settings.mon = request.form.get("mon") == "on"
        settings.tue = request.form.get("tue") == "on"
        settings.wed = request.form.get("wed") == "on"
        settings.thu = request.form.get("thu") == "on"
        settings.fri = request.form.get("fri") == "on"
        settings.sat = request.form.get("sat") == "on"
        settings.sun = request.form.get("sun") == "on"

        db.session.commit()
        flash("Market schedule updated.", "success")
        return redirect(url_for("market_schedule"))

    holidays = MarketHoliday.query.order_by(MarketHoliday.day.asc()).all()
    return render_template("admin_market_schedule.html", settings=settings, holidays=holidays)


@app.route("/admin/holidays/add", methods=["POST"])
@login_required
@admin_required
def add_holiday():
    day_str = (request.form.get("day") or "").strip()
    name = (request.form.get("name") or "").strip()

    try:
        y, m, d = [int(x) for x in day_str.split("-")]
        day_val = date(y, m, d)
    except Exception:
        flash("Enter a valid date in YYYY-MM-DD.", "warning")
        return redirect(url_for("market_schedule"))

    if MarketHoliday.query.filter_by(day=day_val).first() is not None:
        flash("Holiday already exists.", "warning")
        return redirect(url_for("market_schedule"))

    db.session.add(MarketHoliday(day=day_val, name=name or None))
    db.session.commit()
    flash("Holiday added.", "success")
    return redirect(url_for("market_schedule"))


@app.route("/admin/holidays/<int:holiday_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_holiday(holiday_id: int):
    h = MarketHoliday.query.get_or_404(holiday_id)
    db.session.delete(h)
    db.session.commit()
    flash("Holiday removed.", "success")
    return redirect(url_for("market_schedule"))


if __name__ == "__main__":
    app.run(debug=True)
