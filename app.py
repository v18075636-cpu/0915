import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
DATABASE = Path(__file__).with_name("memo.db")


@contextmanager
def connect_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


with connect_db() as connection:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("secret_key", secrets.token_hex(32)),
    )
    secret_key = connection.execute(
        "SELECT value FROM settings WHERE key = ?", ("secret_key",)
    ).fetchone()["value"]

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secret_key,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",
    MAX_CONTENT_LENGTH=16 * 1024,
)

PAGE = """
<!doctype html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }} | 메모 서비스</title>
    <style>
        body { max-width: 400px; margin: 60px auto; padding: 0 20px; font-family: sans-serif; }
        label { display: block; margin-top: 16px; }
        input { box-sizing: border-box; width: 100%; padding: 10px; margin-top: 6px; }
        button { margin-top: 20px; padding: 10px 20px; cursor: pointer; }
        .message { padding: 12px; background: #f1f1f1; }
    </style>
</head>
<body>
    <h1>메모 서비스</h1>
    <h2>{{ title }}</h2>
    {% for message in get_flashed_messages() %}
        <p class="message" role="status">{{ message }}</p>
    {% endfor %}
    {% if user %}
        <p>{{ user['username'] }}님, 환영합니다.</p>
        <form method="post" action="{{ url_for('logout') }}">
            <input type="hidden" name="csrf_token" value="{{ session['csrf_token'] }}">
            <button type="submit">로그아웃</button>
        </form>
    {% else %}
        <form method="post">
            <input type="hidden" name="csrf_token" value="{{ session['csrf_token'] }}">
            <label for="username">아이디</label>
            <input id="username" name="username" required maxlength="50"
                   autocomplete="username" value="{{ request.form.get('username', '') }}">
            <label for="password">비밀번호{% if registering %} (8자 이상){% endif %}</label>
            <input id="password" name="password" type="password" required maxlength="128"
                   {% if registering %}minlength="8"{% endif %}
                   autocomplete="{{ 'new-password' if registering else 'current-password' }}">
            <button type="submit">{{ title }}</button>
        </form>
        <p><a href="{{ url_for('login' if registering else 'register') }}">
            {{ '로그인으로 이동' if registering else '회원가입' }}
        </a></p>
    {% endif %}
</body>
</html>
"""


@app.before_request
def protect_forms():
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        received = request.form.get("csrf_token", "")
        if not expected or not hmac.compare_digest(expected.encode("utf-8"), received.encode("utf-8")):
            return "잘못된 요청입니다. 페이지를 새로고침하고 다시 시도하세요.", 400
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)


def current_user():
    with connect_db() as connection:
        return connection.execute(
            "SELECT id, username FROM users WHERE id = ?", (session.get("user_id"),)
        ).fetchone()


@app.route("/")
def index():
    user = current_user()
    if user is None:
        return redirect(url_for("login"))
    return render_template_string(PAGE, title="홈", user=user)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not 1 <= len(username) <= 50 or not 8 <= len(password) <= 128:
            flash("아이디는 1~50자, 비밀번호는 8~128자로 입력하세요.")
        else:
            try:
                with connect_db() as connection:
                    connection.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
            except sqlite3.IntegrityError:
                flash("이미 사용 중인 아이디입니다.")
            else:
                flash("회원가입이 완료되었습니다. 로그인해 주세요.")
                return redirect(url_for("login"))
    return render_template_string(PAGE, title="회원가입", registering=True, user=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if user and len(password) <= 128 and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(url_for("index"))
        flash("아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template_string(PAGE, title="로그인", registering=False, user=None)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run()
