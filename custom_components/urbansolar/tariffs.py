from __future__ import annotations

import asyncio
import io
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pdfplumber

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SUBSCRIBED_POWER,
    CONF_TARIFF_OPTION,
    SENSOR_TARIFF_ACH_HC_TTC,
    SENSOR_TARIFF_ACH_HP_TTC,
    SENSOR_TARIFF_ACH_TTC,
    SENSOR_TARIFF_ENERGY_HC_TTC,
    SENSOR_TARIFF_ENERGY_HP_TTC,
    SENSOR_TARIFF_ENERGY_TTC,
    TARIFF_OPTION_BASE,
    TARIFF_OPTION_HPHC,
)

import logging

_LOGGER = logging.getLogger(__name__)

_TARIFFS_URL = "https://www.urbansolarenergy.fr/tarifs/"
_NUM_RE = re.compile(r"^\d+,\d{1,4}$")
_KVA_VALUES = {3, 6, 9, 12, 15, 18, 24, 30, 36}


class TariffData:
    def __init__(self, hass, config_entry):
        self.hass = hass
        self.config_entry = config_entry
        self.values: Dict[str, float] = {}
        self.source_url: Optional[str] = None
        self.effective_date: Optional[str] = None
        self.last_update: Optional[str] = None
        self.last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def tariff_option(self) -> str:
        return self.config_entry.data.get(CONF_TARIFF_OPTION, TARIFF_OPTION_BASE)

    @property
    def subscribed_power(self) -> int:
        raw = self.config_entry.data.get(CONF_SUBSCRIBED_POWER, 6)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 6

    async def async_update(self, force: bool = False) -> None:
        if not force and self.last_update:
            return

        async with self._lock:
            if not force and self.last_update:
                return

            try:
                session = async_get_clientsession(self.hass)
                html = await _fetch_text(session, _TARIFFS_URL)
                pdf_url = _find_pdf_url(html, self.tariff_option)
                if not pdf_url:
                    raise ValueError("No matching PDF found on tariffs page")

                pdf_bytes = await _fetch_bytes(session, pdf_url)
                result = await self.hass.async_add_executor_job(
                    _parse_pdf, pdf_bytes, self.tariff_option, self.subscribed_power
                )
                self.values = result["values"]
                self.effective_date = result.get("effective_date")
                self.source_url = pdf_url
                self.last_update = dt_util.utcnow().isoformat()
                self.last_error = None
            except Exception as err:  # pylint: disable=broad-except
                self.last_error = str(err)
                _LOGGER.error("Failed to update Urban Solar tariffs: %s", err)


