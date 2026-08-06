import csv
import math
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from xml.etree import ElementTree as ET
from zipfile import ZipFile

try:
    import numpy as np
except ImportError:
    np = None

from stats_core import (
    EPS_REL, FLAG_LIMIT, diff_ratio, flag_result, max_abs_z, mean_of, robust_pre_scale,
    std_of, threshold_for, zscore,
)


APP_TITLE = "Pre/Post CDF Sigma Compare Tool"
ID_ITEM_NAMES = ("DEVICE_ID",)


def to_float(value):
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
        if not math.isfinite(number):
            return None
        return number
    except ValueError:
        return None


def mean(values):
    return mean_of(values)


def sample_std(values):
    # 판정용 sigma: 표본표준편차(ddof=1), Excel STDEV/JMP 와 일치. §S2.
    return std_of(values, ddof=1)


def normal_cdf(z_value):
    if z_value is None:
        return None
    if z_value == math.inf:
        return 1.0
    if z_value == -math.inf:
        return 0.0
    return 0.5 * (1.0 + math.erf(z_value / math.sqrt(2.0)))


def sigma(value, center, spread):
    return zscore([value], center, spread)[0]


def fmt(value):
    if value is None:
        return ""
    if value == math.inf:
        return "INF"
    if value == -math.inf:
        return "-INF"
    if isinstance(value, float) and math.isnan(value):
        return ""
    return format(value, ".6g")


def finite_values(values):
    return [value for value in values if value is not None and math.isfinite(value)]


def max_abs_sigma(values, center, spread):
    return max_abs_z(values, center, spread)


def paired_diff_values(pre_values, post_values, pre_scale=None):
    paired_count = min(len(pre_values), len(post_values))
    if paired_count <= 0:
        return []
    if np is not None:
        pre = np.asarray(pre_values[:paired_count], dtype=float)
        post = np.asarray(post_values[:paired_count], dtype=float)
        mask = np.isfinite(pre) & np.isfinite(post) & (pre != 0)
        if pre_scale is not None and pre_scale > 0:
            # §S4(범위 축소판): pre 가 절대 0 은 아니지만 항목 스케일 대비 0 에 가까우면
            # diff_ratio 가 폭발해 diff_sigma 를 부풀린다 — numpy 경로도 diff_ratio() 와
            # 동일한 상대 임계로 걸러야 두 경로 결과가 갈리지 않는다.
            mask &= np.abs(pre) >= (EPS_REL * pre_scale)
        return ((post[mask] - pre[mask]) / np.abs(pre[mask])).tolist()
    return finite_values(
        diff_ratio(pre_values[i], post_values[i], pre_scale=pre_scale) for i in range(paired_count)
    )


def natural_sort_key(value):
    text = cell_text(value)
    if not text:
        return (2, "")
    parts = []
    for part in text.replace("_", ".").split("."):
        number = to_float(part)
        parts.append(number if number is not None else part.lower())
    return (0, parts)


def cell_text(value):
    return "" if value is None else str(value).strip()


def norm(value):
    return cell_text(value).lower().replace(" ", "").replace("_", "").replace("-", "")


def column_name_to_index(cell_ref):
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters.upper():
        index = index * 26 + ord(ch) - ord("A") + 1
    return index - 1


def read_shared_strings(zf):
    names = zf.namelist()
    if "xl/sharedStrings.xml" not in names:
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for si in root.findall("x:si", ns):
        parts = [text.text or "" for text in si.findall(".//x:t", ns)]
        strings.append("".join(parts))
    return strings


def first_sheet_path(zf):
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    main_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    first_sheet = workbook.find("x:sheets/x:sheet", main_ns)
    if first_sheet is None:
        raise ValueError("XLSX file has no worksheet.")
    rel_id = first_sheet.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    for rel in rels.findall("r:Relationship", rel_ns):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib.get("Target", "").lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise ValueError("Cannot find worksheet relationship in XLSX file.")


