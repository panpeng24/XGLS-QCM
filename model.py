import numpy as np
from typing import List, Union

# --- 硬件常量 (Inficon 6MHz) ---
# Sauerbrey Constant: ~12.3 ng/(Hz*cm^2) for 6MHz AT-cut
SAUERBREY_C_6MHZ = 12.3e-9

# --- 材料数据库 ---
MATERIALS_DB = {
    # 合金 In(36%)/Sn(64%)
    # 密度估算: 0.36*7.31 + 0.64*7.30 ≈ 7.30
    "InSn": {"density": 7.30, "name": "Indium Tin Alloy"},
    # 常用金属
    "Sn": {"density": 7.30, "name": "Tin"},
    "In": {"density": 7.31, "name": "Indium"},
    "Au": {"density": 19.32, "name": "Gold"},
    "Ag": {"density": 10.49, "name": "Silver"},
    "Cu": {"density": 8.96, "name": "Copper"},

    # --- 新增材料 ---
    # 碳 (注意：蒸发碳膜密度通常在 1.8-2.25 之间，此处取石墨标准 2.25)
    "C": {"density": 2.25, "name": "Carbon"},

    "Default": {"density": 1.0, "name": "Unknown"}
}


class QCMCalculator:
    def __init__(self, c_factor: float = SAUERBREY_C_6MHZ, tooling_factor: float = 1.0):
        """
        初始化计算器
        :param c_factor: 晶振常数
        :param tooling_factor: 工具因子 (1.0 = 100%).
                               如果实际厚度是监测值的 1.5 倍，此处应设为 1.5
        """
        self.c_factor = c_factor
        self.tooling_factor = tooling_factor

    def set_tooling(self, factor_percent: float):
        """
        动态修改 Tooling Factor
        :param factor_percent: 百分比值 (例如输入 150.2 代表 150.2%)
        """
        self.tooling_factor = factor_percent / 100.0

    def freq_to_thickness(self, delta_f: float, material_name: str) -> float:
        """
        Sauerbrey equation: Frequency shift -> Thickness (nm)
        包含 Tooling Factor 修正
        """
        mat = MATERIALS_DB.get(material_name, MATERIALS_DB["Default"])
        rho = mat["density"]

        # 1. 物理计算 (Sauerbrey)
        # 质量增加导致频率下降 (delta_f < 0)，公式带负号抵消
        delta_m_area = -self.c_factor * delta_f
        raw_thickness_cm = delta_m_area / rho

        # 2. 应用 Tooling Factor 校准
        # Tooling = Actual / Monitor
        calibrated_thickness_cm = raw_thickness_cm * self.tooling_factor

        return calibrated_thickness_cm * 1e7  # cm -> nm

    def calc_rate(self, time_arr: Union[List, np.ndarray], thickness_arr: Union[List, np.ndarray]) -> float:
        """
        基于线性拟合计算沉积速率 (nm/min)
        """
        window = 10  # 使用最后10个点计算瞬时速率
        if len(time_arr) < 2:
            return 0.0

        # 转换为 numpy 数组并切片
        t = np.array(time_arr[-window:])
        d = np.array(thickness_arr[-window:])

        try:
            # 拟合 y = kx + b
            coeff = np.polyfit(t, d, 1)
            k = coeff[0]  # nm/s
            return k * 10.0  # Å/s
        except:
            return 0.0

    def is_steady_state(self, freq_arr: List[float], time_arr: List[float], threshold_hz_min: float,
                        window_size: int = 20) -> bool:
        """
        判断系统是否稳定
        """
        if len(freq_arr) < window_size:
            return False

        t_win = np.array(time_arr[-window_size:])
        f_win = np.array(freq_arr[-window_size:])

        try:
            coeff = np.polyfit(t_win, f_win, 1)
            slope_hz_min = abs(coeff[0]) * 60.0
            return slope_hz_min < threshold_hz_min
        except:
            return False


# --- 使用示例 ---

# 1. 实例化 (应用你刚才计算出的 150.2% 校准值)
# 实际值 311 / 监测值 207 = 1.502
qcm_calc = QCMCalculator(tooling_factor=1.502)

# 2. 模拟测试 InSn 合金
# 假设频率变化了 -1000 Hz
delta_freq = -1000
thickness = qcm_calc.freq_to_thickness(delta_freq, "InSn")

print(f"当前 Tooling Factor: {qcm_calc.tooling_factor * 100:.1f}%")
print(f"InSn 频率下降 1000Hz 对应的厚度: {thickness:.2f} nm")

# 3. 模拟测试 Carbon (碳)
# 如果换成镀碳，通常需要重新校准 tooling，这里假设先重置为 100%
qcm_calc.set_tooling(100.0)
c_thickness = qcm_calc.freq_to_thickness(-1000, "C")
print(f"---")
print(f"切换为 Carbon (Tooling 100%)")
print(f"Carbon 频率下降 1000Hz 对应的厚度: {c_thickness:.2f} nm")
