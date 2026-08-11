"""Faraday cup time-of-flight waveform analysis utilities.

The functions in this module turn oscilloscope CSV waveforms into ion energy
spectra.  They are UI independent so the same pipeline can be used from the
PyQt app, scripts, notebooks, or automated tests.
"""

from __future__ import annotations

import csv
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import interpolate

AMU_KG = 1.66053906660e-27
ELEMENTARY_CHARGE_C = 1.602176634e-19

ION_SPECIES_DB: Dict[str, Dict[str, float | str]] = {
    "Xe": {"mass_amu": 131.293, "charge_state": 1, "name": "Xenon"},
    "Sn": {"mass_amu": 118.710, "charge_state": 1, "name": "Tin"},
    "In": {"mass_amu": 114.818, "charge_state": 1, "name": "Indium"},
    "Ar": {"mass_amu": 39.948, "charge_state": 1, "name": "Argon"},
    "He": {"mass_amu": 4.002602, "charge_state": 1, "name": "Helium"},
    "C": {"mass_amu": 12.011, "charge_state": 1, "name": "Carbon"},
    "Cu": {"mass_amu": 63.546, "charge_state": 1, "name": "Copper"},
}

LIGHT_SOURCE_PLATFORMS: Dict[str, Dict[str, float | str]] = {
    "Custom": {"distance_m": 0.60, "description": "手动设置平台"},
    "LaserBench-0.6m": {"distance_m": 0.60, "description": "默认 0.6 m 激光平台"},
    "Compact-0.52m": {"distance_m": 0.52, "description": "紧凑型 0.52 m 平台"},
    "LongTOF-1.0m": {"distance_m": 1.00, "description": "长飞行管 1.0 m 平台"},
}


@dataclass
class GrafanaConfig:
    """InfluxDB-compatible write endpoint used by Grafana data sources."""

    enabled: bool = False
    url: str = ""
    token: str = ""
    org: str = ""
    bucket: str = ""
    measurement: str = "faraday_cup_cycle"


@dataclass
class FaradayCupConfig:
    csv_file_path: str = ""
    output_excel_file: str = "output_cycles_energy_spectrum.xlsx"
    noise_points: int = 100_000
    sample_interval_s: float = 1e-9
    points_per_cycle: int = 500_000
    cycles: Optional[int] = 10
    photoelectric_start: int = 245_000
    photoelectric_end: int = 249_000
    energy_start_ev: int = 300
    energy_stop_ev: int = 20_000
    load_ohm: float = 50.0
    waveform_unit: str = "V"
    signal_polarity: str = "positive"
    ion_species: str = "Xe"
    ion_mass_amu: float = 131.293
    charge_state: int = 1
    platform_name: str = "Custom"
    distance_m: float = 0.60
    interpolation_kind: str = "linear"
    export_excel: bool = True
    grafana: GrafanaConfig = field(default_factory=GrafanaConfig)

    @classmethod
    def for_species_and_platform(
        cls,
        ion_species: str = "Xe",
        platform_name: str = "Custom",
        **kwargs,
    ) -> "FaradayCupConfig":
        species = ION_SPECIES_DB.get(ion_species, ION_SPECIES_DB["Xe"])
        platform = LIGHT_SOURCE_PLATFORMS.get(platform_name, LIGHT_SOURCE_PLATFORMS["Custom"])
        return cls(
            ion_species=ion_species,
            ion_mass_amu=float(species["mass_amu"]),
            charge_state=int(species["charge_state"]),
            platform_name=platform_name,
            distance_m=float(platform["distance_m"]),
            **kwargs,
        )

    @property
    def ion_mass_kg(self) -> float:
        return self.ion_mass_amu * AMU_KG


@dataclass
class CycleAnalysisResult:
    cycle: int
    peak_index: int
    peak_time_s: float
    energy_ev: np.ndarray
    spectrum: np.ndarray
    energy_grid_ev: np.ndarray
    interpolated_spectrum: np.ndarray
    kinetic_energy_mj: float
    peak_voltage: float


def load_waveform_csv(path: str | Path, column: int = 0, skip_header: bool = True) -> np.ndarray:
    values: List[float] = []
    with open(path, "r", newline="", encoding="utf-8-sig", errors="ignore") as file:
        reader = csv.reader(file)
        if skip_header:
            next(reader, None)
        for row in reader:
            if not row or len(row) <= column:
                continue
            try:
                values.append(float(row[column]))
            except ValueError:
                continue
    if not values:
        raise ValueError(f"No numeric waveform samples found in {path}")
    return np.asarray(values, dtype=float)


