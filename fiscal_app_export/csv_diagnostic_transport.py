"""Isolated Resend transport for explicitly authorized diagnostic attachments.

No retries, no request body logging, no transfer on FIFO parser failures.
This module does not manage the recipient mailbox or provider retention.
"""


def send_diagnostic_email(payload: dict, api_key: str):
    """Make one bounded POST; caller handles ambiguous delivery outcomes."""
    import requests

    return requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=12,
    )
