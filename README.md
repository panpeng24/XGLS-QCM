XGLS-QCM
轻量化的石英晶体微天平（QCM，Quartz Crystal Microbalance）数据处理工具，基于 Python 实现 QCM 频率数据到厚度的转换、沉积速率计算、稳态判断等核心功能，适配 Inficon 6MHz AT-cut 晶振，内置常用镀膜材料数据库，支持 Tooling Factor 校准，满足实验室级 QCM 数据分析需求。
核心功能
频率 - 厚度转换：基于 Sauerbrey 方程，将 QCM 频率偏移量转换为镀膜厚度（nm），支持 Tooling Factor 校准修正；
沉积速率计算：通过线性拟合实时计算镀膜速率（Å/s）；
稳态判断：基于频率波动斜率判定镀膜过程是否处于稳态；
材料数据库：内置 InSn 合金、Au/Ag/Cu 金属、碳（C）等常用镀膜材料的密度参数，支持自定义扩展。
快速开始
环境依赖
bash
运行
pip install numpy
基础使用示例
python
运行
from data_source import QCMCalculator

# 1. 初始化计算器（Tooling Factor 150.2% 对应实际厚度是监测值的1.502倍）
qcm_calc = QCMCalculator(tooling_factor=1.502)

# 2. 频率偏移转厚度（InSn 合金，频率下降1000Hz）
delta_freq = -1000  # 频率下降为负，上升为正
thickness_insn = qcm_calc.freq_to_thickness(delta_freq, "InSn")
print(f"InSn 镀膜厚度: {thickness_insn:.2f} nm")

# 3. 切换材料（碳膜）并重置 Tooling Factor 为 100%
qcm_calc.set_tooling(100.0)
thickness_c = qcm_calc.freq_to_thickness(delta_freq, "C")
print(f"碳膜厚度: {thickness_c:.2f} nm")

# 4. 计算沉积速率（模拟时间和厚度数据）
time_arr = [0, 1, 2, 3, 4, 5]  # 单位：秒
thickness_arr = [0, 0.5, 1.0, 1.5, 2.0, 2.5]  # 单位：nm
rate = qcm_calc.calc_rate(time_arr, thickness_arr)
print(f"沉积速率: {rate:.2f} Å/s")

# 5. 稳态判断（模拟频率和时间数据）
freq_arr = [6000000, 6000001, 6000000.5, 5999999.8] * 5  # 模拟稳定的频率序列
steady = qcm_calc.is_steady_state(freq_arr, time_arr, threshold_hz_min=1.0)
print(f"系统是否稳态: {steady}")
核心类说明
QCMCalculator
QCM 数据计算的核心类，封装所有算法逻辑，初始化参数如下：
表格
参数名	类型	默认值	说明
c_factor	float	SAUERBREY_C_6MHZ (12.3e-9)	晶振常数，默认适配 6MHz AT-cut 晶振（Sauerbrey 常数～12.3 ng/(Hz・cm²)）
tooling_factor	float	1.0	工具因子（实际厚度 / 监测厚度），1.0 代表 100%，用于校准实际镀膜厚度
主要方法
表格
方法名	入参说明	返回值	功能说明
set_tooling	factor_percent: float（百分比值，如 150.2 代表 150.2%）	None	动态修改 Tooling Factor
freq_to_thickness	delta_f: float（频率偏移量）
material_name: str（材料名称，如 "InSn"）	float（nm）	将频率偏移量转换为镀膜厚度，自动匹配材料密度并应用 Tooling Factor 校准
calc_rate	time_arr: List/np.ndarray（时间序列，秒）
thickness_arr: List/np.ndarray（厚度序列，nm）	float（Å/s）	基于最后 10 个数据点线性拟合，计算瞬时沉积速率（转换为 Å/s 单位）
is_steady_state	freq_arr: List（频率序列）
time_arr: List（时间序列）
threshold_hz_min: float（稳态阈值，Hz/min）
window_size: int（滑动窗口大小，默认 20）	bool	计算频率序列的斜率（Hz/min），判断是否小于阈值，返回是否稳态
材料数据库扩展
内置材料包含 InSn（铟锡合金）、Sn/In/Au/Ag/Cu（常用金属）、C（碳），可通过修改 MATERIALS_DB 字典扩展自定义材料：
python
运行
# 示例：新增铝（Al）材料
MATERIALS_DB["Al"] = {"density": 2.70, "name": "Aluminum"}

