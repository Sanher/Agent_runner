import re
from dataclasses import dataclass
from typing import List


DEFAULT_SUPPORT_TELEGRAM_URL = "https://t.me/example_support"
DEFAULT_SUPPORT_MARKETING_URL = "https://example.invalid/marketing"
DEFAULT_MARKETPLACE_ORDERS_URL = f"{DEFAULT_SUPPORT_MARKETING_URL}/my-orders"
DEFAULT_SUPPORT_USER_URL_PREFIX = "https://example.invalid"


SOCIAL_UPDATE_KEYWORDS = (
    "social update",
    "socials",
    "logo",
    "banner",
    "token listing",
    "token listin",
    "token update",
    "marketplace",
    "social urls",
)
CIRCULATING_SUPPLY_KEYWORDS = (
    "circulating supply",
    "circulating",
    "change circulating supply",
    "cambiar circulating supply",
    "c. supply",
    "c supply",
    "circ. supply",
    "circ supply",
    "supply circulante",
    "circulante",
    "circulating-supply",
)
PLATFORM_CONNECTION_KEYWORDS = (
    "cannot connect",
    "can't connect",
    "connection problem",
    "problema de conexion",
    "problema de conexión",
    "error de conexion",
    "error de conexión",
    "no carga",
    "vpn",
)
EXCHANGE_INTEGRATION_KEYWORDS = ("integrate exchange", "exchange integration", "integrar exchange")
EXCHANGE_STATUS_KEYWORDS = ("exchange status", "estado exchange")
BLOCKCHAIN_INTEGRATION_KEYWORDS = ("integrate blockchain", "integrar blockchain", "add chain", "añadir cadena")
BLOCKCHAIN_STATUS_KEYWORDS = ("blockchain status", "estado blockchain", "cuando integran")
REFUND_KEYWORDS = ("refund", "reembolso")
POOL_DATA_KEYWORDS = ("pool data", "liquidity", "mcap", "holders")
LOCKS_KEYWORDS = ("lock", "locks", "bloqueo", "liquidez bloqueada", "pinksale")
AUDIT_KEYWORDS = ("audit", "auditoria", "auditoría")
AGGREGATOR_KEYWORDS = ("aggregator", "trade bot", "swap failed", "failed swap")
SCORE_KEYWORDS = ("score", "scoring", "puntuacion", "puntuación")
SEARCH_KEYWORDS = ("not in search", "no aparece en buscador", "token no aparece")
PAIR_EXPLORER_KEYWORDS = ("pair explorer", "trading view", "chart", "transaction history", "tx history")
NITRO_KEYWORDS = ("nitro", "nitros")
INSTANT_ADS_KEYWORDS = ("instant ads", "ads", "publicidad instant")
AIRDROP_KEYWORDS = ("airdrop", "airdrops")
TOKEN_CREATOR_KEYWORDS = ("token creator", "creador de token")
ADVERTISING_KEYWORDS = ("advertising", "publicidad", "ad campaign")
FEATURE_REQUEST_KEYWORDS = ("feature request", "nueva funcionalidad", "implementar funcionalidad")
LAYOUT_KEYWORDS = ("layout", "ui broken", "interfaz rota", "cache")
HELLO_WORDS = {"hello", "hi", "hola", "hey", "buenas", "ola"}
SPAM_PATTERNS = (
    r"\bqa\b",
    r"promo",
    r"promotion",
    r"promocion",
    r"promoción",
    r"crypto",
    r"onlyfans",
    r"adult",
    r"free\s+money",
    r"haz\s+dinero\s+rápido",
    r"buy my token",
    r"vender",
    r"for sale",
    r"pre-?made",
    r"copy.?paste",
    r"shill",
)
SECRET_KEYWORDS = (
    "private key",
    "clave privada",
    "seed phrase",
    "frase semilla",
    "mnemonic",
    "12 words",
    "24 words",
)
OTHER_SUPPORT_TOPIC_GROUPS = (
    SOCIAL_UPDATE_KEYWORDS,
    PLATFORM_CONNECTION_KEYWORDS,
    EXCHANGE_INTEGRATION_KEYWORDS,
    EXCHANGE_STATUS_KEYWORDS,
    BLOCKCHAIN_INTEGRATION_KEYWORDS,
    BLOCKCHAIN_STATUS_KEYWORDS,
    REFUND_KEYWORDS,
    POOL_DATA_KEYWORDS,
    LOCKS_KEYWORDS,
    AUDIT_KEYWORDS,
    AGGREGATOR_KEYWORDS,
    SCORE_KEYWORDS,
    SEARCH_KEYWORDS,
    PAIR_EXPLORER_KEYWORDS,
    NITRO_KEYWORDS,
    INSTANT_ADS_KEYWORDS,
    AIRDROP_KEYWORDS,
    TOKEN_CREATOR_KEYWORDS,
    ADVERTISING_KEYWORDS,
    FEATURE_REQUEST_KEYWORDS,
    LAYOUT_KEYWORDS,
)


