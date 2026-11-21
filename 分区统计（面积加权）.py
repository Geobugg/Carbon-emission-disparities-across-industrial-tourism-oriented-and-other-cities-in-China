# -*- coding: utf-8 -*-
"""
面积加权分区统计工具（GUI，输出 SHP / CSV）
字段名规则：以栅格文件名为基础生成，SHP 上限 10 字符自动截断。

依赖：
    conda install -c conda-forge exactextract geopandas rasterio pandas pyogrio
"""

# --- 显式声明 GDAL 错误处理，消除 FutureWarning ---
try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:
    pass

import os
import re
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import geopandas as gpd
    import pandas as pd
    import rasterio
    from exactextract import exact_extract
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        f"缺少依赖：{e}\n"
        "请先安装：conda install -c conda-forge exactextract geopandas rasterio pandas"
    )


# ----------------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------------
VECTOR_TYPES = [
    ("矢量文件", "*.shp *.gpkg *.geojson *.json *.kml"),
    ("所有文件", "*.*"),
]
RASTER_TYPES = [
    ("栅格文件", "*.tif *.tiff *.img *.vrt *.nc *.asc"),
    ("所有文件", "*.*"),
]
STAT_CHOICES = [
    "mean", "sum", "min", "max", "stdev",
    "count", "median", "variance", "minority", "majority",
]
DEFAULT_STATS = ["mean", "sum", "count", "min", "max", "stdev"]

# 统计量短缩写（保证 "<栅格名>_<缩写>" 尽量不超 10 字符）
STAT_ABBR = {
    "mean": "mean", "sum": "sum", "min": "min", "max": "max",
    "stdev": "sd", "count": "cnt", "median": "med",
    "variance": "var", "minority": "mino", "majority": "majo",
}

SHP_MAX_FIELDS = 255
SHP_MAX_NAME_LEN = 10


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def _safe_field(name, used_lower, max_len=SHP_MAX_NAME_LEN):
    """
    把任意字符串转为合法、不重复的 SHP 字段名：
    - 仅保留 ASCII 字母数字下划线
    - 不以数字开头
    - 不超过 max_len 字符
    - 大小写不敏感地保证唯一（SHP 的 dbf 字段名大小写等价）
    """
    base = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
    if not base:
        base = "f"
    if base[0].isdigit():
        base = "f_" + base
    base = base[:max_len]
    candidate = base
    i = 1
    while candidate.lower() in used_lower:
        suffix = f"_{i}"
        candidate = base[: max_len - len(suffix)] + suffix
        i += 1
    used_lower.add(candidate.lower())
    return candidate


def _stem_to_field_base(stem: str) -> str:
    """把栅格文件主干转为字段名基础（尚未唯一化、尚未加统计量后缀）。"""
    base = re.sub(r"[^0-9A-Za-z_]", "_", stem).strip("_")
    if not base:
        base = "raster"
    if base[0].isdigit():
        base = "f_" + base
    return base


def _plan_field_names(stems, stats, existing_lower=None, max_len=SHP_MAX_NAME_LEN):
    """
    以栅格文件名为基础，为每个栅格的每个统计量规划字段名。

    规则：
    - 单个统计量：字段名 = 栅格文件名（超长截断到 max_len）
    - 多个统计量：字段名 = 栅格名截断 + "_" + 统计量缩写
    - 全程大小写不敏感地避免与 existing_lower 及先前规划的字段名冲突

    返回 (plan, used_lower)：
        plan: {stem: {stat: field_name}}
        used_lower: 规划完成后所有已占用的字段名（小写）
    """
    used = set(existing_lower) if existing_lower else set()
    n_stats = len(stats)
    plan = {}
    for stem in stems:
        base = _stem_to_field_base(stem)
        per_stat = {}
        for s in stats:
            if n_stats == 1:
                desired = base
            else:
                abbr = STAT_ABBR.get(s, s)
                suffix = "_" + abbr
                max_base = max(1, max_len - len(suffix))
                desired = base[:max_base] + suffix
            per_stat[s] = _safe_field(desired, used, max_len=max_len)
        plan[stem] = per_stat
    return plan, used


def _unique_stems(paths):
    """不同目录同名栅格自动加 _1、_2 后缀，避免输出覆盖。"""
    used = {}
    stems = []
    for p in paths:
        stem = os.path.splitext(os.path.basename(p))[0]
        if stem in used:
            used[stem] += 1
            stem = f"{stem}_{used[stem]}"
        else:
            used[stem] = 0
        stems.append(stem)
    return stems


