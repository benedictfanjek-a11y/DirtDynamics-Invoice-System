"""Startup hook for Google Search Console verification.
Serves the verification response before the application's authentication middleware.
"""

def _install():
    try:
        from flask import Flask
    except Exception:
        return
    if getattr(Flask, "_dd_google_verification_patch", False):
        return
    original_init = Flask.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        original_wsgi = self.wsgi_app
        verification_path = "/googleba99813f1d50c84c.html"
        verification_body = b"google-site-verification: googleba99813f1d50c84c.html"

        def verification_wsgi(environ, start_response):
            if environ.get("PATH_INFO") == verification_path:
                headers = [
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(verification_body))),
                    ("Cache-Control", "no-cache, no-store, must-revalidate"),
                ]
                start_response("200 OK", headers)
                return [verification_body]
            return original_wsgi(environ, start_response)

        self.wsgi_app = verification_wsgi

    Flask.__init__ = patched_init
    Flask._dd_google_verification_patch = True

_install()