@dataclass(frozen=True)
class SupportGuidanceConfig:
    telegram_support_url: str = DEFAULT_SUPPORT_TELEGRAM_URL
    marketing_url: str = DEFAULT_SUPPORT_MARKETING_URL
    user_url_prefix: str = DEFAULT_SUPPORT_USER_URL_PREFIX


def _marketing_base_url(marketing_url: str) -> str:
    return str(marketing_url or "").strip().rstrip("/")


def _marketplace_orders_url(marketing_url: str) -> str:
    base = _marketing_base_url(marketing_url)
    return f"{base}/my-orders" if base else DEFAULT_MARKETPLACE_ORDERS_URL


def _create_socials_url(marketing_url: str) -> str:
    base = _marketing_base_url(marketing_url)
    return f"{base}/create-socials" if base else f"{DEFAULT_SUPPORT_MARKETING_URL}/create-socials"


def _has_any(haystack: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in haystack for keyword in keywords)


def _lang_text(language: str, es: str, en: str) -> str:
    return en if language == "en" else es


def detect_language(text: str) -> str:
    lowered = str(text or "").lower()
    english_hits = sum(
        1 for token in ("hello", "please", "thanks", "refund", "listing", "token", "exchange")
        if token in lowered
    )
    spanish_hits = sum(
        1 for token in ("hola", "gracias", "reembolso", "listado", "token", "intercambio", "por favor")
        if token in lowered
    )
    return "en" if english_hits > spanish_hits else "es"


def is_low_context_greeting(text: str) -> bool:
    normalized = re.sub(r"[^a-zA-Záéíóúüñ ]+", " ", str(text or "").lower()).strip()
    words = [piece for piece in normalized.split() if piece]
    if not words or len(words) > 3:
        return False
    return all(word in HELLO_WORDS for word in words)


