import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from scipy import stats
import warnings

warnings.filterwarnings('ignore')

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# ---------------------------------------------------------------
# 辅助：相对增长率 / 总增长率
# ---------------------------------------------------------------
def rel_growth_pct(sen_slope, data):
    m = np.mean(data)
    if m > 0:
        return sen_slope / m * 100
    if m < 0:
        return sen_slope / abs(m) * 100
    return np.nan

def total_growth_pct(data):
    first = data[0]
    if first > 0:
        return (data[-1] - first) / first * 100
    if first < 0:
        return (data[-1] - first) / abs(first) * 100
    return np.nan

# ---------------------------------------------------------------
# 1. Theil-Sen (仅保留斜率点估计)
# ---------------------------------------------------------------
def theil_sen_slope(y, x=None):
    # 移除了 alpha=0.95 和置信区间的返回
    res = stats.theilslopes(y, x)
    return res[0], res[1]

# ---------------------------------------------------------------
# 2. Mann-Kendall
# ---------------------------------------------------------------
def mann_kendall_test(y):
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0, 1.0, "无显著变化", "NSC"

    s = 0.0
    for i in range(n - 1):
        s += np.sign(y[i + 1:] - y[i]).sum()

    _, counts = np.unique(y, return_counts=True)
    counts = counts[counts > 1]
    tie_term = float(np.sum(counts * (counts - 1) * (2 * counts + 5))) if counts.size else 0.0
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    if var_s <= 0:
        return 0.0, 1.0, "无显著变化", "NSC"

    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0

    p = 2 * stats.norm.sf(abs(z))

    if p < 0.01:
        trend_type = "极显著增加" if z > 0 else "极显著减少"
        trend_category = "ESI" if z > 0 else "ESD"
    elif p < 0.05:
        trend_type = "显著增加" if z > 0 else "显著减少"
        trend_category = "SI" if z > 0 else "SD"
    elif p < 0.1:
        trend_type = "微显著增加" if z > 0 else "微显著减少"
        trend_category = "SSI" if z > 0 else "SSD"
    else:
        trend_type = "无显著变化"
        trend_category = "NSC"

    return z, p, trend_type, trend_category

# ---------------------------------------------------------------
# 3. Yue-Pilon 预白化
# ---------------------------------------------------------------
def yue_pilon_mk_test(y, sen_slope=None, sen_intercept=None, x=None):
    y = np.asarray(y, dtype=float)
    n = len(y)
    if x is None:
        x = np.arange(n)
    else:
        x = np.asarray(x, dtype=float)

    if sen_slope is None or sen_intercept is None:
        sen_slope, sen_intercept = theil_sen_slope(y, x)

    trend = sen_intercept + sen_slope * x
    resid = y - trend

    if n > 1 and np.std(resid[:-1]) > 0 and np.std(resid[1:]) > 0:
        r1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1])
        if not np.isfinite(r1):
            r1 = 0.0
    else:
        r1 = 0.0

    threshold = 1.96 / np.sqrt(n) if n > 2 else 0.2

    if r1 > threshold and r1 < 1.0:
        resid_pw = resid[1:] - r1 * resid[:-1]
        y_pw = resid_pw + trend[1:]
    else:
        y_pw = y

    mk_z, mk_p, trend_type, trend_category = mann_kendall_test(y_pw)

    return mk_z, mk_p, trend_type, trend_category, r1, len(y_pw)

# ---------------------------------------------------------------
# 4. 示例 Excel
# ---------------------------------------------------------------
def create_example_excel(path='多地区GDP数据示例.xlsx'):
    regions = ['北京', '上海', '广州', '深圳', '南京', '杭州', '成都', '武汉', '西安', '重庆']
    years = list(range(2000, 2020))
    rng = np.random.default_rng(42)
    data = {}
    for idx, region in enumerate(regions):
        base_gdp = 100 + rng.uniform(-20, 100)
        if idx == 0:   base_growth = 0.12 + rng.uniform(-0.02, 0.03)
        elif idx == 1: base_growth = 0.08 + rng.uniform(-0.02, 0.02)
        elif idx == 2: base_growth = 0.04 + rng.uniform(-0.02, 0.02)
        elif idx == 3: base_growth = 0.00 + rng.uniform(-0.02, 0.02)
        elif idx == 4: base_growth = -0.04 + rng.uniform(-0.02, 0.02)
        elif idx == 5: base_growth = -0.08 + rng.uniform(-0.02, 0.02)
        elif idx == 6: base_growth = -0.12 + rng.uniform(-0.03, 0.02)
        else:          base_growth = rng.uniform(-0.1, 0.1)

        region_data = []
        for _ in range(len(years)):
            if not region_data:
                value = base_gdp
            else:
                noise = rng.normal(0, 0.05)
                factor = max(0.01, 1 + base_growth + noise)
                value = region_data[-1] * factor
            region_data.append(round(value, 2))
        data[region] = region_data

    df = pd.DataFrame(data, index=years).T
    df.index.name = '地区'
    df.to_excel(path)
    return path

