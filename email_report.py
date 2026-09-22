"""Build and deliver the daily HTML report.

Email design is mobile-first: single column, inline CSS, max-width 600px
(most clients ignore <style> blocks, so everything is inlined).
Sending uses Gmail SMTP with an App Password (see .env.example).
"""

from __future__ import annotations

import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from html import escape
from pathlib import Path

from config import CENTER_NAME, RADIUS_KM, RECIPIENT_EMAILS, SEARCH_AREA_LABEL
from models import Listing

SOURCE_LABELS = {
    "sreality": "Sreality",
    "bezrealitky": "Bezrealitky (bez provize)",
    "idnes": "iDNES Reality",
}


# --- formatting helpers -------------------------------------------------------

def _fmt_price(p):
    return f"{p:,} Kč".replace(",", " ") if p else "cena neuvedena"


def _price_line(l: Listing) -> str:
    return _fmt_price(l.price_czk)


def _czech_count(n: int) -> str:
    if n == 1:
        return "1 nový inzerát"
    if 2 <= n <= 4:
        return f"{n} nové inzeráty"
    return f"{n} nových inzerátů"


# --- subject + body -----------------------------------------------------------

def build_subject(listings: list[Listing], when: datetime) -> str:
    return (f"Nemovitosti {SEARCH_AREA_LABEL} — {when.day}.{when.month}. "
            f"({_czech_count(len(listings))})")


def _listing_card(l: Listing) -> str:
    dist = f"{l.distance_km:.1f} km od {CENTER_NAME}" if l.distance_km is not None else ""
    area = f"{l.area_m2} m²" if l.area_m2 else "? m²"
    meta = " · ".join(x for x in (l.disposition, area, _price_line(l)) if x)
    loc = " · ".join(x for x in (escape(l.city or ""), dist) if x)
    district = escape(l.district or "")

    thumb = ""
    if l.image_url:
        thumb = (
            f'<td width="96" valign="top" style="padding-right:12px;">'
            f'<img src="{escape(l.image_url)}" width="84" height="63" '
            f'alt="" style="border-radius:8px;object-fit:cover;display:block;"></td>'
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="margin:0 0 14px 0;border:1px solid #e6e6e6;border-radius:10px;">
      <tr><td style="padding:12px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
          {thumb}
          <td valign="top">
            <div style="font-size:16px;font-weight:600;color:#111;line-height:1.3;">{meta}</div>
            <div style="font-size:13px;color:#666;margin-top:3px;">{loc}{(' · ' + district) if district else ''}</div>
            <a href="{escape(l.url)}" style="display:inline-block;margin-top:8px;font-size:14px;
               color:#1a6dff;text-decoration:none;font-weight:600;">Zobrazit inzerát →</a>
          </td>
        </tr></table>
      </td></tr>
    </table>"""


def build_html(listings: list[Listing], when: datetime) -> str:
    by_source: dict[str, list[Listing]] = {}
    for l in listings:
        by_source.setdefault(l.source, []).append(l)

    sections = []
    for source, items in by_source.items():
        items.sort(key=lambda l: l.distance_km if l.distance_km is not None else 9_999)
        label = SOURCE_LABELS.get(source, source)
        cards = "".join(_listing_card(l) for l in items)
        sections.append(
            f'<div style="font-size:13px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.5px;color:#999;margin:22px 0 10px 0;">'
            f'{escape(label)} · {len(items)}</div>{cards}')

    body = "".join(sections)
    return f"""<!DOCTYPE html>
<html lang="cs"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f4f5;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;">
    <tr><td align="center" style="padding:20px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:600px;background:#fff;border-radius:14px;padding:22px;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
        <tr><td>
          <div style="font-size:20px;font-weight:700;color:#111;">Nové nemovitosti k prodeji</div>
          <div style="font-size:13px;color:#888;margin-top:4px;">
            {when.day}.{when.month}.{when.year} · prodej · do {RADIUS_KM:.0f} km od {SEARCH_AREA_LABEL}
          </div>
          {body}
          <div style="font-size:11px;color:#bbb;margin-top:24px;border-top:1px solid #eee;padding-top:12px;">
            Prodejní cena dle inzerátu. Generováno botem byty-bot.
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# --- delivery -----------------------------------------------------------------

def write_preview(html: str, filename: str = "preview_email.html") -> Path:
    path = Path(__file__).with_name(filename)
    path.write_text(html, encoding="utf-8")
    return path


def _resolve_recipients(recipient: str | list[str] | None = None) -> list[str]:
    if recipient is not None:
        if isinstance(recipient, str):
            return [e.strip() for e in recipient.split(",") if e.strip()]
        return [e.strip() for e in recipient if e.strip()]
    env = os.environ.get("REPORT_RECIPIENT")
    if env:
        return [e.strip() for e in env.split(",") if e.strip()]
    return list(RECIPIENT_EMAILS)


def send_email(subject: str, html: str, recipient: str | list[str] | None = None) -> None:
    """Send via Gmail SMTP. Requires GMAIL_USER + GMAIL_APP_PASSWORD env vars."""
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "Chybí GMAIL_USER / GMAIL_APP_PASSWORD (viz .env.example).")
    to_addrs = _resolve_recipients(recipient)
    if not to_addrs:
        raise RuntimeError("Chybí příjemce e-mailu (REPORT_RECIPIENT / RECIPIENT_EMAILS).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_addrs)
    msg.set_content("HTML e-mail — zobraz v klientu s podporou HTML.")
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
