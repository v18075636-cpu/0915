from werkzeug.middleware.proxy_fix import ProxyFix

from app import app, production


if production:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=0, x_proto=1, x_host=0, x_port=0, x_prefix=0
    )
