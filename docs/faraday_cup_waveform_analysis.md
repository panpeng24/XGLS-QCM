# 法拉第杯波形能谱脚本理解笔记

这份脚本用于处理示波器导出的单列 `.Wfm.csv` 波形数据，将法拉第杯电压信号换算为离子电流、飞行时间能量谱，并按多个激光/放电脉冲周期统计沉积动能。整体流程是：读入电压波形、做噪声基线扣除、按固定周期切片、用光电峰确定每个周期的时间零点、通过飞行时间公式换算能量，再对指定能量范围积分得到每个周期的能量。

## 1. 输入和基础假设

脚本默认输入是示波器导出的 CSV 文件，并假设第一列是电压值，第一行是表头：

```python
csv_file_path = 'D:\\离子实验\\0728Fcup气流场实验\\RefCurve_2025-07-28_0_173534.Wfm.csv'
```

关键实验参数如下：

| 参数 | 含义 | 当前值 |
| --- | --- | --- |
| `Noise_index` | 用于估计基线噪声均值的前置采样点数 | `100000` |
| `L` | 飞行距离，即光圈口到 PF 点距离 | `0.6 m` |
| `points_per_cycle` | 每个周期包含的数据点数 | `500000` |
| `Photoelectric_range_start/end` | 每个周期内寻找光电峰的范围 | `245000` 到 `249000` |
| `estart` / `estop` | 积分统计沉积能量的能量范围 | `300 eV` 到 `20000 eV` |
| `sampling_rate` | 代码中用于生成时间轴的换算因子 | `1e3`，对应横轴单位为 `us` |

注意：脚本中 `Noise_index2`、`startindex_incycle`、`endindex_incycle`、`aaa`、`bbb` 当前没有参与有效计算，属于历史遗留或待扩展参数。

## 2. 数据预处理逻辑

### 2.1 读取电压并扣除基线

脚本读取所有 CSV 行的第一列，转换成浮点电压数组。随后用前 `Noise_index` 个点的平均值作为基线，并从每个采样点中扣除该均值：

```python
mean_voltage = np.mean(voltage[:Noise_index])
voltage = [v - mean_voltage for v in voltage]
```

这一步的目的是把示波器的直流偏置或噪声零点移动到 0 V 附近。

### 2.2 电压换算为电流并画原始波形

代码使用 50 Ω 负载电阻把电压换算为电流：

```python
It = [v / 50 /1000 *1000 for v in voltage]  # mA
```

这个表达式可以化简为 `v / 50`，数值单位标注为 mA 时需要谨慎。若 `v` 单位为 V，则物理上 `I(A)=V/50`，`I(mA)=V/50*1000`。当前代码里的 `/1000*1000` 相互抵消，最终并未转换到 mA。

### 2.3 负值截断为 0

```python
voltage_zero = [max(v, 0) for v in voltage]
```

这一步把扣基线后的负电压全部置零，保留正信号。它能减少负噪声对积分的影响，但也会改变噪声统计性质；如果信号存在真实负极性部分，需要根据实验接线确认是否应该取正值、取负值或取绝对值。

## 3. 按周期提取波形

脚本固定处理前 10 个周期：

```python
for cycle in range(10):
    start_idx = int(cycle * points_per_cycle)
    end_idx = start_idx + points_per_cycle
    cycle_voltage = voltage_zero[start_idx:end_idx]
```

每个周期取 `500000` 个点。若实际 CSV 长度不足 `10 * 500000`，后续周期会拿到不完整数据，可能导致插值或峰值寻找出错。

## 4. 时间零点：用光电峰定位

每个周期中，脚本在 `245000:249000` 范围内寻找最大值，认为该峰是光电信号峰，并将峰位置作为飞行时间起点：

```python
peak_index = np.argmax(cycle_voltage[Photoelectric_range_start:Photoelectric_range_end])
sub_voltage_after_peak = cycle_voltage[(peak_index+Photoelectric_range_start):]
sub_time_after_peak = np.arange(1, len(sub_voltage_after_peak)+1) / 1e9  # s
```

这里 `np.argmax` 返回的是局部窗口内的索引，所以需要加上 `Photoelectric_range_start` 才能回到当前周期的全局索引。`sub_time_after_peak` 从峰后第 1 个采样点开始，时间单位按 1 ns 采样间隔换算为秒。

## 5. 飞行时间换算能量

脚本使用经典动能公式：

```python
energy_ev = [0.5*131.3*1.67*10**(-27)*(L/t)**2/1.6*10**19 for t in sub_time_after_peak]
```

它等价于：

\[
E_{eV} = \frac{1}{2} m \left(\frac{L}{t}\right)^2 \div q_e
\]

其中：