def read_xlsx(path):
    with ZipFile(path) as zf:
        shared_strings = read_shared_strings(zf)
        sheet_xml = zf.read(first_sheet_path(zf))
    root = ET.fromstring(sheet_xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    table = []
    for row in root.findall(".//x:sheetData/x:row", ns):
        values = []
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            col_index = column_name_to_index(ref)
            while len(values) <= col_index:
                values.append("")
            cell_type = cell.attrib.get("t", "")
            if cell_type == "inlineStr":
                text_node = cell.find(".//x:t", ns)
                value = "" if text_node is None else text_node.text or ""
            else:
                node = cell.find("x:v", ns)
                raw = "" if node is None else node.text or ""
                if cell_type == "s" and raw:
                    value = shared_strings[int(raw)]
                else:
                    value = raw
            values[col_index] = value
        table.append(values)
    return table


def read_csv(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(path, newline="", encoding=encoding) as fh:
                return [row for row in csv.reader(fh)]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def read_table(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return read_xlsx(path)
    if ext == ".csv":
        return read_csv(path)
    raise ValueError("Only .xlsx and .csv files are supported.")


def find_row_with_label(table, labels):
    targets = {norm(label) for label in labels}
    for row_index, row in enumerate(table):
        if any(norm(cell) in targets for cell in row):
            return row_index
    return None


def nonempty_count(row):
    return sum(1 for value in row if cell_text(value))


def find_test_item_name_row(table, data_header_index):
    best_index = None
    best_count = 0
    for row_index in range(data_header_index):
        row = table[row_index]
        if not row or norm(row[0]) != "testname":
            continue
        count = nonempty_count(row)
        if count > best_count:
            best_index = row_index
            best_count = count
    return best_index


def find_metadata_row_before_data(table, data_header_index, label):
    target = norm(label)
    for row_index in range(data_header_index - 1, -1, -1):
        row = table[row_index]
        if row and norm(row[0]) == target:
            return row_index
    return None


def find_col_with_label(row, labels):
    targets = {norm(label) for label in labels}
    for col, value in enumerate(row):
        if norm(value) in targets:
            return col
    return None


def row_value_at(row, index):
    return row[index] if index < len(row) else ""


def is_bin_one(value):
    text = cell_text(value)
    number = to_float(text)
    if number is not None:
        return number == 1
    return text == "1"


def filter_records_by_bin_one(records):
    filtered = {}
    for item, item_records in records.items():
        if not item_records or "bin" not in item_records[0]:
            if item_records:
                filtered[item] = item_records
            continue
        bin_records = [record for record in item_records if is_bin_one(record.get("bin"))]
        if bin_records:
            filtered[item] = bin_records
    return filtered


def filter_records_to_last_sample(records):
    filtered = {}
    for item, item_records in records.items():
        by_sample = {}
        for record in item_records:
            by_sample[record["sample"]] = record
        filtered[item] = list(by_sample.values())
    return filtered


def numeric_count(table, start_row, col):
    count = 0
    for row in table[start_row:]:
        if to_float(row_value_at(row, col)) is not None:
            count += 1
    return count


def extract_items(table):
    records = extract_item_records(table)
    items = {}
    for item, item_records in records.items():
        items[item] = [record["value"] for record in item_records]
    return items


def extract_item_records(table):
    if not table:
        raise ValueError("Data file is empty.")

    data_header_index = find_row_with_label(table, ("site #", "site", "serial #", "serial"))
    test_name_index = None
    if data_header_index is not None:
        test_name_index = find_test_item_name_row(table, data_header_index)

    if data_header_index is not None and test_name_index is not None:
        return extract_item_records_from_meta_table(table, test_name_index, data_header_index)

    return extract_item_records_from_legacy_table(table)


def extract_item_records_from_meta_table(table, test_name_index, data_header_index):
    name_row = table[test_name_index]
    header_row = table[data_header_index]
    test_number_row_index = find_metadata_row_before_data(table, data_header_index, "Test Number")
    unit_row_index = find_metadata_row_before_data(table, data_header_index, "Unit")
    if unit_row_index is None:
        unit_row_index = find_metadata_row_before_data(table, data_header_index, "Units")
    lower_row_index = find_metadata_row_before_data(table, data_header_index, "Lower Limit")
    upper_row_index = find_metadata_row_before_data(table, data_header_index, "Upper Limit")
    test_number_row = table[test_number_row_index] if test_number_row_index is not None else []
    unit_row = table[unit_row_index] if unit_row_index is not None else []
    lower_row = table[lower_row_index] if lower_row_index is not None else []
    upper_row = table[upper_row_index] if upper_row_index is not None else []
    data_start = data_header_index + 1
    serial_col = find_col_with_label(header_row, ("Serial #", "Serial", "Sample", "Sample No."))
    if serial_col is None:
        serial_col = 0
    bin_col = find_col_with_label(header_row, ("Bin",))
    site_col = find_col_with_label(header_row, ("Site #", "Site"))

    metadata_cols = {
        col
        for col, value in enumerate(header_row)
        if norm(value) in {"site#", "site", "serial#", "serial", "bin", "xcoord", "ycoord", "sample", "sampleno"}
    }
    first_item_col = max(metadata_cols) + 1 if metadata_cols else 0

    device_id_col = find_col_with_label(name_row, ID_ITEM_NAMES)
    device_id_by_row = {}
    if device_id_col is not None:
        for row_index, row in enumerate(table[data_start:], start=1):
            device_id_by_row[row_index] = cell_text(row_value_at(row, device_id_col))

    records = {}
    max_cols = max(len(row) for row in table)
    for col in range(first_item_col, max_cols):
        if col == device_id_col:
            continue
        item_name = cell_text(row_value_at(name_row, col))
        if not item_name:
            item_name = cell_text(row_value_at(header_row, col))
        if not item_name or numeric_count(table, data_start, col) == 0:
            continue
        lower_limit = to_float(row_value_at(lower_row, col))
        upper_limit = to_float(row_value_at(upper_row, col))
        records[item_name] = []
        for row_index, row in enumerate(table[data_start:], start=1):
            value = to_float(row_value_at(row, col))
            if value is None:
                continue
            sample = cell_text(row_value_at(row, serial_col)) or str(row_index)
            record = {"sample": sample, "value": value, "device_id": device_id_by_row.get(row_index, "")}
            test_number = cell_text(row_value_at(test_number_row, col))
            if test_number:
                record["test_number"] = test_number
            unit = cell_text(row_value_at(unit_row, col))
            if unit:
                record["unit"] = unit
            if lower_limit is not None:
                record["lower_limit"] = lower_limit
            if upper_limit is not None:
                record["upper_limit"] = upper_limit
            if bin_col is not None:
                record["bin"] = cell_text(row_value_at(row, bin_col))
            if site_col is not None:
                record["site"] = cell_text(row_value_at(row, site_col))
            records[item_name].append(record)

    if not records:
        raise ValueError("No numeric Test Item columns were found.")
    return records


def extract_item_records_from_legacy_table(table):
    if len(table) < 3:
        raise ValueError("Data needs at least 3 rows: item header, sample header, and values.")

    header = table[0]
    max_cols = max(len(row) for row in table)
    sample_col = find_col_with_label(table[1], ("Sample", "Sample No.", "Serial #", "Serial"))
    if sample_col is None:
        sample_col = 0

    records = {}
    for col in range(max_cols):
        item_name = cell_text(row_value_at(header, col))
        if not item_name or col == sample_col:
            continue
        if numeric_count(table, 2, col) == 0:
            continue
        records[item_name] = []
        for row_index, row in enumerate(table[2:], start=1):
            value = to_float(row_value_at(row, col))
            if value is None:
                continue
            sample = cell_text(row_value_at(row, sample_col)) or str(row_index)
            records[item_name].append({"sample": sample, "value": value, "device_id": ""})

    if not records:
        raise ValueError("No numeric Test Item columns were found.")
    return records


def empirical_cdf(values):
    data = sorted(values)
    n = len(data)
    return [(value, (i + 1) / n) for i, value in enumerate(data)]


def empirical_cdf_fraction(values, target):
    if target is None or not values:
        return None
    count = sum(1 for value in values if value <= target)
    return max(count, 1) / len(values)


class CdfCompareApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 620)

        self.pre_path = tk.StringVar()
        self.post_path = tk.StringVar()
        self.selected_item = tk.StringVar()
        self.bin1_only = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Pre/Post 파일을 선택한 뒤 Analyze를 누르세요.")
        self.highlight_sample = None

        self.pre_items = {}
        self.post_items = {}
        self.pre_records = {}
        self.post_records = {}
        self.results = []
        self.result_sort_column = None
        self.result_sort_reverse = False

        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        file_frame = ttk.LabelFrame(root, text="Input Files", padding=8)
        file_frame.pack(fill=tk.X)
        self._file_row(file_frame, "Pre Data", self.pre_path, self.pick_pre, 0)
        self._file_row(file_frame, "Post Data", self.post_path, self.pick_post, 1)

        action_frame = ttk.Frame(root)
        action_frame.pack(fill=tk.X, pady=(8, 8))
        ttk.Button(action_frame, text="Analyze", command=self.analyze).pack(side=tk.LEFT)
        ttk.Button(action_frame, text="Export CSV", command=self.export_csv).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Checkbutton(action_frame, text="Pre/Post Bin 1 only", variable=self.bin1_only).pack(side=tk.LEFT, padx=(18, 0))

        body = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        result_frame = ttk.LabelFrame(left, text="Result Summary", padding=6)
        result_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "test_number", "item", "n_pre", "n_post", "pre_mean", "pre_sigma", "post_mean",
            "post_sigma", "mea_s", "diff_mean", "diff_sigma", "diff_s", "result",
        )
        headings = (
            "Test Number", "Item", "N Pre", "N Post", "Pre Mean", "Pre Sigma (n-1)", "Post Mean",
            "Post Sigma (n-1)", "Mea_S", "Diff Mean", "Diff Sigma (n-1)", "Diff_S", "Result",
        )
        widths = (86, 170, 55, 55, 82, 82, 82, 82, 70, 82, 82, 70, 78)
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", height=16)
        for col, heading, width in zip(columns, headings, widths):
            self.tree.heading(col, text=heading, command=lambda c=col: self.sort_results_by_column(c))
            self.tree.column(col, width=width, anchor=tk.CENTER)
        self.tree.tag_configure("flag", background="#ffe2e2")
        self.tree.tag_configure("missing", background="#fff4cc")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        y_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        over_sigma_frame = ttk.LabelFrame(left, text="Items over 3 sigma by Sample", padding=6)
        over_sigma_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.over_sigma_tree = ttk.Treeview(over_sigma_frame, show="headings", height=7)
        self.over_sigma_tree.tag_configure("fail", background="#fff0f0")
        self.over_sigma_tree.bind("<ButtonRelease-1>", self.on_over_sigma_click)
        over_sigma_y_scroll = ttk.Scrollbar(over_sigma_frame, orient=tk.VERTICAL, command=self.over_sigma_tree.yview)
        over_sigma_x_scroll = ttk.Scrollbar(over_sigma_frame, orient=tk.HORIZONTAL, command=self.over_sigma_tree.xview)
        self.over_sigma_tree.configure(yscrollcommand=over_sigma_y_scroll.set, xscrollcommand=over_sigma_x_scroll.set)
        self.over_sigma_tree.grid(row=0, column=0, sticky="nsew")
        over_sigma_y_scroll.grid(row=0, column=1, sticky="ns")
        over_sigma_x_scroll.grid(row=1, column=0, sticky="ew")
        over_sigma_frame.columnconfigure(0, weight=1)
        over_sigma_frame.rowconfigure(0, weight=1)
        self.configure_over_sigma_columns(1)

        detail_frame = ttk.LabelFrame(right, text="Sample Detail", padding=6)
        detail_frame.pack(fill=tk.BOTH, expand=True)
        detail_columns = ("sample", "pre_value", "post_value", "mea_s", "diff", "diff_s", "result")
        detail_headings = ("Sample No.", "Pre", "Post", "Mea_S", "Diff", "Diff_S", "Result")
        detail_widths = (90, 80, 80, 70, 70, 70, 86)
        self.detail_tree = ttk.Treeview(detail_frame, columns=detail_columns, show="headings", height=10)
        for col, heading, width in zip(detail_columns, detail_headings, detail_widths):
            self.detail_tree.heading(col, text=heading)
            self.detail_tree.column(col, width=width, anchor=tk.CENTER)
        self.detail_tree.tag_configure("flag", background="#ffe2e2")
        self.detail_tree.tag_configure("missing", background="#fff4cc")
        detail_y_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_tree.yview)
        detail_x_scroll = ttk.Scrollbar(detail_frame, orient=tk.HORIZONTAL, command=self.detail_tree.xview)
        self.detail_tree.configure(yscrollcommand=detail_y_scroll.set, xscrollcommand=detail_x_scroll.set)
        self.detail_tree.grid(row=0, column=0, sticky="nsew")
        detail_y_scroll.grid(row=0, column=1, sticky="ns")
        detail_x_scroll.grid(row=1, column=0, sticky="ew")
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

        graph_frame = ttk.LabelFrame(right, text="CDF Compare", padding=6)
        graph_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        item_bar = ttk.Frame(graph_frame)
        item_bar.pack(fill=tk.X)
        ttk.Label(item_bar, text="Test Item").pack(side=tk.LEFT)
        self.item_combo = ttk.Combobox(item_bar, textvariable=self.selected_item, state="readonly")
        self.item_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.item_combo.bind("<<ComboboxSelected>>", self.on_item_combo_select)
        self.canvas = tk.Canvas(graph_frame, background="white", highlightthickness=1, highlightbackground="#d0d0d0")
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda _event: self.draw_selected_cdf())

        note = ttk.Label(
            root,
            text="Mea_S = (Measured - group mean) / group sigma\n"
            "Diff. = Post / Pre - 1, Diff_S = (Diff. - diff mean) / diff sigma\n"
            "Flag rule: Mea_S > 3 or Diff_S > 3",
        )
        note.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(root, textvariable=self.status).pack(fill=tk.X, pady=(4, 0))

    def _file_row(self, parent, label, var, command, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Button(parent, text="Browse", command=command).grid(row=row, column=2, padx=(6, 0), pady=2)
        parent.columnconfigure(1, weight=1)

    def pick_pre(self):
        path = filedialog.askopenfilename(filetypes=[("Data files", "*.xlsx *.csv")])
        if path:
            self.pre_path.set(path)

    def pick_post(self):
        path = filedialog.askopenfilename(filetypes=[("Data files", "*.xlsx *.csv")])
        if path:
            self.post_path.set(path)

    def analyze(self):
        try:
            if not self.pre_path.get() or not self.post_path.get():
                raise ValueError("Select both Pre Data and Post Data files.")
            self.pre_records = extract_item_records(read_table(self.pre_path.get()))
            self.post_records = filter_records_to_last_sample(extract_item_records(read_table(self.post_path.get())))
            if self.bin1_only.get():
                self.pre_records = filter_records_by_bin_one(self.pre_records)
                self.post_records = filter_records_by_bin_one(self.post_records)
            self.pre_items = {item: [record["value"] for record in records] for item, records in self.pre_records.items()}
            self.post_items = {item: [record["value"] for record in records] for item, records in self.post_records.items()}
            self.result_sort_column = None
            self.result_sort_reverse = False
            self.results = self.calculate_results()
            self.refresh_results()
            self.status.set(f"완료: Post {len(self.post_items)}개 Item 분석, 선별 {self.count_flags()}개")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "분석 실패\n\n" + str(exc))

    def calculate_results(self):
        results = []
        for item in sorted(self.post_items):
            test_number = self.test_number_for_item(item)
            post_values = self.post_items[item]
            pre_values = self.pre_items.get(item, [])
            post_mean = mean(post_values)
            post_sigma = sample_std(post_values)
            mea_s = max_abs_sigma(post_values, post_mean, post_sigma)
            mea_threshold = threshold_for(len(post_values))
            row = {
                "test_number": test_number,
                "item": item,
                "n_pre": len(pre_values),
                "n_post": len(post_values),
                "pre_mean": None,
                "pre_sigma": None,
                "post_mean": post_mean,
                "post_sigma": post_sigma,
                "mea_s": mea_s,
                "mea_threshold": mea_threshold,
                "diff_mean": None,
                "diff_sigma": None,
                "diff_s": None,
                "diff_threshold": None,
                "result": "NO PRE ITEM",
            }
            if pre_values:
                pre_mean = mean(pre_values)
                pre_sigma = sample_std(pre_values)
                pre_scale = robust_pre_scale(pre_values)
                diffs = paired_diff_values(pre_values, post_values, pre_scale=pre_scale)
                diff_mean = mean(diffs)
                diff_sigma = sample_std(diffs)
                diff_s = max_abs_sigma(diffs, diff_mean, diff_sigma)
                diff_threshold = threshold_for(len(diffs))
                result = flag_result(
                    mea_s, diff_s, len(post_values), sigma=post_sigma, mean=post_mean,
                    diff_n=len(diffs), diff_sigma=diff_sigma, diff_mean=diff_mean,
                    mea_threshold=mea_threshold, diff_threshold=diff_threshold,
                )
                row.update(
                    {
                        "pre_mean": pre_mean,
                        "pre_sigma": pre_sigma,
                        "diff_mean": diff_mean,
                        "diff_sigma": diff_sigma,
                        "diff_s": diff_s,
                        "diff_threshold": diff_threshold,
                        "result": result,
                    }
                )
            results.append(row)
        return results

    def test_number_for_item(self, item):
        for records in (self.post_records.get(item, []), self.pre_records.get(item, [])):
            for record in records:
                test_number = cell_text(record.get("test_number"))
                if test_number:
                    return test_number
        return ""

    def result_sort_key(self, row, column):
        value = row.get(column)
        if column == "test_number":
            return natural_sort_key(value)
        if isinstance(value, (int, float)):
            return (0, value)
        number = to_float(value)
        if number is not None:
            return (0, number)
        return (1, cell_text(value).lower())

    def sort_results_by_column(self, column):
        if self.result_sort_column == column:
            self.result_sort_reverse = not self.result_sort_reverse
        else:
            self.result_sort_column = column
            self.result_sort_reverse = False
        self.results.sort(key=lambda row: self.result_sort_key(row, column), reverse=self.result_sort_reverse)
        self.refresh_results()

    def refresh_results(self):
        self.tree.delete(*self.tree.get_children())
        current_item = self.selected_item.get()
        for row in self.results:
            tag = ""
            if row["result"] == "SELECT":
                tag = "flag"
            elif row["result"] == "NO PRE ITEM":
                tag = "missing"
            values = (
                row["test_number"], row["item"], row["n_pre"], row["n_post"], fmt(row["pre_mean"]), fmt(row["pre_sigma"]),
                fmt(row["post_mean"]), fmt(row["post_sigma"]), fmt(row["mea_s"]), fmt(row["diff_mean"]),
                fmt(row["diff_sigma"]), fmt(row["diff_s"]), row["result"],
            )
            self.tree.insert("", tk.END, iid=row["item"], values=values, tags=(tag,))
        items = [row["item"] for row in self.results]
        self.item_combo["values"] = items
        if items:
            selected_item = current_item if current_item in items else items[0]
            self.selected_item.set(selected_item)
            self.tree.selection_set(selected_item)
            self.tree.see(selected_item)
        self.refresh_over_sigma_table()
        self.refresh_selected_view()

    def sample_sort_key(self, sample):
        number = to_float(sample)
        if number is None:
            return (1, cell_text(sample))
        return (0, number)

    def over_sigma_rows(self):
        rows = []
        for item in sorted(self.post_records):
            post_records = self.post_records.get(item, [])
            pre_records = self.pre_records.get(item, [])
            pre_values = [record["value"] for record in pre_records]
            post_values = [record["value"] for record in post_records]
            post_mean = mean(post_values)
            post_sigma = sample_std(post_values)
            pre_scale = robust_pre_scale(pre_values)
            diffs = paired_diff_values(pre_values, post_values, pre_scale=pre_scale)
            diff_mean = mean(diffs)
            diff_sigma = sample_std(diffs)
            n_post = len(post_values)
            n_diff = len(diffs)
            # n_post/n_diff 는 이 item 안에서 고정이라 임계값을 루프 밖에서 한 번만 계산해
            # 재사용한다 — 표본마다 grubbs_critical 을 다시 계산하지 않기 위해. §S3 후속(성능).
            mea_threshold = threshold_for(n_post)
            diff_threshold = threshold_for(n_diff)
            for index, post_record in enumerate(post_records):
                post_value = post_record["value"]
                pre_value = pre_values[index] if index < len(pre_values) else None
                mea_s = sigma(post_value, post_mean, post_sigma)
                diff = diff_ratio(pre_value, post_value, pre_scale=pre_scale) if pre_value is not None else None
                diff_s = sigma(diff, diff_mean, diff_sigma) if diff is not None else None
                # 각 branch 를 독립적으로 flag_result 로 평가 — item 의 n(post/diff)에 따른
                # Grubbs 임계값 기준. §S3.
                mea_fail = mea_s is not None and flag_result(mea_s, None, n_post, sigma=post_sigma, mean=post_mean, mea_threshold=mea_threshold) == "SELECT"
                diff_fail = diff_s is not None and math.isfinite(diff_s) and flag_result(
                    None, diff_s, n_post, sigma=post_sigma, mean=post_mean,
                    diff_n=n_diff, diff_sigma=diff_sigma, diff_mean=diff_mean,
                    diff_threshold=diff_threshold,
                ) == "SELECT"
                flagged = mea_fail or diff_fail
                if flagged:
                    if mea_fail and diff_fail:
                        trigger = "Mea_S + Diff_S"
                    elif mea_fail:
                        trigger = "Mea_S"
                    else:
                        trigger = "Diff_S"
                    rows.append(
                        {
                            "sample": post_record["sample"],
                            "item": item,
                            "trigger": trigger,
                            "mea_s": mea_s,
                            "diff_s": diff_s,
                            "pre_value": pre_value,
                            "post_value": post_value,
                            "shift": None if pre_value is None else post_value - pre_value,
                            "score": max(
                                abs(mea_s) if mea_s is not None else 0.0,
                                abs(diff_s) if diff_s is not None and math.isfinite(diff_s) else 0.0,
                            ),
                        }
                    )
        return sorted(rows, key=lambda row: (self.sample_sort_key(row["sample"]), -row["score"], row["item"]))

    def items_over_sigma_by_sample(self):
        by_sample = {}
        for row in self.over_sigma_rows():
            by_sample.setdefault(row["sample"], []).append(row["item"])
        return by_sample

    def configure_over_sigma_columns(self, item_count):
        item_count = max(1, item_count)
        columns = ["sample"] + [f"item_{index}" for index in range(item_count)]
        self.over_sigma_tree.configure(columns=columns)
        self.over_sigma_tree.heading("sample", text="Sample #")
        self.over_sigma_tree.column("sample", width=90, anchor=tk.CENTER, stretch=False)
        for index in range(item_count):
            column = f"item_{index}"
            heading = "Items over 3σ" if index == 0 else ""
            self.over_sigma_tree.heading(column, text=heading)
            self.over_sigma_tree.column(column, width=170, anchor=tk.CENTER, stretch=True)

    def refresh_over_sigma_table(self):
        by_sample = self.items_over_sigma_by_sample()
        max_items = max((len(items) for items in by_sample.values()), default=1)
        self.configure_over_sigma_columns(max_items)
        self.over_sigma_tree.delete(*self.over_sigma_tree.get_children())
        for sample in sorted(by_sample, key=self.sample_sort_key):
            items = by_sample[sample]
            values = [sample] + items + [""] * (max_items - len(items))
            self.over_sigma_tree.insert("", tk.END, values=values, tags=("fail",))

    def on_over_sigma_click(self, event):
        row_id = self.over_sigma_tree.identify_row(event.y)
        column_id = self.over_sigma_tree.identify_column(event.x)
        if not row_id or not column_id:
            return
        column_index = int(column_id.replace("#", "")) - 1
        if column_index < 1:
            return
        values = self.over_sigma_tree.item(row_id, "values")
        if column_index >= len(values):
            return
        sample = values[0]
        item = values[column_index]
        if not item:
            return
        self.highlight_sample = sample
        self.selected_item.set(item)
        if item in self.tree.get_children():
            self.tree.see(item)
        self.refresh_selected_view()

    def count_flags(self):
        return sum(1 for row in self.results if row["result"] == "SELECT")

    def on_tree_select(self, _event):
        selected = self.tree.selection()
        if selected:
            self.selected_item.set(selected[0])
            self.highlight_sample = None
            self.refresh_selected_view()

    def on_item_combo_select(self, _event):
        self.highlight_sample = None
        self.refresh_selected_view()

    def refresh_selected_view(self):
        self.draw_selected_cdf()
        self.refresh_sample_detail()

    def sample_details_for_item(self, item):
        post_records = self.post_records.get(item, [])
        pre_records = self.pre_records.get(item, [])
        pre_values = [record["value"] for record in pre_records]
        post_values = [record["value"] for record in post_records]
        pre_mean = mean(pre_values)
        pre_sigma = sample_std(pre_values)
        post_mean = mean(post_values)
        post_sigma = sample_std(post_values)
        pre_scale = robust_pre_scale(pre_values)
        diffs = paired_diff_values(pre_values, post_values, pre_scale=pre_scale)
        diff_mean = mean(diffs)
        diff_sigma = sample_std(diffs)
        n_post = len(post_values)
        n_diff = len(diffs)
        # 이 item 안에서 n_post/n_diff 는 고정이라 임계값을 루프 밖에서 한 번만 계산해
        # 재사용한다. §S3 후속(성능).
        mea_threshold = threshold_for(n_post)
        diff_threshold = threshold_for(n_diff)

        details = []
        for index, post_record in enumerate(post_records):
            post_value = post_record["value"]
            pre_value = pre_values[index] if index < len(pre_values) else None
            mea_s = sigma(post_value, post_mean, post_sigma)
            diff = diff_ratio(pre_value, post_value, pre_scale=pre_scale) if pre_value is not None else None
            diff_s = sigma(diff, diff_mean, diff_sigma) if diff is not None else None
            result = flag_result(
                mea_s, diff_s, n_post, sigma=post_sigma, mean=post_mean,
                diff_n=n_diff, diff_sigma=diff_sigma, diff_mean=diff_mean,
                mea_threshold=mea_threshold, diff_threshold=diff_threshold,
            )
            if pre_value is None:
                result = "NO PRE SAMPLE"
            details.append(
                {
                    "sample": post_record["sample"],
                    "pre_value": pre_value,
                    "post_value": post_value,
                    "pre_mea_s": sigma(pre_value, pre_mean, pre_sigma) if pre_value is not None else None,
                    "pre_cdf": normal_cdf(sigma(pre_value, pre_mean, pre_sigma)) if pre_value is not None else None,
                    "post_cdf": normal_cdf(mea_s),
                    "mea_s": mea_s,
                    "diff": diff,
                    "diff_s": diff_s,
                    "result": result,
                }
            )
        return details

    def refresh_sample_detail(self):
        self.detail_tree.delete(*self.detail_tree.get_children())
        item = self.selected_item.get()
        for index, row in enumerate(self.sample_details_for_item(item)):
            if row["result"] != "SELECT":
                continue
            tag = ""
            if row["result"] == "SELECT":
                tag = "flag"
            elif row["result"] == "NO PRE SAMPLE":
                tag = "missing"
            values = (
                row["sample"], fmt(row["pre_value"]), fmt(row["post_value"]), fmt(row["mea_s"]),
                fmt(row["diff"]), fmt(row["diff_s"]), row["result"],
            )
            self.detail_tree.insert("", tk.END, iid=str(index), values=values, tags=(tag,))

    def spec_limits_for_item(self, item):
        for records in (self.post_records.get(item, []), self.pre_records.get(item, [])):
            for record in records:
                lower_limit = record.get("lower_limit")
                upper_limit = record.get("upper_limit")
                if lower_limit is not None or upper_limit is not None:
                    return lower_limit, upper_limit
        return None, None

    def draw_selected_cdf(self):
        self.canvas.delete("all")
        item = self.selected_item.get()
        width = max(self.canvas.winfo_width(), 320)
        height = max(self.canvas.winfo_height(), 220)
        margin_left = 56
        margin_right = 24
        margin_top = 20
        margin_bottom = 74
        pre_values = self.pre_items.get(item, [])
        post_values = self.post_items.get(item, [])
        lower_limit, upper_limit = self.spec_limits_for_item(item)
        spec_values = [value for value in (lower_limit, upper_limit) if value is not None]
        all_values = pre_values + post_values + spec_values
        if not all_values:
            return
        min_value = min(all_values)
        max_value = max(all_values)
        if min_value == max_value:
            min_value -= 1
            max_value += 1

        def x_pos(value):
            return margin_left + (value - min_value) / (max_value - min_value) * (width - margin_left - margin_right)

        def y_pos(value):
            return margin_top + (1.0 - value) * (height - margin_top - margin_bottom)

        self.canvas.create_rectangle(margin_left, margin_top, width - margin_right, height - margin_bottom, outline="#cfcfcf")
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = y_pos(frac)
            self.canvas.create_line(margin_left, y, width - margin_right, y, fill="#eeeeee")
            self.canvas.create_text(margin_left - 8, y, text=fmt(frac), anchor="e", fill="#555555")
        for value in (min_value, (min_value + max_value) / 2, max_value):
            x = x_pos(value)
            self.canvas.create_text(x, height - margin_bottom + 18, text=format(value, ".2g"), anchor="n", fill="#555555")
        self.canvas.create_text(width / 2, height - 12, text="Measurement Value", fill="#555555")
        self.canvas.create_text(18, height / 2, text="CDF", angle=90, fill="#555555")
        self.draw_spec_line(lower_limit, x_pos, y_pos, margin_top, height - margin_bottom, "#2ca02c", "LSL")
        self.draw_spec_line(upper_limit, x_pos, y_pos, margin_top, height - margin_bottom, "#9467bd", "USL")
        self.draw_cdf_line(pre_values, x_pos, y_pos, "#1f77b4", "Pre")
        self.draw_cdf_line(post_values, x_pos, y_pos, "#d62728", "Post")
        self.draw_shift_marker(item, pre_values, post_values, x_pos, y_pos)
        legend_width = 300
        legend_x = max(margin_left, (width - legend_width) / 2)
        legend_y = height - 30
        self.canvas.create_rectangle(legend_x - 10, legend_y - 13, legend_x + legend_width, legend_y + 13, fill="#f2f2f2", outline="#cfcfcf")
        self.canvas.create_line(legend_x, legend_y, legend_x + 24, legend_y, fill="#1f77b4", width=2)
        self.canvas.create_text(legend_x + 30, legend_y, text="Pre", anchor="w")
        self.canvas.create_line(legend_x + 76, legend_y, legend_x + 100, legend_y, fill="#d62728", width=2)
        self.canvas.create_text(legend_x + 106, legend_y, text="Post", anchor="w")
        self.canvas.create_line(legend_x + 158, legend_y, legend_x + 182, legend_y, fill="#2ca02c", width=2, dash=(4, 3))
        self.canvas.create_text(legend_x + 188, legend_y, text="LSL", anchor="w")
        self.canvas.create_line(legend_x + 226, legend_y, legend_x + 250, legend_y, fill="#9467bd", width=2, dash=(4, 3))
        self.canvas.create_text(legend_x + 256, legend_y, text="USL", anchor="w")

    def draw_spec_line(self, value, x_pos, y_pos, top, bottom, color, label):
        if value is None:
            return
        x = x_pos(value)
        self.canvas.create_line(x, top, x, bottom, fill=color, width=2, dash=(4, 3))
        self.canvas.create_text(x + 4, top + 8, text=f"{label} {fmt(value)}", anchor="nw", fill=color)

    def draw_shift_marker(self, item, pre_values, post_values, x_pos, y_pos):
        sample = self.highlight_sample
        if not sample:
            return
        post_records = self.post_records.get(item, [])
        pre_records = self.pre_records.get(item, [])
        post_index = None
        for index, record in enumerate(post_records):
            if record["sample"] == sample:
                post_index = index
                break
        if post_index is None:
            return
        post_value = post_records[post_index]["value"]
        pre_value = pre_records[post_index]["value"] if post_index < len(pre_records) else None
        post_cdf = empirical_cdf_fraction(post_values, post_value)
        pre_cdf = empirical_cdf_fraction(pre_values, pre_value)
        post_x = x_pos(post_value)
        post_y = y_pos(post_cdf)

        self.canvas.create_oval(post_x - 6, post_y - 6, post_x + 6, post_y + 6, outline="#b00020", width=3)
        self.canvas.create_text(post_x + 8, post_y - 8, text=f"#{sample} Post {fmt(post_value)}", anchor="sw", fill="#b00020")

        if pre_value is None or pre_cdf is None:
            return

        pre_x = x_pos(pre_value)
        pre_y = y_pos(pre_cdf)
        self.canvas.create_oval(pre_x - 6, pre_y - 6, pre_x + 6, pre_y + 6, outline="#004c99", width=3)
        self.canvas.create_line(pre_x, pre_y, post_x, post_y, fill="#111111", width=2, arrow=tk.LAST)
        mid_x = (pre_x + post_x) / 2
        mid_y = (pre_y + post_y) / 2
        self.canvas.create_text(
            mid_x + 6,
            mid_y - 8,
            text=f"Shift {fmt(post_value - pre_value)}",
            anchor="sw",
            fill="#111111",
        )

    def draw_cdf_line(self, values, x_pos, y_pos, color, _label):
        points = empirical_cdf(values)
        if not points:
            return
        line_points = []
        previous_y = y_pos(0.0)
        for value, cdf in points:
            x = x_pos(value)
            y = y_pos(cdf)
            line_points.extend((x, previous_y, x, y))
            previous_y = y
        if len(line_points) >= 4:
            self.canvas.create_line(*line_points, fill=color, width=2)
        for value, cdf in points:
            x = x_pos(value)
            y = y_pos(cdf)
            self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline=color)

    def sample_count_for_export(self):
        counts = []
        counts.extend(len(records) for records in self.pre_records.values())
        counts.extend(len(records) for records in self.post_records.values())
        return max(counts) if counts else 0

    def sample_label_for_index(self, index):
        for records in self.post_records.values():
            if index < len(records):
                return records[index]["sample"]
        for records in self.pre_records.values():
            if index < len(records):
                return records[index]["sample"]
        return str(index + 1)

    def record_value(self, records, index):
        if index < len(records):
            return records[index]["value"]
        return None

    def item_sigma_rows(self, records):
        values = [record["value"] for record in records]
        item_mean = mean(values)
        item_sigma = sample_std(values)
        return [sigma(value, item_mean, item_sigma) for value in values]

    def diff_rows(self, pre_records, post_records):
        paired_count = min(len(pre_records), len(post_records))
        pre_scale = robust_pre_scale([record["value"] for record in pre_records])
        diffs = [
            diff_ratio(pre_records[i]["value"], post_records[i]["value"], pre_scale=pre_scale)
            for i in range(paired_count)
        ]
        diffs = finite_values(diffs)
        diff_mean = mean(diffs)
        diff_sigma = sample_std(diffs)
        diff_sigmas = finite_values(sigma(value, diff_mean, diff_sigma) for value in diffs)
        return diffs, diff_sigmas

    def export_csv(self):
        if not self.results:
            messagebox.showinfo(APP_TITLE, "Analyze results before exporting.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile="cdf_sigma_compare_result.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return

        matched_items = [row["item"] for row in self.results if row["item"] in self.pre_records]
        pre_only_items = sorted(set(self.pre_records) - set(self.post_records))
        post_only_items = sorted(set(self.post_records) - set(self.pre_records))
        sample_count = self.sample_count_for_export()

        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            row1 = ["Test Item Name", "", ""]
            row2 = ["Pre/Post", "", ""]
            row3 = ["Sample No.", "", ""]
            for item in matched_items + post_only_items + pre_only_items:
                row1.extend([item] * 6)
                row2.extend(["Pre", "Pre", "Post", "Post", "Diff.", "Diff."])
                row3.extend(["Measured", "Sigma (n-1)", "Measured", "Sigma (n-1)", "Measured", "Sigma (n-1)"])
            writer.writerow(row1)
            writer.writerow(row2)
            writer.writerow(row3)

            item_cache = {}
            for item in matched_items + post_only_items + pre_only_items:
                pre_records = self.pre_records.get(item, [])
                post_records = self.post_records.get(item, [])
                pre_sigmas = self.item_sigma_rows(pre_records)
                post_sigmas = self.item_sigma_rows(post_records)
                diffs, diff_sigmas = self.diff_rows(pre_records, post_records)
                item_cache[item] = (pre_records, post_records, pre_sigmas, post_sigmas, diffs, diff_sigmas)

            for index in range(sample_count):
                row = [self.sample_label_for_index(index), "", ""]
                for item in matched_items + post_only_items + pre_only_items:
                    pre_records, post_records, pre_sigmas, post_sigmas, diffs, diff_sigmas = item_cache[item]
                    pre_value = self.record_value(pre_records, index)
                    post_value = self.record_value(post_records, index)
                    pre_sigma = pre_sigmas[index] if index < len(pre_sigmas) else None
                    post_sigma = post_sigmas[index] if index < len(post_sigmas) else None
                    diff = diffs[index] if index < len(diffs) else None
                    diff_sigma = diff_sigmas[index] if index < len(diff_sigmas) else None
                    row.extend([fmt(pre_value), fmt(pre_sigma), fmt(post_value), fmt(post_sigma), fmt(diff), fmt(diff_sigma)])
                writer.writerow(row)

        self.status.set("Exported: " + path)


if __name__ == "__main__":
    app = CdfCompareApp()
    app.mainloop()
