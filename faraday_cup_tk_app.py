"""Tkinter fallback UI for the Faraday Cup TOF analyzer.

This UI is intentionally conservative: it avoids Qt entirely so Windows users
with a broken PyQt5 DLL setup can still analyze CSV files and export Excel
summaries from the same core analysis pipeline.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from faraday_cup_analysis import (
    FaradayCupConfig,
    GrafanaConfig,
    ION_SPECIES_DB,
    LIGHT_SOURCE_PLATFORMS,
    analyze_csv,
)


class FaradayCupTkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Faraday Cup TOF Energy Spectrum Analyzer (Tk fallback)")
        self.geometry("1120x760")
        self._worker: threading.Thread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(root)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        right = ttk.Frame(root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.csv_path = tk.StringVar()
        self.output_path = tk.StringVar(value="output_cycles_energy_spectrum.xlsx")
        self.platform = tk.StringVar(value="Custom")
        self.distance_m = tk.DoubleVar(value=0.60)
        self.ion_species = tk.StringVar(value="Xe")
        self.ion_mass_amu = tk.DoubleVar(value=float(ION_SPECIES_DB["Xe"]["mass_amu"]))
        self.charge_state = tk.IntVar(value=1)
        self.noise_points = tk.IntVar(value=100_000)
        self.sample_interval_ns = tk.DoubleVar(value=1.0)
        self.points_per_cycle = tk.IntVar(value=500_000)
        self.cycles = tk.IntVar(value=10)
        self.photo_start = tk.IntVar(value=245_000)
        self.photo_end = tk.IntVar(value=249_000)
        self.waveform_unit = tk.StringVar(value="V")
        self.signal_polarity = tk.StringVar(value="positive")
        self.load_ohm = tk.DoubleVar(value=50.0)
        self.energy_start_ev = tk.IntVar(value=300)
        self.energy_stop_ev = tk.IntVar(value=20_000)
        self.interpolation_kind = tk.StringVar(value="linear")
        self.grafana_enabled = tk.BooleanVar(value=False)
        self.grafana_url = tk.StringVar()
        self.grafana_org = tk.StringVar()
        self.grafana_bucket = tk.StringVar()
        self.grafana_token = tk.StringVar()
        self.grafana_measurement = tk.StringVar(value="faraday_cup_cycle")

        file_box = ttk.LabelFrame(left, text="1. 数据文件", padding=8)
        file_box.pack(fill=tk.X, pady=4)
        ttk.Entry(file_box, textvariable=self.csv_path, width=46).grid(row=0, column=0, sticky="ew")
        ttk.Button(file_box, text="浏览", command=self._select_csv).grid(row=0, column=1, padx=(5, 0))
        ttk.Label(file_box, text="Excel 输出").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(file_box, textvariable=self.output_path, width=46).grid(row=2, column=0, columnspan=2, sticky="ew")

        platform_box = ttk.LabelFrame(left, text="2. 光源平台 / Fcup 距离", padding=8)
        platform_box.pack(fill=tk.X, pady=4)
        platform_combo = ttk.Combobox(platform_box, textvariable=self.platform, values=list(LIGHT_SOURCE_PLATFORMS), state="readonly")
        platform_combo.grid(row=0, column=1, sticky="ew")
        platform_combo.bind("<<ComboboxSelected>>", self._platform_changed)
        ttk.Label(platform_box, text="平台").grid(row=0, column=0, sticky="w")
        ttk.Label(platform_box, text="距离(m)").grid(row=1, column=0, sticky="w")
        ttk.Entry(platform_box, textvariable=self.distance_m).grid(row=1, column=1, sticky="ew")

        ion_box = ttk.LabelFrame(left, text="3. 离子种类", padding=8)
        ion_box.pack(fill=tk.X, pady=4)
        ion_combo = ttk.Combobox(ion_box, textvariable=self.ion_species, values=list(ION_SPECIES_DB), state="readonly")
        ion_combo.grid(row=0, column=1, sticky="ew")
        ion_combo.bind("<<ComboboxSelected>>", self._ion_changed)
        ttk.Label(ion_box, text="离子").grid(row=0, column=0, sticky="w")
        ttk.Label(ion_box, text="质量(amu)").grid(row=1, column=0, sticky="w")
        ttk.Entry(ion_box, textvariable=self.ion_mass_amu).grid(row=1, column=1, sticky="ew")
        ttk.Label(ion_box, text="价态 z").grid(row=2, column=0, sticky="w")
        ttk.Entry(ion_box, textvariable=self.charge_state).grid(row=2, column=1, sticky="ew")

        signal_box = ttk.LabelFrame(left, text="4. 采样与信号", padding=8)
        signal_box.pack(fill=tk.X, pady=4)
        rows = [
            ("噪声点数", self.noise_points),
            ("采样间隔(ns)", self.sample_interval_ns),
            ("每周期点数", self.points_per_cycle),
            ("周期数(0=自动)", self.cycles),
            ("光电峰起点", self.photo_start),
            ("光电峰终点", self.photo_end),
            ("负载(Ω)", self.load_ohm),
        ]
        for idx, (label, variable) in enumerate(rows):
            ttk.Label(signal_box, text=label).grid(row=idx, column=0, sticky="w")
            ttk.Entry(signal_box, textvariable=variable).grid(row=idx, column=1, sticky="ew")
        ttk.Label(signal_box, text="波形单位").grid(row=len(rows), column=0, sticky="w")
        ttk.Combobox(signal_box, textvariable=self.waveform_unit, values=["V", "mV", "uV"], state="readonly").grid(row=len(rows), column=1, sticky="ew")
        ttk.Label(signal_box, text="信号极性").grid(row=len(rows) + 1, column=0, sticky="w")
        ttk.Combobox(signal_box, textvariable=self.signal_polarity, values=["positive", "negative", "absolute", "raw"], state="readonly").grid(row=len(rows) + 1, column=1, sticky="ew")

        energy_box = ttk.LabelFrame(left, text="5. 能量与上传", padding=8)
        energy_box.pack(fill=tk.X, pady=4)
        ttk.Label(energy_box, text="起始 eV").grid(row=0, column=0, sticky="w")
        ttk.Entry(energy_box, textvariable=self.energy_start_ev).grid(row=0, column=1, sticky="ew")
        ttk.Label(energy_box, text="终止 eV").grid(row=1, column=0, sticky="w")
        ttk.Entry(energy_box, textvariable=self.energy_stop_ev).grid(row=1, column=1, sticky="ew")
        ttk.Label(energy_box, text="插值").grid(row=2, column=0, sticky="w")
        ttk.Combobox(energy_box, textvariable=self.interpolation_kind, values=["linear", "cubic", "nearest"], state="readonly").grid(row=2, column=1, sticky="ew")
        ttk.Checkbutton(energy_box, text="上传 InfluxDB/Grafana", variable=self.grafana_enabled).grid(row=3, column=0, columnspan=2, sticky="w")
        for row, (label, variable) in enumerate(
            [
                ("URL", self.grafana_url),
                ("Org", self.grafana_org),
                ("Bucket", self.grafana_bucket),
                ("Token", self.grafana_token),
                ("Measurement", self.grafana_measurement),
            ],
            start=4,
        ):
            ttk.Label(energy_box, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(energy_box, textvariable=variable, show="*" if label == "Token" else "").grid(row=row, column=1, sticky="ew")

        self.run_button = ttk.Button(left, text="开始分析", command=self._run_analysis)
        self.run_button.pack(fill=tk.X, pady=8)

        self.summary = ttk.Treeview(right, columns=("cycle", "ion", "platform", "distance", "peak", "energy"), show="headings")
        for column, label in [
            ("cycle", "Cycle"),
            ("ion", "Ion"),
            ("platform", "Platform"),
            ("distance", "Distance(m)"),
            ("peak", "Peak index"),
            ("energy", "Kinetic energy(mJ)"),
        ]:
            self.summary.heading(column, text=label)
            self.summary.column(column, width=130, anchor=tk.CENTER)
        self.summary.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(right, height=9)
        self.log.pack(fill=tk.X, pady=(8, 0))
        self._log("Tk fallback 已启动：可分析并导出 Excel；若需要内嵌曲线图，请修复 PyQt5 后使用 Qt 界面。")

    def _select_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.csv_path.set(path)
            if self.output_path.get() == "output_cycles_energy_spectrum.xlsx":
                self.output_path.set(str(Path(path).with_name(Path(path).stem + "_energy_spectrum.xlsx")))

    def _platform_changed(self, _event=None) -> None:
        platform = LIGHT_SOURCE_PLATFORMS.get(self.platform.get())
        if platform:
            self.distance_m.set(float(platform["distance_m"]))

    def _ion_changed(self, _event=None) -> None:
        species = ION_SPECIES_DB.get(self.ion_species.get())
        if species:
            self.ion_mass_amu.set(float(species["mass_amu"]))
            self.charge_state.set(int(species["charge_state"]))

    def _build_config(self) -> FaradayCupConfig:
        if not self.csv_path.get().strip():
            raise ValueError("请先选择 CSV 波形文件")
        if self.energy_stop_ev.get() <= self.energy_start_ev.get():
            raise ValueError("终止能量必须大于起始能量")
        if self.photo_end.get() <= self.photo_start.get():
            raise ValueError("光电峰终点必须大于起点")
        return FaradayCupConfig(
            csv_file_path=self.csv_path.get().strip(),
            output_excel_file=self.output_path.get().strip() or "output_cycles_energy_spectrum.xlsx",
            noise_points=self.noise_points.get(),
            sample_interval_s=self.sample_interval_ns.get() * 1e-9,
            points_per_cycle=self.points_per_cycle.get(),
            cycles=self.cycles.get() or None,
            photoelectric_start=self.photo_start.get(),
            photoelectric_end=self.photo_end.get(),
            energy_start_ev=self.energy_start_ev.get(),
            energy_stop_ev=self.energy_stop_ev.get(),
            load_ohm=self.load_ohm.get(),
            waveform_unit=self.waveform_unit.get(),
            signal_polarity=self.signal_polarity.get(),
            ion_species=self.ion_species.get(),
            ion_mass_amu=self.ion_mass_amu.get(),
            charge_state=self.charge_state.get(),
            platform_name=self.platform.get(),
            distance_m=self.distance_m.get(),
            interpolation_kind=self.interpolation_kind.get(),
            grafana=GrafanaConfig(
                enabled=self.grafana_enabled.get(),
                url=self.grafana_url.get().strip(),
                token=self.grafana_token.get().strip(),
                org=self.grafana_org.get().strip(),
                bucket=self.grafana_bucket.get().strip(),
                measurement=self.grafana_measurement.get().strip() or "faraday_cup_cycle",
            ),
        )

    def _run_analysis(self) -> None:
        try:
            config = self._build_config()
        except Exception as exc:
            messagebox.showwarning("参数错误", str(exc))
            return
        self.run_button.configure(state=tk.DISABLED)
        self._log("开始分析...")
        self._worker = threading.Thread(target=self._worker_body, args=(config,), daemon=True)
        self._worker.start()

    def _worker_body(self, config: FaradayCupConfig) -> None:
        try:
            _, summary_df, _ = analyze_csv(config)
        except Exception as exc:
            self.after(0, self._analysis_failed, str(exc))
            return
        self.after(0, self._analysis_finished, summary_df)

    def _analysis_finished(self, summary_df) -> None:
        self.run_button.configure(state=tk.NORMAL)
        for item in self.summary.get_children():
            self.summary.delete(item)
        for _, row in summary_df.iterrows():
            self.summary.insert(
                "",
                tk.END,
                values=(
                    int(row["cycle"]),
                    row["ion_species"],
                    row["platform"],
                    f'{float(row["distance_m"]):.4g}',
                    int(row["peak_index"]),
                    f'{float(row["kinetic_energy_mJ"]):.6g}',
                ),
            )
        self._log(f"完成：{len(summary_df)} 个周期，已导出 Excel。")

    def _analysis_failed(self, message: str) -> None:
        self.run_button.configure(state=tk.NORMAL)
        self._log(f"错误：{message}")
        messagebox.showerror("分析失败", message)

    def _log(self, message: str) -> None:
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)


def main() -> int:
    app = FaradayCupTkApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