# ---------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------
class MultiRegionTrendAnalysisApp:
    def __init__(self, root):
        self.root = root
        self.root.title("多地区趋势分析工具（Theil-Sen + Yue-Pilon 修正MK检验）")
        self.root.geometry("1350x800")

        self.df = None
        self.file_path = None
        self.results_df = None
        self.selected_region = None
        self.year_numeric = None

        self.trend_colors = {
            "极显著增加": "#1f77b4", "显著增加": "#2ca02c", "微显著增加": "#98df8a",
            "无显著变化": "#7f7f7f", "微显著减少": "#ff9896", "显著减少": "#d62728",
            "极显著减少": "#8c564b"
        }

        self.create_widgets()

    def create_widgets(self):
        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame,
                 text="多地区趋势分析工具（含 Yue-Pilon 修正）",
                 font=("Arial", 16, "bold")).pack(pady=10)

        file_frame = tk.LabelFrame(main_frame, text="数据文件选择", padx=10, pady=10)
        file_frame.pack(fill=tk.X, pady=5)

        tk.Button(file_frame, text="选择Excel文件",
                  command=self.load_excel, width=15).pack(side=tk.LEFT, padx=5)
        self.file_label = tk.Label(file_frame, text="未选择文件", fg="gray")
        self.file_label.pack(side=tk.LEFT, padx=10)
        tk.Button(file_frame, text="生成示例Excel",
                  command=self._gen_example, width=15).pack(side=tk.LEFT, padx=5)

        analysis_frame = tk.LabelFrame(main_frame, text="分析控制", padx=10, pady=10)
        analysis_frame.pack(fill=tk.X, pady=5)

        tk.Button(analysis_frame, text="分析所有地区",
                  command=self.analyze_all_regions, width=15).pack(side=tk.LEFT, padx=5)
        tk.Label(analysis_frame, text="选择查看地区:").pack(side=tk.LEFT, padx=10)
        self.region_combo = ttk.Combobox(analysis_frame, state="readonly", width=20)
        self.region_combo.pack(side=tk.LEFT, padx=5)
        self.region_combo.bind("<<ComboboxSelected>>", self.on_region_selected)
        tk.Button(analysis_frame, text="导出结果",
                  command=self.export_results, width=15).pack(side=tk.LEFT, padx=10)

        results_frame = tk.Frame(main_frame)
        results_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        left_frame = tk.LabelFrame(results_frame, text="所有地区分析结果汇总", padx=10, pady=10)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        self.create_results_table(left_frame)

        right_frame = tk.LabelFrame(results_frame, text="单个地区详细分析", padx=10, pady=10)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        text_container = tk.Frame(right_frame)
        text_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.detail_text = tk.Text(text_container, height=15, width=50)
        self.detail_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tk.Scrollbar(text_container, command=self.detail_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.detail_text.config(yscrollcommand=sb.set)

        self.figure_frame = tk.Frame(right_frame)
        self.figure_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))

        legend_frame = tk.Frame(main_frame)
        legend_frame.pack(fill=tk.X, pady=5)
        tk.Label(legend_frame, text="趋势类型颜色说明:",
                 font=("Arial", 9, "bold")).pack(anchor="w")
        legend_items = tk.Frame(legend_frame)
        legend_items.pack(fill=tk.X, pady=(2, 0))
        for t, color in self.trend_colors.items():
            item = tk.Frame(legend_items)
            item.pack(side=tk.LEFT, padx=4)
            tk.Label(item, bg=color, width=2, height=1, relief="solid", bd=1).pack(side=tk.LEFT)
            tk.Label(item, text=t, font=("Arial", 8)).pack(side=tk.LEFT)

    def _gen_example(self):
        try:
            path = create_example_excel()
            messagebox.showinfo("已生成", f"示例文件：\n{path}")
        except Exception as e:
            messagebox.showerror("生成失败", str(e))

    def create_results_table(self, parent):
        # 移除了 CI 下限和 CI 上限列
        columns = ("地区", "Sen斜率", "增长率%", "自相关r1", "修正p值", "趋势类型")
        self.tree = ttk.Treeview(parent, columns=columns, show="headings", height=15)
        widths = [120, 100, 100, 100, 100, 120]
        for col, w in zip(columns, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")
        for t, color in self.trend_colors.items():
            self.tree.tag_configure(t, background=color)
        sb = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_table_select)

    def _get_year_numeric(self):
        if self.df is None or len(self.df.columns) == 0:
            return np.array([], dtype=float)
        try:
            arr = np.asarray(self.df.columns, dtype=float)
            if np.all(np.isfinite(arr)):
                return arr
        except (ValueError, TypeError):
            pass
        return np.arange(len(self.df.columns), dtype=float)

    def load_excel(self):
        fp = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not fp:
            return
        try:
            df = pd.read_excel(fp, index_col=0)
            df = df.apply(pd.to_numeric, errors='coerce')

            if df.dropna(how='all').empty:
                messagebox.showerror("错误", "Excel文件中没有有效数据")
                return

            df.index = df.index.astype(str)
            if df.index.duplicated().any():
                dup = df.index[df.index.duplicated()].unique().tolist()
                dup_str = '、'.join(str(x) for x in dup)
                messagebox.showwarning("索引重复",
                                       f"以下地区名重复，将保留首次出现：\n{dup_str}")
                df = df[~df.index.duplicated(keep='first')].copy()

            self.df = df
            self.file_path = fp
            self.year_numeric = self._get_year_numeric()

            self.file_label.config(text=os.path.basename(fp))

            regions = self.df.index.tolist()
            self.region_combo['values'] = regions
            self.region_combo.set('')
            self.show_data_preview()
        except Exception as e:
            messagebox.showerror("错误", f"读取Excel文件时出错:\n{e}")

    def show_data_preview(self):
        if self.df is None:
            return
        txt = f"数据预览 (共{len(self.df)}个地区，{len(self.df.columns)}个年份):\n\n"
        txt += f"地区列表: {', '.join(self.df.index.tolist()[:5])}...\n"
        if len(self.df.columns) > 0:
            txt += f"年份范围: {self.df.columns[0]} - {self.df.columns[-1]}\n\n"
        txt += f"前3个地区的数据:\n{self.df.head(3).to_string()}"
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.detail_text.delete(1.0, tk.END)
        self.detail_text.insert(1.0, txt)
        for w in self.figure_frame.winfo_children():
            w.destroy()

    def analyze_all_regions(self):
        if self.df is None:
            messagebox.showwarning("警告", "请先选择Excel文件")
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        years_full = self.year_numeric if self.year_numeric is not None \
            else np.arange(len(self.df.columns), dtype=float)

        results, errors = [], []
        pw_count = 0
        skipped_nan = 0

        for region in self.df.index:
            raw = self.df.loc[region].values.astype(float)
            mask = np.isfinite(raw)
            if not mask.all():
                skipped_nan += 1
            data = raw[mask]
            x_year = years_full[mask]

            if len(data) < 5:
                errors.append(f"地区 {region} 有效数据点不足 ({len(data)})")
                continue
            try:
                sen_slope, sen_intercept = theil_sen_slope(data, x=x_year)
                mk_z, mk_p, trend_type, trend_category, r1, len_pw = yue_pilon_mk_test(
                    data, sen_slope, sen_intercept, x=x_year)

                if len_pw < len(data):
                    pw_count += 1

                rg = rel_growth_pct(sen_slope, data)

                results.append({
                    '地区': region, 'Sen斜率': sen_slope, '增长率%': rg,
                    '自相关r1': r1, 'Y-P修正Z值': mk_z, 'Y-P修正p值': mk_p,
                    '预白化后长度': len_pw,
                    '趋势类型': trend_type
                })

                rg_str = f"{rg:.2f}" if np.isfinite(rg) else "N/A"
                self.tree.insert("", "end", values=(
                    str(region), f"{sen_slope:.4f}", rg_str,
                    f"{r1:.3f}", f"{mk_p:.4f}", trend_type
                ), tags=(trend_type,))
            except Exception as e:
                errors.append(f"分析地区 {region} 时出错: {e}")

        if errors:
            messagebox.showwarning("部分分析出错", "前5个错误:\n" + "\n".join(errors[:5]))

        self.results_df = pd.DataFrame(results)
        if len(results) == 0:
            return

        summary = f"分析完成！共 {len(results)} 个地区。\n"
        if skipped_nan:
            summary += (f"其中 {skipped_nan} 个地区包含 NaN/Inf 数据，已按有效数据点参与分析"
                        f"（斜率基于真实时间坐标，不受缺失影响）。\n")
        summary += f"其中 {pw_count} 个地区因残差存在显著正自相关而实施了预白化处理。\n\n"
        summary += "趋势类型统计：\n"
        order = ["极显著增加", "显著增加", "微显著增加", "无显著变化",
                 "微显著减少", "显著减少", "极显著减少"]
        counts = self.results_df['趋势类型'].value_counts()
        for t in order:
            if t in counts.index:
                c = counts[t]
                summary += f"  {t}: {c}个 ({(c / len(results)) * 100:.1f}%)\n"

        self.detail_text.delete(1.0, tk.END)
        self.detail_text.insert(1.0, summary)
        self.plot_all_regions_summary()
        messagebox.showinfo("分析完成", f"成功分析了 {len(results)} 个地区")

    def plot_all_regions_summary(self):
        # (此部分不变，省略)
        if self.results_df is None or len(self.results_df) == 0:
            return
        for w in self.figure_frame.winfo_children():
            w.destroy()

        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        fig.suptitle('所有地区分析结果摘要 (Yue-Pilon 修正)', fontsize=14, fontweight='bold')

        order = ["极显著增加", "显著增加", "微显著增加", "无显著变化",
                 "微显著减少", "显著减少", "极显著减少"]

        ax1 = axes[0, 0]
        counts = self.results_df['趋势类型'].value_counts()
        counts = counts.reindex([t for t in order if t in counts.index])
        colors = [self.trend_colors.get(t, '#7f7f7f') for t in counts.index]
        ax1.bar(range(len(counts)), counts.values, color=colors, edgecolor='black')
        ax1.set_xticks(range(len(counts)))
        ax1.set_xticklabels(counts.index, rotation=45, ha='right')
        ax1.set_title('趋势类型分布')

        ax2 = axes[0, 1]
        all_growth = self.results_df['增长率%'].dropna()
        if len(all_growth) > 0:
            gmin, gmax = all_growth.min(), all_growth.max()
            bins = np.linspace(gmin, gmax, 11) if gmin != gmax else np.linspace(gmin-1, gmax+1, 11)
            for t in counts.index:
                subset = self.results_df[(self.results_df['趋势类型'] == t)]['增长率%'].dropna()
                if len(subset) > 0:
                    ax2.hist(subset, bins=bins, alpha=0.5, label=t, color=self.trend_colors.get(t, '#7f7f7f'), edgecolor='black')
            ax2.legend(loc='best', fontsize=8)
        ax2.axvline(x=0, color='gray', linestyle='--')
        ax2.set_title('增长率分布（按趋势类型，统一分箱）')

        ax3 = axes[1, 0]
        box_data, box_labels = [], []
        for t in counts.index:
            v = self.results_df[self.results_df['趋势类型'] == t]['增长率%'].dropna()
            if len(v) > 0:
                box_data.append(v.values)
                box_labels.append(t)
        if box_data:
            bp = ax3.boxplot(box_data, positions=range(len(box_labels)), patch_artist=True)
            for patch, t in zip(bp['boxes'], box_labels):
                patch.set_facecolor(self.trend_colors.get(t, '#7f7f7f'))
                patch.set_alpha(0.7)
            ax3.set_xticks(range(len(box_labels)))
            ax3.set_xticklabels(box_labels, rotation=45, ha='right')
        ax3.axhline(y=0, color='gray', linestyle='--')
        ax3.set_title('增长率箱线图')

        ax4 = axes[1, 1]
        c = [self.trend_colors.get(t, '#7f7f7f') for t in self.results_df['趋势类型']]
        pvals = self.results_df['Y-P修正p值'].clip(lower=1e-10)
        ax4.scatter(self.results_df['Y-P修正Z值'], -np.log10(pvals), c=c, alpha=0.7, edgecolors='black', s=50)
        ax4.axhline(y=-np.log10(0.1), color='gray', linestyle='--', label='p=0.1')
        ax4.axhline(y=-np.log10(0.05), color='orange', linestyle='--', label='p=0.05')
        ax4.axhline(y=-np.log10(0.01), color='red', linestyle='--', label='p=0.01')
        ax4.set_xlabel('Y-P 修正 Z值')
        ax4.set_ylabel('-log10(修正p值)')
        ax4.set_title('趋势显著性分布')
        ax4.legend(loc='upper right')

        plt.tight_layout()
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        canvas = FigureCanvasTkAgg(fig, master=self.figure_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def on_region_selected(self, event):
        region = self.region_combo.get()
        if region and self.df is not None and region in self.df.index:
            self.selected_region = region
            self.show_region_details(region)

    def on_table_select(self, event):
        sel = self.tree.selection()
        if sel:
            region = self.tree.item(sel[0])['values'][0]
            self.region_combo.set(region)
            self.selected_region = region
            self.show_region_details(region)

    def show_region_details(self, region):
        if self.df is None or region not in self.df.index:
            return

        raw = self.df.loc[region].values.astype(float)
        mask = np.isfinite(raw)
        data = raw[mask]
        years_label = self.df.columns.values[mask]
        years_full = self.year_numeric if self.year_numeric is not None else np.arange(len(self.df.columns), dtype=float)
        years_numeric = years_full[mask]

        if len(data) < 5:
            self.detail_text.delete(1.0, tk.END)
            self.detail_text.insert(1.0, f"地区 {region} 有效数据点不足（{len(data)}），无法进行趋势检验。")
            for w in self.figure_frame.winfo_children():
                w.destroy()
            return

        sen_slope, sen_intercept = theil_sen_slope(data, x=years_numeric)
        mk_z, mk_p, trend_type, trend_category, r1, len_pw = yue_pilon_mk_test(
            data, sen_slope, sen_intercept, x=years_numeric)

        rg = rel_growth_pct(sen_slope, data)
        tg = total_growth_pct(data)

        threshold = 1.96 / np.sqrt(len(data)) if len(data) > 2 else 0.2

        txt = f"地区: {region}\n" + "=" * 50 + "\n\n"
        if not mask.all():
            txt += f"⚠ 检测到 {int((~mask).sum())} 个缺失/无效值，已剔除后分析。\n"
        txt += f"数据年份: {len(data)}年 ({years_label[0]} - {years_label[-1]})\n"

        tg_str = f"{tg:.2f}%" if np.isfinite(tg) else "N/A（起始值为0）"
        txt += f"初始值: {data[0]:.2f}  |  最终值: {data[-1]:.2f}  |  总增长率: {tg_str}\n\n"

        txt += "Theil-Sen 斜率估计结果:\n"
        txt += f"  绝对年增长量: {sen_slope:.4f} (单位/年)\n"
        rg_str = f"{rg:.4f} %/年" if np.isfinite(rg) else "N/A（均值为0）"
        txt += f"  相对年增长率: {rg_str}\n\n"

        txt += "Yue-Pilon 修正检验:\n"
        txt += f"  去趋势残差 lag-1 自相关(r1): {r1:.4f}\n"
        if len_pw < len(data):
            txt += f"  (r1 > {threshold:.3f}，残差显著正自相关，已预白化；预白化后长度 = {len_pw})\n"
        elif r1 < -threshold:
            txt += f"  (r1 < -{threshold:.3f}，残差存在显著负自相关；按 Yue-Pilon 方法不做预白化)\n"
        else:
            txt += f"  (|r1| ≤ {threshold:.3f}，残差自相关不显著，未做修正)\n"
        txt += f"  修正后 Z 统计量: {mk_z:.4f}\n"
        txt += f"  修正后 p 值: {mk_p:.6f}\n"
        txt += f"  趋势类型: {trend_type}\n"

        self.detail_text.delete(1.0, tk.END)
        self.detail_text.insert(1.0, txt)
        self.plot_region_details(region, data, years_label, years_numeric,
                                 sen_slope, sen_intercept,
                                 trend_type, mk_z, mk_p)

    def plot_region_details(self, region, data, years_label, years_numeric,
                            sen_slope, sen_intercept, trend_type, mk_z, mk_p):
        # (修改了绘图部分，移除了 CI 阴影)
        for w in self.figure_frame.winfo_children():
            w.destroy()

        if years_numeric is None:
            years_numeric = np.arange(len(data), dtype=float)

        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        fig.suptitle(f'{region} 趋势分析 - {trend_type}', fontsize=14, fontweight='bold')

        x_plot = np.arange(len(data))

        # 1. 趋势
        ax1 = axes[0, 0]
        ax1.plot(x_plot, data, 'bo-', linewidth=1.5, markersize=4, label='原始数据')
        trend_line = sen_intercept + sen_slope * years_numeric
        ax1.plot(x_plot, trend_line, 'r--', linewidth=2, label=f'Sen斜率: {sen_slope:.4f}/年')
        ax1.set_title(f'{region} 变化趋势')
        ax1.legend(loc='best')
        if len(years_label) <= 20:
            ax1.set_xticks(x_plot)
            ax1.set_xticklabels(years_label, rotation=45)

        # 2. 残差
        ax2 = axes[0, 1]
        residuals = data - trend_line
        ax2.plot(x_plot, residuals, 'go-', linewidth=1.5, markersize=4)
        ax2.axhline(y=0, color='r', linestyle='--', alpha=0.7)
        ax2.set_title('残差分析')
        if len(years_label) <= 20:
            ax2.set_xticks(x_plot)
            ax2.set_xticklabels(years_label, rotation=45)

        # 3. 年增长率
        ax3 = axes[1, 0]
        annual_growth = []
        for i in range(1, len(data)):
            prev = data[i - 1]
            if prev != 0:
                annual_growth.append((data[i] - prev) / abs(prev) * 100)
            else:
                annual_growth.append(0.0)
        colors = ['green' if g > 0 else 'red' for g in annual_growth]
        ax3.bar(x_plot[1:], annual_growth, color=colors, edgecolor='black', alpha=0.7)
        ax3.set_title('年度增长率')
        if len(years_label) <= 20:
            ax3.set_xticks(x_plot[1:])
            ax3.set_xticklabels(years_label[1:], rotation=45)

        # 4. 显著性
        ax4 = axes[1, 1]
        z_lim = max(3.0, abs(mk_z) + 0.5) if np.isfinite(mk_z) else 3.0
        xr = np.linspace(-z_lim, z_lim, 300)
        yr = 2 * stats.norm.sf(np.abs(xr))
        ax4.plot(xr, yr, 'k-', linewidth=1, alpha=0.5)

        mk_p_safe = max(float(mk_p), 1e-12) if np.isfinite(mk_p) else 1.0
        ax4.plot(mk_z, mk_p_safe, 'ro', markersize=10,
                 label=f'Y-P修正: Z={mk_z:.2f}, p={mk_p:.4f}')
        ax4.set_yscale('log')

        if np.isfinite(mk_p) and mk_p > 0:
            p_floor = max(min(mk_p * 0.5, 1e-4), 1e-12)
        else:
            p_floor = 1e-6
        ax4.set_ylim(p_floor, 1)

        ax4.axhline(y=0.01, color='red', linestyle=':', alpha=0.5, label='p=0.01')
        ax4.axhline(y=0.05, color='orange', linestyle=':', alpha=0.5, label='p=0.05')
        ax4.axvline(x=0, color='gray', linestyle='-', alpha=0.3)
        ax4.set_xlabel('Z 值')
        ax4.set_ylabel('p 值')
        ax4.set_title('Yue-Pilon 修正后显著性')
        ax4.legend(loc='best', fontsize=8)

        plt.tight_layout()
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        canvas = FigureCanvasTkAgg(fig, master=self.figure_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        plt.close(fig)

    def export_results(self):
        if self.results_df is None or len(self.results_df) == 0:
            messagebox.showwarning("警告", "请先分析数据，且至少存在一个有效结果")
            return
        fp = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                          initialfile="趋势分析结果.xlsx")
        if not fp:
            return
        try:
            with pd.ExcelWriter(fp, engine='openpyxl') as writer:
                self.df.to_excel(writer, sheet_name='原始数据')
                self.results_df.to_excel(writer, sheet_name='分析结果', index=False)

                trend_stats = (self.results_df['趋势类型']
                               .value_counts()
                               .rename_axis('趋势类型')
                               .reset_index(name='地区数量'))
                trend_stats['百分比'] = (
                    trend_stats['地区数量'] / len(self.results_df) * 100
                ).round(2)
                trend_stats.to_excel(writer, sheet_name='趋势类型统计', index=False)
            messagebox.showinfo("导出成功", f"结果已保存到:\n{fp}")
        except Exception as e:
            messagebox.showerror("导出错误", f"保存时出错:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = MultiRegionTrendAnalysisApp(root)
    root.mainloop()