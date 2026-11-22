import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.security.rate_limit import client_ip, limiter

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT = {
    "/api/stripe/webhook",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/login/mfa",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api") and not await limiter.hit(f"ip:{client_ip(request)}", 600, 60):
            return JSONResponse({"detail": "Muitas requisições. Tente novamente em instantes."}, status_code=429)
        if request.method in UNSAFE and path.startswith("/api") and path not in CSRF_EXEMPT \
                and path != "/api/leads" and not path.startswith(("/api/v1/public/", "/api/webhooks/")):
            has_session = "access_token" in request.cookies or "refresh_token" in request.cookies
            if has_session:
                cookie = request.cookies.get("csrf_token", "")
                header = request.headers.get("x-csrf-token", "")
                if not cookie or not hmac.compare_digest(cookie, header):
                    return JSONResponse({"detail": "Falha na verificação CSRF"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if not path.startswith("/api/docs") and not path.startswith("/api/openapi"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if path.startswith("/api/v1/auth") or path.startswith("/api/v1/users"):
            response.headers["Cache-Control"] = "no-store"
        return response