def _prepare_output_gdf(zones_gdf: gpd.GeoDataFrame):
    """
    复制分区矢量，并把所有非几何字段重命名为 SHP 安全名。
    返回 (新 GeoDataFrame, {原字段: 安全字段} 映射)。
    """
    gdf = zones_gdf.copy()
    geom_name = gdf.geometry.name

    for col in list(gdf.columns):
        if col == geom_name:
            continue
        if pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].astype(str)

    rename = {}
    used = set()
    for col in list(gdf.columns):
        if col == geom_name:
            continue
        safe = _safe_field(col, used)
        if safe != col:
            rename[col] = safe

    if rename:
        gdf = gdf.rename(columns=rename)
    return gdf, rename


# ----------------------------------------------------------------------------
# 主应用
# ----------------------------------------------------------------------------
class ZonalStatsApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("面积加权分区统计工具 (exactextract)")
        self.root.geometry("880x880")
        self.root.minsize(800, 760)

        self.zones_gdf: gpd.GeoDataFrame | None = None
        self.running = False
        self.msg_queue: "queue.Queue[tuple]" = queue.Queue()

        self.zones_path = tk.StringVar()
        self.zone_id_var = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.merge_var = tk.BooleanVar(value=True)
        self.output_format = tk.StringVar(value="shp")
        self.stat_vars = {s: tk.BooleanVar(value=(s in DEFAULT_STATS)) for s in STAT_CHOICES}

        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}

        # -------- 1. 矢量 --------
        frm_data = ttk.LabelFrame(self.root, text="1. 矢量分区文件")
        frm_data.pack(fill="x", **pad)

        ttk.Label(frm_data, text="矢量文件：").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(frm_data, textvariable=self.zones_path).grid(
            row=0, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Button(frm_data, text="浏览…", command=self._browse_zones).grid(
            row=0, column=2, padx=6, pady=4
        )

        ttk.Label(frm_data, text="分区唯一标识列：").grid(
            row=1, column=0, sticky="w", padx=6, pady=4
        )
        self.zone_id_combo = ttk.Combobox(
            frm_data, textvariable=self.zone_id_var, state="readonly"
        )
        self.zone_id_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        frm_data.columnconfigure(1, weight=1)

        # -------- 2. 栅格 --------
        frm_raster = ttk.LabelFrame(self.root, text="2. 栅格数据（可批量添加）")
        frm_raster.pack(fill="both", expand=True, **pad)

        lb_frame = ttk.Frame(frm_raster)
        lb_frame.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        self.raster_list = tk.Listbox(lb_frame, selectmode="extended", height=8)
        self.raster_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.raster_list.yview)
        sb.pack(side="right", fill="y")
        self.raster_list.config(yscrollcommand=sb.set)

        btn_frame = ttk.Frame(frm_raster)
        btn_frame.pack(side="right", fill="y", padx=6, pady=4)
        ttk.Button(btn_frame, text="添加栅格…", command=self._add_rasters).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="移除选中", command=self._remove_selected).pack(fill="x", pady=2)
        ttk.Button(btn_frame, text="清空列表", command=self._clear_rasters).pack(fill="x", pady=2)

        # -------- 3. 选项 --------
        frm_opts = ttk.LabelFrame(self.root, text="3. 统计与输出选项")
        frm_opts.pack(fill="x", **pad)

        ttk.Label(frm_opts, text="统计量：").grid(row=0, column=0, sticky="nw", padx=6, pady=4)
        stat_frame = ttk.Frame(frm_opts)
        stat_frame.grid(row=0, column=1, columnspan=3, sticky="w", padx=6, pady=4)
        for idx, s in enumerate(STAT_CHOICES):
            ttk.Checkbutton(stat_frame, text=s, variable=self.stat_vars[s]).grid(
                row=idx // 5, column=idx % 5, sticky="w", padx=4, pady=2
            )

        ttk.Checkbutton(
            frm_opts,
            text="合并所有栅格结果为一个文件（按 zone_id 关联）",
            variable=self.merge_var,
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Label(frm_opts, text="输出格式：").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        fmt_frame = ttk.Frame(frm_opts)
        fmt_frame.grid(row=2, column=1, columnspan=3, sticky="w", padx=6, pady=4)
        for text, val in [("SHP", "shp"), ("CSV", "csv"), ("两者", "both")]:
            ttk.Radiobutton(
                fmt_frame, text=text, variable=self.output_format, value=val
            ).pack(side="left", padx=4)
        ttk.Label(
            fmt_frame,
            text="（字段名 = 栅格文件名；SHP 上限 10 字符自动截断，SHP 中字段名会自动大写）",
            foreground="#666",
        ).pack(side="left", padx=8)

        ttk.Label(frm_opts, text="输出目录：").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(frm_opts, textvariable=self.output_dir).grid(
            row=3, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Button(frm_opts, text="浏览…", command=self._browse_output).grid(
            row=3, column=2, padx=6, pady=4
        )
        frm_opts.columnconfigure(1, weight=1)

        # -------- 4. 执行 --------
        frm_run = ttk.LabelFrame(self.root, text="4. 执行")
        frm_run.pack(fill="both", expand=True, **pad)

        run_bar = ttk.Frame(frm_run)
        run_bar.pack(fill="x", padx=6, pady=4)
        self.run_btn = ttk.Button(run_bar, text="开始统计", command=self._start)
        self.run_btn.pack(side="left")
        ttk.Button(run_bar, text="预览字段名", command=self._preview_fields).pack(
            side="left", padx=6
        )
        self.progress = ttk.Progressbar(run_bar, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        log_frame = ttk.Frame(frm_run)
        log_frame.pack(fill="both", expand=True, padx=6, pady=4)
        self.log_text = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=log_sb.set)

    # ------------------------------------------------------------------
    # 文件选择
    # ------------------------------------------------------------------
    def _browse_zones(self):
        path = filedialog.askopenfilename(title="选择矢量分区文件", filetypes=VECTOR_TYPES)
        if not path:
            return
        self.zones_path.set(path)
        self._load_zones_async(path)

    def _load_zones_async(self, path: str):
        self.zone_id_combo["values"] = []
        self.zone_id_var.set("")
        self.zones_gdf = None
        self._log(f"正在读取矢量：{path}")
        threading.Thread(target=self._load_zones_worker, args=(path,), daemon=True).start()

    def _load_zones_worker(self, path: str):
        try:
            gdf = gpd.read_file(path)
            cols = list(gdf.columns)
            geom_name = gdf.geometry.name
            if geom_name in cols:
                cols.remove(geom_name)
            self.zones_gdf = gdf
            self.msg_queue.put(("zones_loaded", cols))
        except Exception as e:
            self.msg_queue.put(("error", f"读取矢量失败：{e}\n{traceback.format_exc()}"))

    def _add_rasters(self):
        paths = filedialog.askopenfilenames(title="选择栅格文件（可多选）", filetypes=RASTER_TYPES)
        existing = set(self.raster_list.get(0, "end"))
        for p in paths:
            if p not in existing:
                self.raster_list.insert("end", p)

    def _remove_selected(self):
        for idx in reversed(self.raster_list.curselection()):
            self.raster_list.delete(idx)

    def _clear_rasters(self):
        self.raster_list.delete(0, "end")

    def _browse_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    # ------------------------------------------------------------------
    # 字段名预览
    # ------------------------------------------------------------------
    def _preview_fields(self):
        raster_paths = list(self.raster_list.get(0, "end"))
        if not raster_paths:
            messagebox.showinfo("提示", "请先添加栅格文件。")
            return
        stats = [s for s, v in self.stat_vars.items() if v.get()]
        if not stats:
            messagebox.showinfo("提示", "请至少勾选一个统计量。")
            return

        stems = _unique_stems(raster_paths)
        base_used = set()
        if self.zones_gdf is not None:
            base_gdf, _ = _prepare_output_gdf(self.zones_gdf)
            base_used = {
                c.lower() for c in base_gdf.columns if c != base_gdf.geometry.name
            }

        merge = self.merge_var.get()
        lines = []
        if merge:
            plan, _ = _plan_field_names(stems, stats, base_used)
            for stem in stems:
                for s in stats:
                    lines.append(f"{stem}  ::  {s:>8}  ->  {plan[stem][s]}")
        else:
            for stem in stems:
                p, _ = _plan_field_names([stem], stats, base_used)
                for s in stats:
                    lines.append(f"{stem}  ::  {s:>8}  ->  {p[stem][s]}")

        text = (
            "字段名规划（SHP 字段名限 10 字符，超长会被截断；"
            "SHP 中字段名会被自动大写）：\n\n" + "\n".join(lines)
        )
        messagebox.showinfo("字段名预览", text)

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def _start(self):
        if self.running:
            return

        if self.zones_gdf is None:
            messagebox.showwarning("提示", "请先选择并等待矢量分区文件加载完成。")
            return
        raster_paths = list(self.raster_list.get(0, "end"))
        if not raster_paths:
            messagebox.showwarning("提示", "请至少添加一个栅格文件。")
            return
        zone_id = self.zone_id_var.get().strip()
        if not zone_id:
            messagebox.showwarning("提示", "请选择分区唯一标识列。")
            return
        if zone_id not in self.zones_gdf.columns:
            messagebox.showerror("错误", f"矢量中不存在列：{zone_id}")
            return
        out_dir = self.output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning("提示", "请选择输出目录。")
            return
        stats = [s for s, v in self.stat_vars.items() if v.get()]
        if not stats:
            messagebox.showwarning("提示", "请至少勾选一个统计量。")
            return

        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法创建输出目录：{e}")
            return

        self.running = True
        self.run_btn.config(state="disabled")
        self.progress["maximum"] = len(raster_paths)
        self.progress["value"] = 0
        self._clear_log()
        self._log(f"分区数：{len(self.zones_gdf)}，栅格数：{len(raster_paths)}")
        self._log(f"统计量：{', '.join(stats)}")
        self._log(f"输出格式：{self.output_format.get()}，合并：{self.merge_var.get()}")

        threading.Thread(
            target=self._worker,
            args=(
                self.zones_gdf.copy(),
                zone_id,
                raster_paths,
                stats,
                out_dir,
                self.merge_var.get(),
                self.output_format.get(),
            ),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # 工作线程
    # ------------------------------------------------------------------
    def _worker(self, zones_gdf, zone_id, raster_paths, stats, out_dir, merge, fmt):
        try:
            want_csv = fmt in ("csv", "both")
            want_shp = fmt in ("shp", "both")

            base_gdf, base_rename = _prepare_output_gdf(zones_gdf)
            zone_id_safe = base_rename.get(zone_id, zone_id)
            base_used = {
                c.lower() for c in base_gdf.columns if c != base_gdf.geometry.name
            }
            if base_rename:
                self.msg_queue.put(("log", f"分区矢量字段已安全化：{base_rename}"))

            stems = _unique_stems(raster_paths)

            # ---- 字段名规划 ----
            field_plan = {}
            if merge:
                plan, _ = _plan_field_names(stems, stats, base_used)
                field_plan = plan
            else:
                for stem in stems:
                    p, _ = _plan_field_names([stem], stats, base_used)
                    field_plan[stem] = p[stem]

            self.msg_queue.put(("log", "字段名规划（SHP 限 10 字符；SHP 中字段名会被自动大写）："))
            for stem in stems:
                for s in stats:
                    self.msg_queue.put(
                        ("log", f"   {stem} :: {s} -> {field_plan[stem][s]}")
                    )

            failed = []
            success = 0
            accum_gdf = base_gdf.copy()
            accum_mapping = []   # [(output_field, raster_name, stat), ...]
            accum_dfs = {}

            for i, (raster, stem) in enumerate(zip(raster_paths, stems), 1):
                self.msg_queue.put(
                    ("log", f"[{i}/{len(raster_paths)}] 处理：{os.path.basename(raster)}")
                )
                try:
                    with rasterio.open(raster) as src:
                        raster_crs = src.crs

                    gdf_proj = zones_gdf
                    if (
                        raster_crs is not None
                        and gdf_proj.crs is not None
                        and gdf_proj.crs != raster_crs
                    ):
                        gdf_proj = gdf_proj.to_crs(raster_crs)
                    elif raster_crs is not None and gdf_proj.crs is None:
                        self.msg_queue.put(
                            ("log", "   警告：矢量缺少 CRS，将按原始坐标处理。")
                        )

                    df = exact_extract(
                        raster, gdf_proj, stats,
                        include_cols=[zone_id],
                        output="pandas",
                    )
                    if len(df) != len(zones_gdf):
                        raise RuntimeError(
                            f"exact_extract 返回行数 {len(df)} 与分区数 {len(zones_gdf)} 不一致"
                        )

                    # 用规划好的字段名组装统计列
                    stat_cols = {}
                    mapping_rows = []
                    for s in stats:
                        fname = field_plan[stem][s]
                        stat_cols[fname] = df[s].values
                        mapping_rows.append(
                            (fname, os.path.basename(raster), s)
                        )
                    stat_df = pd.DataFrame(stat_cols)

                    # ---- CSV 输出 ----
                    if want_csv:
                        csv_df = pd.concat(
                            [
                                base_gdf[[zone_id_safe]].reset_index(drop=True),
                                stat_df.reset_index(drop=True),
                            ],
                            axis=1,
                        )
                        csv_path = os.path.join(out_dir, f"{stem}_zonal_stats.csv")
                        csv_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
                        self.msg_queue.put(("log", f"   -> CSV：{csv_path}"))

                    # ---- SHP 输出 ----
                    if want_shp:
                        if merge:
                            for c in stat_df.columns:
                                accum_gdf[c] = stat_df[c].values
                            accum_mapping.extend(mapping_rows)
                        else:
                            out_gdf = base_gdf.copy()
                            for c in stat_df.columns:
                                out_gdf[c] = stat_df[c].values

                            n_fields = len(out_gdf.columns)
                            if n_fields > SHP_MAX_FIELDS:
                                self.msg_queue.put(
                                    ("log",
                                     f"   !! 字段数 {n_fields} 超过 {SHP_MAX_FIELDS}，SHP 写入可能失败")
                                )

                            shp_path = os.path.join(out_dir, f"{stem}_zonal_stats.shp")
                            out_gdf.to_file(
                                shp_path, driver="ESRI Shapefile", encoding="utf-8"
                            )
                            map_path = os.path.join(
                                out_dir, f"{stem}_zonal_stats_field_mapping.csv"
                            )
                            pd.DataFrame(
                                mapping_rows,
                                columns=["output_field", "raster", "stat"],
                            ).to_csv(map_path, index=False, encoding="utf-8-sig")
                            self.msg_queue.put(("log", f"   -> SHP：{shp_path}"))
                            self.msg_queue.put(("log", f"   -> 字段映射：{map_path}"))

                    if merge and want_csv:
                        accum_dfs[stem] = pd.concat(
                            [
                                base_gdf[[zone_id_safe]].reset_index(drop=True),
                                stat_df.reset_index(drop=True),
                            ],
                            axis=1,
                        )

                    success += 1

                except Exception as e:
                    failed.append((raster, str(e)))
                    self.msg_queue.put(("log", f"   !! 失败：{e}"))
                    self.msg_queue.put(("log", traceback.format_exc()))

                self.msg_queue.put(("progress", i))

            # ---- 合并输出 ----
            if merge:
                if want_shp and accum_mapping:
                    n_fields = len(accum_gdf.columns)
                    if n_fields > SHP_MAX_FIELDS:
                        self.msg_queue.put(
                            ("log",
                             f"   !! 合并字段数 {n_fields} 超过 {SHP_MAX_FIELDS}，SHP 写入可能失败")
                        )
                    combined_shp = os.path.join(out_dir, "2001-2024.shp")#修改输出文件名
                    accum_gdf.to_file(
                        combined_shp, driver="ESRI Shapefile", encoding="utf-8"
                    )
                    map_path = os.path.join(
                        out_dir, "zonal_stats_combined_field_mapping.csv"
                    )
                    pd.DataFrame(
                        accum_mapping,
                        columns=["output_field", "raster", "stat"],
                    ).to_csv(map_path, index=False, encoding="utf-8-sig")
                    self.msg_queue.put(("log", f"合并 SHP：{combined_shp}"))
                    self.msg_queue.put(("log", f"合并字段映射：{map_path}"))

                if want_csv and accum_dfs:
                    merged = None
                    for d in accum_dfs.values():
                        merged = d if merged is None else merged.merge(
                            d, on=zone_id_safe, how="outer"
                        )
                    combined_csv = os.path.join(out_dir, "zonal_stats_combined.csv")
                    merged.to_csv(combined_csv, index=False, encoding="utf-8-sig")
                    self.msg_queue.put(("log", f"合并 CSV：{combined_csv}"))

            summary = f"完成：成功 {success} 个，失败 {len(failed)} 个。"
            if failed:
                summary += "\n失败明细：\n" + "\n".join(
                    f"  - {os.path.basename(p)}: {e}" for p, e in failed
                )
            self.msg_queue.put(("done", summary))

        except Exception as e:
            self.msg_queue.put(("error", f"运行异常：{e}\n{traceback.format_exc()}"))

    # ------------------------------------------------------------------
    # 队列轮询
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()

                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "zones_loaded":
                    cols = payload
                    self.zone_id_combo["values"] = cols
                    if cols:
                        self.zone_id_var.set(cols[0])
                    self._log(f"矢量加载完成，可用属性列 {len(cols)} 个。")
                elif kind == "done":
                    self._log(payload)
                    self._finish_run()
                    messagebox.showinfo("完成", payload)
                elif kind == "error":
                    self._log(payload)
                    self._finish_run()
                    messagebox.showerror("错误", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _finish_run(self):
        self.running = False
        self.run_btn.config(state="normal")

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _log(self, text: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = ZonalStatsApp(root)
    root.mainloop()