import sys
import time
import csv
import os
from datetime import datetime
import math
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

    def __init__(self, data_source, is_file_replay, speed=1, save_csv=False, custom_csv_path=""):
        super().__init__()
        self.ds = data_source
        self.is_file_replay = is_file_replay
        self.speed = speed
        self.save_csv = save_csv
        self.custom_csv_path = custom_csv_path
        self.running = True
        self.csv_file = None
        self.csv_writer = None

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
                    # Yield between replay chunks so the GUI event loop can repaint
                    # instead of waiting for a click or for replay completion.
                    self.msleep(10)

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
        self.material_name = "InSn"
        self.last_smooth_rate = 0.0
        self.plot_dirty = False
        self.last_plot_refresh_time = 0.0
        self.csv_file = None
        self.csv_writer = None
        self.rate_region_initialized = False

        # 数据容器
        MAX_LEN = 100000
        self.time_data = deque(maxlen=MAX_LEN)
        self.abs_time_data = deque(maxlen=MAX_LEN)
        self.freq_data = deque(maxlen=MAX_LEN)  # Shift
        self.raw_freq_data = deque(maxlen=MAX_LEN)  # Raw
        self.thick_data = deque(maxlen=MAX_LEN)
        self.rate_data = deque(maxlen=MAX_LEN)
        self.epd_time_data = []
        self.epd_current_data = []
        self.epd_time_is_absolute = False

        self.plot_timer = QTimer()
        self.plot_timer.setInterval(33)
        self.plot_timer.timeout.connect(self.refresh_plots)
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.setInterval(1000)
        self.auto_refresh_timer.timeout.connect(self.on_auto_refresh_tick)

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
        self.combo_mat.setCurrentText("InSn")
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
        self.combo_platform.setCurrentText("LRP (Laser)")
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

        # --- D. 沉积统计 ---
        gb_stats = QGroupBox("4. Deposition Statistics")
        f_stats = QFormLayout()

        self.spin_ref_area = QDoubleSpinBox()
        self.spin_ref_area.setRange(0.000001, 1000000.0)
        self.spin_ref_area.setDecimals(4)
        self.spin_ref_area.setValue(1.0)
        self.spin_ref_area.setSuffix(" cm²")
        self.spin_ref_area.setToolTip("参考样品/沉积区域面积；Total Mass (Ref) 和 ng/s 按此面积换算。")
        self.spin_ref_area.valueChanged.connect(self.update_deposition_stats)

        self.lbl_stat_time = QLabel("--")
        self.lbl_stat_mass_density = QLabel("--")
        self.lbl_stat_total_mass = QLabel("--")
        self.lbl_stat_avg_rate_a = QLabel("--")
        self.lbl_stat_avg_rate_ng = QLabel("--")
        self.lbl_rate_region_mean = QLabel("--")
        self.lbl_rate_region_std = QLabel("--")
        self.lbl_epd_decay = QLabel("--")
        self.widget_epd_path = QWidget()
        layout_epd = QHBoxLayout(self.widget_epd_path)
        layout_epd.setContentsMargins(0, 0, 0, 0)
        self.input_epd_path = QLineEdit()
        self.input_epd_path.setPlaceholderText("EPD CSV: time,current_nA")
        self.btn_epd_browse = QPushButton("...")
        self.btn_epd_browse.setFixedWidth(30)
        self.btn_epd_browse.clicked.connect(self.select_epd_file)
        layout_epd.addWidget(self.input_epd_path)
        layout_epd.addWidget(self.btn_epd_browse)
        for lbl in [self.lbl_stat_time, self.lbl_stat_mass_density, self.lbl_stat_total_mass,
                    self.lbl_stat_avg_rate_a, self.lbl_stat_avg_rate_ng,
                    self.lbl_rate_region_mean, self.lbl_rate_region_std, self.lbl_epd_decay]:
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet("background: #fafafa; border: 1px solid #ddd; padding: 3px;")

        f_stats.addRow("Ref Area:", self.spin_ref_area)
        f_stats.addRow("Time:", self.lbl_stat_time)
        f_stats.addRow("Mass density @ QCM:", self.lbl_stat_mass_density)
        f_stats.addRow("Total Mass (Ref):", self.lbl_stat_total_mass)
        f_stats.addRow("Average rate (Å/s):", self.lbl_stat_avg_rate_a)
        f_stats.addRow("Average rate (ng/s):", self.lbl_stat_avg_rate_ng)
        f_stats.addRow("EPD Data:", self.widget_epd_path)
        f_stats.addRow("Rate ROI mean:", self.lbl_rate_region_mean)
        f_stats.addRow("Rate ROI std:", self.lbl_rate_region_std)
        f_stats.addRow("EPD decay:", self.lbl_epd_decay)
        gb_stats.setLayout(f_stats)

        # --- E. 基础记录控制 ---
        gb_ctrl = QGroupBox("5. Control")
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

        self.btn_auto_refresh = QPushButton("Live Refresh: OFF (1s)")
        self.btn_auto_refresh.setCheckable(True)
        self.btn_auto_refresh.setToolTip("每秒自动读取最新缓冲数据并刷新曲线；文件回放模式下无需点击图表也会更新显示。")
        self.btn_auto_refresh.toggled.connect(self.on_auto_refresh_toggled)

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
        vb_ctrl.addWidget(self.btn_auto_refresh)
        vb_ctrl.addWidget(self.btn_start);
        vb_ctrl.addWidget(self.btn_stop);
        vb_ctrl.addWidget(self.lbl_status)
        gb_ctrl.setLayout(vb_ctrl)

        ctrl_panel.addWidget(gb_source);
        ctrl_panel.addWidget(gb_param)
        ctrl_panel.addWidget(gb_report);
        ctrl_panel.addWidget(gb_stats);
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
        self.plot_r.plotItem.showAxis('right')
        self.epd_axis = self.plot_r.plotItem.getAxis('right')
        self.epd_axis.setLabel('EPD', units='nA')
        self.epd_axis.setPen(pg.mkPen('g'))
        self.epd_axis.show()
        self.epd_view = pg.ViewBox()
        self.plot_r.plotItem.scene().addItem(self.epd_view)
        self.epd_axis.linkToView(self.epd_view)
        self.epd_view.setXLink(self.plot_r)
        self.curve_epd = pg.PlotDataItem(pen=pg.mkPen('g', width=2))
        self.epd_view.addItem(self.curve_epd)
        self.plot_r.plotItem.vb.sigResized.connect(self.update_epd_view_geometry)
        self.update_epd_view_geometry()
        self.rate_region = pg.LinearRegionItem([0, 10], brush=pg.mkBrush(33, 150, 243, 40))
        self.rate_region.setZValue(10)
        self.rate_region.sigRegionChanged.connect(self.update_rate_region_stats)
        self.plot_r.addItem(self.rate_region)
        main_layout.addLayout(ctrl_panel, 1);
        main_layout.addWidget(self.plot_container, 4);
        self.setLayout(main_layout)
        self.on_source_changed(None)

    # ... (常规槽函数保持 V3.7 不变) ...
    def on_source_changed(self, btn):
        sid = self.group_source.checkedId()
        self.widget_file.setVisible(sid == 2);
        self.widget_net.setVisible(sid == 3)

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

    def select_epd_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Select EPD CSV", "", "CSV Files (*.csv);;All (*)")
        if fname:
            self.input_epd_path.setText(fname)
            self.load_epd_csv(fname)

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

    def on_auto_refresh_toggled(self, checked):
        if checked:
            self.last_plot_refresh_time = 0.0
            self.plot_timer.stop()
            self.auto_refresh_timer.start()
            self.btn_auto_refresh.setText("Live Refresh: ON (1s)")
            self.btn_auto_refresh.setStyleSheet("background: #1565C0; color: white; padding: 6px; font-weight: bold;")
            self.on_auto_refresh_tick(force=True)
        else:
            self.auto_refresh_timer.stop()
            if self.worker:
                self.plot_timer.start()
            self.btn_auto_refresh.setText("Live Refresh: OFF (1s)")
            self.btn_auto_refresh.setStyleSheet("")

    def on_auto_refresh_tick(self, force=False):
        if force or self.plot_dirty:
            self.refresh_plots()
            self.last_plot_refresh_time = time.monotonic()

    def get_crosshair_data(self, prefix):
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

    @staticmethod
    def value_at_x(x_data, y_data, x):
        if not x_data or not y_data:
            return x, None

        max_index = min(len(x_data), len(y_data)) - 1
        idx = bisect_left(x_data, x)
        if idx <= 0:
            return x_data[0], y_data[0]
        if idx > max_index:
            return x_data[max_index], y_data[max_index]

        x0 = x_data[idx - 1]
        x1 = x_data[idx]
        y0 = y_data[idx - 1]
        y1 = y_data[idx]
        if x1 == x0:
            return x1, y1

        ratio = (x - x0) / (x1 - x0)
        return x, y0 + ratio * (y1 - y0)

    @staticmethod
    def format_crosshair_value(value, suffix):
        if value is None:
            return "--"
        if not math.isfinite(value):
            return str(value)
        if suffix == "Hz":
            return f"{value:.9f}"
        if suffix == "nm":
            return f"{value:.9f}"
        if suffix == "Å/s":
            return f"{value:.9f}"
        return f"{value:.9g}"

    @staticmethod
    def is_plot_log_y(plot):
        try:
            return bool(plot.plotItem.ctrl.logYCheck.isChecked())
        except AttributeError:
            return False

    @staticmethod
    def data_y_to_view_y(value, is_log_y):
        if not is_log_y:
            return value
        if value is None or value <= 0:
            return None
        return math.log10(value)

    @staticmethod
    def view_y_to_data_y(value, is_log_y):
        if not is_log_y:
            return value
        return 10 ** value

    @staticmethod
    def format_duration(seconds):
        if seconds is None or seconds <= 0:
            return "0.000 s"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours >= 1:
            return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"
        if minutes >= 1:
            return f"{int(minutes):02d}:{secs:06.3f}"
        return f"{secs:.3f} s"

    def calculate_deposition_stats(self):
        if not self.time_data or not self.thick_data:
            return None

        elapsed_s = max(float(self.time_data[-1]), 0.0)
        thickness_nm = float(self.thick_data[-1])
        material = MATERIALS_DB.get(self.material_name, MATERIALS_DB["Default"])
        density_g_cm3 = float(material["density"])
        ref_area_cm2 = float(self.spin_ref_area.value())

        # thickness [nm] -> cm, density [g/cm^3] -> areal mass [ng/cm^2]
        mass_density_ng_cm2 = density_g_cm3 * thickness_nm * 100.0
        total_mass_ng = mass_density_ng_cm2 * ref_area_cm2

        if elapsed_s > 0:
            avg_rate_a_s = thickness_nm * 10.0 / elapsed_s
            avg_rate_ng_s = total_mass_ng / elapsed_s
        else:
            avg_rate_a_s = 0.0
            avg_rate_ng_s = 0.0

        return {
            "elapsed_s": elapsed_s,
            "mass_density_ng_cm2": mass_density_ng_cm2,
            "total_mass_ng": total_mass_ng,
            "avg_rate_a_s": avg_rate_a_s,
            "avg_rate_ng_s": avg_rate_ng_s,
        }

    def update_deposition_stats(self, *_):
        stats = self.calculate_deposition_stats()
        if stats is None:
            for lbl in [self.lbl_stat_time, self.lbl_stat_mass_density, self.lbl_stat_total_mass,
                        self.lbl_stat_avg_rate_a, self.lbl_stat_avg_rate_ng,
                        self.lbl_rate_region_mean, self.lbl_rate_region_std, self.lbl_epd_decay]:
                lbl.setText("--")
            return

        self.lbl_stat_time.setText(self.format_duration(stats["elapsed_s"]))
        self.lbl_stat_mass_density.setText(f"{stats['mass_density_ng_cm2']:.6g} ng/cm²")
        self.lbl_stat_total_mass.setText(f"{stats['total_mass_ng']:.6g} ng")
        self.lbl_stat_avg_rate_a.setText(f"{stats['avg_rate_a_s']:.6g} Å/s")
        self.lbl_stat_avg_rate_ng.setText(f"{stats['avg_rate_ng_s']:.6g} ng/s")
        self.update_rate_region_stats()

    def ensure_rate_region_visible(self, x_data):
        if not hasattr(self, 'rate_region') or not x_data or self.rate_region_initialized:
            return
        x0 = x_data[0]
        x1 = x_data[min(len(x_data) - 1, max(1, min(100, len(x_data) - 1)))]
        if x1 <= x0:
            x1 = x0 + 1.0
        self.rate_region.setRegion([x0, x1])
        self.rate_region_initialized = True

    def update_epd_view_geometry(self):
        if hasattr(self, 'epd_view'):
            self.epd_view.setGeometry(self.plot_r.plotItem.vb.sceneBoundingRect())
            self.epd_view.linkedViewChanged(self.plot_r.plotItem.vb, self.epd_view.XAxis)

    @staticmethod
    def parse_epd_time(value):
        text = str(value).strip()
        try:
            numeric = float(text)
            return numeric, numeric > 1_000_000_000
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(text, fmt).timestamp(), True
            except ValueError:
                continue
        parsed = pd.to_datetime(text, errors='raise')
        return parsed.timestamp(), True

    def load_epd_csv(self, path):
        times = []
        currents = []
        time_is_absolute = False
        try:
            with open(path, 'r', encoding='utf-8-sig', errors='ignore', newline='') as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) < 2:
                        continue
                    try:
                        t, is_abs = self.parse_epd_time(row[0])
                        current = float(str(row[1]).strip())
                    except Exception:
                        continue
                    times.append(t)
                    currents.append(current)
                    time_is_absolute = time_is_absolute or is_abs
            if not times:
                raise ValueError("No valid rows found. Expected CSV columns: time,current_nA")
            combined = sorted(zip(times, currents), key=lambda item: item[0])
            self.epd_time_data = [item[0] for item in combined]
            self.epd_current_data = [item[1] for item in combined]
            self.epd_time_is_absolute = time_is_absolute
            self.refresh_plots()
            self.lbl_status.setText(f"EPD Loaded: {len(self.epd_time_data)} pts")
        except Exception as e:
            QMessageBox.warning(self, "EPD Error", f"无法读取 EPD CSV 文件: {e}")

    def get_epd_plot_data(self):
        if not self.epd_time_data:
            return [], []
        if self.chk_abs_time.isChecked():
            if self.epd_time_is_absolute:
                return self.epd_time_data, self.epd_current_data
            if self.start_ts is not None:
                return [self.start_ts + t for t in self.epd_time_data], self.epd_current_data
            return self.epd_time_data, self.epd_current_data
        if self.epd_time_is_absolute:
            base = self.start_ts if self.start_ts is not None else self.epd_time_data[0]
            return [t - base for t in self.epd_time_data], self.epd_current_data
        return self.epd_time_data, self.epd_current_data

    def update_epd_plot(self):
        if not hasattr(self, 'curve_epd'):
            return
        x_epd, y_epd = self.get_epd_plot_data()
        self.curve_epd.setData(x_epd, y_epd)
        self.update_epd_view_geometry()

    def update_rate_region_stats(self):
        if not hasattr(self, 'rate_region') or not self.time_data or not self.rate_data:
            if hasattr(self, 'lbl_rate_region_mean'):
                self.lbl_rate_region_mean.setText("--")
                self.lbl_rate_region_std.setText("--")
                self.lbl_epd_decay.setText("--")
            return
        start, end = self.rate_region.getRegion()
        if start > end:
            start, end = end, start
        x_data = list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data)
        rates = [r for x, r in zip(x_data, self.rate_data) if start <= x <= end and math.isfinite(r)]
        if not rates:
            self.lbl_rate_region_mean.setText("--")
            self.lbl_rate_region_std.setText("--")
            self.update_epd_decay_stats(start, end)
            return
        mean = sum(rates) / len(rates)
        if len(rates) > 1:
            variance = sum((r - mean) ** 2 for r in rates) / (len(rates) - 1)
            std = math.sqrt(variance)
        else:
            std = 0.0
        self.lbl_rate_region_mean.setText(f"{mean:.6g} Å/s (n={len(rates)})")
        self.lbl_rate_region_std.setText(f"{std:.6g} Å/s")
        self.update_epd_decay_stats(start, end)

    def update_epd_decay_stats(self, start, end):
        x_epd, y_epd = self.get_epd_plot_data()
        selected = [(x, y) for x, y in zip(x_epd, y_epd) if start <= x <= end and math.isfinite(y)]
        if len(selected) < 2:
            self.lbl_epd_decay.setText("--")
            return
        first_x, first_y = selected[0]
        last_x, last_y = selected[-1]
        hours = (last_x - first_x) / 3600.0
        if hours <= 0 or first_y == 0:
            self.lbl_epd_decay.setText("--")
            return
        decay_pct_h = (first_y - last_y) / abs(first_y) / hours * 100.0
        self.lbl_epd_decay.setText(f"{decay_pct_h:.6g} %/h (n={len(selected)})")

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
        self.rate_region_initialized = False
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
                mouse_point = plot.plotItem.vb.mapSceneToView(pos)
                mouse_x = mouse_point.x()
                x_data, y_data, display_prefix = self.get_crosshair_data(prefix)
                is_log_y = self.is_plot_log_y(plot)
                x, data_y = self.value_at_x(x_data, y_data, mouse_x)
                if data_y is None:
                    data_y = self.view_y_to_data_y(mouse_point.y(), is_log_y)
                view_y = self.data_y_to_view_y(data_y, is_log_y)
                if view_y is None:
                    view_y = mouse_point.y()

                v_line.setPos(x)
                h_line.setPos(view_y)
                if self.chk_abs_time.isChecked():
                    try:
                        t_str = datetime.fromtimestamp(x).strftime("%H:%M:%S.%f")[:-3]
                    except:
                        t_str = "Inv"
                else:
                    t_str = f"{x:.6f}s"
                value_str = self.format_crosshair_value(data_y, suffix)
                label.setText(f"Time: {t_str}\n{display_prefix}: {value_str} {suffix}")
                label.setPos(x, view_y)
                v_line.show()
                h_line.show()
                label.show()

        proxy = pg.SignalProxy(plot.scene().sigMouseMoved, rateLimit=60, slot=mouse_moved)
        setattr(plot, 'crosshair_proxy', proxy)

    def init_csv_log(self, custom_csv_path=""):
        self.close_csv_log()
        if custom_csv_path and custom_csv_path.strip():
            filename = custom_csv_path
        else:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"QCM_Log_{ts_str}.csv"
        dirname = os.path.dirname(os.path.abspath(filename))
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname)
        self.csv_file = open(filename, mode='w', newline='', encoding='utf-8')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow([
            "Timestamp_Unix", "Local_Time", "Elapsed_s", "Frequency_Raw_Hz",
            "Frequency_Shift_Hz", "Thickness_nm", "Rate_A_s", "Material",
            "Tooling_percent", "Ref_Area_cm2", "Mass_Density_QCM_ng_cm2",
            "Total_Mass_Ref_ng", "Average_Rate_A_s", "Average_Rate_ng_s"
        ])
        self.on_log_path_received(os.path.abspath(filename))

    def close_csv_log(self):
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

    def write_csv_row(self, now_ts, t_rel, raw_f, delta_f, thick, rate):
        if not self.csv_writer:
            return
        stats = self.calculate_deposition_stats()
        dt_str = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S.%f")
        row = [
            f"{now_ts:.6f}", dt_str, f"{t_rel:.6f}", f"{raw_f:.9f}",
            f"{delta_f:.9f}", f"{thick:.9f}", f"{rate:.9f}", self.material_name,
            f"{self.spin_tooling.value():.6f}", f"{self.spin_ref_area.value():.6f}",
            f"{stats['mass_density_ng_cm2']:.9f}" if stats else "",
            f"{stats['total_mass_ng']:.9f}" if stats else "",
            f"{stats['avg_rate_a_s']:.9f}" if stats else "",
            f"{stats['avg_rate_ng_s']:.9f}" if stats else "",
        ]
        self.csv_writer.writerow(row)

    def start_experiment(self):
        src_id = self.group_source.checkedId()
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
            self.plot_dirty = False
            self.last_plot_refresh_time = 0.0
            self.rate_region_initialized = False
            self.update_deposition_stats()

            speed = self.spin_speed.value();
            save_csv = self.chk_record.isChecked();
            custom_path = self.input_csv_path.text()
            if save_csv:
                self.init_csv_log(custom_path)
            else:
                self.close_csv_log()
            self.worker = QCMWorker(self.ds, is_file_replay=(src_id == 2), speed=speed, save_csv=False,
                                    custom_csv_path="")
            self.worker.chunk_signal.connect(self.process_chunk);
            self.worker.finished_signal.connect(self.on_replay_finished)
            self.worker.error_signal.connect(self.on_worker_error);
            self.worker.log_path_signal.connect(self.on_log_path_received)
            self.worker.start();
            if self.btn_auto_refresh.isChecked():
                self.auto_refresh_timer.start()
            else:
                self.plot_timer.start()
            if src_id == 2 and not self.btn_auto_refresh.isChecked():
                self.btn_auto_refresh.setChecked(True)
            self.btn_start.setEnabled(False);
            self.btn_stop.setEnabled(True);
            self.lbl_status.setText("RUNNING");
            self.lbl_status.setStyleSheet("background: #C8E6C9;")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e)); self.stop_experiment()

    def stop_experiment(self):
        self.plot_timer.stop()
        self.auto_refresh_timer.stop()
        if self.worker: self.worker.stop(); self.worker = None
        if self.ds: self.ds.disconnect()
        self.close_csv_log()
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
        self.plot_dirty = False
        x_data = list(self.abs_time_data) if self.chk_abs_time.isChecked() else list(self.time_data)
        self.ensure_rate_region_visible(x_data)
        if self.chk_raw_freq.isChecked():
            self.curve_f.setData(x_data, list(self.raw_freq_data))
            if self.raw_freq_data: self.plot_f.enableAutoRange(axis='y')
        else:
            self.curve_f.setData(x_data, list(self.freq_data))
            if self.freq_data: self.plot_f.enableAutoRange(axis='y')
        self.curve_t.setData(x_data, list(self.thick_data))
        self.curve_r.setData(x_data, list(self.rate_data))
        self.update_epd_plot()
        self.update_deposition_stats()

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

            # 使用 V3.6 的平滑逻辑，只取最近窗口，避免大文件回放时每个点复制全量数据。
            raw_rate = qcm_calc.calc_rate(list(self.time_data)[-60:], list(self.thick_data)[-60:], window=60)
            alpha = 0.2
            if len(self.rate_data) == 0:
                smooth_rate = raw_rate
            else:
                smooth_rate = alpha * raw_rate + (1 - alpha) * self.last_smooth_rate
            self.last_smooth_rate = smooth_rate
            self.rate_data.append(smooth_rate)
            self.write_csv_row(now_ts, t_rel, raw_f, delta_f, thick, smooth_rate)

        if self.csv_file:
            self.csv_file.flush()

        self.plot_dirty = True
        if self.btn_auto_refresh.isChecked():
            current_time = time.monotonic()
            if current_time - self.last_plot_refresh_time >= 1.0:
                self.refresh_plots()
                self.last_plot_refresh_time = current_time
                QApplication.processEvents()
        else:
            self.refresh_plots()

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