async def _fetch_text(session, url: str) -> str:
    async with session.get(url, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.text()


async def _fetch_bytes(session, url: str) -> bytes:
    async with session.get(url, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.read()


def _find_pdf_url(html: str, option: str) -> Optional[str]:
    links = re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, re.IGNORECASE)
    if not links:
        return None

    def match_link(link: str, token: str) -> bool:
        upper = link.upper()
        return "BV" in upper and "PARTICULIER" in upper and token in upper

    if option == TARIFF_OPTION_HPHC:
        candidates = [l for l in links if match_link(l, "HPHC")]
        if not candidates:
            candidates = [l for l in links if match_link(l, "HP")]
    else:
        candidates = [l for l in links if match_link(l, "BASE")]

    if not candidates:
        candidates = [l for l in links if "BV" in l.upper() and "PARTICULIER" in l.upper()]

    if not candidates:
        return None

    return urljoin(_TARIFFS_URL, candidates[0])


def _parse_pdf(pdf_bytes: bytes, option: str, power_kva: int) -> Dict[str, object]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            raise ValueError("PDF has no pages")

        page = pdf.pages[0]
        text = page.extract_text() or ""
        effective_date = None
        date_match = re.search(r"Au\s+(\d{2}/\d{2}/\d{4})", text)
        if date_match:
            effective_date = date_match.group(1)

        words = page.extract_words(use_text_flow=True) or []
        num_words = _extract_number_words(words)
        kwh_values = [(x, y, val) for x, y, val in num_words if val < 1]

        expected_clusters = 4 if option == TARIFF_OPTION_HPHC else 2
        clusters = _cluster_by_x(kwh_values, expected_clusters)
        if len(clusters) != expected_clusters:
            raise ValueError("Could not detect expected price columns")

        kva_rows = _find_kva_rows(words, page.height)
        target_y = kva_rows.get(power_kva)

        values: Dict[str, float] = {}
        if option == TARIFF_OPTION_HPHC:
            values[SENSOR_TARIFF_ENERGY_HP_TTC] = _pick_ttc(clusters[0])
            values[SENSOR_TARIFF_ENERGY_HC_TTC] = _pick_ttc(clusters[1])
            values[SENSOR_TARIFF_ACH_HP_TTC] = _pick_ttc(clusters[2])
            values[SENSOR_TARIFF_ACH_HC_TTC] = _pick_ttc(clusters[3])
        else:
            values[SENSOR_TARIFF_ENERGY_TTC] = _pick_ttc(clusters[0], target_y)
            values[SENSOR_TARIFF_ACH_TTC] = _pick_ttc(clusters[1], target_y)

        return {"values": values, "effective_date": effective_date}


def _extract_number_words(words: List[Dict[str, object]]) -> List[Tuple[float, float, float]]:
    numbers: List[Tuple[float, float, float]] = []
    for word in words:
        text = str(word.get("text", ""))
        if not _NUM_RE.match(text):
            continue
        value = _parse_number(text)
        if value is None:
            continue
        x = (float(word["x0"]) + float(word["x1"])) / 2
        y = (float(word["top"]) + float(word["bottom"])) / 2
        numbers.append((x, y, value))
    return numbers


def _find_kva_rows(words: List[Dict[str, object]], page_height: float) -> Dict[int, float]:
    candidates: List[Tuple[float, float, int]] = []
    for word in words:
        text = str(word.get("text", ""))
        if not text.isdigit():
            continue
        value = int(text)
        if value not in _KVA_VALUES:
            continue
        x = (float(word["x0"]) + float(word["x1"])) / 2
        y = (float(word["top"]) + float(word["bottom"])) / 2
        candidates.append((x, y, value))

    if not candidates:
        return {}

    min_x = min(x for x, _, _ in candidates)
    left = [c for c in candidates if c[0] <= min_x + 30]
    if not left:
        left = candidates

    y_max = page_height * 0.6
    left = [c for c in left if c[1] <= y_max]

    rows: Dict[int, float] = {}
    for _, y, value in left:
        if value not in rows or y < rows[value]:
            rows[value] = y
    return rows


def _cluster_by_x(values: List[Tuple[float, float, float]], k: int) -> List[List[Tuple[float, float, float]]]:
    if not values or len(values) < k:
        return []

    xs = [v[0] for v in values]
    xs_sorted = sorted(xs)
    centers = [
        xs_sorted[int(i * (len(xs_sorted) - 1) / (k - 1))] for i in range(k)
    ]

    for _ in range(10):
        clusters: List[List[Tuple[float, float, float]]] = [[] for _ in range(k)]
        for item in values:
            idx = min(range(k), key=lambda i: abs(item[0] - centers[i]))
            clusters[idx].append(item)
        new_centers = []
        for i, cluster in enumerate(clusters):
            if cluster:
                new_centers.append(sum(v[0] for v in cluster) / len(cluster))
            else:
                new_centers.append(centers[i])
        if new_centers == centers:
            break
        centers = new_centers

    clusters = [c for _, c in sorted(zip(centers, clusters), key=lambda t: t[0])]
    return clusters


def _pick_ttc(cluster: List[Tuple[float, float, float]], target_y: Optional[float] = None) -> Optional[float]:
    if not cluster:
        return None
    candidates = cluster
    if target_y is not None and len(cluster) > 2:
        candidates = sorted(cluster, key=lambda v: abs(v[1] - target_y))[:2]
    return max(v[2] for v in candidates)


def _parse_number(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None