- `m = 131.3 * 1.67e-27 kg`，近似为 Xe 离子质量；
- `L = 0.6 m`；
- `t` 是从光电峰后开始计算的飞行时间；
- `q_e = 1.6e-19 C`。

因为时间 `t` 越大，能量越低，所以 `energy_ev` 是单调递减序列。

## 6. 电流换算为能谱分布

峰后电压再次按 50 Ω 换算为电流：

```python
It = [sv / 50 / 1000 for sv in sub_voltage_after_peak]  # A
```

如果 `sv` 是 V，通常 `I(A)=sv/50`。这里额外除以 `1000` 会让电流缩小 1000 倍，可能是脚本作者假设原始电压单位为 mV。这个单位假设必须和示波器 CSV 导出格式核对。

随后计算：

```python
dNE = ((It * np.array(sub_time_after_peak) ** 3) / (Mxe * Qc * L ** 2)) * Qc
```

该式试图由法拉第杯电流和飞行时间变换雅可比得到 `dN/dE` 类型的离子数能谱。末尾先除以 `Qc` 又乘以 `Qc`，会相互抵消；如果目标是从电流换算为离子数，通常需要认真检查电荷量因子是否应保留、离子价态是否为 1，以及探测器立体角/收集面积是否已考虑。

## 7. 插值和积分

脚本用 `300 eV` 到 `20000 eV` 的整数能量网格保存每个周期的能谱：

```python
energysave_range = np.linspace(estop, estart, estop - estart + 1)
interfunction = interpolate.interp1d(energy_ev, dNE, kind='cubic')
energysave_dNE = interfunction(energysave_range)
```

由于 `energy_ev` 本身是从高到低递减，`energysave_range` 也从 `estop` 递减到 `estart`，两者方向一致。插值时需要确保 `energysave_range` 没有超出 `energy_ev` 覆盖范围，否则 `interp1d` 默认会报错。

每个周期的沉积动能近似为：

```python
result_sum = np.sum(energysave_range * energysave_dNE) * 1.60 * 10 ** -19
result_sum_mJ = result_sum * 1000
```

这相当于对 `E * dN/dE` 做离散求和，并把 eV 转换成 J，再转换成 mJ。代码注释里也写了“需要更改积分算法”，因为当前方法没有显式乘以能量步长 `dE`；虽然当前网格步长是 1 eV，数值上影响不明显，但更严谨的写法应使用 `np.trapz` 或 `scipy.integrate`。

## 8. 输出结果

脚本输出三类结果：

1. 原始扣基线电流波形图；
2. 负值截断后的电压波形图；
3. 10 个周期的能谱曲线和每周期沉积动能柱状图；
4. Excel 文件 `output_cycles_energy_spectrum0728-1.xlsx`，包含一列能量和每个周期对应的能谱列。

## 9. 需要重点核对的问题

1. **电压单位**：示波器 CSV 第一列到底是 V 还是 mV？这会直接影响 `It` 的 `1000` 倍系数。
2. **电流方向**：真实离子信号是否应为正？如果原始信号是负脉冲，直接 `max(v, 0)` 会把主要信号删掉。
3. **时间零点**：光电峰是否一定落在 `245000:249000`？不同实验文件可能需要自动化或可配置。
4. **周期数量**：固定 `range(10)` 和 `points_per_cycle=500000` 是否适配所有文件？建议根据数据长度自动计算。
5. **插值边界**：`estart/estop` 是否总在 `energy_ev` 范围内？否则会报错。
6. **物理公式单位**：`Mxe` 里使用 `1.66e-27`，能量公式里使用 `1.67e-27`，建议统一。
7. **积分算法**：建议改为梯形积分，并明确 `dN/dE` 的单位与是否包含立体角校正。
8. **未使用变量**：`Noise_index2`、`startindex_incycle`、`endindex_incycle` 等建议删除或真正接入配置。

## 10. 建议的下一步重构方向

为了让脚本更容易复用和排错，建议拆成以下函数：

- `load_waveform_csv(path)`：读取 CSV 电压；
- `remove_baseline(voltage, noise_points)`：扣除基线；
- `clip_signal(voltage, mode)`：选择负值截断、取反或保留原始；
- `split_cycles(voltage, points_per_cycle)`：自动按周期切片；
- `find_photoelectric_peak(cycle_voltage, start, end)`：定位光电峰；
- `tof_to_energy(time_s, distance_m, mass_kg, charge_c)`：飞行时间换算能量；
- `current_to_spectrum(current_a, time_s, ...)`：电流换算为能谱；
- `integrate_energy(energy_ev, spectrum, estart, estop)`：计算沉积动能；
- `export_spectrum_excel(df, output_path)`：导出 Excel。

这样可以把实验参数集中到一个配置区，并且针对每一步单独画图检查。
