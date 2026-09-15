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
        :root { color-scheme: light; --ink: #263e3a; --paper: #f7f2df; --orange: #f16b3e; }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100svh; color: var(--ink); background: #e9e5d4;
            background-image: radial-gradient(#bdbca9 .8px, transparent .8px);
            background-size: 8px 8px; font-family: "Courier New", "Malgun Gothic", monospace; }
        a { color: inherit; text-underline-offset: 5px; }
        .topbar { min-height: 66px; padding: 16px 5%; display: flex; justify-content: space-between;
            align-items: center; gap: 16px; border-bottom: 2px solid var(--ink); background: var(--paper); }
        .brand { font-weight: 900; font-size: 22px; letter-spacing: -1px; text-decoration: none; }
        .brand span { color: #b93f1a; }
        .edition { font-size: 11px; letter-spacing: 2px; }
        main { width: min(1040px, 90%); margin: 76px auto; display: grid;
            grid-template-columns: 1fr 440px; align-items: center; gap: 70px; }
        .eyebrow { font-size: 12px; font-weight: bold; letter-spacing: 2px; }
        .tag { display: inline-block; padding: 7px 11px; border: 1px solid var(--ink); background: #e5ebce; }
        h1 { margin: 22px 0; font-size: clamp(48px, 6vw, 76px); line-height: 1.06; letter-spacing: -5px; }
        h1 em { color: #b93f1a; font-style: normal; }
        .intro { font-size: 14px; line-height: 1.9; }
        .computer { width: 210px; margin: 36px 0 24px; transform: rotate(-4deg); }
        .monitor { padding: 13px 13px 9px; border: 2px solid var(--ink); background: #d2cfb8;
            box-shadow: 6px 6px 0 #263e3a; border-radius: 9px; }
        .screen { padding: 21px 16px; border: 2px solid var(--ink); color: #d6efa9; background: #263e3a;
            font-size: 14px; line-height: 1.7; background-image: repeating-linear-gradient(0deg, transparent 0 3px, #ffffff08 3px 4px); }
        .monitor-label { font-size: 9px; margin-top: 8px; text-align: right; letter-spacing: 2px; }
        .stand { width: 66px; height: 16px; margin: auto; border: 2px solid var(--ink); border-top: 0; background: #b6b59c; }
        .keyboard { height: 17px; border: 2px solid var(--ink); background: repeating-linear-gradient(90deg, #d2cfb8 0 12px, #263e3a 12px 14px); box-shadow: 4px 4px 0 var(--ink); }
        .footnote { font-size: 10px; letter-spacing: 1px; }
        .window { border: 2px solid var(--ink); background: var(--paper); box-shadow: 8px 8px 0 var(--ink); }
        .titlebar { display: flex; justify-content: space-between; align-items: center; padding: 11px 14px;
            background: var(--ink); color: var(--paper); font-size: 11px; letter-spacing: 1px; }
        .window-controls { letter-spacing: 5px; }
        .window-body { padding: 32px; }
        .step { font-size: 10px; color: #5b6860; letter-spacing: 2px; }
        h2 { font-size: 28px; letter-spacing: -1px; margin: 13px 0 10px; }
        .subtitle { font-size: 12px; line-height: 1.8; margin: 0 0 25px; color: #56625b; }
        label { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; font-weight: bold; margin-top: 20px; }
        label span { font-size: 10px; font-weight: normal; color: #616b61; }
        input:not([type=hidden]) { width: 100%; min-height: 47px; padding: 12px; margin-top: 8px;
            border: 2px solid var(--ink); border-radius: 0; background: #fffdf3; color: var(--ink);
            font: inherit; font-size: 14px; box-shadow: inset 3px 3px 0 #e7e4d6; }
        input::placeholder { color: #74786b; font-size: 12px; }
        :focus-visible { outline: 3px solid #b93f1a; outline-offset: 4px; }
        button { width: 100%; margin-top: 26px; padding: 14px 18px; border: 2px solid var(--ink);
            background: var(--orange); color: #172c28; box-shadow: 4px 4px 0 var(--ink);
            font: inherit; font-size: 14px; font-weight: bold; cursor: pointer;
            display: flex; align-items: center; justify-content: space-between; }
        button:hover { background: #ff8357; }
        button:active { transform: translate(3px, 3px); box-shadow: 1px 1px 0 var(--ink); }
        .switch { text-align: center; font-size: 12px; margin: 25px 0 0; line-height: 2; }
        .switch a { font-weight: bold; }
        .statusbar { display: flex; justify-content: space-between; padding: 12px 15px;
            border-top: 2px solid var(--ink); background: #e5e5d2; font-size: 10px; }
        .status-dot { display: inline-block; width: 7px; height: 7px; background: #326b45; margin-right: 6px; }
        .message { padding: 12px; border: 1px dashed var(--ink); background: #f6dfae; font-size: 12px; line-height: 1.8; overflow-wrap: anywhere; }
        .welcome { padding: 22px 16px; border: 2px dashed #859080; background: #e9ecd9;
            line-height: 1.9; font-size: 14px; overflow-wrap: anywhere; }
        footer { width: 90%; margin: 0 auto 25px; padding-top: 18px; border-top: 1px solid #919887;
            display: flex; justify-content: space-between; gap: 12px; font-size: 10px; letter-spacing: 1px; }
        @media (max-width: 800px) {
            main { grid-template-columns: 1fr; max-width: 460px; gap: 30px; margin: 36px auto 44px; }
            h1 { font-size: 52px; letter-spacing: -3px; margin: 16px 0; }
            .computer, .footnote { display: none; }
            .intro { margin-bottom: 0; }
            .edition { font-size: 9px; letter-spacing: 0; }
            .window-body { padding: 26px 22px; }
            footer { flex-wrap: wrap; line-height: 1.6; }
        }
    </style>
</head>
<body>
    <header class="topbar">
        <a class="brand" href="{{ url_for('index') }}">▧ memo<span>.club</span></a>
        <span class="edition">A LITTLE SPACE FOR YOU</span>
    </header>
    <main>
    <section aria-label="메모 클럽 소개">
        <span class="eyebrow tag">YOUR PERSONAL CORNER / VOL. 01</span>
        <h1>반가워요,<br>당신의 <em>작은</em><br><em>아지트.</em></h1>
        <p class="intro">조금 느려도 괜찮아.<br>편안한 마음으로, 메모 클럽에 접속하세요.</p>
        <div class="computer" aria-hidden="true">
            <div class="monitor"><div class="screen">MEMO CLUB [1.0]<br>hello, stranger!<br>&gt; welcome home_</div><div class="monitor-label">PERSONAL COMPUTER ●</div></div>
            <div class="stand"></div><div class="keyboard"></div>
        </div>
        <p class="footnote">LESS NOISE. MORE YOU.</p>
    </section>
    <section class="window" aria-label="{{ title }}">
    <div class="titlebar"><span>▧ {{ 'HOME' if user else 'SIGN_UP' if registering else 'LOGIN' }}.EXE</span><span class="window-controls" aria-hidden="true">─ □ ×</span></div>
    <div class="window-body">
    <div class="step">{{ 'CONNECTION ESTABLISHED' if user else 'NEW MEMBER REGISTRATION' if registering else 'MEMBER ACCESS' }}</div>
    <h2>{{ title }}</h2>
    <p class="subtitle">{{ '다시 만나서 반가워요. 편하게 머물러요.' if user else '우리만의 작은 공간, 함께 시작해요.' if registering else '당신의 자리로 돌아갈 시간이에요.' }}</p>
    {% for message in get_flashed_messages() %}
        <p class="message" role="status">{{ message }}</p>
    {% endfor %}
    {% if user %}
        <div class="welcome"><span aria-hidden="true">✳</span> 접속 완료!<br><strong>{{ user['username'] }}</strong>님, 환영합니다.<br>로그인 상태가 유지되고 있어요.</div>
        <form method="post" action="{{ url_for('logout') }}">
            <input type="hidden" name="csrf_token" value="{{ session['csrf_token'] }}">
            <button type="submit">로그아웃 <span aria-hidden="true">↗</span></button>
        </form>
    {% else %}
        <form method="post">
            <input type="hidden" name="csrf_token" value="{{ session['csrf_token'] }}">
            <label for="username">아이디 <span>USERNAME</span></label>
            <input id="username" name="username" required maxlength="50"
                   autocomplete="username" placeholder="아이디를 입력하세요" value="{{ request.form.get('username', '') }}">
            <label for="password">비밀번호{% if registering %} (8자 이상){% endif %} <span>PASSWORD</span></label>
            <input id="password" name="password" type="password" required maxlength="128"
                   {% if registering %}minlength="8"{% endif %}
                   placeholder="{{ '8자 이상 입력하세요' if registering else '비밀번호를 입력하세요' }}"
                   autocomplete="{{ 'new-password' if registering else 'current-password' }}">
            <button type="submit">{{ '가입하고 시작하기' if registering else '로그인하기' }} <span aria-hidden="true">↗</span></button>
        </form>
        <p class="switch">{{ '이미 클럽 멤버인가요?' if registering else '아직 계정이 없나요?' }} <a href="{{ url_for('login' if registering else 'register') }}">
            {{ '로그인으로 이동' if registering else '회원가입' }}
        </a></p>
    {% endif %}
    </div>
    <div class="statusbar"><span><span class="status-dot" aria-hidden="true"></span>{{ 'CONNECTED' if user else 'READY TO CONNECT' }}</span><span>MEMO CLUB © 2026</span></div>
    </section>
    </main>
    <footer><span>작은 공간, 나다운 시작.</span><span>MADE FOR SLOW MOMENTS ✳</span></footer>
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
