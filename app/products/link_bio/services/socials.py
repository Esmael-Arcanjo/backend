import re
from urllib.parse import quote, urlparse

NETWORKS = {
    "instagram": "Instagram", "facebook": "Facebook", "x": "X (Twitter)", "tiktok": "TikTok", "youtube": "YouTube",
    "linkedin": "LinkedIn", "whatsapp": "WhatsApp", "telegram": "Telegram", "pinterest": "Pinterest",
    "threads": "Threads", "github": "GitHub", "spotify": "Spotify", "twitch": "Twitch", "discord": "Discord",
    "kwai": "Kwai", "snapchat": "Snapchat", "behance": "Behance", "email": "E-mail", "website": "Site",
}


def normalize_url(network: str, value: str) -> str:
    """Builds a safe absolute URL; only https/http, mailto and wa.me are accepted (blocks javascript:/data:)."""
    value = value.strip()
    if network == "whatsapp":
        digits = re.sub(r"\D", "", value.removeprefix("https://wa.me/").split("?")[0])
        if not 10 <= len(digits) <= 15:
            raise ValueError("Informe o WhatsApp com DDI e DDD, apenas números")
        return f"https://wa.me/{digits}"
    if network == "email":
        email = value.removeprefix("mailto:")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("E-mail inválido")
        return f"mailto:{quote(email, safe='@.+-_')}"
    if not re.match(r"^https?://", value, re.I):
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or "." not in parsed.netloc:
        raise ValueError("URL inválida")
    return value
