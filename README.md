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

## Faraday Cup / TOF 能谱分析 App

仓库现在包含一个独立的法拉第杯飞行时间（TOF）能谱分析工具，用于优化并封装原始示波器脚本：

```bash
python faraday_cup_app.py
```

### 支持能力

- **不同检测光源平台**：内置 `Custom`、`LaserBench-0.6m`、`Compact-0.52m`、`LongTOF-1.0m` 等平台预设；选择平台后会自动带出默认 Fcup 距离，也可以手动覆盖。
- **不同离子种类**：内置 Xe、Sn、In、Ar、He、C、Cu 等常见离子质量与默认一价态；界面中可手动修改质量数和价态，方便扩展到其它离子或多价离子。
- **手动设置 Fcup 距离**：界面提供 `Fcup 距离` 输入框，所有飞行时间到能量的换算都会使用该距离。
- **可配置信号处理**：支持噪声窗口、采样间隔、每周期点数、光电峰搜索范围、波形单位、信号极性、负载电阻、能量积分范围和插值方式。
- **Grafana 上传**：Grafana 通常读取 InfluxDB、Prometheus 等数据源。本工具支持将每周期摘要以 InfluxDB line protocol 写入 InfluxDB v2 写入接口，然后在 Grafana 中配置对应 bucket 作为 dashboard 数据源。

### 处理流程

1. 读取示波器导出的 CSV 第一列波形；
2. 使用前置噪声窗口做基线扣除；
3. 根据极性配置保留正信号、负信号、绝对值或原始信号；
4. 按每周期点数切片；
5. 在每个周期的光电峰窗口中寻找时间零点；
6. 由 `E = 0.5 * m * (L / t)^2 / (z * e)` 换算离子能量；
7. 由法拉第杯电流和 TOF 雅可比估算 `dN/dE`；
8. 对指定能量范围插值，并用梯形积分计算每周期动能；
9. 导出 Excel 的 `energy_spectrum` 和 `cycle_summary` 两个 sheet；
10. 可选上传周期摘要到 InfluxDB/Grafana 数据源。

### Grafana / InfluxDB 配置提示

在 App 的 “Grafana / InfluxDB 上传” 区域填写：

- `URL`：InfluxDB 根地址，例如 `http://localhost:8086`；也可以填写完整 `/api/v2/write` URL。
- `Org`：InfluxDB v2 organization。
- `Bucket`：写入 bucket。
- `Token`：具有写入权限的 InfluxDB token。
- `Measurement`：默认 `faraday_cup_cycle`。

上传的字段包括 `distance_m`、`peak_index`、`peak_time_s`、`peak_voltage`、`kinetic_energy_mJ`，标签包括 `ion`、`platform`、`cycle`。
