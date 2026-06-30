from dataclasses import dataclass
from typing import Optional

import httpx

from src.utils.logging import get_logger

logger = get_logger(__name__)


TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
DEFAULT_PARSE_MODE = "Markdown"

ALERT_EMOJI_CRITICAL = "🚨"
ALERT_EMOJI_WARNING = "⚠️"
STATUS_EMOJI_FIRING = "🔴"
STATUS_EMOJI_RESOLVED = "🟢"

ALERT_MESSAGE_TEMPLATE = """{emoji} *Alert: {alertname}*
{status_emoji} Status: {status}
📋 Severity: {severity}
📝 {summary}

```
{description}
```"""


@dataclass
class AlertData:
    alertname: str
    status: str
    severity: str
    summary: str
    description: str


def format_alert_message(alert: dict) -> str:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = alert.get("status", "firing")
    severity = labels.get("severity", "warning")

    emoji = ALERT_EMOJI_CRITICAL if severity == "critical" else ALERT_EMOJI_WARNING
    status_emoji = STATUS_EMOJI_FIRING if status == "firing" else STATUS_EMOJI_RESOLVED

    return ALERT_MESSAGE_TEMPLATE.format(
        emoji=emoji,
        alertname=labels.get("alertname", "Unknown"),
        status_emoji=status_emoji,
        status=status.upper(),
        severity=severity,
        summary=annotations.get("summary", "No description"),
        description=annotations.get("description", "No details"),
    )


class TelegramClient:
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: int = 10,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send_message(self, text: str) -> None:
        if not self.is_configured:
            return

        async with httpx.AsyncClient() as client:
            response = await client.post(
                TELEGRAM_API_URL.format(token=self.bot_token),
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": DEFAULT_PARSE_MODE,
                },
                timeout=self.timeout,
            )
            if not response.is_success:
                raise httpx.HTTPStatusError(
                    f"Telegram API error: {response.status_code}",
                    response=response,
                    request=response.request,
                )

    async def send_alerts(self, alerts: list[dict]) -> None:
        for alert in alerts:
            await self.send_message(format_alert_message(alert))