# 使用新增材料计算厚度
thickness_al = qcm_calc.freq_to_thickness(-1000, "Al")
常量说明
表格
常量名	值	说明
SAUERBREY_C_6MHZ	12.3e-9	6MHz AT-cut 晶振的 Sauerbrey 常数
MATERIALS_DB	dict	材料密度数据库，key 为材料简称，value 包含密度（density）和名称（name）
注意事项
频率偏移量（delta_f）：QCM 中质量增加导致频率下降，因此 delta_f 通常为负数，计算时公式会自动抵消负号；
Tooling Factor 校准：需根据实际镀膜工艺校准（实际厚度 / 监测厚度），是提升厚度计算精度的关键；
碳膜密度：蒸发碳膜密度通常在 1.8-2.25 g/cm³ 之间，默认取石墨标准值 2.25，可根据实验需求调整；
稳态判断阈值：需根据具体工艺场景调整（如高精度镀膜可设为 0.5 Hz/min，粗镀膜可设为 2.0 Hz/min）。

## Troubleshooting: `SyntaxError` on a line starting with `@@` or a hash

If Python reports an error like either of these:

```text
SyntaxError: invalid syntax
@@ -99,117 +100,120 @@ class QCMWorker(QThread):
```

```text
SyntaxError: invalid syntax
dc9ceaaf753ae1809d0f715fae5b.
```

then a unified-diff patch hunk, PR text, or commit/hash fragment was copied into
`main.py` as plain text. Lines that start with `@@`, `diff --git`, `<<<<<<<`,
`=======`, `>>>>>>>`, or a standalone hash are not Python code and must not appear
in the source file.

To check the repository copy before running the GUI:

```bash
python tools/check_source_integrity.py
python -m py_compile main.py
```

If the check reports an artifact, remove that line or replace the affected file
with the clean version from this repository. Apply changes with `git apply` or
`git pull` instead of copy-pasting PR/diff text or commit hashes into `main.py`.

## Real-time Grafana dashboard export

The GUI can stream calculated QCM data to Grafana through an InfluxDB v2 data
source. Start InfluxDB, create a bucket (for example `qcm`) and an API token,
then add that InfluxDB instance as a Grafana data source.

In the QCM GUI:

1. Enable **Upload to Grafana (InfluxDB)**.
2. Fill in the InfluxDB URL, Org, Bucket, and API Token.
3. Start acquisition or file replay.

The GUI includes dashboard presets for multiple tools:

```text
LRP P2: http://10.29.112.200:3000/grafana/d/a0164f95-1a6d-4a78-958f-bf5e437e7a57/lrp-p2?orgId=1
LDP P1: http://10.29.207.25:3000/grafana/d/a0458676-b495-4a67-9b3f-b29f081cf41c/ldp-p1?orgId=1&from=now-6h&to=now
```

Note that these Grafana URLs open dashboards only; real-time data must still be
written to the InfluxDB data source configured behind each dashboard.

The app writes measurement `QCM` with tags `material` and `platform`, and fields:

- `FrequencyRaw_Hz`
- `FrequencyShift_Hz`
- `Thickness_nm`
- `Rate_A_per_s`

Example Flux query in Grafana:

```flux
from(bucket: "qcm")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "qcm")
  |> filter(fn: (r) => r._field == "Thickness_nm" or r._field == "Rate_A_per_s")
```

## File replay formats: IC6 and SQC-310

The File Replay input supports both legacy IC6 datalogs and SQC-310 CSV datalogs.
Use **Replay Format** in the GUI to choose `Auto`, `IC6`, or `SQC-310`:

- `Auto` inspects the file header and detects SQC-310 logs from `Start:`, `Sens1Freq`, or SQC markers; otherwise it falls back to IC6 parsing.
- `IC6` reads the 8 frequency channels and 8 crystal activity values. The default selector is `CH6` to preserve the previous behavior.
- `SQC-310` reads the start date/time line, uses the first CSV column as elapsed seconds, and reads `SensNRate`, `SensNThk`, and `SensNFreq` data from the sensor section. The selected sensor frequency is used as the raw QCM frequency for the existing thickness/rate pipeline.

