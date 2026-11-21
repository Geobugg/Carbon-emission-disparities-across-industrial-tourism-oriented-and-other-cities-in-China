import pandas as pd
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import font_manager

# 设置matplotlib使用中文字体
try:
    # 尝试使用系统自带的中文字体
    font_list = [f.name for f in font_manager.fontManager.ttflist]
    chinese_fonts = ['Times New Roman','SimHei','SimHei', 'Microsoft YaHei', 'SimSun', 'FangSong', 'KaiTi', 'STSong', 'STKaiti']

    available_font = None
    for font in chinese_fonts:
        if font in font_list:
            available_font = font
            break

    if available_font:
        plt.rcParams['font.sans-serif'] = [available_font]
        plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
    else:
        # 如果没有找到中文字体，尝试使用默认字体
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
except:
    # 如果出现错误，使用默认字体
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans']


# 分类函数 - 二分位法（中位数）
def classify_cities_median(df, industrial_col, tourism_col):
    """
    使用二分位法（中位数）对城市进行分类

    参数:
    df: 包含数据的DataFrame
    industrial_col: 工业GDP占比列名
    tourism_col: 旅游收入占比列名

    返回:
    添加了分类结果的DataFrame和中位数阈值
    """
    # 计算中位数
    industrial_median = df[industrial_col].median()
    tourism_median = df[tourism_col].median()

    # 分类函数
    def classify_city(industrial_val, tourism_val):
        if industrial_val > industrial_median and tourism_val < tourism_median:
            return "Industrial cities"
        elif industrial_val < industrial_median and tourism_val > tourism_median:
            return "Tourism-oriented cities"
        else:
            return "Other types of cities"

    # 应用分类
    df['Classification'] = df.apply(
        lambda row: classify_city(row[industrial_col], row[tourism_col]),
        axis=1
    )

    # 返回结果和阈值
    thresholds = {
        'industrial_median': industrial_median,
        'tourism_median': tourism_median
    }

    return df, thresholds


# 创建可视化图表
def create_scatter_plot(df, industrial_col, tourism_col, thresholds):
    """
    创建散点图可视化分类结果

    参数:
    df: 包含数据的DataFrame
    industrial_col: 工业GDP占比列名
    tourism_col: 旅游收入占比列名
    thresholds: 中位数阈值字典

    返回:
    matplotlib图对象
    """
    fig, ax = plt.subplots(figsize=(10, 6))

    # 为不同类别设置颜色
    colors = {
        'Industrial cities': 'red',
        'Tourism-oriented cities': 'blue',
        'Other types of cities': 'gray'
    }

    # 绘制散点图
    for category in df['Classification'].unique():
        subset = df[df['Classification'] == category]
        ax.scatter(
            subset[industrial_col],
            subset[tourism_col],
            c=colors[category],
            label=category,
            alpha=0.6,
            s=50  # 点的大小
        )

    # 添加中位数参考线
    ax.axvline(x=thresholds['industrial_median'], color='green', linestyle='-', alpha=0.7, label='Industry Median')
    ax.axhline(y=thresholds['tourism_median'], color='purple', linestyle='-', alpha=0.7, label='Tourism Median')

    # 设置图表属性
    ax.set_xlabel('Industrial GDP as Percentage of Total GDP (%)')
    ax.set_ylabel('Tourism GDP as Percentage of Total GDP (%)')
    ax.set_title('Urban Classification Results - Median Method')
    ax.legend()
    ax.grid(True, alpha=0.3)

    return fig


