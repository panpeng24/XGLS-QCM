import os
import io
import time
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# 1. 设置 matplotlib 字体 (宋体)
plt.rcParams['font.sans-serif'] = ['SimSun', 'SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False


class StandardReportGenerator:
    def __init__(self):
        self.doc = Document()
        self._setup_styles()

    def _setup_styles(self):
        """配置全局字体为宋体 (SimSun)"""
        # 配置正文 Normal 样式
        style = self.doc.styles['Normal']
        style.font.name = 'SimSun'  # 西文
        style._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')  # 中文
        style.font.size = Pt(11)

        # 配置标题样式 (Heading 1-3)
        for i in range(1, 4):
            style_name = f'Heading {i}'
            if style_name in self.doc.styles:
                s = self.doc.styles[style_name]
                s.font.name = 'SimSun'
                s._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
                s.font.bold = True
                s.font.color.rgb = RGBColor(0, 0, 0)  # 黑色标题

    def generate(self, filepath, meta, qcm_data, rga_data=None):
        """生成全量报告"""
        # 页面设置
        self._setup_page_layout()

        # 页眉页脚 (含页码/日期)
        self._create_header_footer()

        # 封面
        self._create_cover(meta)
        self.doc.add_page_break()

        # 修订记录
        self._create_revision_history()
        self.doc.add_page_break()

        # --- 正文 (复刻 GitHub 模版) ---
        self._create_sec1_info(meta)
        self._create_sec2_scope()
        self._create_sec3_model(qcm_data, rga_data)  # [核心] 插入数据
        self._create_sec4_factors()
        self._create_sec5_layout()
        self._create_sec6_variables()
        self._create_sec7_sop()
        self._create_sec8_data()
        self._create_sec9_risk()
        self._create_sec10_exsitu(meta, qcm_data)  # [核心] 交叉校准
        self._create_sec11_decision(qcm_data)

        # 附录
        self.doc.add_page_break()
        self._create_appendix()

        try:
            self.doc.save(filepath)
            return True, f"报告已生成: {filepath}"
        except Exception as e:
            return False, f"保存失败: {e}"

    # ================= 辅助函数 =================
    def _set_cell_bg(self, cell, color_hex):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), color_hex)
        tcPr.append(shd)

    def _checkbox(self, checked=False):
        return "☑" if checked else "☐"

    def _add_field(self, paragraph, field_code):
        """插入域代码 (页码)"""
        run = paragraph.add_run()
        r = run._r
        fldChar = OxmlElement('w:fldChar')
        fldChar.set(qn('w:fldCharType'), 'begin')
        r.append(fldChar)

        run = paragraph.add_run()
        r = run._r
        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = field_code
        r.append(instrText)

        run = paragraph.add_run()
        r = run._r
        fldChar = OxmlElement('w:fldChar')
        fldChar.set(qn('w:fldCharType'), 'separate')
        r.append(fldChar)

        run = paragraph.add_run()
        r = run._r
        fldChar = OxmlElement('w:fldChar')
        fldChar.set(qn('w:fldCharType'), 'end')
        r.append(fldChar)

    def _setup_page_layout(self):
        section = self.doc.sections[0]
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # ================= 结构实现 =================

    def _create_header_footer(self):
        section = self.doc.sections[0]
        # 页眉
        header = section.header
        p = header.paragraphs[0]
        p.text = "XGLS 检测光源产品部\t实验方案 v1.1 (工程归档)"
        p.style = "Normal"
        p.paragraph_format.tab_stops.add_tab_stop(Inches(6.27), WD_TAB_ALIGNMENT.RIGHT)

        # 页脚
        footer = section.footer
        p = footer.paragraphs[0]
        p.text = ""
        p.style = "Normal"

        # 左侧日期
        run = p.add_run(f"日期: {datetime.now().strftime('%Y-%m-%d')}")
        run.font.size = Pt(9)

        # 右侧页码
        p.add_run("\t")
        p.paragraph_format.tab_stops.add_tab_stop(Inches(6.27), WD_TAB_ALIGNMENT.RIGHT)
        run = p.add_run("第 ")
        run.font.size = Pt(9)
        self._add_field(p, "PAGE")
        run = p.add_run(" 页 / 共 ")
        run.font.size = Pt(9)
        self._add_field(p, "NUMPAGES")
        run = p.add_run(" 页")
        run.font.size = Pt(9)

    def _create_cover(self, meta):
        for _ in range(5): self.doc.add_paragraph()

        t1 = self.doc.add_heading('检测光源多尺度污染测量报告', 0)
        t1.alignment = WD_ALIGN_PARAGRAPH.CENTER

        t2 = self.doc.add_paragraph('General Contamination Measurement Report (DPP/LRP/LDP)')
        t2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        t2.style.font.size = Pt(14)
        t2.style.font.bold = True

        for _ in range(8): self.doc.add_paragraph()

        info = f"部门：检测光源产品部\n编制：{meta.get('operator', 'Engineer')}\n日期：{datetime.now().strftime('%Y-%m-%d')}"
        p = self.doc.add_paragraph(info)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.style.font.size = Pt(12)

    def _create_revision_history(self):
        self.doc.add_heading('修订记录', level=1)
        table = self.doc.add_table(rows=3, cols=4)
        table.style = 'Table Grid'
        headers = ["版本", "修订日期", "变更说明", "修订人"]
        for i, h in enumerate(headers):
            c = table.cell(0, i);
            c.text = h;
            self._set_cell_bg(c, "E0E0E0")

        rows = [("v1.0", "2026-01-23", "版本1.0", "潘鹏"),
                ("v1.1", datetime.now().strftime('%Y-%m-%d'), "自动生成版本", "System")]
        for r, row in enumerate(rows, 1):
            for c, val in enumerate(row): table.cell(r, c).text = val

    def _create_sec1_info(self, meta):
        self.doc.add_heading('1. 实验基本信息与分类', level=1)
        table = self.doc.add_table(rows=3, cols=2)
        table.style = 'Table Grid'

        headers = ["配置项", "实验选择 (请勾选)"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "F2F2F2")

        plat = meta.get('platform', '')
        c_dpp, c_lrp, c_ldp = self._checkbox('DPP' in plat), self._checkbox('LRP' in plat), self._checkbox(
            'LDP' in plat)

        table.cell(1, 0).text = "光源平台"
        table.cell(1, 1).text = f"{c_dpp} DPP (放电)    {c_lrp} LRP (激光)    {c_ldp} LDP (激光辅助)"
        table.cell(2, 0).text = "污染类型"
        table.cell(2,
                   1).text = f"{self._checkbox(True)} Debris (碎屑)    {self._checkbox(False)} Ions (离子)    {self._checkbox(meta.get('has_rga', False))} Outgassing (释气)"

    def _create_sec2_scope(self):
        self.doc.add_heading('2. 测量目标与适用范围', level=1)
        self.doc.add_paragraph(
            "本文件定义检测光源平台（DPP / LRP / LDP）污染测量的统一工程方法，用于在受控条件下获取具有工程可比性的污染监控数据。")
        self.doc.add_heading('2.1 测量目标', level=2)
        p = self.doc.add_paragraph();
        p.style = 'List Bullet';
        p.add_run("建立跨平台统一的污染测量流程")
        self.doc.add_paragraph("监控污染随运行参数变化的趋势行为", style='List Bullet')
        self.doc.add_paragraph("识别高风险运行工况与污染放大机制", style='List Bullet')

    def _create_sec3_model(self, qcm_data, rga_data):
        self.doc.add_heading('3. 物理模型与判定指标 (含实测数据)', level=1)
        self.doc.add_paragraph("针对不同污染组分，其核心监控指标如下表所示：")
        table = self.doc.add_table(rows=4, cols=4)
        table.style = 'Table Grid'
        headers = ["组分类别", "主监测工具", "物理量", "判定准则"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "D9D9D9")

        rows = [("金属蒸汽/碎屑", "QCM", "厚度 / 质量", "沉积率 < 10 nm/h"),
                ("高能离子", "Faraday Cup", "离子电流", "符合溅射模型"),
                ("有机组分", "RGA", "分压", "m/z 50-200 背景可控")]
        for r, row in enumerate(rows, 1):
            for c, val in enumerate(row): table.cell(r, c).text = val

        self.doc.add_heading('3.1 实测数据展示', level=2)

        # 1. QCM 三视图 (恢复三幅图)
        if qcm_data and len(qcm_data['time']) > 0:
            self.doc.add_paragraph("本次实验 QCM 传感器监测到的全过程数据（三轴视图）：")
            mem_img = self._plot_qcm_3_subplots(qcm_data)
            self.doc.add_picture(mem_img, width=Inches(6.2))
            self.doc.add_paragraph(
                "图 3-1: QCM 频率变化(上)、沉积厚度(中)、沉积速率(下) 趋势图").alignment = WD_ALIGN_PARAGRAPH.CENTER
        else:
            self.doc.add_paragraph("[警告] 本次实验未包含有效 QCM 数据。")

        # 2. RGA 视图
        if rga_data is not None and not rga_data.empty:
            self.doc.add_paragraph("RGA 残余气体质谱监测数据：")
            mem_img = self._plot_rga(rga_data)
            self.doc.add_picture(mem_img, width=Inches(6.0))
            self.doc.add_paragraph("图 3-2: RGA 分压趋势图").alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _create_sec4_factors(self):
        self.doc.add_heading('4. 污染测量全链路影响因子分析', level=1)
        table = self.doc.add_table(rows=4, cols=3)
        table.style = 'Table Grid'
        headers = ["链路层级", "关键影响因子", "工程风险"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "F2F2F2")
        rows = [("工装与几何", "采样位置、视角、温升", "非等效沉积"),
                ("传感器", "类型、安装角度、老化", "灵敏度漂移"),
                ("电子学", "噪声、积分时间", "低信噪误判")]
        for r, row in enumerate(rows, 1):
            for c, val in enumerate(row): table.cell(r, c).text = val

    def _create_sec5_layout(self):
        self.doc.add_heading('5. 实验系统布置与环境控制', level=1)
        p = self.doc.add_paragraph();
        p.style = 'List Bullet'
        p.add_run("热隔离：QCM 探头必须配置独立的冷却水回路 (22℃)")
        self.doc.add_paragraph("视线路径：探头位于等离子体羽流直视范围", style='List Bullet')

    def _create_sec6_variables(self):
        self.doc.add_heading('6. 实验变量与控制参数', level=1)
        table = self.doc.add_table(rows=3, cols=4)
        table.style = 'Table Grid'
        headers = ["参数", "工况 A", "工况 B", "本次实验"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "D9D9D9")
        table.cell(1, 0).text = "压力";
        table.cell(1, 1).text = "0.5 Pa";
        table.cell(1, 2).text = "2 Pa"
        table.cell(2, 0).text = "功率";
        table.cell(2, 1).text = "500 W";
        table.cell(2, 2).text = "800 W"

    def _create_sec7_sop(self):
        self.doc.add_heading('7. 实验 SOP (模块化步骤)', level=1)
        self.doc.add_paragraph(
            "1. [预热] 真空度达标后基线记录。\n2. [采集] 功率步进记录。\n3. [冷却] 保持真空冷却 30 min。")

    def _create_sec8_data(self):
        self.doc.add_heading('8. 数据记录与管理', level=1)
        self.doc.add_paragraph("• 原始数据禁止覆盖\n• 数据处理脚本需归档\n• 文件命名统一规范 (Timestamp_ID)")

    def _create_sec9_risk(self):
        self.doc.add_heading('9. 风险评估', level=1)
        table = self.doc.add_table(rows=4, cols=4)
        table.style = 'Table Grid'
        headers = ["风险因素", "潜在影响", "应对措施", "阶段"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "F2F2F2")
        rows = [("材料释气", "假污染信号", "预烘烤处理", "设计"),
                ("真空波动", "数据噪声", "延长稳定时间", "实验"),
                ("探头污染", "数据失真", "定期清洁校准", "处理")]
        for r, row in enumerate(rows, 1):
            for c, val in enumerate(row): table.cell(r, c).text = val

    def _create_sec10_exsitu(self, meta, qcm_data):
        self.doc.add_heading('10. 沉积物离线分析与验证', level=1)
        self.doc.add_heading('10.1 综合分析表征矩阵', level=2)
        table = self.doc.add_table(rows=4, cols=3)
        table.style = 'Table Grid'
        headers = ["分析手段", "检测指标", "核心工程价值"]
        for i, h in enumerate(headers): c = table.cell(0, i); c.text = h; self._set_cell_bg(c, "D9D9D9")
        rows = [("SEM/EDS", "形貌/元素", "判定成膜或喷溅"), ("XPS", "化学价态", "评估氧化/碳化"),
                ("台阶仪", "物理厚度", "拟合真实密度")]
        for r, row in enumerate(rows, 1):
            for c, val in enumerate(row): table.cell(r, c).text = val

        self.doc.add_heading('10.3 多源数据交叉校准', level=2)
        step_thick = meta.get('step_thick', 0.0)
        qcm_thick = qcm_data['thick'][-1] if (qcm_data and qcm_data['thick']) else 0.0

        p = self.doc.add_paragraph()
        p.add_run(f"本次实验校准结果：\n").bold = True
        p.add_run(f"1. QCM 测得厚度: {qcm_thick:.2f} nm\n")
        if step_thick > 0:
            ratio = step_thick / qcm_thick if qcm_thick > 0 else 0
            p.add_run(f"2. 台阶仪实测厚度: {step_thick:.2f} nm\n")
            p.add_run(f"3. 偏差比例 (Step/QCM): {ratio:.2f}\n")
            p.add_run(
                "结论：吻合良好 (Pass)" if 0.9 < ratio < 1.1 else "结论：存在偏差 (Fail)，建议校准 Tooling。").bold = True
        else:
            p.add_run("未输入台阶仪数据，无法交叉校准。")

    def _create_sec11_decision(self, qcm_data):
        self.doc.add_heading('11. 结果输出与工程决策', level=1)
        final_thick = qcm_data['thick'][-1] if (qcm_data and qcm_data['thick']) else 0
        decision = "停机维护" if final_thick > 300 else ("密切观察" if final_thick > 100 else "允许继续运行")
        color = RGBColor(255, 0, 0) if final_thick > 300 else RGBColor(0, 128, 0)

        table = self.doc.add_table(rows=2, cols=2)
        table.style = 'Table Grid'
        table.cell(0, 0).text = "累计沉积量"
        table.cell(0, 1).text = f"{final_thick:.2f} nm"
        c = table.cell(1, 1);
        c.text = decision
        c.paragraphs[0].runs[0].font.bold = True
        c.paragraphs[0].runs[0].font.color.rgb = color

    def _create_appendix(self):
        self.doc.add_heading('附录 A: 污染测量影响因子检查表 (Checklist)', level=1)
        self.doc.add_paragraph("本附录用于在实验前、中、后对关键因素进行检查。")

        checks = [
            ("工装与安装", "法拉第杯 / QCM 安装方向正确", "是 / 否"),
            ("工装与安装", "真空电缆固定可靠", "是 / 否"),
            ("真空与环境", "基线真空度满足实验要求", "是 / 否"),
            ("真空与环境", "残余气体谱中无异常峰", "是 / 否"),
            ("仪器状态", "传感器工作在推荐量程", "是 / 否"),
            ("仪器状态", "无已知硬件异常或报警", "是 / 否")
        ]

        table = self.doc.add_table(rows=len(checks) + 1, cols=3)
        table.style = 'Table Grid'
        headers = ["类别", "检查项", "状态"]
        for i, h in enumerate(headers): table.cell(0, i).text = h; self._set_cell_bg(table.cell(0, i), "E0E0E0")

        for r, (cat, item, val) in enumerate(checks, 1):
            table.cell(r, 0).text = cat
            table.cell(r, 1).text = item
            table.cell(r, 2).text = val

    # ================= 绘图函数 (恢复三视图) =================
    def _plot_qcm_3_subplots(self, data):
        """生成三视图 (Freq, Thick, Rate)"""
        plt.rcParams['font.sans-serif'] = ['SimSun']
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(7, 7), sharex=True)
        t = np.array(data['time'])

        # 1. Freq
        freq = data.get('freq', np.zeros_like(t))
        ax1.plot(t, freq, 'k-', linewidth=1.2)
        ax1.set_ylabel('Freq Shift (Hz)')
        ax1.set_title('频率变化', fontsize=11)
        ax1.grid(True, linestyle='--', alpha=0.3)

        # 2. Thick
        ax2.plot(t, data['thick'], 'r-', linewidth=1.5)
        ax2.set_ylabel('Thickness (nm)')
        ax2.set_title('沉积厚度', fontsize=11)
        ax2.grid(True, linestyle='--', alpha=0.3)

        # 3. Rate
        ax3.plot(t, data['rate'], 'b-', linewidth=1.2)
        ax3.set_ylabel('Rate (Å/s)')
        ax3.set_xlabel('Time (s)')
        ax3.set_title('沉积速率', fontsize=11)
        ax3.grid(True, linestyle='--', alpha=0.3)

        plt.tight_layout()
        mem = io.BytesIO()
        plt.savefig(mem, format='png', dpi=150)
        plt.close()
        return mem

    def _plot_rga(self, df):
        plt.rcParams['font.sans-serif'] = ['SimSun']
        fig, ax = plt.subplots(figsize=(7, 3.5))
        if not df.empty:
            x_col = df.columns[0]
            for col in df.columns[1:6]:
                ax.plot(df[x_col], df[col], label=col)
            ax.set_yscale('log')
            ax.set_ylabel('Partial Pressure (Torr)')
            ax.set_xlabel('Time / Scan')
            ax.legend(loc='upper right', fontsize='small')
            ax.grid(True, which="both", alpha=0.2)
        plt.tight_layout()
        mem = io.BytesIO()
        plt.savefig(mem, format='png', dpi=150)
        plt.close()
        return mem
