import sys
import time
import csv
import os
from datetime import datetime
from collections import deque
from bisect import bisect_left

import pandas as pd  # 用于读取 RGA 数据

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QDoubleSpinBox, QMessageBox, QRadioButton, QButtonGroup,
    QLineEdit, QFormLayout, QGroupBox, QSpinBox, QCheckBox, QFileDialog,
    QDateTimeEdit, QToolButton, QTabWidget
)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal, QDateTime
import pyqtgraph as pg

# ==========================================
# 导入模块
# ==========================================
try:
    from model import qcm_calc, MATERIALS_DB
    from data_source import MockQCMStream, IC6TxtReplay, EthernetQCMClient
    # [新增] 导入报告生成模块
    from report_module import StandardReportGenerator
except ImportError as e:
    print("!!! 严重错误: 找不到必要的模块 (model, data_source, 或 report_module) !!!")
    print(f"详情: {e}")
    sys.exit(1)

pg.setConfigOption("background", "w")
pg.setConfigOption("foreground", "k")
pg.setConfigOption('antialias', True)


# ==========================================
# 0. 工作线程 (保留 V3.7 完整功能)
# ==========================================
class QCMWorker(QThread):
    chunk_signal = pyqtSignal(list)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    log_path_signal = pyqtSignal(str)

    def __init__(self, data_source, is_file_replay, speed=1, save_csv=False, custom_csv_path="",
                 replay_interval_ms=0):
        super().__init__()
        self.ds = data_source
        self.is_file_replay = is_file_replay
        self.speed = speed
        self.save_csv = save_csv
        self.custom_csv_path = custom_csv_path
        self.running = True
        self.csv_file = None
        self.csv_writer = None
        self.replay_interval_ms = replay_interval_ms

    def run(self):
        # 1. 初始化 CSV
        if self.save_csv:
            try:
                if self.custom_csv_path and self.custom_csv_path.strip():
                    filename = self.custom_csv_path
                else:
                    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"QCM_Log_{ts_str}.csv"

                dirname = os.path.dirname(os.path.abspath(filename))
                if dirname and not os.path.exists(dirname): os.makedirs(dirname)

                self.csv_file = open(filename, mode='w', newline='', encoding='utf-8')
                self.csv_writer = csv.writer(self.csv_file)
                # 表头包含原始频率和变化频率
                self.csv_writer.writerow(
                    ["Timestamp_Unix", "Local_Time", "Frequency_Raw_Hz", "Frequency_Shift_Hz", "Thickness_nm",
                     "Rate_A_s"])
                self.log_path_signal.emit(os.path.abspath(filename))
            except Exception as e:
                self.error_signal.emit(f"CSV Init Error: {e}")

        # 2. 循环读取
        batch_buffer = []
        last_emit_time = time.time()

        while self.running:
            try:
                loops = self.speed if self.is_file_replay else 1
                for _ in range(loops):
                    if not self.running: break
                    data = self.ds.read()
                    if data:
                        # CSV 写入逻辑由 Worker 处理，减轻 UI 负担
                        # 注意：这里只写原始数据，厚度速率由主线程计算后写入或此处计算
                        # 为简化，这里 Worker 只负责透传 Raw Data，CSV 写入推迟到主线程处理可能更准确，
                        # 但为了性能，我们通常在 Worker 写 Raw Data。
                        # 修正：为了保证 CSV 包含所有计算值，建议在主线程接收到数据后写入，
                        # 或者在这里只写 Raw，主线程另存一份。
                        # V3.7 逻辑是 Worker 写基础数据。这里我们保持 Worker 写基础，高级报告由主线程生成。
                        if self.csv_writer:
                            dt_str = datetime.fromtimestamp(data['timestamp']).strftime("%Y-%m-%d %H:%M:%S.%f")
                            self.csv_writer.writerow([f"{data['timestamp']:.4f}", dt_str, f"{data['frequency']:.2f}"])

                        batch_buffer.append(data)
                    else:
                        if self.is_file_replay:
                            if batch_buffer: self.chunk_signal.emit(batch_buffer)
                            self.running = False;
                            self.finished_signal.emit();
                            self.cleanup();
                            return
                        else:
                            break

                current_time = time.time()
                if len(batch_buffer) > 0:
                    if self.is_file_replay or len(batch_buffer) >= 10 or (current_time - last_emit_time > 0.03):
                        self.chunk_signal.emit(batch_buffer)
                        batch_buffer = []
                        last_emit_time = current_time

                if not self.is_file_replay:
                    self.msleep(10)
                else:
                    if self.replay_interval_ms > 0:
                        self.msleep(self.replay_interval_ms)
                    elif self.speed < 100:
                        self.msleep(5)

            except Exception as e:
                self.error_signal.emit(str(e))
                self.running = False
        self.cleanup()

    def cleanup(self):
        if self.csv_file: self.csv_file.close(); self.csv_file = None

    def stop(self):
        self.running = False;
        self.wait()