class CityClassifierApp:
    def __init__(self, root):
        """
        初始化城市分类应用程序

        参数:
        root: Tkinter根窗口
        """
        self.root = root
        self.root.title("Urban Classification Tool - Median Method")
        self.root.geometry("1000x800")  # 设置窗口大小

        # 初始化变量
        self.df = None  # 存储数据的DataFrame
        self.fig = None  # 存储matplotlib图形对象
        self.canvas = None  # 存储matplotlib画布对象
        self.industrial_col = None  # 工业GDP占比列名
        self.tourism_col = None  # 旅游收入占比列名
        self.column_names = []  # 存储数据文件的列名列表

        # 创建主框架 - 包含所有UI元素
        main_frame = ttk.Frame(root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置行列权重 - 使界面元素可以随窗口调整大小
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(8, weight=1)

        # 标题标签
        title_label = ttk.Label(main_frame, text="Urban Classification Tool - Median Method",
                                font=("Helvetica", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=10)

        # 分隔线
        separator = ttk.Separator(main_frame, orient='horizontal')
        separator.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # 文件选择部分
        # 输入文件标签
        ttk.Label(main_frame, text="Select input file:").grid(row=2, column=0, sticky=tk.W, pady=5)
        # 输入文件路径变量
        self.input_file = tk.StringVar()
        # 输入文件路径输入框
        ttk.Entry(main_frame, textvariable=self.input_file, width=50).grid(row=2, column=1, sticky=(tk.W, tk.E), padx=5)
        # 浏览按钮
        ttk.Button(main_frame, text="Browse", command=self.browse_input_file).grid(row=2, column=2, padx=5)

        # 输出文件夹选择部分
        ttk.Label(main_frame, text="Select output folder:").grid(row=3, column=0, sticky=tk.W, pady=5)
        # 输出文件夹路径变量
        self.output_folder = tk.StringVar()
        # 输出文件夹路径输入框
        ttk.Entry(main_frame, textvariable=self.output_folder, width=50).grid(row=3, column=1, sticky=(tk.W, tk.E),
                                                                              padx=5)
        # 浏览按钮
        ttk.Button(main_frame, text="Browse", command=self.browse_output_folder).grid(row=3, column=2, padx=5)

        # 列选择部分
        # 工业GDP列选择标签
        ttk.Label(main_frame, text="Select industrial GDP column:").grid(row=4, column=0, sticky=tk.W, pady=5)
        # 工业GDP列选择变量
        self.industrial_var = tk.StringVar()
        # 工业GDP列选择下拉框
        self.industrial_combo = ttk.Combobox(main_frame, textvariable=self.industrial_var, width=47, state="readonly")
        self.industrial_combo.grid(row=4, column=1, sticky=(tk.W, tk.E), padx=5)

        # 旅游收入列选择标签
        ttk.Label(main_frame, text="Select tourism revenue column:").grid(row=5, column=0, sticky=tk.W, pady=5)
        # 旅游收入列选择变量
        self.tourism_var = tk.StringVar()
        # 旅游收入列选择下拉框
        self.tourism_combo = ttk.Combobox(main_frame, textvariable=self.tourism_var, width=47, state="readonly")
        self.tourism_combo.grid(row=5, column=1, sticky=(tk.W, tk.E), padx=5)

        # 分隔线
        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)

        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=3, pady=10)
        # 分类按钮
        ttk.Button(button_frame, text="Classify Cities", command=self.classify_cities).pack(side=tk.LEFT, padx=5)
        # 保存图表按钮 - 修正了这里的拼写错误
        ttk.Button(button_frame, text="Save Chart as TIFF", command=self.save_chart).pack(side=tk.LEFT, padx=5)
        # 退出按钮
        ttk.Button(button_frame, text="Exit", command=root.quit).pack(side=tk.LEFT, padx=5)

        # 输出信息区域
        ttk.Label(main_frame, text="Output Information:").grid(row=8, column=0, sticky=tk.W, pady=5)
        # 输出信息文本框
        self.output_text = tk.Text(main_frame, height=12, width=80)
        self.output_text.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # 添加滚动条到输出文本区域
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        scrollbar.grid(row=9, column=3, sticky=(tk.N, tk.S))
        self.output_text.configure(yscrollcommand=scrollbar.set)

        # 图表区域
        ttk.Label(main_frame, text="Visualization Chart:").grid(row=10, column=0, sticky=tk.W, pady=5)
        # 图表容器框架
        self.canvas_frame = ttk.Frame(main_frame)
        self.canvas_frame.grid(row=11, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)

        # 配置权重使图表区域可以扩展
        main_frame.rowconfigure(11, weight=1)
        main_frame.columnconfigure(1, weight=1)

    def browse_input_file(self):
        """打开文件对话框选择输入文件"""
        filename = filedialog.askopenfilename(
            title="Select input file",
            filetypes=(("Excel files", "*.xlsx"), ("All files", "*.*"))
        )
        if filename:
            self.input_file.set(filename)  # 设置文件路径到输入框
            self.load_file_columns()  # 加载文件的列名

    def browse_output_folder(self):
        """打开文件夹对话框选择输出文件夹"""
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_folder.set(folder)  # 设置文件夹路径到输入框

    def load_file_columns(self):
        """加载文件的列名到下拉菜单"""
        try:
            # 读取Excel文件的第一行获取列名（不读取全部数据以提高效率）
            self.df = pd.read_excel(self.input_file.get(), nrows=1)
            self.column_names = self.df.columns.tolist()  # 获取列名列表

            # 更新下拉菜单的值
            self.industrial_combo['values'] = self.column_names
            self.tourism_combo['values'] = self.column_names

            # 尝试自动选择最后两列（如果存在）
            if len(self.column_names) >= 2:
                self.industrial_var.set(self.column_names[-2])  # 设置工业GDP列为倒数第二列
                self.tourism_var.set(self.column_names[-1])  # 设置旅游收入列为最后一列

            # 清空输出文本并显示加载信息
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, f"Loaded file with {len(self.column_names)} columns.\n")

        except Exception as e:
            # 显示错误信息
            messagebox.showerror("Error", f"Failed to read file: {str(e)}")

    def classify_cities(self):
        """执行城市分类的主要函数"""
        # 验证输入
        if not self.input_file.get():
            messagebox.showerror("Error", "Please select an input file!")
            return

        if not self.output_folder.get():
            messagebox.showerror("Error", "Please select an output folder!")
            return

        if not self.industrial_var.get() or not self.tourism_var.get():
            messagebox.showerror("Error", "Please select both industrial and tourism columns!")
            return

        try:
            # 清空输出文本并显示处理状态
            self.output_text.delete(1.0, tk.END)
            self.output_text.insert(tk.END, "Reading file...\n")
            self.root.update()  # 更新界面以显示状态

            # 读取完整的Excel文件
            self.df = pd.read_excel(self.input_file.get())

            # 获取用户选择的列名
            self.industrial_col = self.industrial_var.get()
            self.tourism_col = self.tourism_var.get()

            # 显示使用的列名
            self.output_text.insert(tk.END, f"Using columns: {self.industrial_col} and {self.tourism_col}\n")

            # 执行分类（二分位法）
            self.df, thresholds = classify_cities_median(self.df, self.industrial_col, self.tourism_col)

            # 显示中位数阈值
            self.output_text.insert(tk.END, "Median thresholds:\n")
            self.output_text.insert(tk.END,
                                    f"Industrial GDP Median: {thresholds['industrial_median']:.2f}%\n")
            self.output_text.insert(tk.END,
                                    f"Tourism revenue Median: {thresholds['tourism_median']:.2f}%\n")

            # 统计各类别数量
            class_counts = self.df['Classification'].value_counts()
            self.output_text.insert(tk.END, "Classification completed!\n")
            self.output_text.insert(tk.END, "Classification results:\n")

            # 显示每个类别的城市数量
            for category, count in class_counts.items():
                self.output_text.insert(tk.END, f"{category}: {count} cities\n")

            # 生成输出文件名（包含时间戳以避免覆盖）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f'City_Classification_Results_{timestamp}.xlsx'
            output_path = os.path.join(self.output_folder.get(), output_filename)

            # 保存结果到Excel文件
            self.df.to_excel(output_path, index=False)
            self.output_text.insert(tk.END, f"Results saved to: {output_path}\n")

            # 显示各类别的部分城市示例
            self.output_text.insert(tk.END, "\nCity examples for each category:\n")
            # 确定城市名称列（优先使用"地区名称"，否则使用第一列）
            city_name_col = '地区名称' if '地区名称' in self.df.columns else self.df.columns[0]

            # 显示每个类别的前3个城市示例
            for category in self.df['Classification'].unique():
                examples = self.df[self.df['Classification'] == category][city_name_col].head(3).tolist()
                self.output_text.insert(tk.END, f"{category}: {', '.join(examples)}\n")

            # 创建可视化图表
            self.create_visualization(self.industrial_col, self.tourism_col, thresholds)

        except Exception as e:
            # 显示错误信息
            messagebox.showerror("Error", f"Error processing file: {str(e)}")

    def create_visualization(self, industrial_col, tourism_col, thresholds):
        """创建并显示可视化图表"""
        # 清除之前的图表
        for widget in self.canvas_frame.winfo_children():
            widget.destroy()

        # 创建新图表
        self.fig = create_scatter_plot(self.df, industrial_col, tourism_col, thresholds)

        # 将图表嵌入到GUI中
        self.canvas = FigureCanvasTkAgg(self.fig, self.canvas_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def save_chart(self):
        """保存图表为300dpi的TIFF格式"""
        # 检查是否有图表可保存
        if self.fig is None:
            messagebox.showerror("Error", "No chart to save. Please run classification first.")
            return

        # 检查是否选择了输出文件夹
        if not self.output_folder.get():
            messagebox.showerror("Error", "Please select an output folder first.")
            return

        try:
            # 生成输出文件名（包含时间戳）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f'Classification_Chart_{timestamp}.tiff'
            output_path = os.path.join(self.output_folder.get(), output_filename)

            # 保存为300dpi的TIFF格式
            self.fig.savefig(
                output_path,
                dpi=300,  # 设置分辨率为300dpi
                format='tiff',  # 设置格式为TIFF
                bbox_inches='tight'  # 紧凑边界框，去除多余空白
            )
            # 显示保存成功信息
            self.output_text.insert(tk.END, f"Chart saved as TIFF: {output_path}\n")

        except Exception as e:
            # 显示保存错误信息
            messagebox.showerror("Error", f"Failed to save chart: {str(e)}")


# 主程序入口
if __name__ == "__main__":
    # 创建Tkinter根窗口
    root = tk.Tk()
    # 创建应用程序实例
    app = CityClassifierApp(root)
    # 启动GUI事件循环
    root.mainloop()