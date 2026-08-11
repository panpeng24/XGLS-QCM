import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from faraday_cup_analysis import (
    GrafanaConfig,
    FaradayCupConfig,
    ION_SPECIES_DB,
    LIGHT_SOURCE_PLATFORMS,
    analyze_csv,
)


class FaradayCupWorker(QThread):
    finished_signal = pyqtSignal(object, object, object)
    error_signal = pyqtSignal(str)

    def __init__(self, config: FaradayCupConfig):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self.finished_signal.emit(*analyze_csv(self.config))
        except Exception as exc:
            self.error_signal.emit(str(exc))


class FaradayCupApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Faraday Cup TOF Energy Spectrum Analyzer")
        self.resize(1280, 820)
        self.worker = None
        self.spectra_df = None
        self.summary_df = None
        self.cycle_results = []
        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        controls = QVBoxLayout()
        controls.setSpacing(8)
        root.addLayout(controls, 0)

        file_box = QGroupBox("1. 数据文件")
        file_layout = QVBoxLayout(file_box)
        row = QHBoxLayout()
        self.input_csv = QLineEdit()
        self.input_csv.setPlaceholderText("选择示波器导出的 .Wfm.csv")
        browse = QPushButton("浏览")
        browse.clicked.connect(self._select_csv)
        row.addWidget(self.input_csv)
        row.addWidget(browse)
        file_layout.addLayout(row)
        self.output_excel = QLineEdit("output_cycles_energy_spectrum.xlsx")
        file_layout.addWidget(QLabel("Excel 输出路径"))
        file_layout.addWidget(self.output_excel)
        controls.addWidget(file_box)

        platform_box = QGroupBox("2. 光源平台 / Fcup 距离")
        platform_form = QFormLayout(platform_box)
        self.platform = QComboBox()
        self.platform.addItems(LIGHT_SOURCE_PLATFORMS.keys())
        self.platform.currentTextChanged.connect(self._on_platform_changed)
        self.distance = QDoubleSpinBox()
        self.distance.setRange(0.001, 100.0)
        self.distance.setDecimals(4)
        self.distance.setValue(0.60)
        self.distance.setSuffix(" m")
        platform_form.addRow("平台", self.platform)
        platform_form.addRow("Fcup 距离", self.distance)
        controls.addWidget(platform_box)

        ion_box = QGroupBox("3. 离子种类")
        ion_form = QFormLayout(ion_box)
        self.ion = QComboBox()
        self.ion.addItems(ION_SPECIES_DB.keys())
        self.ion.currentTextChanged.connect(self._on_ion_changed)
        self.mass = QDoubleSpinBox()
        self.mass.setRange(0.001, 1000.0)
        self.mass.setDecimals(6)
        self.mass.setValue(float(ION_SPECIES_DB["Xe"]["mass_amu"]))
        self.mass.setSuffix(" amu")
        self.charge = QSpinBox()
        self.charge.setRange(1, 20)
        self.charge.setValue(1)
        ion_form.addRow("离子", self.ion)
        ion_form.addRow("质量", self.mass)
        ion_form.addRow("价态 z", self.charge)
        controls.addWidget(ion_box)

        signal_box = QGroupBox("4. 采样与信号")
        signal_form = QFormLayout(signal_box)
        self.noise_points = QSpinBox()
        self.noise_points.setRange(1, 100_000_000)
        self.noise_points.setValue(100_000)
        self.sample_interval_ns = QDoubleSpinBox()
        self.sample_interval_ns.setRange(0.001, 1_000_000.0)
        self.sample_interval_ns.setDecimals(3)
        self.sample_interval_ns.setValue(1.0)
        self.sample_interval_ns.setSuffix(" ns")
        self.points_per_cycle = QSpinBox()
        self.points_per_cycle.setRange(10, 100_000_000)
        self.points_per_cycle.setValue(500_000)
        self.cycles = QSpinBox()
        self.cycles.setRange(0, 100_000)
        self.cycles.setValue(10)
        self.photo_start = QSpinBox()
        self.photo_start.setRange(0, 100_000_000)
        self.photo_start.setValue(245_000)
        self.photo_end = QSpinBox()
        self.photo_end.setRange(1, 100_000_000)
        self.photo_end.setValue(249_000)
        self.unit = QComboBox()
        self.unit.addItems(["V", "mV", "uV"])
        self.polarity = QComboBox()
        self.polarity.addItems(["positive", "negative", "absolute", "raw"])
        self.load_ohm = QDoubleSpinBox()
        self.load_ohm.setRange(0.001, 1_000_000.0)
        self.load_ohm.setValue(50.0)
        self.load_ohm.setSuffix(" Ω")
        signal_form.addRow("噪声点数", self.noise_points)
        signal_form.addRow("采样间隔", self.sample_interval_ns)
        signal_form.addRow("每周期点数", self.points_per_cycle)
        signal_form.addRow("周期数(0=自动)", self.cycles)
        signal_form.addRow("光电峰起点", self.photo_start)
        signal_form.addRow("光电峰终点", self.photo_end)
        signal_form.addRow("波形单位", self.unit)
        signal_form.addRow("信号极性", self.polarity)
        signal_form.addRow("负载", self.load_ohm)
        controls.addWidget(signal_box)

        energy_box = QGroupBox("5. 能量范围")
        energy_form = QFormLayout(energy_box)
        self.energy_start = QSpinBox()
        self.energy_start.setRange(1, 10_000_000)
        self.energy_start.setValue(300)
        self.energy_stop = QSpinBox()
        self.energy_stop.setRange(1, 10_000_000)
        self.energy_stop.setValue(20_000)
        self.interp = QComboBox()
        self.interp.addItems(["linear", "cubic", "nearest"])
        energy_form.addRow("起始 eV", self.energy_start)
        energy_form.addRow("终止 eV", self.energy_stop)
        energy_form.addRow("插值", self.interp)
        controls.addWidget(energy_box)

        grafana_box = QGroupBox("6. Grafana / InfluxDB 上传")
        grafana_form = QFormLayout(grafana_box)
        self.grafana_enabled = QCheckBox("分析后上传周期摘要")
        self.grafana_url = QLineEdit()
        self.grafana_url.setPlaceholderText("http://localhost:8086 或完整 /api/v2/write URL")
        self.grafana_org = QLineEdit()
        self.grafana_bucket = QLineEdit()
        self.grafana_token = QLineEdit()
        self.grafana_token.setEchoMode(QLineEdit.Password)
        self.grafana_measurement = QLineEdit("faraday_cup_cycle")
        grafana_form.addRow(self.grafana_enabled)
        grafana_form.addRow("URL", self.grafana_url)
        grafana_form.addRow("Org", self.grafana_org)
        grafana_form.addRow("Bucket", self.grafana_bucket)
        grafana_form.addRow("Token", self.grafana_token)
        grafana_form.addRow("Measurement", self.grafana_measurement)
        controls.addWidget(grafana_box)

        self.run_btn = QPushButton("开始分析")
        self.run_btn.clicked.connect(self._run_analysis)
        controls.addWidget(self.run_btn)
        controls.addStretch(1)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)
        self.plot = pg.PlotWidget(title="Energy Spectrum")
        self.plot.setLabel("bottom", "Energy", units="eV")
        self.plot.setLabel("left", "Ion flux", units="ions/eV-pulse")
        self.plot.addLegend()
        tabs.addTab(self.plot, "能谱")
        self.table = QTableWidget()
        tabs.addTab(self.table, "周期摘要")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        tabs.addTab(self.log, "日志")

    def _select_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择波形 CSV", "", "CSV Files (*.csv);;All Files (*)")
        if path:
            self.input_csv.setText(path)
            if self.output_excel.text() == "output_cycles_energy_spectrum.xlsx":
                self.output_excel.setText(str(Path(path).with_name(Path(path).stem + "_energy_spectrum.xlsx")))

    def _on_platform_changed(self, name):
        platform = LIGHT_SOURCE_PLATFORMS.get(name)
        if platform:
            self.distance.setValue(float(platform["distance_m"]))

    def _on_ion_changed(self, name):
        species = ION_SPECIES_DB.get(name)
        if species:
            self.mass.setValue(float(species["mass_amu"]))
            self.charge.setValue(int(species["charge_state"]))

    def _build_config(self) -> FaradayCupConfig:
        if self.energy_stop.value() <= self.energy_start.value():
            raise ValueError("终止能量必须大于起始能量")
        if self.photo_end.value() <= self.photo_start.value():
            raise ValueError("光电峰终点必须大于起点")
        cycles = self.cycles.value() or None
        return FaradayCupConfig(
            csv_file_path=self.input_csv.text().strip(),
            output_excel_file=self.output_excel.text().strip() or "output_cycles_energy_spectrum.xlsx",
            noise_points=self.noise_points.value(),
            sample_interval_s=self.sample_interval_ns.value() * 1e-9,
            points_per_cycle=self.points_per_cycle.value(),
            cycles=cycles,
            photoelectric_start=self.photo_start.value(),
            photoelectric_end=self.photo_end.value(),
            energy_start_ev=self.energy_start.value(),
            energy_stop_ev=self.energy_stop.value(),
            load_ohm=self.load_ohm.value(),
            waveform_unit=self.unit.currentText(),
            signal_polarity=self.polarity.currentText(),
            ion_species=self.ion.currentText(),
            ion_mass_amu=self.mass.value(),
            charge_state=self.charge.value(),
            platform_name=self.platform.currentText(),
            distance_m=self.distance.value(),
            interpolation_kind=self.interp.currentText(),
            grafana=GrafanaConfig(
                enabled=self.grafana_enabled.isChecked(),
                url=self.grafana_url.text().strip(),
                token=self.grafana_token.text().strip(),
                org=self.grafana_org.text().strip(),
                bucket=self.grafana_bucket.text().strip(),
                measurement=self.grafana_measurement.text().strip() or "faraday_cup_cycle",
            ),
        )

    def _run_analysis(self):
        try:
            config = self._build_config()
        except Exception as exc:
            QMessageBox.warning(self, "参数错误", str(exc))
            return
        if not config.csv_file_path:
            QMessageBox.warning(self, "缺少文件", "请先选择 CSV 波形文件")
            return
        self.run_btn.setEnabled(False)
        self.log.append("开始分析...")
        self.worker = FaradayCupWorker(config)
        self.worker.finished_signal.connect(self._analysis_finished)
        self.worker.error_signal.connect(self._analysis_failed)
        self.worker.start()

    def _analysis_finished(self, spectra_df, summary_df, cycle_results):
        self.run_btn.setEnabled(True)
        self.spectra_df = spectra_df
        self.summary_df = summary_df
        self.cycle_results = cycle_results
        self._refresh_plot()
        self._refresh_table()
        self.log.append(f"完成：{len(summary_df)} 个周期，已导出 Excel。")

    def _analysis_failed(self, message):
        self.run_btn.setEnabled(True)
        self.log.append(f"错误：{message}")
        QMessageBox.critical(self, "分析失败", message)

    def _refresh_plot(self):
        self.plot.clear()
        self.plot.addLegend()
        for result in self.cycle_results:
            mask = result.interpolated_spectrum > 0
            self.plot.plot(
                result.energy_grid_ev[mask],
                result.interpolated_spectrum[mask],
                pen=pg.intColor(result.cycle, hues=max(3, len(self.cycle_results))),
                name=f"Cycle {result.cycle}",
            )
        self.plot.setLogMode(x=True, y=True)

    def _refresh_table(self):
        if self.summary_df is None:
            return
        self.table.setRowCount(len(self.summary_df))
        self.table.setColumnCount(len(self.summary_df.columns))
        self.table.setHorizontalHeaderLabels(list(self.summary_df.columns))
        for row_idx, (_, row) in enumerate(self.summary_df.iterrows()):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(f"{value:.6g}" if isinstance(value, float) else str(value))
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)
        self.table.resizeColumnsToContents()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FaradayCupApp()
    window.show()
    sys.exit(app.exec_())
