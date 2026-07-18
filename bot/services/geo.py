"""Работа с локацией через зону/сетку, а не точный пин.

Принцип из брифа: наружу никогда не отдаётся точная точка. Координаты рыбака
сразу округляются до центра ячейки сетки (по умолчанию 1 км). Это заложено в
архитектуру с первого дня, чтобы не переделывать приватность потом.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Один градус широты ≈ 111 320 м (постоянная величина).
_METERS_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Zone:
    zone_id: str      # стабильный идентификатор ячейки, напр. "z_557_378"
    lat: float        # широта центра ячейки
    lon: float        # долгота центра ячейки

    @property
    def label(self) -> str:
        """Человекочитаемая подпись зоны (без точного пина)."""
        return f"~{self.lat:.3f}, {self.lon:.3f}"


def snap_to_zone(lat: float, lon: float, grid_size_m: int = 1000) -> Zone:
    """Округляет точку до центра ячейки сетки заданного размера.

    Долгота корректируется на косинус широты — иначе у полюсов ячейки
    «сплющиваются».
    """
    deg_lat = grid_size_m / _METERS_PER_DEG_LAT
    meters_per_deg_lon = _METERS_PER_DEG_LAT * math.cos(math.radians(lat))
    # Защита от деления на ноль у полюсов.
    meters_per_deg_lon = max(meters_per_deg_lon, 1.0)
    deg_lon = grid_size_m / meters_per_deg_lon

    iy = math.floor(lat / deg_lat)
    ix = math.floor(lon / deg_lon)

    center_lat = (iy + 0.5) * deg_lat
    center_lon = (ix + 0.5) * deg_lon

    zone_id = f"z_{iy}_{ix}"
    return Zone(zone_id=zone_id, lat=round(center_lat, 5), lon=round(center_lon, 5))