def remove_baseline(voltage: np.ndarray, noise_points: int) -> Tuple[np.ndarray, float]:
    if noise_points <= 0:
        raise ValueError("noise_points must be positive")
    if len(voltage) < noise_points:
        raise ValueError("waveform is shorter than the requested noise window")
    baseline = float(np.mean(voltage[:noise_points]))
    return voltage - baseline, baseline


def normalize_polarity(voltage: np.ndarray, polarity: str) -> np.ndarray:
    polarity = polarity.lower()
    if polarity == "positive":
        return np.maximum(voltage, 0)
    if polarity == "negative":
        return np.maximum(-voltage, 0)
    if polarity == "absolute":
        return np.abs(voltage)
    if polarity == "raw":
        return voltage.copy()
    raise ValueError("signal_polarity must be one of: positive, negative, absolute, raw")


def voltage_to_current(voltage: np.ndarray, load_ohm: float, waveform_unit: str) -> np.ndarray:
    if load_ohm <= 0:
        raise ValueError("load_ohm must be positive")
    unit_scale = {"V": 1.0, "mV": 1e-3, "uV": 1e-6, "µV": 1e-6}
    try:
        volts = voltage * unit_scale[waveform_unit]
    except KeyError as exc:
        raise ValueError("waveform_unit must be V, mV, uV, or µV") from exc
    return volts / load_ohm


def tof_to_energy_ev(time_s: np.ndarray, distance_m: float, ion_mass_kg: float, charge_state: int = 1) -> np.ndarray:
    if distance_m <= 0:
        raise ValueError("distance_m must be positive")
    if ion_mass_kg <= 0:
        raise ValueError("ion_mass_kg must be positive")
    if charge_state <= 0:
        raise ValueError("charge_state must be positive")
    return 0.5 * ion_mass_kg * (distance_m / time_s) ** 2 / (charge_state * ELEMENTARY_CHARGE_C)


def current_to_dnde(
    current_a: np.ndarray,
    time_s: np.ndarray,
    ion_mass_kg: float,
    distance_m: float,
    charge_state: int = 1,
) -> np.ndarray:
    if charge_state <= 0:
        raise ValueError("charge_state must be positive")
    return current_a * time_s**3 / (ion_mass_kg * distance_m**2)


def _interpolate_descending(x_desc: np.ndarray, y: np.ndarray, grid_desc: np.ndarray, kind: str) -> np.ndarray:
    order = np.argsort(x_desc)
    x = x_desc[order]
    y_sorted = y[order]
    grid_asc = np.sort(grid_desc)
    kind_to_use = kind
    if kind == "cubic" and len(x) < 4:
        kind_to_use = "linear"
    fn = interpolate.interp1d(x, y_sorted, kind=kind_to_use, bounds_error=False, fill_value=0.0)
    interpolated_asc = fn(grid_asc)
    return interpolated_asc[::-1] if grid_desc[0] > grid_desc[-1] else interpolated_asc


def analyze_waveform(voltage: np.ndarray, config: FaradayCupConfig) -> Tuple[pd.DataFrame, pd.DataFrame, List[CycleAnalysisResult]]:
    corrected, _ = remove_baseline(voltage, config.noise_points)
    signal_voltage = normalize_polarity(corrected, config.signal_polarity)

    total_cycles = len(signal_voltage) // config.points_per_cycle
    if config.cycles is not None:
        total_cycles = min(total_cycles, config.cycles)
    if total_cycles <= 0:
        raise ValueError("waveform does not contain a complete cycle")

    energy_grid = np.arange(config.energy_stop_ev, config.energy_start_ev - 1, -1, dtype=float)
    spectra_df = pd.DataFrame({"ions_energy(eV)": energy_grid})
    summary_rows: List[Mapping[str, float | int | str]] = []
    cycle_results: List[CycleAnalysisResult] = []

    for cycle in range(total_cycles):
        start_idx = cycle * config.points_per_cycle
        end_idx = start_idx + config.points_per_cycle
        cycle_voltage = signal_voltage[start_idx:end_idx]
        if config.photoelectric_end > len(cycle_voltage):
            raise ValueError("photoelectric search window exceeds cycle length")

        local_peak = int(np.argmax(cycle_voltage[config.photoelectric_start:config.photoelectric_end]))
        peak_index = config.photoelectric_start + local_peak
        after_peak = cycle_voltage[peak_index + 1 :]
        if len(after_peak) < 4:
            continue

        tof_s = np.arange(1, len(after_peak) + 1, dtype=float) * config.sample_interval_s
        energy_ev = tof_to_energy_ev(tof_s, config.distance_m, config.ion_mass_kg, config.charge_state)
        current_a = voltage_to_current(after_peak, config.load_ohm, config.waveform_unit)
        spectrum = current_to_dnde(current_a, tof_s, config.ion_mass_kg, config.distance_m, config.charge_state)
        interpolated = _interpolate_descending(energy_ev, spectrum, energy_grid, config.interpolation_kind)
        kinetic_j = float(np.trapz(energy_grid[::-1] * interpolated[::-1], energy_grid[::-1]) * ELEMENTARY_CHARGE_C)
        kinetic_mj = kinetic_j * 1000.0

        col_name = f"dN_dE_cycle_{cycle + 1}"
        spectra_df[col_name] = interpolated
        result = CycleAnalysisResult(
            cycle=cycle + 1,
            peak_index=peak_index,
            peak_time_s=(start_idx + peak_index) * config.sample_interval_s,
            energy_ev=energy_ev,
            spectrum=spectrum,
            energy_grid_ev=energy_grid,
            interpolated_spectrum=interpolated,
            kinetic_energy_mj=kinetic_mj,
            peak_voltage=float(cycle_voltage[peak_index]),
        )
        cycle_results.append(result)
        summary_rows.append(
            {
                "cycle": cycle + 1,
                "ion_species": config.ion_species,
                "platform": config.platform_name,
                "distance_m": config.distance_m,
                "peak_index": peak_index,
                "peak_time_s": result.peak_time_s,
                "peak_voltage": result.peak_voltage,
                "kinetic_energy_mJ": kinetic_mj,
            }
        )

    return spectra_df, pd.DataFrame(summary_rows), cycle_results


