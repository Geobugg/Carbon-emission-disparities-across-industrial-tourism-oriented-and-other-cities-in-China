import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import numpy as np
from scipy import stats
import warnings

warnings.filterwarnings('ignore')


class MBBToolApp:
    def __init__(self, root):
        self.root = root
        self.root.title("移动块自助法 (MBB) - Sen斜率置信区间计算工具 (2000次)")
        self.root.geometry("1100x680")

        self.df = None
        self.result_df = None

        # 默认参数：n=24 推荐 block_size=3
        self.block_size = 3
        self.n_bootstraps = 2000

        self.create_widgets()

    def create_widgets(self):
        # --- 顶部：参数与文件 ---
        frame_top = tk.Frame(self.root, padx=10, pady=10)
        frame_top.pack(fill=tk.X)

        tk.Button(frame_top, text="1. 选择面板数据 Excel", command=self.load_file, bg="#4CAF50", fg="white",
                  width=20).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.lbl_file = tk.Label(frame_top, text="未选择文件", fg="gray")
        self.lbl_file.grid(row=0, column=1, padx=5, pady=5, columnspan=4, sticky="w")

        tk.Label(frame_top, text="块长 (Block Size):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.entry_block = tk.Entry(frame_top, width=10)
        self.entry_block.insert(0, str(self.block_size))
        self.entry_block.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        tk.Label(frame_top, text="重采样次数 (Bootstraps):").grid(row=1, column=2, padx=5, pady=5, sticky="e")
        self.entry_boot = tk.Entry(frame_top, width=10)
        self.entry_boot.insert(0, str(self.n_bootstraps))
        self.entry_boot.grid(row=1, column=3, padx=5, pady=5, sticky="w")

        # --- 中部：控制按钮 ---
        frame_mid = tk.Frame(self.root, padx=10, pady=10)
        frame_mid.pack(fill=tk.X)

        self.btn_calc = tk.Button(frame_mid, text="2. 开始计算 (MBB)", command=self.run_mbb, bg="#2196F3", fg="white",
                                  width=20, state=tk.DISABLED)
        self.btn_calc.pack(side=tk.LEFT, padx=5)

        self.btn_export = tk.Button(frame_mid, text="3. 导出结果", command=self.export_excel, bg="#FF9800", fg="white",
                                    width=20, state=tk.DISABLED)
        self.btn_export.pack(side=tk.LEFT, padx=5)

        # --- 进度条 ---
        self.progress = ttk.Progressbar(frame_mid, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(side=tk.LEFT, padx=20)

        # --- 底部：结果预览 ---
        frame_bottom = tk.Frame(self.root, padx=10, pady=10)
        frame_bottom.pack(fill=tk.BOTH, expand=True)

        columns = (
            'Region',
            'Sen_Slope',
            'MBB_CI_Lower',
            'MBB_CI_Upper',
            'MBB_Significant',
            'Original_CI_Lower',
            'Original_CI_Upper',
            'Original_Significant'
        )
        self.tree = ttk.Treeview(frame_bottom, columns=columns, show='headings', height=15)

        col_names = {
            'Region': '地区',
            'Sen_Slope': 'Sen斜率 (中位数)',
            'MBB_CI_Lower': 'MBB 95% CI 下限',
            'MBB_CI_Upper': 'MBB 95% CI 上限',
            'MBB_Significant': 'MBB 是否显著',
            'Original_CI_Lower': '传统 CI 下限',
            'Original_CI_Upper': '传统 CI 上限',
            'Original_Significant': '传统 是否显著'
        }
        col_widths = [100, 120, 120, 120, 110, 120, 120, 110]

        for col, width in zip(columns, col_widths):
            self.tree.heading(col, text=col_names[col])
            self.tree.column(col, width=width, anchor="center")

        sb = ttk.Scrollbar(frame_bottom, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    def load_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not file_path:
            return
        try:
            self.df = pd.read_excel(file_path, index_col=0)
            self.df = self.df.dropna(how='all')

            self.lbl_file.config(text=file_path.split('/')[-1], fg="black")
            self.btn_calc.config(state=tk.NORMAL)
            messagebox.showinfo("成功", f"已加载数据。共有 {len(self.df)} 个地区。\n请点击计算。")
        except Exception as e:
            messagebox.showerror("读取错误", f"无法读取文件:\n{e}")

    def run_mbb(self):
        try:
            block_size = int(self.entry_block.get())
            n_boot = int(self.entry_boot.get())
        except ValueError:
            messagebox.showerror("参数错误", "块长和重采样次数必须是整数！")
            return

        if self.df is None:
            return

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)

        results = []

        # 禁用按钮防止重复点击
        self.btn_calc.config(state=tk.DISABLED)
        self.root.config(cursor="watch")

        x_coords = np.arange(len(self.df.columns))
        total_regions = len(self.df)

        # 设置进度条
        self.progress['maximum'] = total_regions
        self.progress['value'] = 0

        # 预先定义随机数生成器以加速
        rng = np.random.default_rng()

        for idx, region in enumerate(self.df.index):
            y = self.df.loc[region].values.astype(float)
            mask = np.isfinite(y)
            y_clean = y[mask]
            x_clean = x_coords[mask]
            n = len(y_clean)

            if n < max(5, block_size * 2):
                continue

            # 1. 计算原始 Sen 斜率（作为点估计）
            res = stats.theilslopes(y_clean, x_clean, alpha=0.95)
            sen_slope_orig = res[0]
            orig_ci_low, orig_ci_high = res[2], res[3]

            # 2. MBB 重采样
            slopes = []
            num_blocks = int(np.ceil(n / block_size))

            for _ in range(n_boot):
                # 随机抽取块起始点
                starts = rng.integers(0, n - block_size + 1, size=num_blocks)
                # 拼凑新序列
                boot_y = np.concatenate([y_clean[s: s + block_size] for s in starts])[:n]

                try:
                    boot_slope = stats.theilslopes(boot_y, x_clean)[0]
                    slopes.append(boot_slope)
                except (ValueError, RuntimeWarning):
                    continue

            # 3. 中心化 MBB 置信区间（修正原始 percentile 区间偏宽问题）
            if len(slopes) > 0:
                slopes_arr = np.array(slopes)
                boot_mean = np.mean(slopes_arr)
                # 中心化：boot_slope - bootstrap均值，再加上原始 Sen 点估计
                centered = slopes_arr - boot_mean + sen_slope_orig

                mbb_ci_low = np.percentile(centered, 2.5)
                mbb_ci_high = np.percentile(centered, 97.5)
            else:
                mbb_ci_low, mbb_ci_high = np.nan, np.nan

            # 显著性判定：CI 不包含 0 即为显著
            mbb_sig = "显著" if (mbb_ci_low > 0 or mbb_ci_high < 0) else "不显著"
            orig_sig = "显著" if (orig_ci_low > 0 or orig_ci_high < 0) else "不显著"

            # 4. 保存结果
            results.append({
                '地区': region,
                'Sen斜率': sen_slope_orig,
                'MBB CI下限': mbb_ci_low,
                'MBB CI上限': mbb_ci_high,
                'MBB显著性': mbb_sig,
                '传统 CI下限': orig_ci_low,
                '传统 CI上限': orig_ci_high,
                '传统显著性': orig_sig
            })

            # 显示在界面
            self.tree.insert("", "end", values=(
                region, f"{sen_slope_orig:.4f}",
                f"{mbb_ci_low:.4f}", f"{mbb_ci_high:.4f}",
                mbb_sig,
                f"{orig_ci_low:.4f}", f"{orig_ci_high:.4f}",
                orig_sig
            ))

            # 更新进度条
            self.progress['value'] = idx + 1
            if idx % 10 == 0:
                self.root.update()

        self.result_df = pd.DataFrame(results)
        self.btn_export.config(state=tk.NORMAL)
        self.btn_calc.config(state=tk.NORMAL)
        self.root.config(cursor="")
        self.progress['value'] = 0
        messagebox.showinfo("完成", "MBB 计算完成！对比 MBB 和传统 CI 的显著性。")

    def export_excel(self):
        if self.result_df is None or self.result_df.empty:
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile="MBB_Sen斜率置信区间_2000次.xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="选择保存位置"
        )

        if save_path:
            try:
                self.result_df.to_excel(save_path, index=False)
                messagebox.showinfo("成功", f"结果已成功导出至:\n{save_path}")
            except Exception as e:
                messagebox.showerror("导出错误", f"保存文件时出错:\n{e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = MBBToolApp(root)
    root.mainloop()