# ==========================================
# 1. 动态时间轴 (保留 V3.7 双行显示)
# ==========================================
class DynamicTimeAxis(pg.AxisItem):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_absolute = False

    def tickStrings(self, values, scale, spacing):
        if self.is_absolute:
            strings = []
            for v in values:
                try:
                    strings.append(datetime.fromtimestamp(v).strftime("%Y-%m-%d\n%H:%M:%S"))
                except:
                    strings.append("")
            return strings
        else:
            return [f"{v:.1f}" for v in values]


# ==========================================
# 2. 主窗口 (集成 V4.0 报告功能)
# ==========================================
class QCMApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("XKL QCM Analyzer Pro V4.0 (Integrated Report)")
        self.resize(1400, 900)

        self.worker = None
        self.ds = None
        self.f0 = None
        self.start_ts = None
        self.material_name = "Sn"
        self.last_smooth_rate = 0.0

        # 数据容器
        MAX_LEN = 100000
        self.time_data = deque(maxlen=MAX_LEN)
        self.abs_time_data = deque(maxlen=MAX_LEN)
        self.freq_data = deque(maxlen=MAX_LEN)  # Shift
        self.raw_freq_data = deque(maxlen=MAX_LEN)  # Raw
        self.thick_data = deque(maxlen=MAX_LEN)
        self.rate_data = deque(maxlen=MAX_LEN)

        self.plot_timer = QTimer()
        self.plot_timer.setInterval(33)
        self.plot_timer.timeout.connect(self.refresh_plots)

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()
        ctrl_panel = QVBoxLayout()
        ctrl_panel.setSpacing(10)

        # --- A. 数据源 ---
        gb_source = QGroupBox("1. Data Connection")
        vb_source = QVBoxLayout()
        self.group_source = QButtonGroup()
        self.rb_mock = QRadioButton("Mock Simulation")
        self.rb_file = QRadioButton("File Replay")
        self.rb_net = QRadioButton("Ethernet (TCP)")
        self.group_source.addButton(self.rb_mock, 1)
        self.group_source.addButton(self.rb_file, 2)
        self.group_source.addButton(self.rb_net, 3)
        self.rb_net.setChecked(True)
        self.group_source.buttonClicked.connect(self.on_source_changed)

        self.widget_file = QWidget()
        l_f = QHBoxLayout(self.widget_file);
        l_f.setContentsMargins(0, 0, 0, 0)
        self.input_file_path = QLineEdit("IC6_Data_Log.txt")
        self.btn_browse = QPushButton("...");
        self.btn_browse.setFixedWidth(30);
        self.btn_browse.clicked.connect(self.select_file)
        l_f.addWidget(self.input_file_path);
        l_f.addWidget(self.btn_browse)

        self.widget_net = QWidget()
        f_net = QFormLayout(self.widget_net);
        f_net.setContentsMargins(0, 0, 0, 0)
        self.input_ip = QLineEdit("10.211.72.202");
        self.input_port = QLineEdit("2101")
        self.lbl_net_status = QLabel("Disconnected");
        self.lbl_net_status.setStyleSheet("color: gray")
        f_net.addRow("IP:", self.input_ip);
        f_net.addRow("Port:", self.input_port);
        f_net.addRow("Status:", self.lbl_net_status)

        vb_source.addWidget(self.rb_mock);
        vb_source.addWidget(self.rb_file);
        vb_source.addWidget(self.widget_file)
        vb_source.addWidget(self.rb_net);
        vb_source.addWidget(self.widget_net)
        gb_source.setLayout(vb_source)

        # --- B. 参数 (保留 V3.7 所有设置) ---
        gb_param = QGroupBox("2. Parameters")
        f_param = QFormLayout()
        self.combo_mat = QComboBox();
        self.combo_mat.addItems(MATERIALS_DB.keys());
        self.combo_mat.setCurrentText("Sn")
        self.combo_mat.currentTextChanged.connect(self.on_material_changed)

        self.widget_tooling_container = QWidget()
        layout_tooling_v = QVBoxLayout(self.widget_tooling_container);
        layout_tooling_v.setContentsMargins(0, 0, 0, 0)
        row_tooling_top = QWidget();
        layout_tooling_h = QHBoxLayout(row_tooling_top);
        layout_tooling_h.setContentsMargins(0, 0, 0, 0)
        self.spin_tooling = QDoubleSpinBox();
        self.spin_tooling.setRange(10, 500);
        self.spin_tooling.setValue(150.2);
        self.spin_tooling.setSuffix("%")
        self.spin_tooling.valueChanged.connect(self.on_tooling_changed)
        self.btn_calib_date = QPushButton("🕒");
        self.btn_calib_date.setCheckable(True);
        self.btn_calib_date.setFixedWidth(30);
        self.btn_calib_date.setStyleSheet("border: none; font-size: 14px;")
        layout_tooling_h.addWidget(self.spin_tooling);
        layout_tooling_h.addWidget(self.btn_calib_date)
        self.date_calib = QDateTimeEdit(QDateTime.currentDateTime());
        self.date_calib.setDisplayFormat("yyyy-MM-dd HH:mm");
        self.date_calib.setVisible(False)
        self.btn_calib_date.toggled.connect(self.date_calib.setVisible)
        layout_tooling_v.addWidget(row_tooling_top);
        layout_tooling_v.addWidget(self.date_calib)

        self.spin_speed = QSpinBox();
        self.spin_speed.setRange(1, 5000);
        self.spin_speed.setValue(100);
        self.spin_speed.setSuffix(" x")

        self.chk_abs_time = QCheckBox("Show Clock Time");
        self.chk_abs_time.setChecked(True)
        self.chk_abs_time.toggled.connect(self.on_time_axis_changed)

        self.chk_raw_freq = QCheckBox("Show Raw Freq (Hz)");
        self.chk_raw_freq.setChecked(False)
        self.chk_raw_freq.setStyleSheet("color: #D32F2F;")
        self.chk_raw_freq.toggled.connect(self.on_raw_freq_changed)

        f_param.addRow("Material:", self.combo_mat)
        f_param.addRow("Tooling:", self.widget_tooling_container)
        f_param.addRow("Replay Speed:", self.spin_speed)
        f_param.addRow(self.chk_abs_time)
        f_param.addRow(self.chk_raw_freq)
        gb_param.setLayout(f_param)

        # --- C. 实验报告 & 交叉校准 (新增功能) ---
        gb_report = QGroupBox("3. Report & Calibration")
        f_report = QFormLayout()

        # 平台选择 (Section 1)
        self.combo_platform = QComboBox()
        self.combo_platform.addItems(["DPP (Discharge)", "LRP (Laser)", "LDP (Hybrid)"])
        self.combo_platform.setToolTip("选择光源平台类型 (Section 1)")

        # 台阶仪校准 (Section 11)
        self.spin_step_thick = QDoubleSpinBox()
        self.spin_step_thick.setRange(0, 10000)
        self.spin_step_thick.setSuffix(" nm")
        self.spin_step_thick.setToolTip("输入台阶仪测得的物理厚度，用于计算有效密度 (Section 11)")

        # RGA 导入 (Section 3)
        self.widget_rga_path = QWidget();
        layout_rga = QHBoxLayout(self.widget_rga_path);
        layout_rga.setContentsMargins(0, 0, 0, 0)
        self.input_rga_path = QLineEdit();
        self.input_rga_path.setPlaceholderText("RGA CSV File...")
        self.btn_rga_browse = QPushButton("...");
        self.btn_rga_browse.setFixedWidth(30)
        self.btn_rga_browse.clicked.connect(self.select_rga_file)
        layout_rga.addWidget(self.input_rga_path);
        layout_rga.addWidget(self.btn_rga_browse)

        # 报告生成按钮
        self.btn_gen_report = QPushButton("Generate Official Report")
        self.btn_gen_report.setStyleSheet("background-color: #673AB7; color: white; padding: 6px; font-weight: bold;")
        self.btn_gen_report.clicked.connect(self.generate_full_report)

        f_report.addRow("Platform:", self.combo_platform)
        f_report.addRow("Step Profiler:", self.spin_step_thick)
        f_report.addRow("RGA Data:", self.widget_rga_path)
        f_report.addRow(self.btn_gen_report)
        gb_report.setLayout(f_report)

        # --- D. 基础记录控制 ---
        gb_ctrl = QGroupBox("4. Control")
        vb_ctrl = QVBoxLayout()

        self.chk_record = QCheckBox("Save QCM to CSV");
        self.chk_record.setChecked(True);
        self.chk_record.setStyleSheet("font-weight: bold; color: blue;")
        self.widget_csv_path = QWidget();
        layout_csv = QHBoxLayout(self.widget_csv_path);
        layout_csv.setContentsMargins(0, 0, 0, 0)
        self.input_csv_path = QLineEdit();
        self.input_csv_path.setPlaceholderText("Auto-generated Path")
        self.btn_csv_browse = QPushButton("...");
        self.btn_csv_browse.setFixedWidth(30);
        self.btn_csv_browse.clicked.connect(self.select_save_csv)
        layout_csv.addWidget(self.input_csv_path);
        layout_csv.addWidget(self.btn_csv_browse)

        self.btn_save_img = QPushButton("Screenshot Graph");
        self.btn_save_img.clicked.connect(self.save_plots_as_image)

        self.combo_live_refresh = QComboBox()
        self.combo_live_refresh.addItem("Live Refresh: 5 seconds", 5_000)
        self.combo_live_refresh.addItem("Live Refresh: 1 minute", 60_000)
        self.combo_live_refresh.addItem("Live Refresh: 5 minutes", 300_000)
        self.combo_live_refresh.addItem("Live Refresh: 30 minutes", 1_800_000)
        self.combo_live_refresh.setToolTip(
            "File Replay 模式下每隔所选时间读取一批数据并刷新图表。"
            "该模式必须选择 CSV 保存文件。"
        )

        self.btn_start = QPushButton("START");
        self.btn_start.setStyleSheet("background: #2e7d32; color: white; padding: 10px; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_experiment)
        self.btn_stop = QPushButton("STOP");
        self.btn_stop.setStyleSheet("background: #c62828; color: white; padding: 10px; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_experiment);
        self.btn_stop.setEnabled(False)
        self.lbl_status = QLabel("Ready");
        self.lbl_status.setAlignment(Qt.AlignCenter);
        self.lbl_status.setStyleSheet("background: #f0f0f0; border: 1px solid #ccc; padding: 5px;")

        vb_ctrl.addWidget(self.chk_record);
        vb_ctrl.addWidget(self.widget_csv_path)
        vb_ctrl.addWidget(self.btn_save_img)
        vb_ctrl.addWidget(self.combo_live_refresh)
        vb_ctrl.addWidget(self.btn_start);
        vb_ctrl.addWidget(self.btn_stop);
        vb_ctrl.addWidget(self.lbl_status)
        gb_ctrl.setLayout(vb_ctrl)

        ctrl_panel.addWidget(gb_source);
        ctrl_panel.addWidget(gb_param)
        ctrl_panel.addWidget(gb_report);
        ctrl_panel.addWidget(gb_ctrl)  # [修改] 布局顺序
        ctrl_panel.addStretch()

        # --- 右侧绘图 ---
        self.plot_container = QWidget();
        self.plot_container.setStyleSheet("background: white;")
        p_layout = QVBoxLayout(self.plot_container)
        self.axis_f = DynamicTimeAxis(orientation='bottom');
        self.axis_t = DynamicTimeAxis(orientation='bottom');
        self.axis_r = DynamicTimeAxis(orientation='bottom')
        self.axes_list = [self.axis_f, self.axis_t, self.axis_r];
        self.axis_f.is_absolute = True

        self.plot_f = pg.PlotWidget(title="Freq Shift (Hz)", axisItems={'bottom': self.axis_f})
        self.plot_t = pg.PlotWidget(title="Thickness (nm)", axisItems={'bottom': self.axis_t})
        self.plot_r = pg.PlotWidget(title="Rate (Å/s)", axisItems={'bottom': self.axis_r})

        for p, unit, name in zip([self.plot_f, self.plot_t, self.plot_r], ["Hz", "nm", "Å/s"], ["Freq", "Thk", "Rate"]):
            p.showGrid(x=True, y=True, alpha=0.3);
            p.setClipToView(True);
            p.setDownsampling(mode='peak')
            p.getAxis('bottom').setHeight(60);
            p.getAxis('left').setWidth(60);
            p.setLabel('left', "Value", units=unit)
            p_layout.addWidget(p);
            self.add_crosshair(p, name, unit)

        self.plot_f.setXLink(self.plot_t);
        self.plot_r.setXLink(self.plot_t)
        self.curve_f = self.plot_f.plot(pen=pg.mkPen('k', width=2))
        self.curve_t = self.plot_t.plot(pen=pg.mkPen('r', width=2))
        self.curve_r = self.plot_r.plot(pen=pg.mkPen('b', width=2))
        main_layout.addLayout(ctrl_panel, 1);
        main_layout.addWidget(self.plot_container, 4);
        self.setLayout(main_layout)
        self.on_source_changed(None)

    # ... (常规槽函数保持 V3.7 不变) ...
    def on_source_changed(self, btn):
        sid = self.group_source.checkedId()
        is_file_replay = sid == 2
        self.widget_file.setVisible(is_file_replay);
        self.widget_net.setVisible(sid == 3)
        if is_file_replay:
            self.chk_record.setChecked(True)
        self.chk_record.setEnabled(not is_file_replay)

    def select_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Select Log", "", "Txt (*.txt);;All (*)")
        if fname: self.input_file_path.setText(fname)

    def select_save_csv(self):
        fname, _ = QFileDialog.getSaveFileName(self, "Save Data As", f"QCM_{datetime.now().strftime('%Y%m%d')}.csv",
                                               "CSV Files (*.csv)")
        if fname: self.input_csv_path.setText(fname)

    # [新增] RGA 文件选择
    def select_rga_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Select RGA CSV", "", "CSV Files (*.csv);;All (*)")
        if fname: self.input_rga_path.setText(fname)

    # [新增] 报告生成逻辑
    def generate_full_report(self):
        if len(self.time_data) == 0:
            QMessageBox.warning(self, "No Data", "请先运行实验或加载 QCM 数据。")
            return

        # 1. 询问保存路径
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Report",
                                                   f"Report_{datetime.now().strftime('%Y%m%d')}.docx",
                                                   "Word Documents (*.docx)")
        if not save_path: return

        # 2. 收集元数据 (对应上传文档要求)
        meta = {
            "operator": "Engineer",
            "platform": self.combo_platform.currentText(),  # Section 1
            "sample_id": f"Sample-{int(time.time())}",
            "material": self.material_name,
            "tooling": self.spin_tooling.value(),
            "step_thick": self.spin_step_thick.value(),  # Section 11
            "rga_file": os.path.basename(self.input_rga_path.text())
        }

        # 3. 准备 QCM 数据
        qcm_pack = {
            "time": list(self.time_data),
            "thick": list(self.thick_data),
            "rate": list(self.rate_data),
            "freq": list(self.freq_data)  # Shift
        }

        # 4. 读取 RGA 数据
        rga_df = None
        if self.input_rga_path.text():
            try:
                rga_df = pd.read_csv(self.input_rga_path.text())
            except Exception as e:
                QMessageBox.warning(self, "RGA Error", f"无法读取 RGA 文件: {e}")

        # 5. 生成
        generator = StandardReportGenerator()
        self.lbl_status.setText("Generating Report...")
        QApplication.processEvents()  # 刷新界面

        success, msg = generator.generate(save_path, meta, qcm_pack, rga_df)

        if success:
            self.lbl_status.setText("Report Ready")
            QMessageBox.information(self, "Success", msg)
            try:
                os.startfile(save_path)
            except:
                pass
        else:
            self.lbl_status.setText("Report Failed")
            QMessageBox.critical(self, "Error", msg)

    def on_material_changed(self, name):
        self.material_name = name
        if not self.worker and len(self.freq_data) > 0: self.recalculate_all()

    def on_tooling_changed(self, val):
        qcm_calc.set_tooling(val)
        if not self.worker and len(self.freq_data) > 0: self.recalculate_all()

    def recalculate_all(self):
        freqs = list(self.freq_data)
        new_thicks = [qcm_calc.freq_to_thickness(f, self.material_name) for f in freqs]
        self.thick_data.clear();
        self.thick_data.extend(new_thicks);
        self.refresh_plots()

    def on_time_axis_changed(self, checked):
        for ax in self.axes_list: ax.is_absolute = checked
        self.refresh_plots()

    def on_raw_freq_changed(self, checked):
        if checked:
            self.plot_f.setTitle("Raw Frequency (Hz)")
            self.plot_f.setLabel('left', "Raw Freq", units="Hz")
            if self.raw_freq_data: self.curve_f.setData(
                list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data),
                list(self.raw_freq_data)); self.plot_f.enableAutoRange(axis='y')
        else:
            self.plot_f.setTitle("Freq Shift (Hz)")
            self.plot_f.setLabel('left', "Shift", units="Hz")
            if self.freq_data: self.curve_f.setData(
                list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data),
                list(self.freq_data)); self.plot_f.enableAutoRange(axis='y')
        self.refresh_plots()

    def save_plots_as_image(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save Graphs",
                                                  f"QCM_Graph_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                                                  "PNG Image (*.png);;JPEG Image (*.jpg)")
        if filename:
            screen = QApplication.primaryScreen();
            pixmap = screen.grabWindow(self.plot_container.winId());
            pixmap.save(filename)
            QMessageBox.information(self, "Saved", f"Graphs saved to:\n{filename}")

    def _series_for_crosshair(self, prefix):
        x_data = list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data)
        if prefix == "Freq":
            y_data = list(self.raw_freq_data) if self.chk_raw_freq.isChecked() else list(self.freq_data)
            display_prefix = "Raw" if self.chk_raw_freq.isChecked() else "Freq"
        elif prefix == "Thk":
            y_data = list(self.thick_data)
            display_prefix = "Thk"
        else:
            y_data = list(self.rate_data)
            display_prefix = "Rate"
        return x_data, y_data, display_prefix

    def _nearest_point(self, x_data, y_data, x):
        if not x_data or not y_data:
            return None
        idx = bisect_left(x_data, x)
        if idx <= 0:
            nearest = 0
        elif idx >= len(x_data):
            nearest = len(x_data) - 1
        else:
            before = idx - 1
            nearest = idx if abs(x_data[idx] - x) < abs(x_data[before] - x) else before
        if nearest >= len(y_data):
            return None
        return nearest, x_data[nearest], y_data[nearest]

    def add_crosshair(self, plot, prefix, suffix):
        v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#666', style=Qt.DashLine))
        h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('#666', style=Qt.DashLine))
        plot.addItem(v_line, ignoreBounds=True);
        plot.addItem(h_line, ignoreBounds=True)
        label = pg.TextItem(anchor=(0, 1), color="k", fill=pg.mkBrush(255, 255, 255, 200));
        plot.addItem(label)

        def mouse_moved(evt):
            pos = evt[0]
            if plot.sceneBoundingRect().contains(pos):
                mouse_point = plot.plotItem.vb.mapSceneToView(pos);
                x = mouse_point.x()
                x_data, y_data, display_prefix = self._series_for_crosshair(prefix)
                nearest = self._nearest_point(x_data, y_data, x)
                if nearest is None:
                    return
                idx, sample_x, sample_y = nearest
                v_line.setPos(sample_x);
                h_line.setPos(sample_y)
                if self.chk_abs_time.isChecked():
                    try:
                        t_str = datetime.fromtimestamp(sample_x).strftime("%H:%M:%S.%f")[:-3]
                    except:
                        t_str = "Inv"
                else:
                    t_str = f"{sample_x:.6f}s"
                label.setText(f"Time: {t_str}\n{display_prefix}: {sample_y:.8g} {suffix}\nPoint: {idx + 1}");
                label.setPos(sample_x, sample_y)
                v_line.show();
                h_line.show();
                label.show()

        proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)
        setattr(plot, 'crosshair_proxy', proxy)

    def start_experiment(self):
        src_id = self.group_source.checkedId()
        if src_id == 2 and not self.input_csv_path.text().strip():
            QMessageBox.warning(
                self,
                "Select Save File",
                "File Replay 的实时刷新模式需要先选择一个 CSV 保存文件。"
            )
            self.select_save_csv()
            if not self.input_csv_path.text().strip():
                return
        self.lbl_net_status.setText("Disconnected");
        self.lbl_net_status.setStyleSheet("color: gray")
        self.input_csv_path.setEnabled(False);
        self.btn_csv_browse.setEnabled(False)
        try:
            if src_id == 1:
                self.ds = MockQCMStream()
            elif src_id == 2:
                path = self.input_file_path.text();
                if not path: return
                self.ds = IC6TxtReplay(path)
            elif src_id == 3:
                ip = self.input_ip.text();
                port = int(self.input_port.text())
                self.lbl_net_status.setText("Connecting...");
                QApplication.processEvents()
                self.ds = EthernetQCMClient(ip, port)
            self.ds.connect()
            if src_id == 3:
                if self.ds.sock:
                    self.lbl_net_status.setText("Connected"); self.lbl_net_status.setStyleSheet(
                        "color: green; font-weight: bold;")
                else:
                    self.lbl_net_status.setText("Failed"); self.lbl_net_status.setStyleSheet(
                        "color: red; font-weight: bold;"); raise ConnectionError("Network connection failed")

            self.time_data.clear();
            self.abs_time_data.clear()
            self.freq_data.clear();
            self.raw_freq_data.clear();
            self.thick_data.clear();
            self.rate_data.clear()
            self.f0 = None;
            self.start_ts = None;
            self.last_smooth_rate = 0.0

            speed = self.spin_speed.value();
            save_csv = self.chk_record.isChecked() or src_id == 2
            custom_path = self.input_csv_path.text().strip()
            replay_interval_ms = self.combo_live_refresh.currentData() if src_id == 2 else 0
            self.worker = QCMWorker(self.ds, is_file_replay=(src_id == 2), speed=speed, save_csv=save_csv,
                                    custom_csv_path=custom_path, replay_interval_ms=replay_interval_ms)
            self.worker.chunk_signal.connect(self.process_chunk);
            self.worker.finished_signal.connect(self.on_replay_finished)
            self.worker.error_signal.connect(self.on_worker_error);
            self.worker.log_path_signal.connect(self.on_log_path_received)
            self.worker.start();
            self.plot_timer.start()
            self.btn_start.setEnabled(False);
            self.btn_stop.setEnabled(True);
            self.lbl_status.setText("RUNNING");
            self.lbl_status.setStyleSheet("background: #C8E6C9;")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); self.stop_experiment()

    def stop_experiment(self):
        self.plot_timer.stop()
        if self.worker: self.worker.stop(); self.worker = None
        if self.ds: self.ds.disconnect()
        self.input_csv_path.setEnabled(True);
        self.btn_csv_browse.setEnabled(True)
        self.btn_start.setEnabled(True);
        self.btn_stop.setEnabled(False);
        self.lbl_status.setText("STOPPED");
        self.lbl_status.setStyleSheet("background: #f0f0f0;")
        if self.group_source.checkedId() == 3: self.lbl_net_status.setText(
            "Disconnected"); self.lbl_net_status.setStyleSheet("color: gray")
        self.refresh_plots()

    def on_log_path_received(self, path):
        self.input_csv_path.setText(path); self.input_csv_path.setToolTip(f"Recording to: {path}")

    def on_replay_finished(self):
        self.stop_experiment(); QMessageBox.information(self, "Info", "Replay Finished")

    def on_worker_error(self, msg):
        self.stop_experiment(); QMessageBox.warning(self, "Error", msg)

    def refresh_plots(self):
        if not self.time_data: return
        x_data = list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data)
        if self.chk_raw_freq.isChecked():
            self.curve_f.setData(x_data, list(self.raw_freq_data))
            if self.raw_freq_data: self.plot_f.enableAutoRange(axis='y')
        else:
            self.curve_f.setData(x_data, list(self.freq_data))
            if self.freq_data: self.plot_f.enableAutoRange(axis='y')
        self.curve_t.setData(x_data, list(self.thick_data))
        self.curve_r.setData(x_data, list(self.rate_data))

    def process_chunk(self, data_list):
        for data in data_list:
            now_ts = data["timestamp"];
            raw_f = data["frequency"]
            if self.start_ts is None: self.start_ts = now_ts; self.f0 = raw_f
            t_rel = now_ts - self.start_ts
            delta_f = raw_f - self.f0
            thick = qcm_calc.freq_to_thickness(delta_f, self.material_name)
            self.abs_time_data.append(now_ts);
            self.time_data.append(t_rel)
            self.freq_data.append(delta_f);
            self.raw_freq_data.append(raw_f)
            self.thick_data.append(thick)

            # 使用 V3.6 的平滑逻辑
            raw_rate = qcm_calc.calc_rate(list(self.time_data), list(self.thick_data), window=60)
            alpha = 0.2
            if len(self.rate_data) == 0:
                smooth_rate = raw_rate
            else:
                smooth_rate = alpha * raw_rate + (1 - alpha) * self.last_smooth_rate
            self.last_smooth_rate = smooth_rate
            self.rate_data.append(smooth_rate)

        if len(self.freq_data) > 60:
            if qcm_calc.is_steady_state(list(self.freq_data)[-60:], list(self.time_data)[-60:], 1.0):
                self.lbl_status.setText("STEADY");
                self.lbl_status.setStyleSheet("background: #BBDEFB;")
            else:
                self.lbl_status.setText("RUNNING"); self.lbl_status.setStyleSheet("background: #C8E6C9;")


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv); win = QCMApp(); win.show(); sys.exit(app.exec_())
    except Exception as e:
        print("CRASH:", e); input("Press Enter...")