Saved QCM CSV output includes `Source_Format`, `QCM_Channel`, SQC `Phase`, all IC6 channel columns, and SQC sensor rate/thickness/frequency columns so replay exports can be reused for future multi-channel analysis.

### v4.5 replay improvements

Version v4.5 improves replay compatibility in two areas:

- **SQC-310**: the parser reads the `Start:` date/time line, uses the first CSV column as elapsed seconds, finds the `Sensors:` section in each data row, and takes each sensor group as `Rate, Thk, Freq`. If the selected SQC sensor has a zero/empty frequency, the parser falls back to the first valid non-zero sensor frequency so rows like `Sens1Freq=5964243.070` are still decoded and sent into the normal QCM thickness/rate calculations.
- **IC6**: `CH1` through `CH8` can be checked independently or together. The selected primary channel is still used for the main statistics/export path, while all checked IC6 channels are calculated and plotted on the same synchronized time axis for frequency, thickness, and rate comparison.

### Stability and layout notes

The GUI limits plotted points to the newest 20,000 samples per curve while keeping the full in-memory/logging history, and rate calculations now use fixed 60-point windows instead of repeatedly slicing full replay histories. This reduces UI pressure during large file replay. Grafana/InfluxDB settings are opened from **Grafana Settings...** in a secondary dialog so the main control panel remains compact. IC6 channel checkboxes are arranged in a compact two-row grid.

### IC6 channel visibility

In File Replay, IC6 `CH1`-`CH8` checkboxes now directly control whether each channel curve is displayed. All eight IC6 channels are calculated from the replay rows, and each visible channel uses a distinct pyqtgraph color on the synchronized frequency, thickness, and rate plots. Unchecking a channel hides its curves without stopping replay.

### v4.5.1 replay and EPD UI fixes

EPD CSV loading now refreshes the EPD curve even before QCM data is present and auto-ranges the EPD right-axis view. File replay can auto-start after selecting a log file when **Auto-start replay after file select** is enabled. Large replay plots are reduced by even sampling across the full document range, so the visible plot represents the whole file instead of only the latest tail. Data Connection controls are opened from **Data Connection...** in a secondary dialog to keep the main panel compact.

## LRP InfluxDB / Grafana upload

The Grafana upload panel supports the LRP InfluxDB 1.x write endpoint. Use **Grafana Settings...** and keep **Influx API** set to `InfluxDB 1.x (LRP)`. The default fields are prefilled for the LRP server:

```text
Influx URL: http://10.29.112.200:8087
User: dg130
Database: dg130
Password: huawei
```

When **Upload to Grafana (InfluxDB)** is enabled and acquisition/replay starts, each calculated QCM row is written to `/write?db=dg130&u=dg130&p=huawei` as line protocol measurement `QCM`. Fields include `FrequencyRaw_Hz`, `FrequencyShift_Hz`, `Thickness_nm`, and `Rate_A_per_s`; tags include `material`, `platform`, `qcm_source`, and `qcm_channel`. Grafana should query the same `dg130` database and `QCM` measurement.

### InfluxDB line-protocol data contract

LRP upload uses one line-protocol point per QCM timestamp. The measurement name is configurable (default `QCM`; examples include `LiquidTin`, `QCM`, and `EPD`). Field names include English units and avoid special unit characters: `FrequencyRaw_Hz`, `FrequencyShift_Hz`, `Thickness_nm`, and `Rate_A_per_s`. Values are converted to `float`, and timestamps are Unix nanoseconds. Use the DB preset selector before starting upload: `P1 (LRP-P1-Sensors)` writes to `LRP-P1-Sensors`, `P2 (LRP-P2-Sensors)` writes to `LRP-P2-Sensors`, `Alpha1 (LRP-Alpha1)` writes to `LRP-Alpha1`, and `Test (dg130)` writes to `dg130`. The uploader clears its local queue at start, buffers points in memory, and writes batches of up to 100 lines per request.