def analyze_csv(config: FaradayCupConfig) -> Tuple[pd.DataFrame, pd.DataFrame, List[CycleAnalysisResult]]:
    voltage = load_waveform_csv(config.csv_file_path)
    spectra_df, summary_df, cycle_results = analyze_waveform(voltage, config)
    if config.export_excel:
        with pd.ExcelWriter(config.output_excel_file, engine="openpyxl") as writer:
            spectra_df.to_excel(writer, sheet_name="energy_spectrum", index=False)
            summary_df.to_excel(writer, sheet_name="cycle_summary", index=False)
    if config.grafana.enabled:
        upload_summary_to_grafana(summary_df, config.grafana)
    return spectra_df, summary_df, cycle_results


def _escape_line_protocol_value(value: object) -> str:
    text = str(value)
    return text.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def summary_to_influx_lines(summary_df: pd.DataFrame, config: GrafanaConfig) -> str:
    lines: List[str] = []
    for _, row in summary_df.iterrows():
        tags = {
            "ion": row.get("ion_species", "unknown"),
            "platform": row.get("platform", "unknown"),
            "cycle": int(row["cycle"]),
        }
        tag_text = ",".join(f"{k}={_escape_line_protocol_value(v)}" for k, v in tags.items())
        fields = {
            "distance_m": float(row["distance_m"]),
            "peak_index": int(row["peak_index"]),
            "peak_time_s": float(row["peak_time_s"]),
            "peak_voltage": float(row["peak_voltage"]),
            "kinetic_energy_mJ": float(row["kinetic_energy_mJ"]),
        }
        field_text = ",".join(
            f"{key}={value}i" if isinstance(value, int) else f"{key}={value}"
            for key, value in fields.items()
        )
        lines.append(f"{config.measurement},{tag_text} {field_text}")
    return "\n".join(lines)


def upload_summary_to_grafana(summary_df: pd.DataFrame, config: GrafanaConfig, timeout_s: float = 10.0) -> str:
    """Upload cycle summary to an InfluxDB v2 write endpoint used by Grafana.

    Grafana itself is usually a visualization layer.  For dashboards, send data
    to a datasource such as InfluxDB and configure Grafana to read that bucket.
    """

    if not config.url:
        raise ValueError("Grafana/InfluxDB write URL is required")
    line_protocol = summary_to_influx_lines(summary_df, config)
    url = config.url
    if config.org and config.bucket and "/api/v2/write" not in url:
        separator = "&" if "?" in url else "?"
        url = f"{url.rstrip('/')}/api/v2/write{separator}org={config.org}&bucket={config.bucket}&precision=s"
    request = urllib.request.Request(
        url,
        data=line_protocol.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    if config.token:
        request.add_header("Authorization", f"Token {config.token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"upload failed: HTTP {exc.code} {detail}") from exc


def save_config(config: FaradayCupConfig, path: str | Path) -> None:
    payload = config.__dict__.copy()
    payload["grafana"] = config.grafana.__dict__.copy()
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