def is_spam_like_message(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(re.search(pattern, lowered) for pattern in SPAM_PATTERNS)


def contains_sensitive_material(text: str) -> bool:
    lowered = str(text or "").lower()
    if _has_any(lowered, SECRET_KEYWORDS):
        return True
    if re.search(r"\b[0-9a-fA-F]{64}\b", str(text or "")):
        return True
    return False


def has_reference_url(text: str, config: SupportGuidanceConfig) -> bool:
    lowered = str(text or "").lower()
    prefix = str(config.user_url_prefix or "").strip().lower()
    return bool(
        re.search(r"https?://\S+", lowered)
        or "www." in lowered
        or (prefix and prefix in lowered)
    )


def build_prompt_policy_lines(config: SupportGuidanceConfig) -> List[str]:
    marketing_url = _marketing_base_url(config.marketing_url) or DEFAULT_SUPPORT_MARKETING_URL
    return [
        "No pidas nunca información personal sensible ni claves privadas.",
        "Si el usuario comparte clave privada o seed phrase, avísale de inmediato y pídele borrarla.",
        "Responde en el idioma del usuario.",
        (
            "Para social update, logo, token listing, token update, socials, marketplace o social urls, "
            f"redirige al soporte de Telegram {config.telegram_support_url} y advierte sobre scammers."
        ),
        (
            "Para publicidad y updates de assets/socials usa la URL de marketing "
            f"{marketing_url} con #advertising o /create-socials según corresponda."
        ),
        (
            "Si el mensaje SOLO trata sobre cambiar Circulating Supply, comparte "
            f"{marketing_url}. Si mezcla otros temas, no compartas ese enlace y pide "
            "los datos necesarios para Circulating Supply."
        ),
        (
            "Si el usuario ya comparte URL de referencia o un address junto a URL, "
            "evita pedir de nuevo el contrato."
        ),
    ]


def build_email_support_guidance(
    subject: str,
    body: str,
    config: SupportGuidanceConfig,
) -> List[str]:
    haystack = f"{subject}\n{body}".lower()
    marketplace_orders_url = _marketplace_orders_url(config.marketing_url)
    guidance: List[str] = []

    if _has_any(haystack, SOCIAL_UPDATE_KEYWORDS):
        guidance.append(
            (
                "Advise the user to contact Telegram support for social/token listing updates: "
                f"{config.telegram_support_url}. Remind them that real admins never DM first."
            )
        )
        if _has_any(haystack, ("paid", "payment", "pagado", "not reflected", "no se refleja", "token page")):
            guidance.append(
                (
                    "If payment was done and not reflected yet, ask them to review status in "
                    f"{marketplace_orders_url} using Details."
                )
            )

    workflow = match_support_workflow_reply(f"{subject}\n{body}", config)
    if workflow:
        guidance.append(
            "Apply this workflow in the draft reply and keep it concise:\n"
            f"{workflow}"
        )
    return guidance


def match_support_workflow_reply(text: str, config: SupportGuidanceConfig) -> str:
    haystack = str(text or "").lower()
    marketing_url = _marketing_base_url(config.marketing_url) or DEFAULT_SUPPORT_MARKETING_URL
    language = detect_language(text)
    url_shared = has_reference_url(text, config)
    contract_hint_es = (
        " Si ya compartiste una URL de referencia, no hace falta repetir el contrato."
        if url_shared
        else " Incluye contrato/address del token."
    )
    contract_hint_en = (
        " If you already shared a reference URL, you do not need to repeat the contract."
        if url_shared
        else " Include token contract/address."
    )

    if contains_sensitive_material(text):
        return _lang_text(
            language,
            "No compartas nunca claves privadas ni seed phrase. Bórralo de inmediato y comparte solo wallet pública si hace falta.",
            "Never share private keys or seed phrases. Delete that message immediately and only share public wallet addresses.",
        )

    if _has_any(haystack, CIRCULATING_SUPPLY_KEYWORDS):
        has_other_support_topics = any(
            _has_any(haystack, keywords) for keywords in OTHER_SUPPORT_TOPIC_GROUPS
        )
        if not has_other_support_topics:
            return _lang_text(
                language,
                f"Para cambios de Circulating Supply usa {marketing_url}",
                f"For Circulating Supply changes use {marketing_url}",
            )
        return _lang_text(
            language,
            (
                "Para revisar Circulating Supply necesitamos: token/address, valor actual mostrado, "
                "valor esperado y una fuente verificable (explorer/captura). "
                "Si hay más temas en el mismo mensaje, envíalos por separado."
                + contract_hint_es
            ),
            (
                "To review Circulating Supply we need: token/address, current displayed value, "
                "expected value, and a verifiable source (explorer/screenshot). "
                "If there are additional topics in the same message, send them separately."
                + contract_hint_en
            ),
        )

    if _has_any(haystack, SOCIAL_UPDATE_KEYWORDS):
        return _lang_text(
            language,
            (
                f"Para updates de socials/logo/banner/listing usa soporte Telegram: {config.telegram_support_url}. "
                "Ten cuidado con scammers: ningún admin real te escribe primero por DM."
            ),
            (
                f"For socials/logo/banner/listing updates, use Telegram support: {config.telegram_support_url}. "
                "Be careful with scammers: real admins never DM first."
            ),
        )

    if "refund" in haystack or "reembolso" in haystack:
        return _lang_text(
            language,
            "Para revisar reembolso necesitamos: wallet pública, TX del refund y fecha/hora del incidente.",
            "To review a refund we need: public wallet address, refund TX and incident date/time.",
        )

    if _has_any(haystack, PLATFORM_CONNECTION_KEYWORDS):
        return _lang_text(
            language,
            (
                "¿Usas VPN? Si la usas, desconéctala y prueba de nuevo. "
                "Si no se resuelve, envía wallet pública y errores de consola (F12 > Inspect > Console)."
            ),
            (
                "Are you using a VPN? If yes, disconnect it and try again. "
                "If still failing, share your public wallet and browser console errors (F12 > Inspect > Console)."
            ),
        )

    if _has_any(haystack, EXCHANGE_INTEGRATION_KEYWORDS):
        return _lang_text(
            language,
            (
                "Para integrar un exchange envía: nombre, blockchains, URL swap, logo URL, "
                "router EVM y factory (o equivalente en Solana/TON), y socials (X/Telegram/Discord/email)."
                + contract_hint_es
            ),
            (
                "To integrate an exchange send: name, blockchains, swap URL, logo URL, "
                "EVM router and factory (or equivalent in Solana/TON), and socials (X/Telegram/Discord/email)."
                + contract_hint_en
            ),
        )

    if _has_any(haystack, EXCHANGE_STATUS_KEYWORDS):
        return _lang_text(
            language,
            "Consultaremos el estado con el equipo de desarrollo y te actualizamos.",
            "We will check the status with the development team and update you.",
        )

    if _has_any(haystack, BLOCKCHAIN_INTEGRATION_KEYWORDS):
        return _lang_text(
            language,
            (
                "Para integrar blockchain necesitamos: nombre, si es EVM, TVL, chain id (si EVM), token, explorer, "
                "exchange principal y RPC (si aplica). Tenemos lista larga de cadenas; para acelerar, habla con marketing."
            ),
            (
                "For blockchain integration we need: name, whether it is EVM, TVL, chain id (if EVM), token, explorer, "
                "main exchange and RPC (if applicable). We have a long chain queue; to prioritize, contact marketing."
            ),
        )

    if _has_any(haystack, BLOCKCHAIN_STATUS_KEYWORDS):
        return _lang_text(
            language,
            "La lista de blockchains por integrar es larga; puede tardar en completarse.",
            "The blockchain integration queue is long; integration may take time.",
        )

    if _has_any(haystack, POOL_DATA_KEYWORDS):
        return _lang_text(
            language,
            "Para revisar pool data (liquidez/mcap/holders) envía token y valor correcto esperado; lo investigará desarrollo.",
            "To review pool data (liquidity/mcap/holders), share token and expected correct value; dev team will investigate.",
        )

    if _has_any(haystack, LOCKS_KEYWORDS):
        if "pinksale" in haystack and ("percentage" in haystack or "porcentaje" in haystack):
            return _lang_text(
                language,
                "En locks tipo LP/liquidez no mostramos porcentaje, solo valor LP bloqueado. Comparte URL del lock y token/pool.",
                "For LP/liquidity locks we do not show percentage, only locked LP value. Share lock URL and token/pool.",
            )
        return _lang_text(
            language,
            "Comparte la URL del lock y el token/pool address (si falta) para revisarlo.",
            "Share the lock URL and token/pool address (if missing) so we can review it.",
        )

    if _has_any(haystack, AUDIT_KEYWORDS):
        if "already" in haystack or "ya" in haystack:
            return _lang_text(
                language,
                "Si ya contactaste con la auditora, comparte token address y lo revisamos.",
                "If you already contacted the auditor, share token address and we will review it.",
            )
        return _lang_text(
            language,
            "Contacta primero con la empresa auditora; actualizaremos el valor si corresponde.",
            "Please contact the audit company first; we will update the value if needed.",
        )

    if _has_any(haystack, AGGREGATOR_KEYWORDS):
        return _lang_text(
            language,
            "Para problemas de agregador/trade bot envía orden o transferencia, token del swap, fecha/hora y wallet pública.",
            "For aggregator/trade bot issues, share order or transfer, swap token, date/time and public wallet address.",
        )

    if _has_any(haystack, SCORE_KEYWORDS):
        return _lang_text(
            language,
            "Comparte token y puntuación incorrecta mostrada; desarrollo lo revisará.",
            "Share token and incorrect displayed score; dev team will review it.",
        )

    if _has_any(haystack, SEARCH_KEYWORDS):
        return _lang_text(
            language,
            "Verifica si está activado ocultar pares sin movimiento. Si no, envía nombre/symbol/address del token.",
            "Check if hide no-movement pairs is enabled. If not, send token name/symbol/address.",
        )

    if _has_any(haystack, PAIR_EXPLORER_KEYWORDS):
        return _lang_text(
            language,
            "Para incidencias de pair explorer/chart/tx history comparte address y, si aplica, tx id.",
            "For pair explorer/chart/tx history issues, share address and tx id if applicable.",
        )

    if _has_any(haystack, NITRO_KEYWORDS):
        return _lang_text(
            language,
            "Para pagos de Nitro envía token, fecha/hora y TX/enlace. Si pasaron 24-48h, el pago se considera expirado.",
            "For Nitro payments share token, date/time and TX/link. If 24-48h passed, payment is considered expired.",
        )

    if _has_any(haystack, INSTANT_ADS_KEYWORDS):
        return _lang_text(
            language,
            (
                "Para Instant Ads envía token, TX/enlace de pago e intervalo contratado. "
                "Recuerda: se muestran solo a usuarios free/no conectados (standard y premium no los ven)."
            ),
            (
                "For Instant Ads share token, payment TX/link and purchased interval. "
                "Reminder: ads are shown only to free/non-connected users (standard and premium do not see them)."
            ),
        )

    if _has_any(haystack, AIRDROP_KEYWORDS):
        return _lang_text(
            language,
            "Para incidencias en airdrops comparte TX de pago y token donde se añadió el airdrop.",
            "For airdrop issues share payment TX and token where the airdrop was added.",
        )

    if _has_any(haystack, TOKEN_CREATOR_KEYWORDS):
        return _lang_text(
            language,
            "Para incidencias de token creator comparte TX de pago y CA/address del token creado.",
            "For token creator issues share payment TX and created token CA/address.",
        )

    if _has_any(haystack, ADVERTISING_KEYWORDS):
        return _lang_text(
            language,
            f"Para contratar publicidad usa {marketing_url}#advertising",
            f"To purchase advertising use {marketing_url}#advertising",
        )

    if (
        "update socials" in haystack
        or "actualizar socials" in haystack
        or "actualizar url" in haystack
        or "update logo" in haystack
        or "update banner" in haystack
    ):
        return _lang_text(
            language,
            f"Para actualizar socials/URL/logo/banner usa {_create_socials_url(marketing_url)}",
            f"For socials/URL/logo/banner updates use {_create_socials_url(marketing_url)}",
        )

    if _has_any(haystack, FEATURE_REQUEST_KEYWORDS):
        return _lang_text(
            language,
            "Describe la funcionalidad y comparte capturas/enlaces de referencia para evaluarla.",
            "Describe the requested feature and share screenshots/reference links for evaluation.",
        )

    if _has_any(haystack, LAYOUT_KEYWORDS):
        return _lang_text(
            language,
            "Prueba resetear caché del navegador para nuestra web y reconectar la wallet.",
            "Try resetting browser cache for our website and reconnecting the wallet.",
        )

    return ""
