import io
import json
import hashlib
import math
import os
import pickle
import re
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    import numpy as np
except ImportError:
    np = None

from cdf_compare_tool import (
    APP_TITLE,
    CdfCompareApp,
    extract_item_records,
    filter_records_to_last_sample,
    fmt,
    read_table,
)
from stats_core import (
    _UNSET, EPS_REL, FLAG_ALPHA, FLAG_LIMIT, FLAG_MODE, diff_ratio, flag_result, mean_of,
    robust_pre_scale, std_of, threshold_for, zscore,
)


HOST = "127.0.0.1"
PORT = 8765
PORT_END = 8799
DATA_ROOT = os.environ.get("CDFTOOL_DATA_ROOT") or r"D:\000_업무폴더\1000. 업무자동화\Reliability Test Data"
APP_REVISION = "Rev.0.028"
CURRENT_APP = None
CURRENT_ITEMS = {}
CURRENT_PAYLOADS = {}
CURRENT_CACHE_KEYS = {}
CURRENT_ANALYSIS_STATUS = {}
CURRENT_ANALYSIS_RUN_ID = ""
APP_LOCK = threading.Lock()
JOBS = {}
JOB_LOCK = threading.Lock()


HTML = r"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pre/Post CDF Sigma Compare Tool</title>
  <style>
    :root {
      --bg: #f7f9fc;
      --panel: #ffffff;
      --line: #dce4ee;
      --head: #0a9da3;
      --head-dark: #05717f;
      --head2: #f8fafc;
      --nav: #06244c;
      --nav2: #041b3b;
      --accent: #02a2b8;
      --text: #071f49;
      --muted: #687792;
      --danger: #d93025;
      --select: #fff0f0;
      --blue: #1f77b4;
      --red: #d62728;
      --green: #2ca02c;
      --purple: #9467bd;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
      min-height: 100vh;
      overflow-y: auto;
    }
    h1 { margin: 0; font-size: 26px; font-weight: 500; letter-spacing: 0; }
    h2, h3 { letter-spacing: 0; }
    main {
      min-height: 100vh;
      padding: 0;
    }
    .layout, .meta-grid, .files, .toolbar, .grid, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
    }
    .app-shell {
      display: grid;
      grid-template-columns: 300px minmax(0, 1fr);
      min-height: 100vh;
      background: var(--bg);
    }
    .side {
      border-right: 0;
      padding: 0 22px;
      background: linear-gradient(180deg, var(--nav) 0%, var(--nav2) 100%);
      color: #fff;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }
    .side-title {
      background: transparent;
      padding: 28px 0 24px;
      color: #fff;
      font-size: 22px;
      line-height: 1.1;
      margin: 0 0 14px;
      border-bottom: 1px solid rgba(255,255,255,.18);
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .side-link {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      text-align: left;
      border: 0;
      background: transparent;
      border-radius: 7px;
      padding: 11px 10px;
      margin: 2px 0;
      font-size: 15px;
      font-weight: 600;
      color: rgba(255,255,255,.92);
    }
    .side-link:hover, .side-link.active {
      background: linear-gradient(90deg, rgba(7,158,181,.85), rgba(7,158,181,.35));
      color: #fff;
    }
    .side-exit {
      margin-top: auto;
      border-top: 1px solid rgba(255,255,255,.22);
      padding: 18px 0 26px;
    }
    .exit-button {
      color: #ff6d78;
    }
    .exit-button:hover {
      background: rgba(255,109,120,.12);
      color: #ff9aa2;
    }
    .content { padding: 24px 22px 12px; min-width: 0; overflow: hidden; height: 100vh; }
    .view { display: none; }
    .view.active { display: block; height: 100%; overflow: auto; }
    #rdaView.active {
      display: flex;
      flex-direction: column;
      min-height: 0;
      overflow: hidden;
    }
    #rdaView > .view-header,
    #rdaView > .rda-card {
      flex: 0 0 auto;
    }
    .view-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 22px;
    }
    .view-header .status { color: var(--muted); }
    .view-title { margin: 0; font-size: 32px; font-weight: 800; color: var(--text); }
    .view-subtitle { margin-top: 8px; color: var(--text); font-size: 17px; }
    .path-tools {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      min-width: 0;
    }
    .path-tools .status {
      max-width: 520px;
      min-width: 420px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      border: 1px solid #cfd9e6;
      background: #fff;
      border-radius: 5px;
      padding: 10px 14px;
    }
    .dashboard-band {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      border-bottom: 1px solid var(--line);
      background: #f2f3f5;
    }
    .dashboard-band div {
      min-height: 40px;
      padding: 8px 12px;
      border-right: 1px solid var(--line);
      font-size: 13px;
    }
    .dashboard-band span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 2px;
    }
    .rda-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 20px;
      margin-bottom: 12px;
      box-shadow: 0 8px 24px rgba(7,31,73,.05);
    }
    .rda-form {
      display: grid;
      grid-template-columns: repeat(4, minmax(170px, 1fr));
      gap: 18px 40px;
    }
    .field { min-width: 0; }
    .field label {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .field input, .field select {
      width: 100%;
      min-width: 0;
      border: 1px solid #c8d3dc;
      border-radius: 5px;
      padding: 10px 12px;
      outline: 0;
      background: #fff;
      font: inherit;
    }
    .field select { min-width: 0; }
    .section-title { padding: 6px 2px; font-weight: 500; margin: 6px 0; }
    .files { padding: 10px; display: grid; grid-template-columns: 1fr; gap: 8px 10px; align-items: center; }
    input[type=file], input[type=text] { width: 100%; }
    .toolbar { padding: 14px 20px; display: flex; align-items: center; gap: 28px; margin-bottom: 12px; flex: 0 0 auto; }
    .condition-toggle {
      width: 100%;
      border: 0;
      background: transparent;
      cursor: pointer;
      font: inherit;
      text-align: left;
    }
    .condition-toggle:hover .title-text { color: #0b5ca8; }
    .condition-summary-line {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      font-weight: 600;
      color: var(--muted);
      display: none;
    }
    .condition-toggle-caret {
      flex: 0 0 auto;
      font-size: 14px;
      color: var(--muted);
      transition: transform .15s ease;
    }
    .rda-card.condition-card { margin-bottom: 0; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
    .toolbar.condition-attached { border-top: 0; border-top-left-radius: 0; border-top-right-radius: 0; box-shadow: none; margin-bottom: 12px; }
    #rdaView.condition-collapsed .condition-toggle-caret { transform: rotate(-90deg); }
    #rdaView.condition-collapsed .condition-card .condition-body,
    #rdaView.condition-collapsed > .toolbar.condition-attached {
      display: none;
    }
    #rdaView.condition-collapsed .condition-card .condition-title {
      border-bottom: 0;
      margin-bottom: 0;
    }
    #rdaView.condition-collapsed .condition-card {
      border-bottom-left-radius: 8px;
      border-bottom-right-radius: 8px;
    }
    #rdaView.condition-collapsed .condition-summary-line {
      display: block;
    }
    .analysis-results-section {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 14px;
      box-shadow: 0 8px 24px rgba(7,31,73,.05);
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    body:not(.results-window).parent-results-hidden .analysis-results-section {
      display: none !important;
    }
    body:not(.results-window).parent-results-visible .analysis-results-section {
      display: flex !important;
      height: var(--parent-results-section-height, auto);
      max-height: var(--parent-results-section-max-height, none);
      overflow: var(--parent-results-section-overflow, hidden);
    }
    body:not(.results-window).parent-results-fixed-height .analysis-results-section {
      flex: 0 0 var(--parent-results-section-height);
    }
    body:not(.results-window).parent-results-visible .analysis-results-scroll {
      height: var(--parent-results-scroll-height, auto);
      overflow: var(--parent-results-scroll-overflow, auto);
    }
    body:not(.results-window).parent-results-visible #passResultsGrid:not(.results-hidden) {
      height: var(--parent-results-grid-height, auto);
      min-height: var(--parent-results-grid-min-height, 0);
      overflow: var(--parent-results-grid-overflow, visible);
    }
    .analysis-results-scroll {
      flex: 1 1 auto;
      min-height: 0;
      overflow: auto;
      padding-right: 4px;
      display: flex;
      flex-direction: column;
    }
    .summary-strip {
      display: flex;
      flex-wrap: nowrap;
      align-items: stretch;
      gap: 10px 16px;
      margin: 0 0 10px;
      height: 62px;
      box-sizing: border-box;
    }
    .summary-strip:empty {
      display: none;
      margin: 0;
    }
    .summary-card {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      justify-content: center;
      gap: 2px;
      min-width: 92px;
      padding: 8px 14px;
      border: 1px solid #d8e4f1;
      border-radius: 8px;
      background: #fff;
      height: 100%;
      flex: 0 0 auto;
      box-sizing: border-box;
    }
    .summary-card-value {
      font-size: 20px;
      font-weight: 800;
      color: #1a3b63;
    }
    .summary-card-flag .summary-card-value { color: #c0392b; }
    .summary-card-ok .summary-card-value { color: #1a7f4a; }
    .summary-card-warn { border-color: #f0c36d; background: #fff9ec; }
    .summary-card-warn .summary-card-value { color: #a86a00; }
    .summary-card-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--muted);
    }
    .judgment-footnote {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-left: auto;
      font-size: 12px;
      color: var(--muted);
      white-space: nowrap;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .footnote-info {
      cursor: help;
      color: #7c93b3;
      font-size: 13px;
    }
    .fail-count-badge {
      margin-left: 6px;
      padding: 1px 7px;
      border-radius: 999px;
      background: #c0392b;
      color: #fff;
      font-size: 11px;
      font-weight: 800;
    }
    .tab-count-badge {
      margin-left: 6px;
      padding: 1px 7px;
      border-radius: 999px;
      background: #0a7890;
      color: #fff;
      font-size: 11px;
      font-weight: 800;
    }
    #overSampleTableWrap { display: none; }
    .analysis-filter-bar {
      display: none;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: start;
      gap: 8px 18px;
      padding: 10px 12px;
      margin: 0 0 10px;
      border: 1px solid #d8e4f1;
      border-radius: 8px;
      background: #fff;
    }
    .analysis-filter-bar.active {
      display: grid;
    }
    .table-filter-area {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
    }
    .filter-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px 18px;
      width: 100%;
      min-width: 0;
    }
    .filter-group {
      display: inline-flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }
    .filter-group strong {
      color: #17345f;
      font-size: 13px;
      margin-right: 2px;
    }
    .filter-chip {
      min-height: 30px;
      padding: 5px 10px;
      border-color: #c6d8ea;
      color: #0b356f;
      background: #fff;
      font-size: 13px;
    }
    .filter-chip.active {
      color: #fff;
      border-color: #047c80;
      background: linear-gradient(180deg, #11b7b5, #008f88);
    }
    .readout-toggle {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      min-height: 30px;
      padding: 4px 8px;
      border: 1px solid #c6d8ea;
      border-radius: 6px;
      color: #17345f;
      background: #fff;
      font-size: 13px;
      font-weight: 700;
    }
    .readout-toggle input,
    .filter-check input {
      width: 16px;
      height: 16px;
      accent-color: #126bcb;
    }
    .filter-check {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 30px;
      padding: 4px 8px;
      border: 1px solid #c6d8ea;
      border-radius: 6px;
      color: #17345f;
      background: #fff;
      font-size: 13px;
      font-weight: 700;
    }
    .temp-filter-group .filter-check {
      min-height: 26px;
      padding: 3px 7px;
      gap: 4px;
      font-size: 12px;
    }
    .temp-filter-group .filter-chip {
      min-width: 64px;
      min-height: 28px;
      padding: 4px 9px;
      font-size: 12px;
    }
    .graph-filter-bar {
      display: none;
      align-items: flex-start;
      flex-wrap: wrap;
      justify-self: end;
      align-self: start;
      gap: 8px 14px;
      padding: 8px 10px;
      border: 1px solid #d8e4f1;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(31,74,118,.06);
    }
    .graph-filter-bar.active {
      display: flex;
    }
    .graph-readout-stack {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 8px;
      min-width: 0;
    }
    .graph-filter-group {
      display: inline-flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }
    .graph-filter-group strong {
      color: #17345f;
      font-size: 13px;
      margin-right: 2px;
    }
    button {
      border: 1px solid #9fb1bf;
      background: #fff;
      border-radius: 5px;
      padding: 7px 14px;
      cursor: pointer;
      font-weight: 600;
    }
    button.primary { background: linear-gradient(180deg, #058b99, #056f7e); color: white; border-color: #056f7e; }
    button.secondary { background: #eef6fa; color: #0b6070; border-color: #bdd3df; }
    button:disabled { opacity: .55; cursor: default; }
    .status { color: var(--muted); }
    .manager-section { margin-bottom: 30px; }
    .manager-section h2 {
      margin: 0;
      padding: 10px 14px;
      font-size: 15px;
      background: var(--head2);
    }
    .status-table { width: 100%; min-width: 980px; border-collapse: collapse; }
    .status-table th { background: var(--head); color: #fff; position: static; }
    .status-table td { height: 48px; background: #fff; }
    .status-table tr:nth-child(even) td { background: #f6f8fa; }
    .grid {
      padding: 0;
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(0, 1.15fr);
      grid-template-rows: minmax(0, 1fr);
      grid-template-areas: "resulttab graphtab";
      gap: 14px;
      align-items: stretch;
      border: 0;
      background: transparent;
      flex: 1 1 auto;
      min-height: 560px;
    }
    .result-table-column {
      display: flex;
      flex-direction: column;
      grid-area: resulttab;
      min-width: 0;
      min-height: 0;
      gap: 12px;
    }
    .result-graph-column {
      display: flex;
      flex-direction: column;
      grid-area: graphtab;
      min-width: 0;
      min-height: 0;
      gap: 12px;
    }
    .results-window-title {
      display: none !important;
    }
    .results-hidden { display: none; }
    .panel {
      min-width: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-height: 150px;
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(7,31,73,.05);
    }
    /* 좌측은 탭 패널(요약/Fail/이상 샘플) : 상세 를 1:2 비율로 나눈다. over-panel 은
       메인 화면에서는 항상 숨김(§updatePanelMode, popup 전용으로 남겨둠)이라
       flex 계산에서 제외된다. */
    .summary-panel { flex: 1 1 0; }
    .over-panel { flex: 1 1 0; }
    .detail-panel { flex: 2 1 0; }
    .chart-tools.graph-item-toolbar { flex: 0 0 auto; }
    .chart-panel,
    .diff-cdf-panel,
    .ppf-panel,
    .scatter-panel {
      display: none;
      flex: 1 1 0;
      min-height: 180px;
    }
    .chart-panel.active-graph,
    .diff-cdf-panel.active-graph,
    .ppf-panel.active-graph,
    .scatter-panel.active-graph {
      display: flex;
    }
    .wafer-panel {
      display: flex;
      flex: 1 1 0;
      min-height: 160px;
    }
    .panel h2 {
      margin: 0;
      padding: 14px 18px;
      font-size: 15px;
      background: var(--head2);
      border-bottom: 1px solid var(--line);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .table-wrap { overflow: auto; flex: 1; min-height: 0; }
    table { border-collapse: collapse; width: max-content; min-width: 100%; }
    th, td {
      border: 1px solid #dbe2e8;
      padding: 6px 8px;
      text-align: center;
      white-space: nowrap;
    }
    th {
      background: var(--head);
      color: #fff;
      position: sticky;
      top: 0;
      z-index: 1;
      cursor: pointer;
      user-select: none;
    }
    td.item, td.over-item { text-align: left; }
    tr.select-row { background: var(--select); }
    tr.active { background: #e3f4fb; box-shadow: inset 3px 0 0 #0a7890; }
    td.over-item.active { background: #e3f4fb; box-shadow: inset 3px 0 0 #0a7890; font-weight: 700; }
    td.sigma-fail {
      background: #ffd9d9;
      color: #9b1c1c;
      font-weight: 700;
    }
    td.sigma-action {
      cursor: pointer;
      text-decoration: underline;
      text-underline-offset: 2px;
    }
    td.active-cell {
      box-shadow: inset 0 0 0 2px #111;
    }
    td.over-item { cursor: pointer; color: #064f78; font-weight: 600; }
    .chart-tools { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid var(--line); }
    .graph-item-toolbar { display: none; }
    .graph-tabs {
      margin-left: 0;
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .graph-tabs button {
      min-width: 96px;
      min-height: 32px;
      padding: 5px 12px;
      color: #0b356f;
      background: #fff;
      border-color: #c8d8ea;
    }
    .graph-tabs button.active {
      color: #fff;
      background: linear-gradient(180deg, #1d75df 0%, #0d56bf 100%);
      border-color: #0d56bf;
    }
    select { min-width: 240px; padding: 5px; }
    canvas { width: 100%; height: 100%; display: block; background: #fff; }
    .chart-box, .scatter-box, .wafer-box { flex: 1 1 0; min-height: 0; }
    .item-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: flex-end;
      min-height: 40px;
    }
    .item-tab {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 38px;
      padding: 6px 14px;
      border: 1px solid #c9d9eb;
      border-radius: 999px 999px 0 0;
      border-bottom: 3px solid transparent;
      background: #f2f6fb;
      color: #33445c;
      font-size: 13px;
      font-weight: 700;
      box-sizing: border-box;
    }
    .item-tab.active {
      background: #fff;
      color: #0b5ca8;
      border-bottom-color: #1266c8;
      box-shadow: 0 -2px 8px rgba(18,102,200,.10);
    }
    .item-tab-empty {
      opacity: .45;
      cursor: default;
    }
    .item-tab-badge {
      padding: 1px 7px;
      border-radius: 999px;
      background: rgba(18,102,200,.12);
      color: #0b5ca8;
      font-size: 11px;
      font-weight: 800;
      min-width: 56px;
      text-align: center;
      font-variant-numeric: tabular-nums;
      box-sizing: border-box;
    }
    .item-tab.active .item-tab-badge {
      background: rgba(18,102,200,.18);
    }
    .brand-mark {
      width: 42px;
      height: 42px;
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      align-items: end;
      gap: 3px;
    }
    .brand-mark span { display: block; background: #f7fbff; border-radius: 1px; }
    .brand-mark span:nth-child(1) { height: 20px; }
    .brand-mark span:nth-child(2) { height: 34px; background: #20c4d8; }
    .brand-mark span:nth-child(3) { height: 27px; background: #5ec6f2; }
    .brand-mark span:nth-child(4) { height: 40px; background: #fff; }
    .brand-text strong { display: block; font-size: 21px; }
    .brand-text small { display: block; margin-top: 7px; color: rgba(255,255,255,.86); font-size: 14px; }
    .tree { display: flex; flex-direction: column; gap: 12px; padding-top: 4px; }
    .tree-group { color: #fff; }
    .tree-parent {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      padding: 11px 0;
      color: rgba(255,255,255,.95);
      font-weight: 700;
    }
    .tree-children {
      margin-left: 25px;
      padding: 0 0 0 16px;
      border-left: 1px solid rgba(255,255,255,.45);
    }
    .tree-child {
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 30px;
      color: rgba(255,255,255,.9);
    }
    .tree-child::before {
      content: "";
      position: absolute;
      left: -16px;
      width: 12px;
      border-top: 1px solid rgba(255,255,255,.45);
    }
    .tree-link {
      flex: 1;
      color: inherit;
      border: 0;
      background: transparent;
      text-align: left;
      padding: 7px 8px;
      border-radius: 6px;
      font-weight: 500;
    }
    .tree-link:hover, .tree-link.active { background: rgba(7,158,181,.28); color: #fff; }
    .tree-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #06c9e8;
      flex: 0 0 auto;
    }
    .tree-icon {
      width: 24px;
      height: 24px;
      border: 2px solid currentColor;
      border-radius: 3px;
      display: inline-block;
      position: relative;
      flex: 0 0 auto;
    }
    .tree-icon::before {
      content: "";
      position: absolute;
      left: 2px;
      top: -6px;
      width: 12px;
      height: 7px;
      border: 2px solid currentColor;
      border-bottom: 0;
      border-radius: 3px 3px 0 0;
      background: var(--nav);
    }
    .tree-link[disabled],
    .side-link[disabled] {
      opacity: .5;
      cursor: default;
      pointer-events: none;
    }
    .badge-wip {
      flex: 0 0 auto;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(255,255,255,.16);
      color: rgba(255,255,255,.85);
      font-size: 11px;
      font-weight: 700;
      white-space: nowrap;
    }
    .side-exit-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .side-exit-row .side-link { width: auto; flex: 1; }
    .nav-symbol {
      width: 22px;
      height: 22px;
      display: inline-block;
      position: relative;
      flex: 0 0 auto;
    }
    .home-symbol::before {
      content: "";
      position: absolute;
      inset: 7px 4px 2px;
      border: 2px solid currentColor;
      border-top: 0;
      border-radius: 2px;
    }
    .home-symbol::after {
      content: "";
      position: absolute;
      left: 4px;
      top: 3px;
      width: 13px;
      height: 13px;
      border-left: 2px solid currentColor;
      border-top: 2px solid currentColor;
      transform: rotate(45deg);
    }
    .gear-symbol::before {
      content: "";
      position: absolute;
      inset: 3px;
      border: 2px solid currentColor;
      border-radius: 50%;
      box-shadow: 0 -6px 0 -3px currentColor, 0 6px 0 -3px currentColor, 6px 0 0 -3px currentColor, -6px 0 0 -3px currentColor;
    }
    .power-symbol::before {
      content: "";
      position: absolute;
      inset: 4px;
      border: 2px solid currentColor;
      border-top-color: transparent;
      border-radius: 50%;
    }
    .power-symbol::after {
      content: "";
      position: absolute;
      left: 10px;
      top: 2px;
      height: 10px;
      border-left: 2px solid currentColor;
    }
    .top-icons { display: flex; align-items: center; gap: 14px; color: var(--text); font-weight: 800; }
    .top-icon {
      width: 24px;
      height: 24px;
      border: 2px solid var(--text);
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      line-height: 1;
    }
    .condition-title {
      display: flex;
      align-items: center;
      gap: 11px;
      font-size: 20px;
      font-weight: 800;
      color: var(--text);
      padding-bottom: 16px;
      margin-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }
    .condition-title .title-text {
      flex: 1 1 auto;
    }
    .icon-window-btn {
      width: 34px;
      height: 34px;
      min-height: 34px;
      padding: 0;
      border: 1px solid #9fc5d8;
      border-radius: 6px;
      background: #fff;
      color: #0b5ca8;
      box-shadow: 0 5px 14px rgba(21,83,150,.08);
      position: relative;
      z-index: 2;
    }
    .icon-window-btn::before {
      content: "";
      position: absolute;
      left: 9px;
      top: 9px;
      width: 13px;
      height: 13px;
      border: 2px solid currentColor;
      border-radius: 2px;
    }
    .icon-window-btn::after {
      content: "";
      position: absolute;
      right: 8px;
      top: 8px;
      width: 9px;
      height: 9px;
      border-top: 2px solid currentColor;
      border-right: 2px solid currentColor;
    }
    .icon-window-btn:hover {
      background: #eaf6fb;
    }
    .icon-window-btn:disabled {
      opacity: .45;
      cursor: default;
      background: #f4f8fb;
    }
    body.results-window .side,
    body.results-window .view-header,
    body.results-window .rda-card,
    body.results-window #analyzeBtn,
    body.results-window #stopAnalyzeBtn,
    body.results-window .toolbar-mode,
    body.results-window .toolbar > label,
    body.results-window #initializeBtn,
    body.results-window #summary,
    body.results-window #openResultsWindowBtn {
      display: none !important;
    }
    body.results-window {
      zoom: 1;
      width: 100%;
      min-height: 100vh;
      overflow: hidden;
    }
    body.results-window .app-shell {
      grid-template-columns: 1fr;
      height: 100vh;
      min-height: 100vh;
      overflow: hidden;
    }
    body.results-window .content {
      height: 100vh;
      min-height: 0;
      padding: 0;
      overflow: hidden;
    }
    body.results-window main {
      height: 100vh;
      min-height: 100vh;
      padding: 0;
      overflow: hidden;
    }
    body.results-window #rdaView.active {
      display: grid;
      grid-template-rows: max-content minmax(0, 1fr);
      height: 100vh;
      min-height: 0;
      overflow: hidden;
    }
    body.results-window .toolbar {
      margin: 10px 12px 8px;
      min-height: 62px;
      padding: 12px 20px;
      align-items: center;
      flex: 0 0 auto;
    }
    body.results-window .analysis-results-section {
      display: grid;
      grid-template-rows: minmax(0, 1fr);
      align-self: stretch;
      margin: 8px 12px 0;
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      overflow: var(--results-section-overflow, hidden);
      height: var(--results-section-height, 100%);
      min-height: 0;
    }
    body.results-window #summaryStrip {
      display: none !important;
    }
    body.results-window .analysis-results-section > .condition-title {
      display: none !important;
    }
    body.results-window .analysis-results-scroll {
      display: block;
      overflow: var(--results-scroll-overflow, auto);
      overflow-x: var(--results-scroll-overflow-x, hidden);
      overflow-y: var(--results-scroll-overflow-y, scroll);
      padding: 0;
      background: transparent;
      min-height: 0;
      height: var(--results-scroll-height, 100%);
    }
    body.results-window .analysis-filter-bar {
      display: grid;
      position: sticky;
      top: 0;
      z-index: 5;
      margin: 0 0 10px;
      padding: 14px 18px;
      gap: 8px 18px;
      border-radius: 8px;
      box-shadow: 0 7px 20px rgba(21,83,150,.08);
    }
    body.results-window .analysis-filter-bar:not(.active) {
      display: none;
    }
    body.results-window .filter-group {
      gap: 8px;
    }
    body.results-window .reliability-filter-group {
      flex: 1 1 100%;
    }
    body.results-window .temp-filter-group {
      flex: 0 1 auto;
      padding-left: 0;
    }
    body.results-window .filter-chip {
      min-width: 88px;
      min-height: 38px;
      font-size: 14px;
      font-weight: 800;
    }
    body.results-window .temp-filter-group .filter-chip {
      min-width: 70px;
      min-height: 30px;
      padding: 4px 10px;
      font-size: 12px;
    }
    body.results-window #passResultsGrid:not(.results-hidden) {
      display: grid;
      grid-template-columns: minmax(760px, 1.55fr) minmax(540px, 1fr);
      grid-template-rows: minmax(0, 1fr);
      grid-template-areas: none;
      gap: 10px;
      height: var(--results-grid-height, 100%);
      min-height: var(--results-grid-min-height, 0);
      align-items: stretch;
      padding: 0;
      border: 0;
      background: transparent;
      overflow: var(--results-grid-overflow, hidden);
    }
    body.results-window #passResultsGrid.results-hidden {
      display: none;
    }
    body.results-window .result-table-column,
    body.results-window .result-graph-column {
      display: grid;
      grid-area: auto;
      min-width: 0;
      min-height: 0;
      height: 100%;
      gap: 10px;
    }
    body.results-window .result-table-column > .panel,
    body.results-window .result-graph-column > .panel {
      grid-area: auto;
    }
    body.results-window .result-table-column {
      grid-template-rows: minmax(0, .85fr) minmax(0, .85fr) minmax(0, 1.15fr);
      padding: 0;
      border: 1px solid #d7e3f1;
      border-radius: 9px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(31,74,118,.06);
      overflow: hidden;
    }
    body.results-window .summary-panel { order: 1; }
    body.results-window .over-panel { order: 2; }
    body.results-window .detail-panel { order: 3; }
    body.results-window .result-graph-column {
      grid-template-rows: auto minmax(0, 1fr) minmax(0, .9fr);
      overflow: hidden;
    }
    body.results-window .fail-layout .result-table-column {
      grid-template-rows: minmax(0, .85fr) minmax(0, .85fr) minmax(0, 1.15fr);
    }
    body.results-window .fail-layout .result-graph-column {
      grid-template-rows: auto minmax(0, 1fr) minmax(0, .9fr);
    }
    body.results-window .results-window-title {
      display: none !important;
    }
    body.results-window .panel {
      border-radius: 8px;
      box-shadow: 0 8px 22px rgba(31,74,118,.07);
      min-height: 0;
      overflow: hidden;
    }
    body.results-window .panel h2 {
      min-height: 42px;
      padding: 10px 18px;
      font-size: 16px;
      flex: 0 0 auto;
    }
    body.results-window .chart-box,
    body.results-window .scatter-box,
    body.results-window .wafer-box {
      min-height: 0;
      padding: 8px 12px 12px;
    }
    body.results-window .over-panel {
      display: flex !important;
    }
    body.results-window .chart-panel,
    body.results-window .diff-cdf-panel,
    body.results-window .ppf-panel,
    body.results-window .scatter-panel {
      display: none;
    }
    body.results-window .chart-panel.active-graph,
    body.results-window .diff-cdf-panel.active-graph,
    body.results-window .ppf-panel.active-graph,
    body.results-window .scatter-panel.active-graph,
    body.results-window .wafer-panel {
      display: flex;
    }
    body.results-window .table-wrap {
      flex: 1 1 auto;
      min-height: 0;
      overflow-x: auto;
      overflow-y: scroll;
    }
    body.results-window table {
      min-width: 100%;
      table-layout: fixed;
    }
    body.results-window th,
    body.results-window td {
      height: 36px;
      padding: 7px 10px;
      font-size: 13px;
    }
    body.results-window #resultTable {
      min-width: 1680px;
      table-layout: auto;
    }
    body.results-window #resultTable th,
    body.results-window #resultTable td {
      width: auto !important;
    }
    body.results-window .detail-panel .table-wrap {
      overflow-x: hidden;
    }
    body.results-window #detailTable {
      width: 100%;
      min-width: 0;
      table-layout: fixed;
    }
    body.results-window #detailTable th,
    body.results-window #detailTable td {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    body.results-window #detailTable th {
      line-height: 1.15;
      white-space: normal;
      word-break: keep-all;
    }
    body.results-window #detailTable th:nth-child(1),
    body.results-window #detailTable td:nth-child(1) { width: 7.5%; }
    body.results-window #detailTable th:nth-child(2),
    body.results-window #detailTable td:nth-child(2) { width: 7%; }
    body.results-window #detailTable th:nth-child(3),
    body.results-window #detailTable td:nth-child(3) { width: 12%; }
    body.results-window #detailTable th:nth-child(4),
    body.results-window #detailTable td:nth-child(4) { width: 8.5%; }
    body.results-window #detailTable th:nth-child(5),
    body.results-window #detailTable td:nth-child(5) { width: 8.5%; }
    body.results-window #detailTable th:nth-child(6),
    body.results-window #detailTable td:nth-child(6) { width: 8.5%; }
    body.results-window #detailTable th:nth-child(7),
    body.results-window #detailTable td:nth-child(7) { width: 8.5%; }
    body.results-window #detailTable th:nth-child(8),
    body.results-window #detailTable td:nth-child(8) { width: 6%; }
    body.results-window #detailTable th:nth-child(9),
    body.results-window #detailTable td:nth-child(9) { width: 9%; }
    body.results-window #detailTable th:nth-child(10),
    body.results-window #detailTable td:nth-child(10) { width: 8%; }
    body.results-window #detailTable th:nth-child(11),
    body.results-window #detailTable td:nth-child(11) { width: 8%; }
    body.results-window #detailTable th:nth-child(12),
    body.results-window #detailTable td:nth-child(12) { width: 8.5%; }
    body.results-window #overTable th:nth-child(1),
    body.results-window #overTable td:nth-child(1) { width: 9%; }
    body.results-window #overTable th:not(:first-child),
    body.results-window #overTable td:not(:first-child) { width: 22%; }
    body.results-window .chart-tools {
      padding: 10px 18px;
      gap: 14px;
    }
    body.results-window .graph-item-toolbar {
      display: flex;
      align-items: center;
      min-height: 52px;
      border: 1px solid #d7e3f1;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(31,74,118,.07);
    }
    body.results-window .chart-tools select {
      min-width: 56%;
      height: 36px;
      font-size: 15px;
    }
    body.results-window .graph-filter-bar {
      display: flex;
      min-height: 42px;
      padding: 8px 12px;
    }
    body.results-window .graph-filter-bar:not(.active) {
      display: none;
    }
    .filter-icon {
      width: 18px;
      height: 18px;
      border: 2px solid #0077ff;
      border-top: 0;
      transform: perspective(12px) rotateX(-24deg);
      clip-path: polygon(0 0, 100% 0, 62% 48%, 62% 100%, 38% 100%, 38% 48%);
    }
    .toolbar-mode {
      display: inline-flex;
      border: 1px solid #0a7890;
      border-radius: 5px;
      overflow: hidden;
      height: 42px;
    }
    .toolbar-mode button {
      display: inline-flex;
      align-items: center;
      padding: 0 30px;
      font-weight: 700;
      color: var(--text);
      background: #fff;
      border: 0;
      border-radius: 0;
      height: 100%;
    }
    .toolbar-mode button.active {
      background: linear-gradient(180deg, #078c99, #05717f);
      color: #fff;
    }
    .result-tab-groups {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      padding: 9px 16px;
      border-radius: 13px;
      background: #dff5e8;
      color: #178044;
      font-weight: 800;
    }
    .panel-label { display: inline-flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 auto; }
    .flag-alpha-label { font-weight: 400; font-size: 12px; color: var(--muted); }
    .column-toggle-wrap { position: relative; flex: 0 0 auto; }
    .column-toggle-btn {
      background: #eef6fa;
      color: #0b6070;
      border: 1px solid #bdd3df;
      border-radius: 13px;
      padding: 5px 12px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .column-toggle-btn:hover { background: #e0eef4; }
    .column-toggle-menu {
      display: none;
      position: absolute;
      top: calc(100% + 6px);
      right: 0;
      z-index: 20;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(20, 40, 70, 0.15);
      padding: 8px;
      min-width: 160px;
      max-height: 280px;
      overflow-y: auto;
    }
    .column-toggle-menu.open { display: block; }
    .column-toggle-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 5px 6px;
      font-size: 13px;
      font-weight: 400;
      color: var(--text);
      cursor: pointer;
      white-space: nowrap;
    }
    .column-toggle-item:hover { background: #f4f8fb; border-radius: 4px; }
    #cdfPanelTitle,
    #diffCdfPanelTitle,
    #scatterPanelTitle {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .panel-icon {
      width: 20px;
      height: 20px;
      position: relative;
      display: inline-block;
      color: var(--text);
      flex: 0 0 auto;
    }
    .latest-date {
      margin-left: auto;
      white-space: nowrap;
      font-weight: 700;
    }
    .icon-summary::before {
      content: "";
      position: absolute;
      left: 2px;
      top: 4px;
      width: 3px;
      height: 3px;
      background: currentColor;
      box-shadow: 0 6px 0 currentColor, 0 12px 0 currentColor, 6px 0 0 currentColor, 6px 6px 0 currentColor, 6px 12px 0 currentColor, 12px 0 0 currentColor, 12px 6px 0 currentColor, 12px 12px 0 currentColor;
    }
    .icon-detail::before {
      content: "";
      position: absolute;
      inset: 2px 4px;
      border: 2px solid currentColor;
      border-radius: 2px;
    }
    .icon-detail::after {
      content: "";
      position: absolute;
      left: 8px;
      top: 7px;
      width: 8px;
      border-top: 2px solid currentColor;
      box-shadow: 0 5px 0 currentColor;
    }
    .icon-sample::before {
      content: "";
      position: absolute;
      left: 4px;
      top: 2px;
      width: 12px;
      height: 16px;
      border: 2px solid currentColor;
      border-top: 0;
      clip-path: polygon(35% 0, 65% 0, 65% 35%, 100% 100%, 0 100%, 35% 35%);
    }
    .icon-cdf::before {
      content: "";
      position: absolute;
      left: 2px;
      bottom: 3px;
      width: 16px;
      height: 13px;
      border-left: 2px solid currentColor;
      border-bottom: 2px solid currentColor;
    }
    .icon-cdf::after {
      content: "";
      position: absolute;
      left: 4px;
      top: 5px;
      width: 13px;
      height: 9px;
      border-top: 2px solid currentColor;
      border-radius: 50%;
      transform: rotate(-18deg);
    }
    .icon-scatter::before {
      content: "";
      position: absolute;
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: currentColor;
      left: 4px;
      top: 12px;
      box-shadow: 5px -6px 0 currentColor, 10px -2px 0 currentColor, 13px -10px 0 currentColor;
    }
    .panel-actions { display: inline-flex; gap: 14px; color: var(--text); font-size: 20px; letter-spacing: 2px; }
    .copy-chart-btn {
      border: 1px solid #9fc5d8;
      background: #fff;
      color: var(--head);
      border-radius: 6px;
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
    }
    .copy-chart-btn:hover { background: #eaf6fb; }
    body {
      background:
        radial-gradient(circle at 86% 5%, rgba(17, 134, 206, .10), transparent 24%),
        linear-gradient(180deg, #f8fbff 0%, #f3f7fc 100%);
      color: #10305f;
    }
    .app-shell {
      grid-template-columns: 354px minmax(0, 1fr);
      background: transparent;
    }
    .side {
      padding: 0 18px;
      background: linear-gradient(180deg, #004fae 0%, #092f8f 48%, #302c91 100%);
      box-shadow: inset -1px 0 0 rgba(255,255,255,.08), 12px 0 34px rgba(28,70,136,.10);
    }
    .side-title {
      padding: 28px 0 26px;
      margin-bottom: 24px;
      border-bottom: 1px solid rgba(255,255,255,.20);
    }
    .brand-text strong { font-size: 21px; font-weight: 800; }
    .brand-text small { margin-top: 5px; font-size: 13px; color: rgba(255,255,255,.88); }
    .tree { gap: 18px; }
    .tree-parent {
      min-height: 36px;
      padding: 6px 0;
      font-weight: 800;
      color: rgba(255,255,255,.96);
    }
    .tree-children {
      margin-left: 14px;
      padding-left: 18px;
      border-left: 1px solid rgba(114, 204, 255, .45);
    }
    .tree-child {
      min-height: 32px;
      gap: 9px;
    }
    .tree-dot {
      width: 7px;
      height: 7px;
      background: #34d6ff;
      box-shadow: 0 0 12px rgba(52,216,255,.70);
    }
    .side-link,
    .tree-link {
      color: rgba(255,255,255,.94);
      border-radius: 18px;
      font-weight: 700;
    }
    .side-link:hover,
    .side-link.active,
    .tree-link:hover,
    .tree-link.active {
      background: linear-gradient(90deg, #14b9e9, #176fe0);
      box-shadow: inset 4px 0 0 rgba(60,235,255,.85), 0 8px 20px rgba(1,87,187,.35);
      color: #fff;
    }
    .side-exit {
      border-top: 1px solid rgba(255,255,255,.18);
      padding-bottom: 28px;
    }
    .content {
      padding: 36px 34px 28px;
      background:
        radial-gradient(circle at 96% 0%, rgba(25,124,212,.10), transparent 28%),
        #f8fbff;
    }
    .view-header {
      margin-bottom: 26px;
    }
    .view-title {
      color: #063b7c;
      font-size: 30px;
      line-height: 1.1;
      font-weight: 900;
    }
    .view-subtitle {
      margin-top: 12px;
      color: #122d58;
      font-size: 14px;
      font-weight: 500;
    }
    .path-tools {
      gap: 12px;
    }
    .path-tools strong {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-height: 28px;
      color: #082a58;
      font-weight: 900;
    }
    .path-tools strong::before {
      content: "";
      width: 17px;
      height: 13px;
      border: 2px solid #0e5aa8;
      border-radius: 2px;
      transform: translateY(1px);
      box-shadow: 4px -5px 0 -3px #0e5aa8;
    }
    .path-tools {
      padding: 8px 10px 8px 14px;
      border: 1px solid #d8e4f1;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 24px rgba(28,70,136,.08);
    }
    .path-tools .status {
      min-width: 360px;
      max-width: 520px;
      border: 0;
      padding: 8px 4px;
      color: #17345f;
      background: transparent;
      font-size: 12px;
    }
    .top-icons {
      margin-left: 10px;
      gap: 10px;
    }
    .top-icon {
      width: 32px;
      height: 32px;
      border: 1px solid #c8d8ea;
      background: #fff;
      color: #102f61;
      box-shadow: 0 6px 18px rgba(28,70,136,.10);
    }
    .rda-card,
    .toolbar,
    .analysis-results-section {
      border: 1px solid #d8e4f1;
      border-radius: 10px;
      background: rgba(255,255,255,.96);
      box-shadow: 0 10px 30px rgba(28,70,136,.08);
    }
    .rda-card {
      padding: 0;
      overflow: hidden;
    }
    .rda-card .condition-title,
    .analysis-results-section > .condition-title {
      margin: 0;
      padding: 20px 26px;
      color: #073d81;
      font-size: 20px;
      background:
        linear-gradient(104deg, rgba(229,247,255,.98) 0%, rgba(255,255,255,.98) 28%, rgba(255,255,255,.96) 100%);
      border-bottom: 1px solid #dce8f4;
      position: relative;
      overflow: hidden;
    }
    .rda-card .condition-title::after,
    .analysis-results-section > .condition-title::after {
      content: "";
      position: absolute;
      right: 16px;
      top: 12px;
      width: 72px;
      height: 52px;
      opacity: .30;
      background-image: radial-gradient(#2cc6eb 1px, transparent 1px);
      background-size: 10px 10px;
      pointer-events: none;
    }
    .filter-icon {
      width: 22px;
      height: 22px;
      border-color: #0fa4d1;
    }
    .rda-form {
      padding: 22px 34px 26px;
      gap: 18px 34px;
    }
    .field label {
      color: #68758a;
      font-size: 12px;
      font-weight: 700;
    }
    .field input,
    .field select,
    select {
      border: 1px solid #ccd9ea;
      border-radius: 6px;
      min-height: 40px;
      color: #0d2448;
      background: linear-gradient(180deg, #fff, #fbfdff);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.80);
    }
    .toolbar {
      min-height: 76px;
      padding: 16px 20px;
      gap: 20px;
      overflow: hidden;
    }
    button {
      border-radius: 6px;
      min-height: 36px;
      box-shadow: 0 5px 14px rgba(21,83,150,.08);
    }
    button.primary {
      background: linear-gradient(180deg, #1d75df 0%, #0d56bf 100%);
      border-color: #0d56bf;
    }
    button.secondary {
      background: #fff;
      color: #1e4e87;
      border-color: #c9d9eb;
    }
    .toolbar-mode {
      height: 38px;
      border: 1px solid #c8d8ea;
      border-radius: 6px;
      box-shadow: 0 5px 14px rgba(21,83,150,.08);
    }
    .toolbar-mode button {
      padding: 0 24px;
      color: #0b356f;
      background: #fff;
    }
    .toolbar-mode button.active {
      background: linear-gradient(180deg, #11b7b5, #008f88);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.35);
    }
    .status-pill {
      border-radius: 9px;
      padding: 8px 18px;
      background: #d8f5df;
      color: #14783a;
    }
    .latest-date {
      color: #5a6680;
    }
    .analysis-results-section {
      padding: 0;
      overflow: hidden;
    }
    .analysis-results-scroll {
      padding: 14px;
      background: #fbfdff;
    }
    .grid {
      gap: 16px;
    }
    .panel {
      border: 1px solid #d7e3f1;
      border-radius: 9px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(28,70,136,.07);
    }
    .panel h2 {
      min-height: 48px;
      padding: 13px 18px;
      background: linear-gradient(180deg, #ffffff, #f6f9fd);
      color: #0b438c;
      border-bottom: 1px solid #dce8f4;
      font-size: 15px;
      font-weight: 900;
    }
    .panel-icon {
      color: #0968bd;
    }
    body.results-window #passResultsGrid:not(.results-hidden) {
      display: grid;
    }
    body.results-window #passResultsGrid.results-hidden {
      display: none;
    }
    body.results-window .chart-box,
    body.results-window .scatter-box {
      min-height: 0;
    }
    th {
      background: linear-gradient(180deg, #10aaa5, #078a87);
      border-color: #49bdb8;
      color: #fff;
      font-weight: 800;
    }
    td {
      border-color: #dbe5f1;
      color: #14294a;
      background: #fff;
    }
    tr:nth-child(even) td {
      background: #fbfdff;
    }
    .chart-tools {
      padding: 10px 14px;
      background: #fff;
      border-bottom: 1px solid #edf2f8;
    }
    .copy-chart-btn {
      border-color: #91bff1;
      color: #1266c8;
      border-radius: 5px;
      background: #fff;
      flex: 0 0 auto;
    }
    .panel-actions {
      color: #0d4f99;
      font-size: 16px;
    }
    body {
      zoom: 1;
      width: auto;
      max-width: 100%;
      min-height: 100vh;
      overflow-x: hidden;
      font-size: 14px;
    }
    main,
    .app-shell,
    .side {
      min-height: 100vh;
    }
    main,
    .app-shell,
    .content,
    #rdaView {
      max-width: 100%;
      overflow-x: hidden;
    }
    .app-shell {
      grid-template-columns: 280px minmax(0, 1fr);
    }
    .content {
      height: 100vh;
      padding: 28px 30px 22px;
    }
    .view-title {
      font-size: 28px;
    }
    .view-subtitle {
      margin-top: 8px;
      font-size: 13px;
    }
    .brand-text strong {
      font-size: 22px;
    }
    .brand-text small,
    .side-link,
    .tree-link,
    .tree-parent {
      font-size: 14px;
      line-height: 1.18;
    }
    .path-tools .status,
    .field label,
    .latest-date,
    .status,
    .copy-chart-btn {
      font-size: 13px;
    }
    .field input,
    .field select,
    select,
    button,
    .toolbar-mode button {
      font-size: 13px;
    }
    .condition-title,
    .rda-card .condition-title,
    .analysis-results-section > .condition-title {
      font-size: 20px;
    }
    .panel h2 {
      font-size: 15px;
    }
    th,
    td {
      font-size: 13px;
      padding: 6px 8px;
    }
    .toolbar {
      font-size: 13px;
      min-width: 0;
      flex-wrap: nowrap;
      gap: 12px;
      min-height: 60px;
      padding: 12px 18px;
    }
    .toolbar > label {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
      line-height: 1.15;
    }
    .raw-export-btn {
      margin-left: auto;
      flex: 0 0 auto;
      white-space: nowrap;
      min-width: 132px;
    }
    .toolbar #summary {
      flex: 1 1 210px;
      min-width: 150px;
      line-height: 1.35;
    }
    .toolbar-mode {
      height: 36px;
      flex: 0 0 auto;
    }
    .toolbar-mode button {
      width: 166px;
      min-height: 0;
      padding: 0 12px;
      justify-content: center;
      text-align: center;
      line-height: 1.12;
      white-space: normal;
    }
    #resultTabBar, #resultViewBar {
      flex-wrap: nowrap;
    }
    #resultTabBar button, #resultViewBar button {
      width: auto;
      flex: 1 1 0;
      min-width: 0;
      padding: 0 8px;
    }
    button {
      min-height: 34px;
      padding: 6px 12px;
      line-height: 1.15;
      white-space: normal;
    }
    #analyzeBtn {
      width: 84px;
      min-height: 44px;
      padding: 6px 10px;
    }
    #stopAnalyzeBtn {
      width: 64px;
    }
    #initializeBtn {
      width: 126px;
      min-height: 44px;
    }
    .status-pill {
      font-size: 13px;
      padding: 7px 14px;
      white-space: nowrap;
    }
    .latest-date {
      flex: 0 0 auto;
      margin-left: 0;
    }
    .field input,
    .field select {
      min-height: 36px;
      padding: 8px 12px;
    }
    .rda-card .condition-title,
    .analysis-results-section > .condition-title {
      padding: 18px 24px;
    }
    .rda-form {
      padding: 20px 30px 24px;
      gap: 16px 28px;
    }
    .side {
      padding: 0 18px;
    }
    .side-title {
      padding: 26px 0 22px;
    }
    .tree-link {
      padding: 5px 8px;
    }
    @media (max-width: 1100px) {
      main { padding: 14px; }
      .app-shell { grid-template-columns: 1fr; }
      .side { min-height: auto; border-right: 0; border-bottom: 2px solid var(--head-dark); display: block; overflow-x: auto; padding: 0 14px 14px; }
      .side-title { min-width: 190px; margin-bottom: 0; font-size: 22px; }
      .tree { min-width: 720px; flex-direction: row; align-items: flex-start; }
      .side-link, .tree-link { white-space: nowrap; }
      .content { padding: 14px; }
      .view-header { align-items: flex-start; flex-direction: column; }
      .path-tools { width: 100%; justify-content: flex-start; }
      .path-tools .status { min-width: 0; max-width: 100%; flex: 1; }
      .dashboard-band { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .rda-form { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
      .files { grid-template-columns: 90px 1fr; }
      .grid {
        grid-template-columns: 1fr;
        grid-template-rows: 380px 380px 340px 420px 420px;
        grid-template-areas:
          "summary"
          "detail"
          "over"
          "chart"
          "scatter";
      }
    }
  </style>
</head>
<body>
  <main>
    <section class="app-shell">
      <nav class="side">
        <h1 class="side-title">
          <span class="brand-mark"><span></span><span></span><span></span><span></span></span>
          <span class="brand-text"><strong data-label-key="brand">Work Manager</strong><small>Automation Suite</small></span>
        </h1>
        <div class="tree">
          <div class="tree-group">
            <div class="tree-parent">
              <button class="side-link" data-view="managerView"><span class="nav-symbol home-symbol"></span><span data-label-key="dashboard">Dashboard</span></button>
            </div>
          </div>
          <div class="tree-group">
            <div class="tree-parent"><span class="tree-icon"></span><span data-label-key="reliability">Reliability</span></div>
            <div class="tree-children">
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link active" data-view="rdaView"><span data-label-key="rda">Reliability Data Analysis</span></button></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="schedule">Schedule Management</span></button><span class="badge-wip">준비 중</span></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="final">Final Result</span></button><span class="badge-wip">준비 중</span></div>
            </div>
          </div>
          <div class="tree-group">
            <div class="tree-parent"><span class="tree-icon"></span><span data-label-key="iso">ISO 26262</span></div>
            <div class="tree-children">
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" data-view="fsView"><span data-label-key="fs">FS Deliverables Management</span></button></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="deliverables">Deliverables Status</span></button><span class="badge-wip">준비 중</span></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="matrix">Traceability Matrix</span></button><span class="badge-wip">준비 중</span></div>
            </div>
          </div>
          <div class="tree-group">
            <div class="tree-parent"><span class="tree-icon"></span><span data-label-key="rma">RMA</span></div>
            <div class="tree-children">
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" data-view="reportView"><span data-label-key="report">8D Report</span></button></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="action">Action Tracking</span></button><span class="badge-wip">준비 중</span></div>
              <div class="tree-child"><span class="tree-dot"></span><button class="tree-link" type="button" disabled><span data-label-key="effect">Effectiveness Check</span></button><span class="badge-wip">준비 중</span></div>
            </div>
          </div>
        </div>
        <div class="side-exit">
          <div class="side-exit-row">
            <button class="side-link" type="button" disabled><span class="nav-symbol gear-symbol"></span><span data-label-key="settings">Settings</span></button>
            <span class="badge-wip">준비 중</span>
          </div>
          <button id="exitBtn" class="side-link exit-button" type="button"><span class="nav-symbol power-symbol"></span><span>Exit Tool</span></button>
        </div>
      </nav>
      <div class="content">
        <section id="managerView" class="view">
          <div class="manager-section">
            <h2>On-Going RMA Status</h2>
            <div class="table-wrap">
              <table class="status-table">
                <thead><tr><th>RMA No.</th><th>Customer</th><th>Device</th><th>Ver.</th><th>Issued Phenomenon</th><th>Sample Received Date</th><th>WF Lot No. & WF #</th><th>Ass'y Lot No</th><th>Non_Destructive Analysis</th><th>Bench</th><th>FT</th><th>Design Analysis</th><th>PFA</th><th>Report Issue Data</th></tr></thead>
                <tbody>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <div class="manager-section">
            <h2>On-Going Reliability Status</h2>
            <div class="table-wrap">
              <table class="status-table">
                <thead><tr><th>Device</th><th>Ver.</th><th>Qual. Type</th><th>Purpose</th><th>Issued Phenomenon</th><th>Sample Received Date</th><th>WF Lot No. & WF #</th><th>Ass'y Lot No</th><th>Non_Destructive Analysis</th><th>Bench</th><th>FT</th><th>Design Analysis</th><th>PFA</th><th>Report Issue</th></tr></thead>
                <tbody>
                  <tr><td>SM3502Q</td><td>MVT1-2</td><td>AEC-Q100</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                  <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
        <section id="rdaView" class="view active">
          <div class="view-header">
            <div><h2 class="view-title">Reliability Data Analysis</h2><div class="view-subtitle">Reliability Data Analyzer___APP_REVISION__</div></div>
            <div class="path-tools"><strong>Data Path:</strong><span class="status" id="dataPath">-</span><button id="browseDataPathBtn" class="secondary" type="button">Browse...</button></div>
          </div>
          <section class="rda-card condition-card" id="conditionCard">
            <button type="button" class="condition-title condition-toggle" id="conditionToggle" aria-expanded="true" aria-controls="conditionBody">
              <span class="filter-icon"></span><span class="title-text">1. Analysis Condition &amp; Execution</span>
              <span class="condition-summary-line" id="conditionSummaryLine"></span>
              <span class="condition-toggle-caret" id="conditionToggleCaret" aria-hidden="true">▾</span>
            </button>
            <div class="condition-body" id="conditionBody">
              <div class="rda-form">
                <div class="field"><label>Device</label><input id="deviceInput" type="text" list="deviceOptions" placeholder="SM3502Q"><datalist id="deviceOptions"></datalist></div>
                <div class="field"><label>Ver.</label><select id="verSelect"></select></div>
                <div class="field"><label>Lot No.</label><select id="lotSelect"></select></div>
                <div class="field"><label>Purpose</label><select id="purposeSelect"></select></div>
                <div class="field"><label>Reliability Items</label><select id="reliabilityItemSelect"></select></div>
                <div class="field"><label>Read-out</label><select id="readoutSelect"></select></div>
                <div class="field"><label>FT Temp.</label><select id="ftTempSelect"></select></div>
              </div>
            </div>
          </section>
        <section class="toolbar condition-attached" id="executionToolbar">
          <button id="analyzeBtn" class="primary">▶ &nbsp;Analyze</button>
          <button id="stopAnalyzeBtn" class="secondary" type="button" disabled>Stop</button>
          <label><input id="includePreCheck" type="checkbox" checked> Including Pre</label>
          <button id="initializeBtn" class="secondary" type="button">Analysis Initialization</button>
          <strong>Status:</strong><span class="status-pill" id="status">Ready</span>
          <span class="status" id="summary"></span>
          <span class="status latest-date" id="latestAnalysisDate">Latest Analysis Date: -</span>
          <button id="rawExportBtn" class="secondary raw-export-btn" type="button" disabled>Raw Data Export</button>
        </section>
        <section class="analysis-results-section">
          <div class="condition-title"><span class="filter-icon"></span><span class="title-text">2. Analysis Results</span><button id="openResultsWindowBtn" class="icon-window-btn" type="button" title="Open Analysis Results in a new window" disabled></button></div>
          <div class="analysis-results-scroll">
        <section id="summaryStrip" class="summary-strip"></section>
        <section id="analysisFilterBar" class="analysis-filter-bar"></section>
        <section id="passResultsGrid" class="grid results-hidden">
      <div class="result-table-column">
      <div class="condition-title results-window-title"><span class="filter-icon"></span><span class="title-text">2. Analysis Results</span></div>
      <section class="panel summary-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-summary"></span>Abnormal Shift Items (Mea_S or Diff_S &gt; Grubbs threshold)<span id="flagAlphaLabel" class="flag-alpha-label"></span></span><div class="column-toggle-wrap" id="columnToggleWrap"><button id="columnToggleBtn" class="column-toggle-btn" type="button">＋ 열</button><div id="columnToggleMenu" class="column-toggle-menu"></div></div></h2>
        <div class="result-tab-groups">
          <div class="toolbar-mode result-tab-bar" id="resultTabBar">
            <button id="failModeBtn" type="button" data-mode="fail">Fail 항목 List</button>
            <button id="passModeBtn" class="active" type="button" data-mode="pass">Abnormal Pass Data</button>
          </div>
          <div class="toolbar-mode result-view-bar" id="resultViewBar">
            <button id="itemViewBtn" class="active" type="button" data-view="item">항목 기준</button>
            <button id="sampleViewBtn" type="button" data-view="sample">샘플 기준</button>
          </div>
        </div>
        <div class="table-wrap" id="resultTableWrap"><table id="resultTable"></table></div>
        <div class="table-wrap" id="overSampleTableWrap"><table id="overSampleTable"></table></div>
      </section>
      <section class="panel over-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-sample"></span>Abnormal Shift Sample</span></h2>
        <div class="table-wrap"><table id="overTable"></table></div>
      </section>
      <section class="panel detail-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-detail"></span>Abnormal Shift Details</span></h2>
        <div class="table-wrap"><table id="detailTable"></table></div>
      </section>
      </div>
      <div class="result-graph-column">
      <div class="chart-tools graph-item-toolbar">
        <label>Test Item</label>
        <select id="itemSelect"></select>
        <span class="status" id="itemThresholdLabel"></span>
      </div>
      <section class="panel chart-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-cdf"></span><span id="cdfPanelTitle">CDF Distribution</span></span><button class="copy-chart-btn" type="button" data-canvas="cdfCanvas">Copy</button></h2>
        <div class="chart-box"><canvas id="cdfCanvas"></canvas></div>
      </section>
      <section class="panel diff-cdf-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-cdf"></span><span id="diffCdfPanelTitle">Diff. CDF Distribution</span></span><button class="copy-chart-btn" type="button" data-canvas="diffCdfCanvas">Copy</button></h2>
        <div class="chart-box"><canvas id="diffCdfCanvas"></canvas></div>
      </section>
      <section class="panel ppf-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-cdf"></span><span id="ppfPanelTitle">Standard Normal Distribution</span></span><button class="copy-chart-btn" type="button" data-canvas="ppfCanvas">Copy</button></h2>
        <div class="chart-box"><canvas id="ppfCanvas"></canvas></div>
      </section>
      <section class="panel scatter-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-scatter"></span><span id="scatterPanelTitle">Scattered Plot</span></span><button class="copy-chart-btn" type="button" data-canvas="scatterCanvas">Copy</button></h2>
        <div class="scatter-box"><canvas id="scatterCanvas"></canvas></div>
      </section>
      <section class="panel wafer-panel">
        <h2><span class="panel-label">Wafer No. &amp; Wafer Map</span></h2>
        <div class="wafer-box"><canvas id="waferCanvas"></canvas></div>
      </section>
      </div>
        </section>
          </div>
        </section>
        </section>
        <section id="fsView" class="view">
          <div class="view-header"><h2 class="view-title">FS Deliverables Management</h2><span class="status">Ready</span></div>
          <div class="manager-section"><h2>Deliverables Status</h2><div class="table-wrap"><table class="status-table"><thead><tr><th>Device</th><th>Version</th><th>Owner</th><th>Document</th><th>Status</th><th>Due Date</th><th>Remark</th></tr></thead><tbody><tr><td>SM3502Q</td><td>MVT1-2</td><td></td><td>FS</td><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr><tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr></tbody></table></div></div>
        </section>
        <section id="reportView" class="view">
          <div class="view-header"><h2 class="view-title">8D Report</h2><span class="status">Ready</span></div>
          <div class="manager-section"><h2>8D Report Status</h2><div class="table-wrap"><table class="status-table"><thead><tr><th>Issue No.</th><th>Customer</th><th>Device</th><th>Owner</th><th>D-Step</th><th>Status</th><th>Report Issue Date</th></tr></thead><tbody><tr><td></td><td></td><td>SM3502Q</td><td></td><td>D1</td><td></td><td></td></tr><tr><td></td><td></td><td></td><td></td><td>D2</td><td></td><td></td></tr><tr><td></td><td></td><td></td><td></td><td>D3</td><td></td><td></td></tr></tbody></table></div></div>
        </section>
      </div>
    </section>
  </main>
<script>
let analysis = null;
let itemCache = {};
let selectedItem = "";
let highlightSample = null;
let highlightMode = null;
let sortState = { column: "severity", reverse: true };
let detailSortState = { column: null, reverse: false };
let analysisMode = "pass";
let resultViewMode = "item";
let modePayloads = {};
let stopAnalysisRequested = false;
let activeAnalysisRunId = "";
let activeGraphTab = "cdf";
let needBenchState = {};
let pendingItemLoads = {};
let analysisFilters = {
  reliability_item: "",
  ft_temp_multi: false,
  ft_temps: { Room: true, Hot: false, Cold: false },
  readouts: { pre_t0: true, post_t1: true, post_t2: true, post_t3: true },
  fail_exception: false
};
const isResultsWindow = window.location.pathname === "/results-window";

function chartPixelRatio() {
  return Math.max(2, Math.min(4, (window.devicePixelRatio || 1) * 2));
}

function setupHiResCanvas(canvas, minWidth, minHeight) {
  const box = canvas.parentElement.getBoundingClientRect();
  // 박스가 0(숨김 상태)일 때만 minWidth/minHeight 로 폴백한다.
  // 기존처럼 Math.max(min, box) 를 쓰면 박스가 min 보다 작을 때
  // canvas{width:100%;height:100%} 에 의해 그림이 눌리거나 잘린다.
  const width  = Math.max(80, Math.floor(box.width)  || minWidth);
  const height = Math.max(80, Math.floor(box.height) || minHeight);
  const ratio = chartPixelRatio();
  canvas.width  = Math.floor(width  * ratio);
  canvas.height = Math.floor(height * ratio);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, w: width, h: height, ratio };
}

function itemUnitForGraph(data) {
  const detailUnit = (data?.details || []).map(row => row?.unit).find(unit => String(unit || "").trim());
  return String(data?.unit || detailUnit || "").trim();
}
function isBinaryGraphItem(data) {
  const unit = itemUnitForGraph(data).toLowerCase().replace(/[^a-z0-9]/g, "");
  return unit === "binary" || unit === "binnary";
}
function drawGraphNotice(canvas, message, minWidth = 360, minHeight = 260) {
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, minWidth, minHeight);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#50627c";
  ctx.font = "700 14px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(message, w / 2, h / 2);
}
function drawBinaryGraphNotice(canvas, minWidth = 360, minHeight = 260) {
  drawGraphNotice(canvas, "Binary unit item is excluded from graph display.", minWidth, minHeight);
}
const passColumns = [
  ["test_number", "Test No."], ["item", "Item"], ["reason", "Reason"], ["n", "N (σ n-1)"], ["unit", "Unit"], ["lower_limit", "LL"],
  ["upper_limit", "UL"], ["avg", "Avg."], ["stdev", "Stdev. (n-1)"], ["shift", "Shift"], ["shift_sigma", "Shift/σ"],
  ["diff_mean", "Δ Mean"], ["min", "Min."], ["max", "Max."], ["severity", "Max |σ|"], ["qty", "Q'ty"], ["qty_ratio", "%"],
  ["sample_numbers", "Sample No."]
];
// Fail 목록은 규격 이탈로 이미 선별된 항목이라 Reason/Max |σ| (Pass 전용 판정 근거) 가
// 없다 -- 값 없는 열을 N/A 로 채우는 대신 아예 목록에서 뺀다. 대신 이탈 유형(fail_type)과
// 시험(reliability_item) 을 추가한다.
const failColumns = [
  ["test_number", "Test No."], ["reliability_item", "시험"], ["item", "Item"], ["fail_type", "이탈 유형"],
  ["n", "N (σ n-1)"], ["qty", "Q'ty"], ["sample_numbers", "Sample No."]
];
const DEFAULT_VISIBLE_COLUMNS_PASS = ["test_number", "item", "reason", "n", "severity", "qty"];
const DEFAULT_VISIBLE_COLUMNS_FAIL = failColumns.map(([key]) => key);
const columnVisibility = {
  pass: new Set(DEFAULT_VISIBLE_COLUMNS_PASS),
  fail: new Set(DEFAULT_VISIBLE_COLUMNS_FAIL)
};
const reliabilityItems = ["HTOL", "HAST", "uHAST", "TC", "PTC", "HTSL", "HBM", "CDM", "LU"];
const AUTO_LATEST_READOUT = "__latest__";
const lookupOrder = [
  ["ver", "verSelect"],
  ["lot", "lotSelect"],
  ["purpose", "purposeSelect"],
  ["item", "reliabilityItemSelect"],
  ["readout", "readoutSelect"],
  ["ft_temp", "ftTempSelect"]
];
const lookupState = { device: "", ver: "", purpose: "", lot: "", item: "", readout: "", ft_temp: "" };
function normalizedAnalysisSelection(extra = {}) {
  const payload = { ...lookupState, ...extra };
  const hasBaseSelection = ["device", "ver", "purpose", "lot"].every(key => (payload[key] || "").trim());
  const hasCompleteDetailSelection = ["item", "readout", "ft_temp"].every(key => (payload[key] || "").trim());
  if (hasBaseSelection && !hasCompleteDetailSelection) {
    payload.item = "";
    payload.readout = "";
    payload.ft_temp = "";
  }
  return payload;
}
let dataRootPath = "";

function setStatus(text) {
  const target = document.getElementById("status") || document.getElementById("dataPath");
  if (target) target.textContent = text;
}
function updateReliabilityTabs() {
  const active = analysisFilters.reliability_item || "";
  document.querySelectorAll("#analysisFilterBar .item-tab").forEach(button => {
    button.classList.toggle("active", (button.dataset.item || "") === active);
  });
}
function bindNavigation() {
  const navButtons = document.querySelectorAll(".side-link[data-view], .tree-link[data-view]");
  navButtons.forEach(button => {
    if (!button.dataset.view) return;
    button.addEventListener("click", () => {
      const target = button.dataset.view;
      navButtons.forEach(item => item.classList.toggle("active", item === button));
      document.querySelectorAll(".view").forEach(view => view.classList.toggle("active", view.id === target));
      if (target === "rdaView" && analysis) setTimeout(drawCharts, 0);
    });
  });
  const exitBtn = document.getElementById("exitBtn");
  if (exitBtn) {
    exitBtn.addEventListener("click", async () => {
      if (!confirm("Exit this tool?")) return;
      exitBtn.disabled = true;
      setStatus("Closing tool...");
      try {
        await fetch("/shutdown", { method: "POST" });
        document.body.innerHTML = "<main style='padding:32px;font-family:Arial,sans-serif'><h1>Tool closed</h1><p>You can close this browser tab.</p></main>";
      } catch (err) {
        alert("Close failed. Please end the process from Task Manager.");
        exitBtn.disabled = false;
      }
    });
  }
}
function setSelectOptions(selectId, options, placeholder = "", disabled = false) {
  const sel = document.getElementById(selectId);
  const previous = sel.value;
  sel.innerHTML = "";
  sel.disabled = disabled;
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = placeholder;
  sel.appendChild(empty);
  options.forEach(value => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    sel.appendChild(opt);
  });
  if (options.includes(previous)) sel.value = previous;
}
function setReadoutOptions(options, placeholder = "Select") {
  const sel = document.getElementById("readoutSelect");
  const previous = sel.value;
  sel.innerHTML = "";
  sel.disabled = !lookupState.item || options.length === 0;
  if (options.length) {
    // 맨 위 "최신 자동" 이 기본값이다 - 특정 회차를 고르면 그 시점 기준으로
    // 판정하는 기존 동작은 그대로 유지된다.
    const auto = document.createElement("option");
    auto.value = AUTO_LATEST_READOUT;
    auto.textContent = "최신 자동";
    sel.appendChild(auto);
  } else {
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    sel.appendChild(empty);
  }
  options.forEach(value => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    sel.appendChild(opt);
  });
  const nextValue = options.length
    ? (previous === AUTO_LATEST_READOUT || options.includes(previous) ? previous : AUTO_LATEST_READOUT)
    : "";
  sel.value = nextValue;
  lookupState.readout = nextValue;
}
function setFtTempOptions(options, placeholder = "Select") {
  setSelectOptions("ftTempSelect", options, placeholder, !lookupState.readout || options.length === 0);
}
function setDatalistOptions(listId, options) {
  const list = document.getElementById(listId);
  const current = Array.from(list.options).map(option => option.value);
  if (current.length === options.length && current.every((value, index) => value === options[index])) return;
  list.innerHTML = "";
  options.forEach(value => {
    const opt = document.createElement("option");
    opt.value = value;
    list.appendChild(opt);
  });
}
function setDataRootPath(path) {
  if (!path) return;
  dataRootPath = path;
  document.getElementById("dataPath").textContent = dataRootPath;
}
function resetLookupControls() {
  lookupState.device = "";
  const device = document.getElementById("deviceInput");
  if (device) device.value = "";
  lookupOrder.forEach(([key, selectId]) => {
    lookupState[key] = "";
    if (key === "readout") {
      setReadoutOptions([], "Select");
    } else if (key === "ft_temp") {
      setFtTempOptions([], "Select");
    } else {
      setSelectOptions(selectId, [], "Select");
    }
  });
}
function clearLookupAfter(field) {
  const index = lookupOrder.findIndex(([key]) => key === field);
  lookupOrder.slice(index + 1).forEach(([key, selectId]) => {
    lookupState[key] = "";
    if (key === "readout") {
      setReadoutOptions([], "Select");
    } else if (key === "ft_temp") {
      setFtTempOptions([], "Select");
    } else {
      setSelectOptions(selectId, [], "Select");
    }
  });
}
async function loadLookup(field) {
  const params = new URLSearchParams({ field, device: lookupState.device });
  lookupOrder.forEach(([key]) => {
    if (lookupState[key]) params.set(key, lookupState[key]);
  });
  const res = await fetch(`/lookup?${params.toString()}`);
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || "Lookup failed");
  return data;
}
async function refreshLookup(field) {
  if (field !== "device" && !lookupState.device) return;
  try {
    setStatus("Searching data...");
    const data = await loadLookup(field);
    if (field === "device") {
      setDatalistOptions("deviceOptions", data.options || []);
    } else {
      const entry = lookupOrder.find(([key]) => key === field);
      if (entry) {
        if (field === "readout") {
          setReadoutOptions(data.options || [], (data.options || []).length ? "Select" : "No data");
          if (lookupState.readout) await refreshLookup("ft_temp");
        } else if (field === "ft_temp") {
          setFtTempOptions(data.options || [], (data.options || []).length ? "Select" : "No data");
        } else {
          setSelectOptions(entry[1], data.options || [], "Select");
        }
      }
    }
    if (field === "purpose" && (data.options || []).length === 1) {
      const purposeSelect = document.getElementById("purposeSelect");
      purposeSelect.value = data.options[0];
      lookupState.purpose = data.options[0];
      const itemData = await loadLookup("item");
      setSelectOptions("reliabilityItemSelect", itemData.options || [], "전체 (미선택)");
    }
    if (field === "device") setDataRootPath(data.path);
    setStatus("Ready");
  } catch (err) {
    setStatus("Lookup failed");
    alert(err.message);
  }
}
function bindLookupControls() {
  const device = document.getElementById("deviceInput");
  const browseDataPathBtn = document.getElementById("browseDataPathBtn");
  let deviceLookupLoaded = false;
  refreshLookup("device");
  deviceLookupLoaded = true;
  if (browseDataPathBtn) {
    browseDataPathBtn.addEventListener("click", async () => {
      browseDataPathBtn.disabled = true;
      setStatus("Selecting data path...");
      try {
        const res = await fetch("/browse-data-root", { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || "Path selection failed");
        setDataRootPath(data.path);
        if (data.changed) {
          resetLookupControls();
          await refreshLookup("device");
          deviceLookupLoaded = true;
        } else {
          setStatus("Ready");
        }
      } catch (err) {
        setStatus("Path selection failed");
        alert(err.message);
      } finally {
        browseDataPathBtn.disabled = false;
      }
    });
  }
  device.addEventListener("change", async () => {
    lookupState.device = device.value.trim();
    modePayloads = {};
    clearAnalysisDisplay("");
    lookupOrder.forEach(([key, selectId]) => {
      lookupState[key] = "";
      if (key === "readout") {
        setReadoutOptions([], "Select");
      } else if (key === "ft_temp") {
        setFtTempOptions([], "Select");
      } else {
        setSelectOptions(selectId, [], "Select");
      }
    });
    await refreshLookup("ver");
  });
  device.addEventListener("focus", async () => {
    if (deviceLookupLoaded && document.getElementById("deviceOptions").options.length) return;
    await refreshLookup("device");
    deviceLookupLoaded = true;
  });
  lookupOrder.forEach(([key, selectId], index) => {
    const sel = document.getElementById(selectId);
    if (key === "readout") {
      setReadoutOptions([], "Select");
    } else if (key === "ft_temp") {
      setFtTempOptions([], "Select");
    } else {
      setSelectOptions(selectId, [], "Select");
    }
    sel.addEventListener("change", async () => {
      lookupState[key] = sel.value;
      modePayloads = {};
      clearAnalysisDisplay("");
      clearLookupAfter(key);
      const next = lookupOrder[index + 1];
      if (next && lookupState[key]) await refreshLookup(next[0]);
    });
  });
}

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  if (v === Infinity) return "INF";
  if (v === -Infinity) return "-INF";
  if (typeof v === "number") return Number(v.toPrecision(6)).toString();
  return v;
}
function fmtCell(v) {
  // Summary/Detail 표 전용: null(§S5 "정의 불가")은 빈칸이 아니라 "N/A"로 명시한다.
  if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "N/A";
  return fmt(v);
}
function naturalKey(v) {
  const text = String(v ?? "");
  return text.replace(/_/g, ".").split(".").map(p => {
    const n = Number(p);
    return Number.isFinite(n) ? n : p.toLowerCase();
  });
}
function compareValues(a, b, col) {
  let av = a[col], bv = b[col];
  if (col === "test_number") {
    const ak = naturalKey(av), bk = naturalKey(bv);
    for (let i = 0; i < Math.max(ak.length, bk.length); i++) {
      if (ak[i] === undefined) return -1;
      if (bk[i] === undefined) return 1;
      if (ak[i] < bk[i]) return -1;
      if (ak[i] > bk[i]) return 1;
    }
    return 0;
  }
  const an = Number(av), bn = Number(bv);
  if (Number.isFinite(an) && Number.isFinite(bn)) return an - bn;
  return String(av ?? "").localeCompare(String(bv ?? ""));
}
function setAnalyzeProgress(percent, label) {
  const value = Math.max(0, Math.min(100, Math.round(percent || 0)));
  setStatus(`${label || "Analyzing"} ${value}%`);
}
function emptyParallelProgressState() {
  return {
    pass: { progress: 0, message: "Waiting" },
    fail: { progress: 0, message: "Waiting" }
  };
}
let parallelAnalysisProgress = emptyParallelProgressState();
function modeDisplayName(mode) {
  return mode === "fail" ? "Fail" : "Pass";
}
function resetParallelAnalysisProgress() {
  parallelAnalysisProgress = emptyParallelProgressState();
}
function setParallelAnalysisProgress(mode, percent, message = "Analyzing") {
  const key = mode === "fail" ? "fail" : "pass";
  const value = Math.max(0, Math.min(100, Math.round(percent || 0)));
  parallelAnalysisProgress[key] = { progress: value, message };
  const pass = parallelAnalysisProgress.pass;
  const fail = parallelAnalysisProgress.fail;
  const total = Math.round((pass.progress + fail.progress) / 2);
  setStatus(`Pass ${pass.progress}% / Fail ${fail.progress}% - ${modeDisplayName(key)} ${message || "Analyzing"} ${total}%`);
}
function setAnalysisMode(mode, renderExisting = true) {
  analysisMode = mode === "fail" ? "fail" : "pass";
  updateResultTabButtons();
  updateResultTabVisibility();
  if (isResultsWindow && renderExisting && !modePayloads[analysisMode]) {
    loadLatestAnalysis(analysisMode, { retry: true });
    return;
  }
  if (renderExisting && modePayloads[analysisMode]) {
    applyAnalysisPayload(modePayloads[analysisMode], false);
    refreshSelectedItem();
  } else if (renderExisting && analysis && analysis.analysis_mode !== analysisMode) {
    clearAnalysisDisplay("Select Analyze to display results.");
  }
}
function resultColumns() {
  return (analysis?.analysis_mode || analysisMode) === "fail" ? failColumns : passColumns;
}
function resultColumnsForPayload(payload, mode = payload?.analysis_mode) {
  const resultMode = mode === "fail" ? "fail" : (payload?.analysis_mode || "pass");
  return resultMode === "fail" ? failColumns : passColumns;
}
function readoutDetailColumns() {
  const labels = (itemCache[selectedItem]?.post_readout_labels || analysis?.post_readout_labels || []).slice(0, 3);
  if (labels.length) {
    return labels.map((label, index) => [`post_t${index + 1}`, label]);
  }
  const details = itemCache[selectedItem]?.details || [];
  return details.some(row => row.post_value !== undefined) ? [["post_value", "Post"]] : [];
}
function postReadoutHeader(index) {
  const labels = itemCache[selectedItem]?.post_readout_labels || analysis?.post_readout_labels || [];
  return labels[index - 1] || `T${index}`;
}
function detailColumns() {
  return [
    ["sample", "Sample No."], ["result", "Result"], ["spec_out_type", "Spec.-Out Type"],
    ["pre_value", "Pre"], ["post_t1", postReadoutHeader(1)], ["post_t2", postReadoutHeader(2)], ["post_t3", postReadoutHeader(3)],
    ["unit", "Unit"], ["mea_s", "σ (Measured)"], ["diff", "Delta"],
    ["diff_s", "σ (Delta)"], ["need_bench", "Need Bench?"]
  ];
}
  function updatePanelMode() {
    const mode = analysis?.analysis_mode || analysisMode;
    const grid = document.getElementById("passResultsGrid");
    const section = document.querySelector(".analysis-results-section");
    const summaryTitle = document.querySelector(".summary-panel .panel-label");
    const detailTitle = document.querySelector(".detail-panel .panel-label");
    const overPanel = document.querySelector(".over-panel");
    if (grid) grid.classList.toggle("fail-grid", mode === "fail");
    if (section) section.classList.toggle("fail-layout", mode === "fail");
    if (summaryTitle) summaryTitle.lastChild.textContent = isResultsWindow ? "1. Fail Data List" : "Fail & Abnormal Data Lists - All";
    if (detailTitle) detailTitle.lastChild.textContent = isResultsWindow ? "3. Data Analysis Result" : "Fail & Abnormal Data Analysis Result";
    if (overPanel) {
      overPanel.style.display = isResultsWindow ? "" : "none";
      const overTitle = overPanel.querySelector(".panel-label");
      if (overTitle) overTitle.lastChild.textContent = isResultsWindow ? "2. Abnormal Pass List" : "Abnormal Shift Sample";
    }
    updateResultTabButtons();
    updateResultTabVisibility();
    updateGraphPanels();
  }
function emptyAnalysisPayload(mode = analysisMode, message = "") {
  return {
    results: [],
    selected_summary: [],
    over_sigma: [],
    select_count: 0,
    analysis_mode: mode,
    message
  };
}
function itemKey(row) {
  return row?.item_key || row?.item || "";
}
function itemDisplayName(key) {
  const data = itemCache[key];
  return data?.item || data?.display_item || key;
}
function selectedResultRow() {
  return (analysis?.results || []).find(row => itemKey(row) === selectedItem)
    || (analysis?.selected_summary || []).find(row => itemKey(row) === selectedItem);
}
function selectedItemTitleName() {
  const data = itemCache[selectedItem];
  const row = selectedResultRow();
  return data?.item || row?.item || data?.display_item || selectedItem || "";
}
function updateChartTitles() {
  const itemName = selectedItemTitleName();
  const suffix = itemName ? ` - ${itemName}` : "";
  const titles = [
    ["cdfPanelTitle", "CDF Distribution"],
    ["diffCdfPanelTitle", "Diff. CDF Distribution"],
    ["ppfPanelTitle", "Standard Normal Distribution"],
    ["scatterPanelTitle", "Scattered Plot"]
  ];
  titles.forEach(([id, base]) => {
    const node = document.getElementById(id);
    if (node) node.textContent = `${base}${suffix}`;
  });
}
function updateGraphPanels() {
  const panelMap = {
    cdf: "chart-panel",
    diff: "diff-cdf-panel",
    ppf: "ppf-panel",
    scatter: "scatter-panel"
  };
  document.querySelectorAll(".graph-tabs button").forEach(button => {
    button.classList.toggle("active", button.dataset.graph === activeGraphTab);
  });
  Object.entries(panelMap).forEach(([key, className]) => {
    document.querySelectorAll(`.${className}`).forEach(panel => {
      panel.classList.toggle("active-graph", key === activeGraphTab);
    });
  });
}
function itemOptionText(row) {
  return row.test_number ? `${row.test_number} - ${row.item}` : (row.item || "");
}
function resetAnalysisFilters() {
  analysisFilters = {
    reliability_item: "",
    ft_temp_multi: false,
    ft_temps: { Room: true, Hot: false, Cold: false },
    readouts: { pre_t0: true, post_t1: true, post_t2: true, post_t3: true },
    fail_exception: false
  };
}
function availableFilterTemps() {
  return ["Room", "Hot", "Cold"];
}
function ensureFtTempState() {
  if (!analysisFilters.ft_temps) analysisFilters.ft_temps = { Room: true, Hot: false, Cold: false };
  availableFilterTemps().forEach(temp => {
    if (analysisFilters.ft_temps[temp] === undefined) analysisFilters.ft_temps[temp] = temp === "Room";
  });
}
function selectedFtTemps() {
  ensureFtTempState();
  return availableFilterTemps().filter(temp => analysisFilters.ft_temps?.[temp]);
}
function setOnlyFtTemp(temp) {
  ensureFtTempState();
  availableFilterTemps().forEach(candidate => {
    analysisFilters.ft_temps[candidate] = candidate === temp;
  });
}
function tempSelectionCount() {
  return selectedFtTemps().length;
}
function singleSelectedFtTemp() {
  const temps = selectedFtTemps();
  return temps.length === 1 ? temps[0] : "";
}
function tempMatchesFilters(temp) {
  const temps = selectedFtTemps();
  if (!temps.length) return false;
  if (!temp) return true;
  return temps.includes(temp);
}
function graphTempMatches(temp) {
  return tempMatchesFilters(temp);
}
function rowMatchesAnalysisFilters(row) {
  if (!analysis?.total_analysis) return true;
  if (analysisFilters.reliability_item && row.reliability_item !== analysisFilters.reliability_item) return false;
  if (!tempMatchesFilters(row.ft_temp)) return false;
  return true;
}
function rowMatchesPayloadFilters(row, payload) {
  if (!payload?.total_analysis) return true;
  if (analysisFilters.reliability_item && row.reliability_item !== analysisFilters.reliability_item) return false;
  if (!tempMatchesFilters(row.ft_temp)) return false;
  return true;
}
function payloadForMode(mode) {
  const resultMode = mode === "fail" ? "fail" : "pass";
  if (modePayloads[resultMode]) return modePayloads[resultMode];
  if ((analysis?.analysis_mode || analysisMode) === resultMode) return analysis;
  return null;
}
function activatePayloadMode(mode, item = "") {
  const payload = payloadForMode(mode);
  if (!payload) return false;
  analysisMode = mode === "fail" ? "fail" : "pass";
  analysis = payload;
  itemCache = payload.items || {};
  if (item) selectedItem = item;
  return true;
}
function filteredResultRows() {
  return (analysis?.results || []).filter(rowMatchesAnalysisFilters);
}
function ensureSelectedItemVisible() {
  const rows = filteredResultRows();
  if (!rows.length) {
    selectedItem = "";
    return;
  }
  if (!rows.some(row => itemKey(row) === selectedItem)) {
    selectedItem = itemKey(rows[0]);
  }
}
function overSigmaRows() {
  return (analysis?.over_sigma || []).filter(rowMatchesAnalysisFilters);
}
function ensureSelectedOverItemVisible() {
  const keys = [];
  overSigmaRows().forEach(row => (row.items || []).forEach(item => { if (item) keys.push(item); }));
  if (!keys.length) {
    selectedItem = "";
    return;
  }
  if (!keys.includes(selectedItem)) {
    selectedItem = keys[0];
  }
}
function ensureSelectedItemVisibleForActiveTab() {
  if (!isResultsWindow && resultViewMode === "sample") ensureSelectedOverItemVisible();
  else ensureSelectedItemVisible();
}
function updateResultTabButtons() {
  document.querySelectorAll("#resultTabBar button").forEach(button => {
    button.classList.toggle("active", button.dataset.mode === analysisMode);
  });
  document.querySelectorAll("#resultViewBar button").forEach(button => {
    button.classList.toggle("active", button.dataset.view === resultViewMode);
  });
}
function updateResultTabVisibility() {
  const resultWrap = document.getElementById("resultTableWrap");
  const overWrap = document.getElementById("overSampleTableWrap");
  const toggleWrap = document.getElementById("columnToggleWrap");
  const showOver = !isResultsWindow && resultViewMode === "sample";
  if (resultWrap) resultWrap.style.display = showOver ? "none" : "";
  if (overWrap) overWrap.style.display = showOver ? "block" : "none";
  if (toggleWrap) toggleWrap.style.display = showOver ? "none" : "";
}
function setResultViewMode(view) {
  if (isResultsWindow) return;
  resultViewMode = view === "sample" ? "sample" : "item";
  updateResultTabButtons();
  updateResultTabVisibility();
  ensureSelectedItemVisibleForActiveTab();
  refreshSelectedItem();
}
function renderAnalysisFilterBar() {
  const bar = document.getElementById("analysisFilterBar");
  if (!bar) return;
  if (!analysis || (!analysis.total_analysis && !isResultsWindow)) {
    bar.classList.remove("active");
    bar.innerHTML = "";
    return;
  }
  bar.classList.add("active");
  bar.innerHTML = "";
  const tableFilterArea = document.createElement("div");
  tableFilterArea.className = "table-filter-area";
  const reliabilityRow = document.createElement("div");
  reliabilityRow.className = "filter-row reliability-filter-row";
  const secondaryRow = document.createElement("div");
  secondaryRow.className = "filter-row secondary-filter-row";
  const makeTempButton = temp => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-chip";
    button.textContent = temp;
    button.classList.toggle("active", selectedFtTemps().includes(temp));
    button.addEventListener("click", async () => {
      ensureFtTempState();
      if (analysisFilters.ft_temp_multi) {
        analysisFilters.ft_temps[temp] = !analysisFilters.ft_temps[temp];
      } else {
        setOnlyFtTemp(temp);
      }
      renderAnalysisFilterBar();
      renderGraphFilterBar();
      ensureSelectedItemVisibleForActiveTab();
      renderSummary();
      await refreshSelectedItem();
    });
    return button;
  };
  const reliabilityGroup = document.createElement("div");
  reliabilityGroup.className = "item-tabs";
  reliabilityGroup.setAttribute("role", "tablist");
  reliabilityGroup.setAttribute("aria-label", "시험 항목");
  const itemCounts = {};
  (analysis?.item_counts || []).forEach(entry => { itemCounts[entry.reliability_item] = entry; });
  const totalItemCount = () => {
    const entries = analysis?.item_counts || [];
    if (!entries.length) return null;
    return entries.reduce((acc, entry) => ({
      select: acc.select + (entry.select || 0),
      total: acc.total + (entry.total || 0),
    }), { select: 0, total: 0 });
  };
  const makeItemTab = (value, label, count) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "item-tab";
    button.dataset.item = value;
    // value === "" 는 「전체」 탭. 합계가 0 이어도 비활성화하지 않는다.
    const isEmpty = value !== "" && count && count.total === 0;
    button.classList.toggle("item-tab-empty", !!isEmpty);
    if (isEmpty) button.disabled = true;
    button.classList.toggle("active", (analysisFilters.reliability_item || "") === value);
    const labelSpan = document.createElement("span");
    labelSpan.className = "item-tab-label";
    labelSpan.textContent = label;
    button.appendChild(labelSpan);
    if (count) {
      const badge = document.createElement("span");
      badge.className = "item-tab-badge";
      badge.textContent = `${count.select}/${count.total}`;
      badge.title = analysisMode === "fail"
        ? `Fail ${count.select}대 / 전체 Sample ${count.total}대`
        : `이상 데이터 식별 ${count.select}건 / 분석 항목 ${count.total}건`;
      button.appendChild(badge);
    }
    button.addEventListener("click", async () => {
      analysisFilters.reliability_item = value;
      updateReliabilityTabs();
      ensureSelectedItemVisibleForActiveTab();
      renderSummary();
      await refreshSelectedItem();
    });
    return button;
  };
  reliabilityGroup.appendChild(makeItemTab("", "전체", totalItemCount()));
  const reliabilityOptions = analysis?.total_analysis ? reliabilityItems : (analysis.total_reliability_items?.length ? analysis.total_reliability_items : reliabilityItems);
  reliabilityOptions.forEach(item => reliabilityGroup.appendChild(makeItemTab(item, item, itemCounts[item] || null)));
  reliabilityRow.appendChild(reliabilityGroup);
  tableFilterArea.appendChild(reliabilityRow);

  const tempGroup = document.createElement("div");
  tempGroup.className = "filter-group temp-filter-group";
  tempGroup.innerHTML = "<strong>FT Temp.</strong>";
  availableFilterTemps().forEach(temp => tempGroup.appendChild(makeTempButton(temp)));
  tempGroup.appendChild(makeGraphCheckbox("Multi", analysisFilters.ft_temp_multi, async checked => {
    analysisFilters.ft_temp_multi = checked;
    if (!checked) setOnlyFtTemp(selectedFtTemps()[0] || "Room");
    renderAnalysisFilterBar();
    renderGraphFilterBar();
    ensureSelectedItemVisible();
    renderSummary();
    await refreshSelectedItem();
  }));
  secondaryRow.appendChild(tempGroup);
  tableFilterArea.appendChild(secondaryRow);
  bar.appendChild(tableFilterArea);

  const graphBar = document.createElement("div");
  graphBar.id = "graphFilterBar";
  graphBar.className = "graph-filter-bar";
  bar.appendChild(graphBar);
}
function makeGraphCheckbox(labelText, checked, onChange) {
  const label = document.createElement("label");
  label.className = "filter-check";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = checked;
  checkbox.addEventListener("change", () => onChange(checkbox.checked));
  label.appendChild(checkbox);
  label.appendChild(document.createTextNode(labelText));
  return label;
}
function graphTabOptions() {
  return [["cdf", "CDF"], ["diff", "Diff. CDF"], ["ppf", "PPF"], ["scatter", "Scattered Plot"]];
}
function makeGraphTabButton(key, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.graph = key;
  button.textContent = label;
  button.classList.toggle("active", activeGraphTab === key);
  button.addEventListener("click", () => {
    activeGraphTab = key;
    updateGraphPanels();
    drawCharts();
  });
  return button;
}
function renderGraphFilterBar() {
  const bar = document.getElementById("graphFilterBar");
  if (!bar) return;
  if (!analysis) {
    bar.classList.remove("active");
    bar.innerHTML = "";
    return;
  }
  bar.classList.add("active");
  bar.innerHTML = "";
  const readoutStack = document.createElement("div");
  readoutStack.className = "graph-readout-stack";
  const readoutGroup = document.createElement("div");
  readoutGroup.className = "graph-filter-group";
  readoutGroup.innerHTML = "<strong>Read-out</strong>";
  [["pre_t0", "T0"], ["post_t1", "T1"], ["post_t2", "T2"], ["post_t3", "T3"]].forEach(([key, label]) => {
    readoutGroup.appendChild(makeGraphCheckbox(label, analysisFilters.readouts[key] !== false, checked => {
      analysisFilters.readouts[key] = checked;
      drawCharts();
    }));
  });
  readoutStack.appendChild(readoutGroup);
  const graphTabs = document.createElement("div");
  graphTabs.className = "graph-tabs";
  graphTabs.setAttribute("role", "tablist");
  graphTabs.setAttribute("aria-label", "Graph Type");
  graphTabOptions().forEach(([key, label]) => graphTabs.appendChild(makeGraphTabButton(key, label)));
  readoutStack.appendChild(graphTabs);
  bar.appendChild(readoutStack);

  const graphGroup = document.createElement("div");
  graphGroup.className = "graph-filter-group graph-option-group";
  graphGroup.innerHTML = "<strong>Graph</strong>";
  graphGroup.appendChild(makeGraphCheckbox("Fail Exception", analysisFilters.fail_exception, async checked => {
    analysisFilters.fail_exception = checked;
    drawCharts();
  }));
  bar.appendChild(graphGroup);
}
function setResultPanelsVisible(visible) {
  const grid = document.getElementById("passResultsGrid");
  if (grid) grid.classList.toggle("results-hidden", !visible);
  const resultsWindowBtn = document.getElementById("openResultsWindowBtn");
  if (resultsWindowBtn) resultsWindowBtn.disabled = !visible;
  const rawExportBtn = document.getElementById("rawExportBtn");
  if (rawExportBtn) rawExportBtn.disabled = !visible;
  updatePanelMode();
}
function clearAnalysisDisplay(message = "") {
  analysis = emptyAnalysisPayload(analysisMode, message);
  setResultPanelsVisible(false);
  itemCache = {};
  selectedItem = "";
  highlightSample = null;
  highlightMode = null;
  sortState = { column: "severity", reverse: true };
  detailSortState = { column: null, reverse: false };
  resetAnalysisFilters();
  renderSummary();
  renderDetailTable();
  drawCharts();
  updateReliabilityTabs();
  document.getElementById("summary").textContent = message;
}
function applyAnalysisPayload(data, remember = true) {
  analysis = data || emptyAnalysisPayload();
  if (remember) modePayloads[analysis.analysis_mode || analysisMode] = analysis;
  setResultPanelsVisible(true);
  itemCache = analysis.items || {};
  sortState = { column: "severity", reverse: true };
  detailSortState = { column: null, reverse: false };
  resetAnalysisFilters();
  selectedItem = itemKey(analysis.results?.[0]) || "";
  highlightSample = null;
  highlightMode = null;
  document.getElementById("latestAnalysisDate").textContent = `Latest Analysis Date: ${analysis.analysis_date || "-"}`;
  updateReliabilityTabs();
  renderSummary();
}
function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
function uploadAnalyze(fd) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/analyze");
    xhr.upload.onprogress = event => {
      if (event.lengthComputable) setAnalyzeProgress((event.loaded / event.total) * 20, "Uploading");
    };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || "{}"); }
      catch (_err) { reject(new Error("Invalid server response.")); return; }
      if (xhr.status < 200 || xhr.status >= 300 || data.error) reject(new Error(data.error || "Analyze failed"));
      else resolve(data);
    };
    xhr.onerror = () => reject(new Error("Analyze request failed."));
    xhr.send(fd);
  });
}
async function waitForJob(jobId, label = "", mode = "") {
  while (true) {
    if (stopAnalysisRequested) throw new Error("Analysis stopped.");
    const res = await fetch(`/progress?id=${encodeURIComponent(jobId)}`);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Analyze failed");
    const rawMessage = data.message || "Analyzing";
    const message = `${label}${rawMessage}`;
    if (mode) {
      setParallelAnalysisProgress(mode, data.progress, rawMessage);
    } else {
      setAnalyzeProgress(data.progress, message);
    }
    if (data.status === "done") {
      const resultMode = mode === "fail" ? "fail" : "pass";
      const params = new URLSearchParams({ mode: resultMode });
      if (activeAnalysisRunId) params.set("run", activeAnalysisRunId);
      const latestRes = await fetch(`/latest-analysis?${params.toString()}`);
      const latest = await latestRes.json();
      if (!latestRes.ok || latest.error) throw new Error(latest.error || "Analyze failed");
      return latest;
    }
    if (data.status === "error") throw new Error(data.message || "Analyze failed");
    await delay(250);
  }
}

async function requestAnalysisMode(mode) {
  if (stopAnalysisRequested) throw new Error("Analysis stopped.");
  setParallelAnalysisProgress(mode, 0, "Preparing");
  const includePre = document.getElementById("includePreCheck").checked ? "1" : "0";
  const payload = normalizedAnalysisSelection({ analysis_mode: mode, include_pre: includePre, analysis_run_id: activeAnalysisRunId });
  const res = await fetch("/analyze-selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const job = await res.json();
  if (!res.ok || job.error) throw new Error(`${mode === "pass" ? "Pass" : "Fail"} Analyze failed: ${job.error || "Analyze failed"}`);
  const data = await waitForJob(job.job_id, `${mode === "pass" ? "Pass" : "Fail"} `, mode);
  if (stopAnalysisRequested) throw new Error("Analysis stopped.");
  modePayloads[data.analysis_mode || mode] = data;
  return data;
}

async function runAnalysis() {
  const btn = document.getElementById("analyzeBtn");
  const stopBtn = document.getElementById("stopAnalyzeBtn");
  const displayMode = analysisMode;
  activeAnalysisRunId = createAnalysisRunId();
  openAnalysisResultsWindow(displayMode, true, activeAnalysisRunId);
  btn.disabled = true;
  stopBtn.disabled = false;
  stopAnalysisRequested = false;
  setAnalyzeProgress(0, "Preparing");
  try {
    modePayloads = {};
    clearAnalysisDisplay("Analysis is running...");
    resetParallelAnalysisProgress();
    await prepareAnalysisResultsRun(activeAnalysisRunId);
    const [passData, failData] = await Promise.all([
      requestAnalysisMode("pass"),
      requestAnalysisMode("fail")
    ]);
    const displayData = displayMode === "fail" ? failData : passData;
    setAnalysisMode(displayMode, false);
    applyAnalysisPayload(displayData);
    await refreshSelectedItem();
    const loaded = [passData, failData].every(data => data.cache_status === "loaded");
    setStatus(loaded ? "Loaded" : "Done");
    document.getElementById("summary").textContent = displayData.message || `Pass/Fail analysis completed. Showing ${displayMode === "fail" ? "Fail" : "Pass"} results.`;
    if (!isResultsWindow) setConditionCollapsed(true);
  } catch (err) {
    if (stopAnalysisRequested || err.message === "Analysis stopped.") {
      setStatus("Stopped");
      document.getElementById("summary").textContent = "Analysis stopped.";
      await reportAnalysisResultsRunStatus("stopped", "Analysis stopped.");
    } else {
      setStatus("Failed");
      await reportAnalysisResultsRunStatus("error", err.message || "Analyze failed.");
      alert(err.message);
    }
  } finally {
    btn.disabled = false;
    stopBtn.disabled = true;
  }
}

async function initializeAnalysis() {
  const btn = document.getElementById("initializeBtn");
  btn.disabled = true;
  setStatus("Initializing...");
  try {
    const includePre = document.getElementById("includePreCheck").checked ? "1" : "0";
    const payload = normalizedAnalysisSelection({ include_pre: includePre });
    const res = await fetch("/initialize-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Initialization failed");
    modePayloads = {};
    clearAnalysisDisplay(`Initialized saved results (${data.deleted || 0})`);
    setStatus("Ready");
  } catch (err) {
    setStatus("Failed");
    alert(err.message);
  } finally {
    btn.disabled = false;
  }
}

function createAnalysisRunId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function prepareAnalysisResultsRun(runId) {
  const res = await fetch("/prepare-analysis-results", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId })
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || "Preparing Analysis Results failed.");
}

async function reportAnalysisResultsRunStatus(status, message) {
  try {
    await fetch("/analysis-results-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, message, run_id: activeAnalysisRunId })
    });
  } catch (_err) {
  }
}

let latestAnalysisRetryTimer = null;

async function preloadAnalysisPayload(mode, options = {}) {
  const resultMode = mode === "fail" ? "fail" : "pass";
  if (modePayloads[resultMode]) return modePayloads[resultMode];
  const retry = !!options.retry;
  const maxAttempts = options.maxAttempts ?? 900;
  const delayMs = options.delayMs ?? 1000;
  for (let attempt = 0; attempt <= maxAttempts; attempt++) {
    try {
      const params = new URLSearchParams({ mode: resultMode });
      if (activeAnalysisRunId) params.set("run", activeAnalysisRunId);
      const res = await fetch(`/latest-analysis?${params.toString()}`);
      const data = await res.json();
      if (!res.ok || data.error) {
        if (retry && data.status === "running" && attempt < maxAttempts) {
          await delay(delayMs);
          continue;
        }
        return null;
      }
      modePayloads[data.analysis_mode || resultMode] = data;
      return data;
    } catch (_err) {
      if (retry && attempt < maxAttempts) {
        await delay(delayMs);
        continue;
      }
      return null;
    }
  }
  return null;
}

async function loadLatestAnalysis(mode = analysisMode, options = {}) {
  if (latestAnalysisRetryTimer) {
    clearTimeout(latestAnalysisRetryTimer);
    latestAnalysisRetryTimer = null;
  }
  setStatus("Loading results...");
  try {
    const resultMode = mode === "fail" ? "fail" : "pass";
    const params = new URLSearchParams({ mode: resultMode });
    if (activeAnalysisRunId) params.set("run", activeAnalysisRunId);
    const res = await fetch(`/latest-analysis?${params.toString()}`);
    const data = await res.json();
    if (!res.ok || data.error) {
      if (data.status === "running" && options.retry) {
        clearAnalysisDisplay(data.message || "Analysis is running...");
        setStatus("Waiting");
        latestAnalysisRetryTimer = setTimeout(() => loadLatestAnalysis(resultMode, options), 1000);
        return;
      }
      throw new Error(data.error || "Analysis Results are not available.");
    }
    modePayloads[data.analysis_mode || resultMode] = data;
    setAnalysisMode(data.analysis_mode || resultMode, false);
    applyAnalysisPayload(data);
    if (isResultsWindow) {
      preloadAnalysisPayload(resultMode === "fail" ? "pass" : "fail", { retry: options.retry }).then(payload => {
        if (payload) renderSummary();
      });
    }
    await refreshSelectedItem();
    setStatus("Done");
  } catch (err) {
    clearAnalysisDisplay(err.message);
    setStatus("Failed");
  }
}

function initializeResultsWindow() {
  document.title = "Analysis Results";
  document.body.classList.add("results-window");
  const params = new URLSearchParams(window.location.search);
  applyResultsWindowTuning(params);
  const mode = params.get("mode") === "fail" ? "fail" : "pass";
  activeAnalysisRunId = params.get("run") || "";
  setAnalysisMode(mode, false);
  loadLatestAnalysis(mode, { retry: true });
}

function parseCssPixelLength(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  if (!normalized) return null;
  if (/^-?\d+(\.\d+)?$/.test(normalized)) return `${normalized}px`;
  if (/^-?\d+(\.\d+)?px$/i.test(normalized)) return `${parseFloat(normalized)}px`;
  return null;
}

function parseCssLength(value) {
  if (value == null) return null;
  const normalized = String(value).trim();
  if (!normalized) return null;
  if (/^-?\d+(\.\d+)?$/.test(normalized)) return `${normalized}px`;
  if (/^-?\d+(\.\d+)?(px|vh|vw|vmin|vmax|rem|em|%)$/i.test(normalized)) return normalized;
  return null;
}

function viewportMinusPixelLength(length) {
  const pixels = parseFloat(length);
  if (!Number.isFinite(pixels)) return null;
  if (pixels < 0) return `calc(100vh + ${Math.abs(pixels)}px)`;
  return `calc(100vh - ${pixels}px)`;
}

function parseOverflowValue(value) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (["visible", "hidden", "auto", "scroll", "clip"].includes(normalized)) return normalized;
  return null;
}

function setResultsCssVar(name, value, applied) {
  if (!value) return;
  document.documentElement.style.setProperty(name, value);
  applied.push(`${name.replace("--results-", "")}=${value}`);
}

function firstQueryValue(params, names) {
  for (const name of names) {
    if (params.has(name)) return params.get(name);
  }
  return null;
}

function parseToggleValue(value) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on", "show", "visible"].includes(normalized)) return true;
  if (["0", "false", "no", "off", "hide", "hidden"].includes(normalized)) return false;
  return null;
}

function setParentResultsCssVar(name, value, applied, label) {
  if (!value) return false;
  document.documentElement.style.setProperty(name, value);
  applied.push(`${label}=${value}`);
  return true;
}

function applyParentResultsTuning(params) {
  const applied = [];
  const visibility = parseToggleValue(firstQueryValue(params, ["showParentResults", "parentResults"]));
  if (visibility === false) {
    document.body.classList.remove("parent-results-visible", "parent-results-fixed-height");
    document.body.classList.add("parent-results-hidden");
    return;
  }

  const sectionHeight = parseCssLength(firstQueryValue(params, [
    "parentResultsHeight", "analysisResultsHeight", "resultsSectionHeight", "sectionHeight"
  ]));
  const sectionOffset = parseCssPixelLength(firstQueryValue(params, [
    "parentResultsOffset", "analysisResultsOffset", "resultsSectionOffset", "heightOffset"
  ]));
  const sectionMaxHeight = parseCssLength(firstQueryValue(params, [
    "parentResultsMaxHeight", "analysisResultsMaxHeight", "resultsSectionMaxHeight"
  ]));
  const scrollHeight = parseCssLength(firstQueryValue(params, [
    "parentResultsScrollHeight", "resultsScrollHeight", "scrollHeight"
  ]));
  const gridHeight = parseCssLength(firstQueryValue(params, [
    "parentResultsGridHeight", "resultsGridHeight", "gridHeight"
  ]));
  const gridMinHeight = parseCssLength(firstQueryValue(params, [
    "parentResultsGridMinHeight", "resultsGridMinHeight", "gridMinHeight"
  ]));
  const sectionOverflow = parseOverflowValue(firstQueryValue(params, [
    "parentResultsOverflow", "resultsSectionOverflow", "sectionOverflow"
  ]));
  const scrollOverflow = parseOverflowValue(firstQueryValue(params, [
    "parentResultsScrollOverflow", "resultsScrollOverflow", "scrollOverflow"
  ]));
  const gridOverflow = parseOverflowValue(firstQueryValue(params, [
    "parentResultsGridOverflow", "resultsGridOverflow", "gridOverflow"
  ]));

  const adjustedHeight = sectionHeight || (sectionOffset ? viewportMinusPixelLength(sectionOffset) : null);
  const hasTuning = visibility === true || adjustedHeight || sectionMaxHeight || scrollHeight ||
    gridHeight || gridMinHeight || sectionOverflow || scrollOverflow || gridOverflow;
  if (!hasTuning) return;

  document.body.classList.remove("parent-results-hidden");
  document.body.classList.add("parent-results-visible");
  if (adjustedHeight) {
    setParentResultsCssVar("--parent-results-section-height", adjustedHeight, applied, "parentResultsHeight");
    document.body.classList.add("parent-results-fixed-height");
  }
  setParentResultsCssVar("--parent-results-section-max-height", sectionMaxHeight, applied, "parentResultsMaxHeight");
  setParentResultsCssVar("--parent-results-scroll-height", scrollHeight, applied, "parentResultsScrollHeight");
  setParentResultsCssVar("--parent-results-grid-height", gridHeight, applied, "parentResultsGridHeight");
  setParentResultsCssVar("--parent-results-grid-min-height", gridMinHeight, applied, "parentResultsGridMinHeight");
  setParentResultsCssVar("--parent-results-section-overflow", sectionOverflow, applied, "parentResultsOverflow");
  setParentResultsCssVar("--parent-results-scroll-overflow", scrollOverflow, applied, "parentResultsScrollOverflow");
  setParentResultsCssVar("--parent-results-grid-overflow", gridOverflow, applied, "parentResultsGridOverflow");
  if (visibility === true && !applied.length) applied.push("parentResults=show");
  if (applied.length) {
    document.title = `Pre/Post CDF Sigma Compare Tool (${applied.join(", ")})`;
  }
}

function applyResultsWindowTuning(params) {
  const applied = [];
  const sectionHeight = parseCssPixelLength(params.get("sectionHeight") || params.get("resultsHeight"));
  const scrollHeight = parseCssPixelLength(params.get("scrollHeight"));
  const directGridHeight = parseCssPixelLength(params.get("gridHeight") || params.get("resultsGridHeight"));
  const gridOffset = parseCssPixelLength(params.get("gridOffset") || params.get("heightOffset"));
  const clipMode = String(params.get("clip") || "").trim().toLowerCase();
  if (["off", "false", "0", "visible"].includes(clipMode)) {
    setResultsCssVar("--results-section-overflow", "visible", applied);
    setResultsCssVar("--results-scroll-overflow", "visible", applied);
    setResultsCssVar("--results-scroll-overflow-x", "visible", applied);
    setResultsCssVar("--results-scroll-overflow-y", "visible", applied);
    setResultsCssVar("--results-grid-overflow", "visible", applied);
  } else if (["on", "true", "1", "hidden"].includes(clipMode)) {
    setResultsCssVar("--results-section-overflow", "hidden", applied);
    setResultsCssVar("--results-scroll-overflow-x", "hidden", applied);
    setResultsCssVar("--results-scroll-overflow-y", "scroll", applied);
    setResultsCssVar("--results-grid-overflow", "hidden", applied);
  }
  setResultsCssVar("--results-section-overflow", parseOverflowValue(params.get("sectionOverflow")), applied);
  const scrollOverflow = parseOverflowValue(params.get("scrollOverflow"));
  if (scrollOverflow) {
    setResultsCssVar("--results-scroll-overflow", scrollOverflow, applied);
    setResultsCssVar("--results-scroll-overflow-x", scrollOverflow, applied);
    setResultsCssVar("--results-scroll-overflow-y", scrollOverflow, applied);
  }
  setResultsCssVar("--results-scroll-overflow-x", parseOverflowValue(params.get("scrollOverflowX")), applied);
  setResultsCssVar("--results-scroll-overflow-y", parseOverflowValue(params.get("scrollOverflowY")), applied);
  setResultsCssVar("--results-grid-overflow", parseOverflowValue(params.get("gridOverflow")), applied);
  if (sectionHeight) {
    document.documentElement.style.setProperty("--results-section-height", sectionHeight);
    applied.push(`sectionHeight=${sectionHeight}`);
  }
  if (scrollHeight) {
    document.documentElement.style.setProperty("--results-scroll-height", scrollHeight);
    applied.push(`scrollHeight=${scrollHeight}`);
  }
  if (directGridHeight) {
    document.documentElement.style.setProperty("--results-grid-height", directGridHeight);
    applied.push(`gridHeight=${directGridHeight}`);
  } else if (gridOffset) {
    const adjustedGridHeight = viewportMinusPixelLength(gridOffset);
    if (adjustedGridHeight) {
      document.documentElement.style.setProperty("--results-grid-height", adjustedGridHeight);
      applied.push(`gridOffset=${gridOffset}`);
    }
  }
  if (applied.length) {
    document.title = `Analysis Results (${applied.join(", ")})`;
  }
}

function exportRawData() {
  if (!analysis || !analysis.analysis_mode) {
    alert("Analysis result is not available.");
    return;
  }
  const runId = activeAnalysisRunId || analysis.analysis_run_id || "";
  const href = `/export-raw-data?run=${encodeURIComponent(runId)}`;
  const link = document.createElement("a");
  link.href = href;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function bindResultControls() {
  document.querySelectorAll("#resultTabBar button").forEach(button => {
    button.addEventListener("click", () => setAnalysisMode(button.dataset.mode));
  });
  document.querySelectorAll("#resultViewBar button").forEach(button => {
    button.addEventListener("click", () => setResultViewMode(button.dataset.view));
  });
  document.querySelectorAll(".copy-chart-btn").forEach(button => {
    button.addEventListener("click", () => copyCanvasToClipboard(button.dataset.canvas, button));
  });
  const rawExportBtn = document.getElementById("rawExportBtn");
  if (rawExportBtn) rawExportBtn.addEventListener("click", exportRawData);
  document.getElementById("itemSelect").addEventListener("change", async e => {
    selectedItem = e.target.value;
    highlightSample = null;
    highlightMode = null;
    await refreshSelectedItem();
  });
  const columnToggleBtn = document.getElementById("columnToggleBtn");
  const columnToggleMenu = document.getElementById("columnToggleMenu");
  if (columnToggleBtn && columnToggleMenu) {
    columnToggleBtn.addEventListener("click", event => {
      event.stopPropagation();
      columnToggleMenu.classList.toggle("open");
    });
    document.addEventListener("click", event => {
      if (!columnToggleMenu.classList.contains("open")) return;
      if (columnToggleMenu.contains(event.target) || event.target === columnToggleBtn) return;
      columnToggleMenu.classList.remove("open");
    });
  }
}

function bindParentControls() {
  bindNavigation();
  document.getElementById("analyzeBtn").addEventListener("click", runAnalysis);
  document.getElementById("stopAnalyzeBtn").addEventListener("click", () => {
    stopAnalysisRequested = true;
    setStatus("Stopping...");
  });
  document.getElementById("initializeBtn").addEventListener("click", initializeAnalysis);
  document.getElementById("openResultsWindowBtn").addEventListener("click", () => openAnalysisResultsWindow());
  bindLookupControls();
  bindConditionToggle();
}

function setConditionCollapsed(collapsed) {
  const rdaView = document.getElementById("rdaView");
  const toggle = document.getElementById("conditionToggle");
  if (!rdaView || !toggle) return;
  rdaView.classList.toggle("condition-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (collapsed) renderConditionSummaryLine();
}

function renderConditionSummaryLine() {
  const line = document.getElementById("conditionSummaryLine");
  if (!line) return;
  const parts = [];
  if (lookupState.device) parts.push(lookupState.device);
  if (lookupState.ver) parts.push(lookupState.ver);
  if (lookupState.lot) parts.push(`Lot ${lookupState.lot}`);
  if (lookupState.purpose) parts.push(lookupState.purpose);
  parts.push(lookupState.item ? lookupState.item : "전체 시험 항목");
  if (lookupState.readout && lookupState.readout !== AUTO_LATEST_READOUT) parts.push(lookupState.readout);
  if (lookupState.ft_temp) parts.push(lookupState.ft_temp);
  const includePre = document.getElementById("includePreCheck")?.checked;
  line.textContent = `✓ ${parts.join(" · ")}${includePre ? " · Pre 포함" : " · Pre 제외"}`;
}

function bindConditionToggle() {
  const toggle = document.getElementById("conditionToggle");
  if (!toggle) return;
  toggle.addEventListener("click", () => {
    const rdaView = document.getElementById("rdaView");
    setConditionCollapsed(!rdaView.classList.contains("condition-collapsed"));
  });
}

bindResultControls();
if (isResultsWindow) {
  initializeResultsWindow();
} else {
  bindParentControls();
  applyParentResultsTuning(new URLSearchParams(window.location.search));
}

function renderSummary() {
  renderAnalysisFilterBar();
  renderGraphFilterBar();
  updateGraphPanels();
  ensureSelectedItemVisibleForActiveTab();
  renderItemSelect();
  renderResultTable();
  renderOverTable();
  renderFlagAlphaLabel();
  renderSummaryStrip();
}
function failSelectCount() {
  // "항목 List" 탭이므로 배지는 항목 수 기준으로 맞춘다(Pass 쪽 요약 스트립의
  // "이상 데이터 식별" 카드와 동일 단위). 상세(샘플) 건수는 참고용으로 병기한다.
  const payload = modePayloads.fail;
  if (!payload) return null;
  const itemCount = Array.isArray(payload.selected_summary) ? payload.selected_summary.length : null;
  const detailCount = payload.select_count;
  return {
    items: Number.isFinite(itemCount) ? itemCount : null,
    details: Number.isFinite(detailCount) ? detailCount : null,
  };
}
function passSelectCount() {
  const payload = modePayloads.pass;
  const value = payload?.summary_counts?.select;
  return Number.isFinite(value) ? value : null;
}
function overSampleItemCount(payload = modePayloads.pass) {
  if (!payload) return null;
  const keys = new Set();
  (payload.over_sigma || []).forEach(row => (row.items || []).forEach(item => { if (item) keys.add(item); }));
  return keys.size;
}
function setTabBadge(btn, value, title) {
  if (!btn) return;
  let badge = btn.querySelector(".tab-count-badge");
  if (value != null) {
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "tab-count-badge";
      btn.appendChild(badge);
    }
    badge.textContent = value;
    if (title) badge.title = title;
  } else if (badge) {
    badge.remove();
  }
}
function renderSummaryStrip() {
  const strip = document.getElementById("summaryStrip");
  const failBtn = isResultsWindow ? null : document.getElementById("failModeBtn");
  if (failBtn) {
    let badge = failBtn.querySelector(".fail-count-badge");
    const failCount = failSelectCount();
    if (failCount && failCount.items) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "fail-count-badge";
        failBtn.appendChild(badge);
      }
      // 탭 버튼이 고정폭(166px)이라 배지는 항목 수만 짧게 표시하고, 상세 건수는
      // 필요할 때 마우스오버로 확인하도록 title 에 병기한다.
      badge.textContent = failCount.items;
      badge.title = (failCount.details != null && failCount.details !== failCount.items)
        ? `이상 항목 ${failCount.items}개 / 상세 ${failCount.details}건`
        : `이상 항목 ${failCount.items}개`;
    } else if (badge) {
      badge.remove();
    }
  }
  if (!isResultsWindow) {
    const passCount = passSelectCount();
    setTabBadge(document.getElementById("passModeBtn"), passCount, passCount != null ? `이상 데이터 식별 ${passCount}개` : "");
  }
  if (!strip) return;
  strip.innerHTML = "";
  // Pass 는 항목 기준(분석 항목 수 중 몇 개가 이상인지), Fail 은 유닛 기준(전체 Sample 중
  // 몇 대가 Fail/Pass 인지) -- 서로 다른 질문이라 카드 구성 자체를 모드별로 나눈다.
  const counts = analysisMode === "pass" ? analysis?.summary_counts : analysis?.sample_counts;
  if (!counts) return;
  const cards = analysisMode === "pass" ? [
    { key: "total_items", label: "분석 항목" },
    { key: "select", label: "이상 데이터 식별", cls: "flag" },
    { key: "ok", label: "정상", cls: "ok" },
    { key: "not_evaluated", label: "판정 불가", cls: "warn", icon: "⚠", hideIfZero: true }
  ] : [
    { key: "total", label: "전체 Sample" },
    { key: "fail", label: "Fail", cls: "flag" },
    { key: "pass", label: "Pass", cls: "ok" }
  ];
  cards.forEach(card => {
    const value = counts[card.key] ?? 0;
    if (card.hideIfZero && !value) return;
    const div = document.createElement("div");
    div.className = `summary-card${card.cls ? " summary-card-" + card.cls : ""}`;
    const valueEl = document.createElement("div");
    valueEl.className = "summary-card-value";
    valueEl.textContent = card.icon ? `${value} ${card.icon}` : `${value}`;
    const labelEl = document.createElement("div");
    labelEl.className = "summary-card-label";
    labelEl.textContent = card.label;
    div.appendChild(valueEl);
    div.appendChild(labelEl);
    strip.appendChild(div);
  });
  const footnote = document.createElement("div");
  footnote.id = "judgmentFootnote";
  footnote.className = "judgment-footnote";
  strip.appendChild(footnote);
  renderJudgmentFootnote();
}
function renderJudgmentFootnote() {
  const el = document.getElementById("judgmentFootnote");
  if (!el) return;
  if (!analysis) { el.innerHTML = ""; return; }
  if (analysisMode === "fail") { renderFailJudgmentFootnote(el); return; }
  const parts = ["판정 기준 Grubbs"];
  if (analysis.flag_mode === "fixed") {
    parts.push(`고정 임계=${analysis.flag_limit ?? 3}`);
  } else {
    const alpha = Number(analysis.flag_alpha);
    if (Number.isFinite(alpha)) parts.push(`α ${alpha}`);
  }
  const row = selectedResultRow() || {};
  const n = Number(row.n_post);
  const mea = Number(row.mea_threshold ?? itemCache[selectedItem]?.mea_threshold);
  if (Number.isFinite(n)) parts.push(`유닛 ${n}개`);
  if (Number.isFinite(mea)) parts.push(`임계 ${mea.toFixed(3)}`);
  let text = parts.join(" · ");
  const readout = row.judged_readout;
  if (readout) text += ` · 판정 Read-out ${readout} (최신) T0~T3 는 추세 비교용`;
  const textSpan = document.createElement("span");
  textSpan.textContent = text;
  const infoSpan = document.createElement("span");
  infoSpan.className = "footnote-info";
  infoSpan.title = "임계는 유닛 수에 따라 달라집니다 (N=57→3.539, N=145→3.879, N=3000→4.673)";
  infoSpan.textContent = "ⓘ";
  el.innerHTML = "";
  el.appendChild(textSpan);
  el.appendChild(infoSpan);
}
function renderFailJudgmentFootnote(el) {
  // Fail 목록은 규격(LSL/USL) 이탈이 1차 선별 기준이라 Pass 탭의 "판정 기준 Grubbs·임계"
  // 문구를 그대로 쓰면 오해를 준다. Grubbs 통계(mea/diff threshold)는 이탈 유형
  // (Intermittent/Unstable/Excessive/Slight/Tail) 을 보조 분류하는 데만 쓰인다.
  const parts = ["판정 기준 규격 이탈(Spec Out)"];
  const failItemCount = (analysis.selected_summary || []).length;
  if (failItemCount) parts.push(`Fail 항목 ${failItemCount}건`);
  let text = parts.join(" · ");
  const readout = (selectedResultRow() || {}).judged_readout;
  if (readout) text += ` · 판정 Read-out ${readout} (최신) T0~T3 는 추세 비교용`;
  const textSpan = document.createElement("span");
  textSpan.textContent = text;
  const infoSpan = document.createElement("span");
  infoSpan.className = "footnote-info";
  infoSpan.title = "Fail 목록은 규격(LSL/USL) 이탈 여부를 1차 기준으로 선별합니다. 이탈 유형(Intermittent/Unstable/Excessive/Slight/Tail)은 정상 표본 분포 기준 Grubbs 통계로 보조 분류한 결과입니다.";
  infoSpan.textContent = "ⓘ";
  el.innerHTML = "";
  el.appendChild(textSpan);
  el.appendChild(infoSpan);
}
function renderFlagAlphaLabel() {
  // §S7: 판정 임계가 항목별 Grubbs(alpha 기반)로 바뀐 뒤, 패널 제목에 박혀 있던
  // 고정 "> 3" 문구가 실제 판정과 어긋나 보이는 걸 막기 위해 현재 alpha 를 표시한다.
  // 값 자체는 payload 의 flag_mode/flag_alpha 를 그대로 읽기만 한다(재계산 없음).
  const el = document.getElementById("flagAlphaLabel");
  if (!el) return;
  if (!analysis) { el.textContent = ""; return; }
  if (analysis.flag_mode === "fixed") {
    el.textContent = `(fixed limit=${analysis.flag_limit ?? 3})`;
  } else {
    const alpha = Number(analysis.flag_alpha);
    el.textContent = Number.isFinite(alpha) ? `(alpha=${alpha}, 항목별 n 기준 Grubbs 임계)` : "";
  }
}
function renderItemThresholdLabel() {
  // 선택된 항목의 실제 판정 임계값(n_post/n_diff 에 따라 항목마다 다름). payload 에
  // 이미 있는 mea_threshold/diff_threshold(§S3) 를 표시만 한다 — 재계산하지 않는다.
  const el = document.getElementById("itemThresholdLabel");
  if (!el) return;
  const data = itemCache[selectedItem] || analysis?.items?.[selectedItem] || {};
  const mea = Number(data.mea_threshold);
  const diff = Number(data.diff_threshold);
  const parts = [];
  if (Number.isFinite(mea)) parts.push(`Mea threshold=${mea.toFixed(4)}`);
  if (Number.isFinite(diff)) parts.push(`Diff threshold=${diff.toFixed(4)}`);
  el.textContent = parts.join("  /  ");
}
function analysisResultsWindowUrl(mode = analysisMode, waitForResults = false, runId = "") {
  const params = new URLSearchParams({ mode: mode === "fail" ? "fail" : "pass" });
  if (waitForResults) params.set("wait", "1");
  if (runId) params.set("run", runId);
  return `/results-window?${params.toString()}`;
}
function openAnalysisResultsWindow(mode = analysis?.analysis_mode || analysisMode, allowEmpty = false, runId = "") {
  if (!allowEmpty && !analysis) {
    alert("Analysis Results are not available.");
    return null;
  }
  const popup = window.open(analysisResultsWindowUrl(mode, allowEmpty, runId), "analysisResultsWindow", "width=1800,height=1050,resizable=yes,scrollbars=yes");
  if (!popup) {
    alert("New window was blocked by the browser.");
    return null;
  }
  popup.focus();
  return popup;
}
async function copyCanvasToClipboard(canvasId, button) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (!navigator.clipboard || !window.ClipboardItem) {
    alert("Clipboard image copy is not supported in this browser.");
    return;
  }
  const copyCanvas = document.createElement("canvas");
  const includeTestItem = canvasId === "cdfCanvas";
  const ratio = chartPixelRatio();
  const headerHeight = includeTestItem ? Math.max(44, Math.round(44 * ratio)) : 0;
  copyCanvas.width = canvas.width;
  copyCanvas.height = canvas.height + headerHeight;
  const ctx = copyCanvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, copyCanvas.width, copyCanvas.height);
  if (includeTestItem) {
    const itemText = document.getElementById("itemSelect")?.selectedOptions?.[0]?.textContent || selectedItem || "";
    ctx.fillStyle = "#17212b";
    ctx.font = `${Math.round(14 * ratio)}px Segoe UI, Arial, sans-serif`;
    ctx.textBaseline = "middle";
    ctx.fillText(`Test Item: ${itemText}`, Math.round(18 * ratio), Math.round(headerHeight / 2));
  }
  ctx.drawImage(canvas, 0, headerHeight);
  const blob = await new Promise(resolve => copyCanvas.toBlob(resolve, "image/png"));
  if (!blob) {
    alert("Chart copy failed.");
    return;
  }
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
  const oldText = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = oldText; }, 1200);
}
async function refreshSelectedItem() {
  try {
    renderGraphFilterBar();
    renderItemSelect();
    renderResultTable();
    renderOverTable();
    const itemSelect = document.getElementById("itemSelect");
    if (itemSelect) itemSelect.value = selectedItem;
    renderDetailTable();
    await loadItem(selectedItem);
    await loadRelatedGraphItems();
    renderDetailTable();
    renderItemThresholdLabel();
    renderJudgmentFootnote();
    drawCharts();
    if (analysis) setStatus("Done");
  } catch (err) {
    setStatus("Failed");
    alert(err.message);
  }
}
function renderItemSelect() {
  const sel = document.getElementById("itemSelect");
  sel.innerHTML = "";
  filteredResultRows().forEach(r => {
    const opt = document.createElement("option");
    opt.value = itemKey(r);
    opt.textContent = itemOptionText(r);
    sel.appendChild(opt);
  });
  sel.value = selectedItem;
}
function numericValues(values) {
  // §S5: finiteNumber() 와 동일한 이유 -- Number(null)===0 이라 null 을 그냥 Number() 에
  // 넣으면 유효한 0 처럼 필터를 통과해버린다.
  return (values || []).map(finiteNumber).filter(value => value !== null);
}
function summaryCellValue(row, key, payload = analysis) {
  const data = (payload?.items || itemCache)[itemKey(row)] || {};
  if (key === "qty_ratio") {
    // §S5: null(정의 불가, n_pass=0)을 Number()로 강제 변환하면 0 이 되어 "0.0%"로
    // 새어나간다 -- null 은 계산 전에 걸러 N/A(fmtCell)로 떨어지게 한다.
    if (row.qty_ratio === null || row.qty_ratio === undefined) return null;
    const ratio = Number(row.qty_ratio);
    return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}%` : "";
  }
  if (key === "diff_mean") {
    if (row.diff_mean === null || row.diff_mean === undefined) return null;
    const ratio = Number(row.diff_mean);
    return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(2)}%` : "";
  }
  if (key === "unit") return row.unit || data.unit || "";
  if (key === "lower_limit") return row.lower_limit ?? data.lower_limit;
  if (key === "upper_limit") return row.upper_limit ?? data.upper_limit;
  return row[key];
}
function compareSummaryValues(a, b, col, payload = analysis) {
  return compareValues({ [col]: summaryCellValue(a, col, payload) }, { [col]: summaryCellValue(b, col, payload) }, col);
}
function sortedResults() {
  const rows = [...(analysis.selected_summary || [])].filter(rowMatchesAnalysisFilters);
  if (sortState.column) {
    rows.sort((a, b) => compareSummaryValues(a, b, sortState.column) * (sortState.reverse ? -1 : 1));
  }
  return rows;
}
function sortedPayloadSummaryRows(payload) {
  const rows = [...(payload?.selected_summary || [])].filter(row => rowMatchesPayloadFilters(row, payload));
  if (sortState.column) {
    rows.sort((a, b) => compareSummaryValues(a, b, sortState.column, payload) * (sortState.reverse ? -1 : 1));
  }
  return rows;
}
function sortedDetails(details) {
  const mode = analysis?.analysis_mode || analysisMode;
  const rows = mode === "fail" ? details.filter(d => d.fail_type) : details.filter(d => d.result === "SELECT");
  if (detailSortState.column) {
    rows.sort((a, b) => compareValues(a, b, detailSortState.column) * (detailSortState.reverse ? -1 : 1));
  }
  return rows;
}
async function loadItemForPayload(payload, item, mode = "") {
  if (!payload || !item) return null;
  payload.items = payload.items || {};
  if (payload.items[item]) return payload.items[item];
  const resultMode = mode || payload.analysis_mode || analysisMode;
  const requestKey = `${resultMode}:${item}`;
  if (pendingItemLoads[requestKey]) return pendingItemLoads[requestKey];
  setStatus("Loading item...");
  pendingItemLoads[requestKey] = (async () => {
    const params = new URLSearchParams({ name: item, mode: resultMode });
    const res = await fetch(`/item?${params.toString()}`);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Item load failed");
    payload.items[item] = data;
    if (payload === analysis || resultMode === (analysis?.analysis_mode || analysisMode)) {
      itemCache[item] = data;
    }
    return data;
  })();
  try {
    return await pendingItemLoads[requestKey];
  } finally {
    delete pendingItemLoads[requestKey];
  }
}
async function loadItem(item) {
  if (!analysis || !item || itemCache[item]) return;
  await loadItemForPayload(analysis, item, analysis.analysis_mode || analysisMode);
}
function relatedGraphItemKeys(payload = analysis) {
  if (!payload || !selectedItem) return [];
  const baseRow = selectedResultRow() || {};
  const baseData = itemCache[selectedItem] || payload.items?.[selectedItem] || {};
  const targetItem = baseData.item || baseRow.item || "";
  const targetReliability = baseData.reliability_item || baseRow.reliability_item || "";
  const keys = new Set([selectedItem]);
  (payload.selected_summary || []).forEach(row => {
    if (targetItem && row.item !== targetItem) return;
    if (targetReliability && row.reliability_item && row.reliability_item !== targetReliability) return;
    if (!graphTempMatches(row.ft_temp)) return;
    const key = itemKey(row);
    if (key) keys.add(key);
  });
  return [...keys];
}
async function loadRelatedGraphItems() {
  if (!analysis || !selectedItem) return;
  const mode = analysis.analysis_mode || analysisMode;
  await Promise.all(relatedGraphItemKeys(analysis).map(item => loadItemForPayload(analysis, item, mode)));
}
function scheduleModeItemLoad(mode, item) {
  const payload = modePayloads[mode];
  if (!payload || !item || payload.items?.[item]) return;
  loadItemForPayload(payload, item, mode).then(() => {
    if (mode === "fail") drawCharts();
  }).catch(() => {});
}
function renderResultTable() {
  const table = document.getElementById("resultTable");
  if (isResultsWindow) {
    renderFailDataListTable(table);
    return;
  }
  renderSummaryListTable(table, analysis, analysis?.analysis_mode || analysisMode);
}
function renderFailDataListTable(table) {
  renderSummaryListTable(table, payloadForMode("fail"), "fail");
}
function renderAbnormalPassListTable(table) {
  renderSummaryListTable(table, payloadForMode("pass"), "pass");
}
function renderColumnToggleMenu(resultMode, allCols) {
  const menu = document.getElementById("columnToggleMenu");
  if (!menu) return;
  const visible = columnVisibility[resultMode] || new Set(resultMode === "fail" ? DEFAULT_VISIBLE_COLUMNS_FAIL : DEFAULT_VISIBLE_COLUMNS_PASS);
  menu.innerHTML = "";
  allCols.forEach(([key, label]) => {
    const item = document.createElement("label");
    item.className = "column-toggle-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = visible.has(key);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) visible.add(key); else visible.delete(key);
      renderResultTable();
      renderOverTable();
    });
    item.appendChild(checkbox);
    item.appendChild(document.createTextNode(label));
    menu.appendChild(item);
  });
}
function renderSummaryListTable(table, payload, mode) {
  table.innerHTML = "";
  const thead = table.createTHead();
  const hr = thead.insertRow();
  const resultMode = mode === "fail" ? "fail" : (payload?.analysis_mode || "pass");
  const allCols = resultColumnsForPayload(payload, mode);
  const visible = columnVisibility[resultMode] || new Set(resultMode === "fail" ? DEFAULT_VISIBLE_COLUMNS_FAIL : DEFAULT_VISIBLE_COLUMNS_PASS);
  const cols = allCols.filter(([key]) => visible.has(key));
  renderColumnToggleMenu(resultMode, allCols);
  cols.forEach(([key, label]) => {
    const th = document.createElement("th");
    th.textContent = label + (sortState.column === key ? (sortState.reverse ? " v" : " ^") : "");
    if (key === "n") th.title = "표준편차 계산에 사용된 유닛 수";
    th.onclick = () => {
      if (sortState.column === key) sortState.reverse = !sortState.reverse;
      else sortState = { column: key, reverse: false };
      renderResultTable();
      renderOverTable();
    };
    hr.appendChild(th);
  });
  const tbody = table.createTBody();
  if (!payload) {
    const tr = tbody.insertRow();
    const td = tr.insertCell();
    td.colSpan = Math.max(1, cols.length);
    td.textContent = "No data";
    return;
  }
  sortedPayloadSummaryRows(payload).forEach(r => {
    const tr = tbody.insertRow();
    const key = itemKey(r);
    if (r.result === "SELECT") tr.classList.add("select-row");
    if (key === selectedItem && analysis?.analysis_mode === payload.analysis_mode) tr.classList.add("active");
    tr.onclick = async () => {
      if (!activatePayloadMode(mode, key)) return;
      selectedItem = key;
      highlightSample = null;
      highlightMode = null;
      await refreshSelectedItem();
    };
    cols.forEach(([key]) => {
      const td = tr.insertCell();
      td.textContent = fmtCell(summaryCellValue(r, key, payload));
      if (key === "item") td.className = "item";
      if (key === "sample_numbers") td.className = "item";
    });
  });
}
function renderOverTable() {
  const table = document.getElementById("overTable");
  if (isResultsWindow) {
    renderAbnormalPassListTable(table);
    return;
  }
  renderOverSampleTable(document.getElementById("overSampleTable"));
}
function renderOverSampleTable(table) {
  if (!table) return;
  table.innerHTML = "";
  const overRows = overSigmaRows();
  const maxItems = Math.max(1, ...overRows.map(r => r.items.length));
  const head = table.createTHead().insertRow();
  ["Sample #", ...Array.from({ length: maxItems }, (_, i) => i === 0 ? "Abnormal Shift Items" : "")].forEach(label => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
  const body = table.createTBody();
  overRows.forEach(row => {
    const tr = body.insertRow();
    tr.insertCell().textContent = row.sample;
    for (let i = 0; i < maxItems; i++) {
      const td = tr.insertCell();
      const item = row.items[i] || "";
      td.textContent = itemDisplayName(item);
      if (item) {
        td.className = "over-item";
        td.classList.toggle("active", item === selectedItem);
        td.onclick = async () => {
          selectedItem = item;
          highlightSample = row.sample;
          highlightMode = "diff_s";
          document.getElementById("itemSelect").value = item;
          await refreshSelectedItem();
        };
      }
    }
  });
}
function detailResultLabel(row) {
  const mode = analysis?.analysis_mode || analysisMode;
  if (mode === "fail" || row.fail_type) return "Fail";
  if (row.result === "SELECT") return "Pass";
  return row.result || "";
}
function detailSpecOutType(row) {
  if (row.fail_type) return row.fail_type;
  const meaLimit = flagLimit("mea_s");
  const diffLimit = flagLimit("diff_s");
  if (Math.abs(Number(row.mea_s)) > meaLimit && Math.abs(Number(row.diff_s)) > diffLimit) return "Measured + Delta";
  if (Math.abs(Number(row.mea_s)) > meaLimit) return "Measured";
  if (Math.abs(Number(row.diff_s)) > diffLimit) return "Delta";
  return "";
}
function detailReadoutValue(row, key) {
  if (row[key] !== undefined) return row[key];
  return key === "post_t1" ? row.post_value : "";
}
function needBenchKey(row) {
  return [activeAnalysisRunId || "latest", analysis?.analysis_mode || analysisMode, selectedItem, row.sample].join("|");
}
function detailCellValue(row, key) {
  const data = itemCache[selectedItem] || {};
  const summary = selectedResultRow() || {};
  if (key === "result") return detailResultLabel(row);
  if (key === "spec_out_type") return detailSpecOutType(row);
  if (["post_t1", "post_t2", "post_t3"].includes(key)) return detailReadoutValue(row, key);
  if (key === "unit") return row.unit || summary.unit || data.unit || "";
  return row[key];
}
function renderDetailTable() {
  const table = document.getElementById("detailTable");
  table.innerHTML = "";
  const head = table.createTHead().insertRow();
  const cols = detailColumns();
  cols.forEach(([key, label]) => {
    const th = document.createElement("th");
    th.textContent = label + (detailSortState.column === key ? (detailSortState.reverse ? " v" : " ^") : "");
    th.onclick = () => {
      if (detailSortState.column === key) detailSortState.reverse = !detailSortState.reverse;
      else detailSortState = { column: key, reverse: false };
      renderDetailTable();
    };
    head.appendChild(th);
  });
  const body = table.createTBody();
  const item = itemCache[selectedItem];
  if (!item) {
    const tr = body.insertRow();
    const td = tr.insertCell();
    td.colSpan = cols.length;
    td.textContent = selectedItem ? "Loading..." : "";
    return;
  }
  sortedDetails(item.details).forEach(d => {
    const tr = body.insertRow();
    if (String(d.sample) === String(highlightSample)) tr.classList.add("active");
    cols.forEach(([key]) => {
      const td = tr.insertCell();
      if (key === "need_bench") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = !!needBenchState[needBenchKey(d)];
        checkbox.addEventListener("change", event => {
          event.stopPropagation();
          needBenchState[needBenchKey(d)] = checkbox.checked;
        });
        td.appendChild(checkbox);
        return;
      }
      td.textContent = fmtCell(detailCellValue(d, key));
      if (key === "sample") {
        td.classList.add("sigma-action");
        td.title = "Show this sample on CDF Distribution and Scattered Plot";
        td.onclick = event => {
          event.stopPropagation();
          highlightSample = d.sample;
          highlightMode = "sample";
          renderDetailTable();
          drawCharts();
        };
        if (String(d.sample) === String(highlightSample) && highlightMode === "sample") {
          td.classList.add("active-cell");
        }
      }
      if (key === "mea_s" || key === "diff_s") {
        if (Math.abs(Number(d[key])) > flagLimit(key)) {
          td.classList.add("sigma-fail");
        }
      }
    });
  });
}
function canvasPoint(canvas, value, cdf, min, max) {
  const w = canvas.width, h = canvas.height;
  const ml = 58, mr = 132, mt = 24, mb = 46;
  return [
    ml + (value - min) / (max - min) * (w - ml - mr),
    mt + (1 - cdf) * (h - mt - mb)
  ];
}
function cdfFraction(values, target) {
  if (target === null || target === undefined || !values.length) return null;
  let count = 0;
  values.forEach(v => { if (v <= target) count++; });
  return Math.max(count, 1) / values.length;
}
function postReadoutSeries(data) {
  return (data?.post_readout_values || [])
    .map(series => ({
      ...series,
      values: (series.values || []).map(Number).filter(value => Number.isFinite(value))
    }))
    .filter(series => series.values.length);
}
function selectedPostReadoutSeries(data) {
  return postReadoutSeries(data).filter(series => analysisFilters.readouts?.[series.key] !== false);
}
function tablePostReadoutSeries(data) {
  return postReadoutSeries(data);
}
function readoutColor(key, index = 0) {
  const palette = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4", "#9467bd", "#2aa198", "#8c564b", "#e377c2", "#7f7f7f"];
  return palette[index % palette.length] || { post_t1: "#d62728", post_t2: "#ff7f0e", post_t3: "#2ca02c" }[key] || palette[0];
}
function finiteNumber(value) {
  // §S5: null/undefined("정의 불가")을 그냥 Number()에 넣으면 0 으로 굳어버려(Number(null)===0),
  // 이 함수를 쓰는 모든 그래프/포인트 필터("=== null 이면 점을 안 찍는다")가 무력화된다.
  // 숫자 변환 이전에 명시적으로 걸러야 한다.
  if (value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function meanValue(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}
function populationStd(values) {
  if (values.length < 2) return 0;
  const avg = meanValue(values);
  return Math.sqrt(values.reduce((sum, value) => sum + Math.pow(value - avg, 2), 0) / values.length);
}
function diffFromPre(preValue, postValue) {
  // Denominator is abs(pre), not signed pre: pure move-direction (down=negative, up=positive),
  // not a degradation/improvement judgment. Must match diff_ratio() in cdf_compare_tool.py
  // exactly. See 통계개선_프롬프트.md §S4.
  const pre = finiteNumber(preValue);
  const post = finiteNumber(postValue);
  if (pre === null || post === null || pre === 0) return null;
  return (post - pre) / Math.abs(pre);
}
function graphValuesForReadoutSeries(data, series, fallbackValues = []) {
  const mode = analysis?.analysis_mode || analysisMode;
  const values = numericValues(series?.values || []);
  if (mode === "fail" && series?.key === "post_t1") {
    if (values.length) return values;
    const passValues = numericValues(data?.pass_post_values || []);
    if (passValues.length) return passValues;
  }
  return values.length ? values : numericValues(fallbackValues);
}
function graphDiffValuesForReadoutSeries(data, series, fallbackValues = []) {
  const mode = analysis?.analysis_mode || analysisMode;
  if (mode === "fail" && series?.key === "post_t1") {
    const passDiffValues = numericValues(data?.pass_diff_values || []);
    if (passDiffValues.length) return passDiffValues;
  }
  return numericValues(fallbackValues);
}
function readoutDetailSeries(data) {
  return postReadoutSeries(data).map((series, index) => {
    let postValues, diffValues, points;
    if (series.stats) {
      // Backend writes m{n}/d{n} (mea_s/diff_s for post_t{n}) onto each detail row (population-
      // dependent, must stay backend-authoritative - read only, never recomputed here). The raw
      // per-point "diff" is NOT sent by the backend (payload-size fix): it's a pure (post-pre)/
      // abs(pre) ratio with no population ambiguity, identical to diff_ratio() server-side, so
      // rebuilding it via diffFromPre() here is the doc's permitted "pure display/axis-range
      // calculation" - not a judgment recomputation.
      const key = series.key;
      const n = key.replace("post_t", "");
      postValues = numericValues(series.values || []);
      points = (data?.details || [])
        .map(row => {
          const postValue = finiteNumber(row[key]);
          if (postValue === null) return null;
          const preValue = finiteNumber(row.pre_value);
          // diffFromPre() = diff_ratio(): (post-pre)/abs(pre), 결정적 계산이라 여기서 만들어도
          // 백엔드 값과 항상 같다 (§S4 완료: 2026-08-05, 분모 부호 반전 버그 수정).
          return {
            sample: row.sample,
            pre_value: preValue,
            post_value: postValue,
            diff: diffFromPre(preValue, postValue),
            mea_s: row[`m${n}`] ?? null,
            diff_s: row[`d${n}`] ?? null,
          };
        })
        .filter(Boolean);
      const mode = analysis?.analysis_mode || analysisMode;
      diffValues = (mode === "fail" && key === "post_t1")
        ? numericValues(data?.pass_diff_values || [])
        : points.map(point => point.diff).filter(value => value !== null && value !== undefined);
    } else {
      // §S7: 예전엔 여기서 mea_s/diff_s 를 ddof=0 로 클라이언트 재계산했다(§V5 백엔드 sigma
      // 권위, §S3 NOT EVALUATED, §S4 EPS_REL 게이트를 전부 무시). 백엔드는 post_readout_values
      // 항목마다 항상 stats 를 채워 보내므로(post_readout_series_entry), 이 분기는 오직 이
      // 세션 이전 코드가 만든 캐시 버전(stats 필드 없음)이 아직 살아있을 때만 탄다 - 그런
      // 데이터는 재계산하지 않고 버리고, 사용자에게 다시 분석하라고 안내한다.
      console.warn(`readoutDetailSeries: series "${series.key}" has no backend stats (stale cache) - re-analyze required.`);
      setStatus("캐시 형식이 오래되었습니다. 다시 분석하세요.");
      postValues = [];
      diffValues = [];
      points = [];
    }
    return { ...series, values: postValues, color: readoutColor(series.key, index), points, post_values: postValues, diff_values: diffValues };
  }).filter(series => series.points.length || series.values.length);
}
function selectedReadoutDetailSeries(data) {
  return readoutDetailSeries(data).filter(series => analysisFilters.readouts?.[series.key] !== false);
}
function fallbackFailT1Series(source, sourceIndex = 0) {
  const mode = analysis?.analysis_mode || analysisMode;
  if (mode !== "fail" || analysisFilters.readouts?.post_t1 === false) return [];
  const points = (source?.details || [])
    .map(row => {
      const postValue = finiteNumber(row.post_value);
      if (postValue === null) return null;
      return { sample: row.sample, pre_value: finiteNumber(row.pre_value), post_value: postValue, diff: finiteNumber(row.diff), row };
    })
    .filter(Boolean);
  if (!points.length) return [];
  const pointValues = points.map(point => point.post_value);
  const pointDiffValues = points.map(point => point.diff).filter(value => value !== null);
  const seriesStub = { key: "post_t1", values: [] };
  const values = graphValuesForReadoutSeries(source, seriesStub, pointValues);
  const diffValues = graphDiffValuesForReadoutSeries(source, seriesStub, pointDiffValues);
  return [{
    key: "post_t1",
    label: source.post_readout_labels?.[0] || "T1",
    values,
    points,
    post_values: values,
    diff_values: diffValues,
    source,
    color: readoutColor("post_t1", sourceIndex * 3)
  }];
}
function graphSourcePayloads() {
  const base = itemCache[selectedItem];
  if (!base) return [];
  const row = selectedResultRow() || {};
  const targetItem = base.item || row.item || "";
  const targetReliability = base.reliability_item || row.reliability_item || "";
  const sources = Object.values(itemCache || {}).filter(data => {
    if (!data) return false;
    const itemMatches = targetItem ? data.item === targetItem : data === base;
    if (!itemMatches) return false;
    if (targetReliability && data.reliability_item && data.reliability_item !== targetReliability) return false;
    return graphTempMatches(data.ft_temp);
  });
  if (sources.length) return sources;
  return graphTempMatches(base.ft_temp) ? [base] : [];
}
function allGraphReadoutDetailSeries() {
  return graphSourcePayloads().flatMap((source, sourceIndex) => {
    const seriesList = readoutDetailSeries(source);
    const effectiveSeries = seriesList.length ? seriesList : fallbackFailT1Series(source, sourceIndex);
    return effectiveSeries.map((series, index) => ({
      ...series,
      source,
      color: readoutColor(series.key, sourceIndex * 3 + index),
      label: [source.ft_temp, series.label || series.readout || series.key].filter(Boolean).join(" ")
    }));
  });
}
function selectedGraphReadoutDetailSeries() {
  return allGraphReadoutDetailSeries().filter(series => analysisFilters.readouts?.[series.key] !== false);
}
function hasSelectedPreReadout() {
  return analysisFilters.readouts?.pre_t0 !== false;
}
function preColor(temp, index = 0) {
  const colors = { Room: "#1f77b4", Hot: "#7b61c9", Cold: "#0097a7" };
  return colors[temp] || ["#1f77b4", "#7b61c9", "#0097a7"][index % 3];
}
function allGraphPreSeries() {
  if (!hasSelectedPreReadout()) return [];
  const seenTemps = new Set();
  const series = [];
  graphSourcePayloads().forEach((source, index) => {
    const temp = source.ft_temp || "";
    const dedupeKey = temp || `source_${index}`;
    if (seenTemps.has(dedupeKey)) return;
    seenTemps.add(dedupeKey);
    const values = numericValues(source.pre_values || []);
    if (!values.length) return;
    series.push({
      key: `pre_${dedupeKey}`,
      label: temp ? `${temp} Pre` : "Pre",
      values,
      color: preColor(temp, index),
      source
    });
  });
  return series;
}
function selectedReadoutKeys() {
  return ["post_t1", "post_t2", "post_t3"].filter(key => analysisFilters.readouts?.[key] !== false);
}
function isPostT1Selected() {
  return analysisFilters.readouts?.post_t1 !== false;
}
function hasSelectedReadouts() {
  return selectedReadoutKeys().length > 0;
}
function hasSelectedAnyReadout() {
  return hasSelectedPreReadout() || hasSelectedReadouts();
}
function hasSelectedGraphTemps() {
  return tempSelectionCount() > 0;
}
function failExceptionEnabled() {
  return analysisFilters.fail_exception === true;
}
function selectedGraphSpecSource() {
  const temp = singleSelectedFtTemp();
  if (!temp) return null;
  return graphSourcePayloads().find(source => source?.ft_temp === temp) || null;
}
function selectedFailItemData() {
  return null;
}
function failOverlayPoints(data) {
  if (!data) return [];
  const keys = selectedReadoutKeys();
  if (!keys.length) return [];
  const points = [];
  (data.details || []).forEach(row => {
    const readoutValues = keys
      .map(key => ({ key, value: finiteNumber(row[key]) }))
      .filter(entry => entry.value !== null);
    if (readoutValues.length) {
      readoutValues.forEach(entry => points.push({ sample: row.sample, value: entry.value, key: entry.key, row }));
      return;
    }
    if (!keys.includes("post_t1")) return;
    const postValue = finiteNumber(row.post_value);
    if (postValue !== null) points.push({ sample: row.sample, value: postValue, key: "post_t1", row });
  });
  return points;
}
function drawFailOverlay(ctx, points, x, y, baselineValues) {
  if (!points.length) return;
  ctx.save();
  ctx.fillStyle = "#ff4d4f";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.4;
  points.forEach(point => {
    const cdf = cdfFraction(baselineValues, point.value) ?? 0.5;
    const px = x(point.value);
    const py = y(cdf);
    ctx.fillRect(px - 4.5, py - 4.5, 9, 9);
    ctx.strokeRect(px - 4.5, py - 4.5, 9, 9);
    if (String(point.sample) === String(highlightSample)) {
      ctx.strokeStyle = "#111";
      ctx.lineWidth = 2;
      ctx.strokeRect(px - 7, py - 7, 14, 14);
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.4;
    }
  });
  ctx.restore();
}
function drawReadoutLegend(ctx, series, x, y, align = "left") {
  if (!series.length) return;
  ctx.save();
  ctx.font = "10px Segoe UI";
  ctx.textAlign = "left";
  series.forEach((entry, index) => {
    const label = entry.label || entry.readout || entry.name || entry.key || "";
    const lineWidth = 18;
    const gap = 6;
    const width = lineWidth + gap + ctx.measureText(label).width;
    const startX = align === "center" ? x - width / 2 : x;
    ctx.strokeStyle = entry.color || readoutColor(entry.key, index);
    ctx.fillStyle = entry.color || readoutColor(entry.key, index);
    ctx.lineWidth = 2;
    if (entry.markerOnly) {
      ctx.beginPath();
      ctx.arc(startX + lineWidth / 2, y - 4, 4, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.moveTo(startX, y - 4);
      ctx.lineTo(startX + lineWidth, y - 4);
      ctx.stroke();
    }
    ctx.fillStyle = "#233b5f";
    ctx.fillText(label, startX + lineWidth + gap, y);
    y += 16;
  });
  ctx.restore();
}
function failCdfForValue(value, row, fallbackValues = []) {
  const lower = finiteNumber(row?.lower_limit);
  const upper = finiteNumber(row?.upper_limit);
  if (lower !== null && value < lower) return 0;
  if (upper !== null && value > upper) return 1;
  return cdfFraction(fallbackValues, value) ?? 0.5;
}
function drawFailReadoutMarkers(ctx, readoutSeries, x, y) {
  ctx.save();
  readoutSeries.forEach(series => {
    ctx.fillStyle = series.color || getCss("--red");
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.4;
    (series.points || []).forEach(point => {
      const value = finiteNumber(point.post_value);
      if (value === null) return;
      const cx = x(value);
      const cy = y(failCdfForValue(value, point.row, series.post_values || series.values || []));
      ctx.beginPath();
      ctx.arc(cx, cy, 4.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      if (String(point.sample) === String(highlightSample)) {
        ctx.strokeStyle = "#111";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx, cy, 6.5, 0, Math.PI * 2);
        ctx.stroke();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1.4;
      }
    });
  });
  ctx.restore();
}
function drawChart() {
  const canvas = document.getElementById("cdfCanvas");
  const { ctx, w, h } = setupHiResCanvas(canvas, 360, 260);
  const data = itemCache[selectedItem];
  if (!data) return;
  if (isBinaryGraphItem(data)) { drawBinaryGraphNotice(canvas, 360, 260); return; }
  if (!hasSelectedGraphTemps()) return;
  if (!hasSelectedAnyReadout()) return;
  const mode = analysis?.analysis_mode || analysisMode;
  const hideFailData = mode === "fail" && failExceptionEnabled();
  const readoutSeries = selectedGraphReadoutDetailSeries();
  const preSeries = allGraphPreSeries();
  const hasReadoutSeries = readoutSeries.length > 0;
  const readoutSelected = hasSelectedReadouts();
  const fallbackPostSelected = readoutSelected && isPostT1Selected();
  const preSelected = hasSelectedPreReadout();
  const useSeriesLegend = true;
  const specSource = selectedGraphSpecSource();
  const showSpecLines = !!specSource;
  const ml = 58, mr = useSeriesLegend ? 220 : 150, mt = 24, mb = 78;
  const plotRight = w - mr;
  const legendX = plotRight + mr / 2;
  const legendY = mt + 16;
  const hasPre = preSeries.length > 0;
  const preAxisValues = preSeries.flatMap(series => series.values);
  const postAxisValues = mode === "fail"
    ? (hasReadoutSeries ? readoutSeries.flatMap(series => series.values) : [])
    : hasReadoutSeries ? readoutSeries.flatMap(series => series.values) : fallbackPostSelected ? data.post_values : [];
  const failOverlay = failOverlayPoints(selectedFailItemData());
  const failOverlayValues = failOverlay.map(point => point.value);
  const all = [...preAxisValues, ...postAxisValues, ...failOverlayValues];
  if (showSpecLines && specSource.lower_limit !== null) all.push(specSource.lower_limit);
  if (showSpecLines && specSource.upper_limit !== null) all.push(specSource.upper_limit);
  if (!all.length) return;
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const x = v => ml + (v - min) / (max - min) * (w - ml - mr);
  const y = c => mt + (1 - c) * (h - mt - mb);
  ctx.strokeStyle = "#cfcfcf"; ctx.strokeRect(ml, mt, w - ml - mr, h - mt - mb);
  ctx.fillStyle = "#555"; ctx.font = "10px Segoe UI";
  [0, .25, .5, .75, 1].forEach(c => {
    ctx.strokeStyle = "#eee"; ctx.beginPath(); ctx.moveTo(ml, y(c)); ctx.lineTo(plotRight, y(c)); ctx.stroke();
    ctx.fillText(fmt(c), 8, y(c) + 4);
  });
  [min, (min + max) / 2, max].forEach(v => ctx.fillText(Number(v.toPrecision(2)).toString(), x(v) - 12, h - mb + 18));
  if (showSpecLines) {
    drawSpec(ctx, x, mt, h - mb, specSource.lower_limit, "LSL", getCss("--green"), plotRight);
    drawSpec(ctx, x, mt, h - mb, specSource.upper_limit, "USL", getCss("--purple"), plotRight);
  }
  if (mode === "fail") {
    preSeries.forEach(series => drawCdf(ctx, series.values, x, y, series.color));
    if (hasReadoutSeries) {
      readoutSeries.forEach(series => drawCdf(ctx, series.values, x, y, series.color));
    }
    if (!hideFailData && hasReadoutSeries) {
      drawFailReadoutMarkers(ctx, readoutSeries, x, y);
    }
  } else {
    preSeries.forEach(series => drawCdf(ctx, series.values, x, y, series.color));
    if (hasReadoutSeries) {
      readoutSeries.forEach(series => drawCdf(ctx, series.values, x, y, series.color));
    } else if (fallbackPostSelected) {
      drawCdf(ctx, data.post_values, x, y, getCss("--red"));
    }
  }
  if (failOverlay.length) {
    const baselineValues = postAxisValues.length ? postAxisValues : data.post_values || [];
    drawFailOverlay(ctx, failOverlay, x, y, baselineValues);
  }
  if (preSelected && !hideFailData && (hasReadoutSeries || fallbackPostSelected)) drawShift(ctx, data, x, y, hasReadoutSeries ? readoutSeries : null, ml, plotRight);
  const readoutLegendY = drawLegend(ctx, legendX, legendY, mode, useSeriesLegend ? false : hasPre, useSeriesLegend, "center", showSpecLines);
  const displayedPreSeries = preSeries.map(series => ({ ...series, markerOnly: true }));
  const displayedReadoutSeries = mode === "fail"
    ? readoutSeries.map(series => ({ ...series, markerOnly: true }))
    : readoutSeries.map(series => ({ ...series, markerOnly: true }));
  drawReadoutLegend(ctx, useSeriesLegend ? [...displayedPreSeries, ...displayedReadoutSeries] : displayedReadoutSeries, legendX, readoutLegendY, "center");
}
function standardNormalDensity(value) {
  return Math.exp(-0.5 * value * value) / Math.sqrt(2 * Math.PI);
}
function normalDensityAt(value, mean = 0, spread = 1) {
  const sigma = Math.max(Number(spread) || 0, 0.08);
  return standardNormalDensity((value - mean) / sigma) / sigma;
}
function normalPdfCurve(mean, spread, min, max) {
  const span = max - min || 1;
  const gridCount = 220;
  return Array.from({ length: gridCount }, (_, index) => {
    const value = min + (span * index) / (gridCount - 1);
    return { value, density: normalDensityAt(value, mean, spread) };
  });
}
function ppfReferenceValues(entry, data) {
  const sourcePre = numericValues(entry?.source?.pre_values || []);
  if (sourcePre.length) return sourcePre;
  return numericValues(data?.pre_values || []);
}
function ppfFitSeries(entry, data) {
  const values = numericValues(entry?.values || []);
  if (!values.length) return null;
  const refValues = ppfReferenceValues(entry, data);
  const reference = refValues.length ? refValues : values;
  const refMean = meanValue(reference);
  let refSigma = populationStd(reference);
  if (!Number.isFinite(refSigma) || refSigma <= 0) {
    refSigma = populationStd(values) || 1;
  }
  const isPre = String(entry?.key || "").startsWith("pre_");
  const meanZ = isPre ? 0 : (meanValue(values) - refMean) / refSigma;
  const sigmaZ = isPre ? 1 : Math.max(populationStd(values) / refSigma, 0.08);
  const baseLabel = entry.label || entry.readout || entry.key || "Series";
  const shiftLabel = isPre ? "Ref" : `μ ${fmt(meanZ)}σ`;
  return {
    ...entry,
    label: `${baseLabel} ${shiftLabel}`,
    meanZ,
    sigmaZ,
    isPre
  };
}
function drawDensityCurve(ctx, curve, x, y, color, dashed = false, lineWidth = 2.2) {
  if (!curve.length) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  if (dashed) ctx.setLineDash([6, 4]);
  ctx.beginPath();
  curve.forEach((point, index) => {
    const px = x(point.value);
    const py = y(point.density);
    if (index === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  });
  ctx.stroke();
  ctx.restore();
}
function drawPpfChart() {
  const canvas = document.getElementById("ppfCanvas");
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, 360, 260);
  const data = itemCache[selectedItem];
  if (!data) return;
  if (isBinaryGraphItem(data)) { drawBinaryGraphNotice(canvas, 360, 260); return; }
  if (!hasSelectedGraphTemps()) return;
  if (!hasSelectedAnyReadout()) return;
  const readoutSeries = selectedGraphReadoutDetailSeries();
  const preSeries = allGraphPreSeries();
  const fits = [...preSeries, ...readoutSeries]
    .map(entry => ppfFitSeries(entry, data))
    .filter(Boolean);
  if (!fits.length) return;
  const ml = 58, mr = 230, mt = 24, mb = 78;
  const plotRight = w - mr;
  const legendX = plotRight + mr / 2;
  const legendY = mt + 16;
  let min = Math.min(-4, ...fits.map(entry => entry.meanZ - 4 * entry.sigmaZ));
  let max = Math.max(4, ...fits.map(entry => entry.meanZ + 4 * entry.sigmaZ));
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) { min = -4; max = 4; }
  const pad = Math.max((max - min) * 0.03, 0.15);
  min -= pad;
  max += pad;
  const curves = fits.map(entry => ({ ...entry, curve: normalPdfCurve(entry.meanZ, entry.sigmaZ, min, max) }));
  const maxDensity = Math.max(
    standardNormalDensity(0),
    ...curves.flatMap(entry => entry.curve.map(point => point.density)),
    0
  );
  if (!Number.isFinite(maxDensity) || maxDensity <= 0) return;
  const yMax = maxDensity * 1.08;
  const x = value => ml + (value - min) / (max - min) * (w - ml - mr);
  const y = density => mt + (1 - density / yMax) * (h - mt - mb);
  ctx.strokeStyle = "#cfcfcf";
  ctx.strokeRect(ml, mt, w - ml - mr, h - mt - mb);
  ctx.fillStyle = "#555";
  ctx.font = "10px Segoe UI";
  ctx.textAlign = "left";
  [0, .25, .5, .75, 1].map(ratio => yMax * ratio).forEach(density => {
    ctx.strokeStyle = "#eee";
    ctx.beginPath(); ctx.moveTo(ml, y(density)); ctx.lineTo(plotRight, y(density)); ctx.stroke();
    ctx.fillText(fmt(density), 8, y(density) + 4);
  });
  ctx.textAlign = "center";
  uniqueTicks([min, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, max])
    .filter(value => value >= min && value <= max)
    .forEach(value => ctx.fillText(fmt(value), x(value), h - mb + 18));
  ctx.save();
  ctx.strokeStyle = "#9aa5b1";
  ctx.fillStyle = "#606b78";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x(0), mt);
  ctx.lineTo(x(0), h - mb);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.textAlign = "left";
  ctx.fillText("Pre Mean", x(0) + 4, mt + 14);
  ctx.restore();
  ctx.font = "700 10px Segoe UI";
  ctx.fillStyle = "#555";
  ctx.textAlign = "center";
  ctx.fillText("Z from Pre", (ml + plotRight) / 2, h - 18);
  ctx.save();
  ctx.beginPath();
  ctx.rect(ml, mt, plotRight - ml, h - mt - mb);
  ctx.clip();
  curves.forEach(entry => drawDensityCurve(ctx, entry.curve, x, y, entry.color, entry.isPre, entry.isPre ? 2 : 2.2));
  ctx.restore();
  const readoutLegendY = drawLegend(ctx, legendX, legendY, analysis?.analysis_mode || analysisMode, false, true, "center", false);
  drawReadoutLegend(ctx, curves, legendX, readoutLegendY, "center");
}
function drawCharts() {
  updateGraphPanels();
  updateChartTitles();
  drawChart();
  drawPpfChart();
  drawScatterPlot();
  drawDiffCdfChart();
  drawWaferMap();
}
function waferPositionForSample(sample) {
  const text = String(sample ?? "").trim();
  const numeric = Number(text.replace(/[^0-9.-]/g, ""));
  const index = Number.isFinite(numeric) && numeric > 0 ? Math.floor(numeric) - 1 : 0;
  return { row: Math.floor(index / 12), col: index % 12 };
}
function drawWaferMap() {
  const canvas = document.getElementById("waferCanvas");
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, 520, 300);
  const data = itemCache[selectedItem];
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#0b438c";
  ctx.font = "800 16px Segoe UI";
  ctx.fillText("Wafer No.:", 18, 30);
  const selectedDetail = data?.details?.find(row => String(row.sample) === String(highlightSample)) || data?.details?.[0] || {};
  ctx.fillText(selectedDetail.wafer || selectedDetail.wafer_no || data?.wafer_no || "W--", 106, 30);
  const rows = 10, cols = 12;
  const left = 115;
  const top = 50;
  const legendReserve = Math.min(190, Math.max(110, w * 0.24));
  const cellW = (w - left - legendReserve - 16) / cols;
  const cellH = (h - top - 14) / (rows + 0.9);  // 0.9 = 반지름 여유(0.45셀) + 하단 여백
  const cell = Math.max(6, Math.min(cellW, cellH));
  const gridW = cols * cell;
  const gridH = rows * cell;
  const cx = left + gridW / 2;
  const cy = top + gridH / 2;
  const radius = Math.min(gridW, gridH) / 2 + cell * 0.45;
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.clip();
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = left + col * cell;
      const y = top + row * cell;
      const centerX = x + cell / 2;
      const centerY = y + cell / 2;
      const edge = Math.hypot(centerX - cx, centerY - cy) > radius - cell * 0.8;
      ctx.fillStyle = edge ? "#cfcfcf" : "#b8dafc";
      ctx.fillRect(x, y, cell - 1, cell - 1);
    }
  }
  const selectedSample = highlightSample || selectedDetail.sample;
  if (selectedSample !== undefined && selectedSample !== null && selectedSample !== "") {
    const pos = waferPositionForSample(selectedSample);
    const sx = left + Math.max(0, Math.min(cols - 1, pos.col)) * cell;
    const sy = top + Math.max(0, Math.min(rows - 1, pos.row)) * cell;
    ctx.fillStyle = "#ff6b6b";
    ctx.fillRect(sx, sy, cell - 1, cell - 1);
  }
  ctx.restore();
  ctx.strokeStyle = "#777";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = "#0b438c";
  ctx.font = "700 10px Segoe UI";
  ctx.textAlign = "center";
  for (let col = 0; col < cols; col++) ctx.fillText(String(col + 1), left + col * cell + cell / 2, top - 12);
  ctx.textAlign = "right";
  "ABCDEFGHIJ".split("").forEach((label, row) => ctx.fillText(label, left - 10, top + row * cell + cell / 2 + 4));
  const legendX = Math.min(left + gridW + 40, w - 150);
  const legendY = top + 70;
  const legend = [["#ff6b6b", `Fail${highlightSample ? ` (Sample #${highlightSample})` : ""}`], ["#b8dafc", "Good"], ["#cfcfcf", "Edge / No Die"]];
  ctx.textAlign = "left";
  ctx.font = "10px Segoe UI";
  legend.forEach(([color, label], index) => {
    const y = legendY + index * 28;
    ctx.fillStyle = color;
    ctx.fillRect(legendX, y - 13, 18, 18);
    ctx.fillStyle = "#17345f";
    ctx.fillText(label, legendX + 28, y + 1);
  });
}
function drawDiffCdfChart() {
  const canvas = document.getElementById("diffCdfCanvas");
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, 360, 260);
  const data = itemCache[selectedItem];
  if (!data) return;
  if (isBinaryGraphItem(data)) { drawBinaryGraphNotice(canvas, 360, 260); return; }
  if (!hasSelectedGraphTemps()) return;
  if (!hasSelectedReadouts()) return;
  const mode = analysis?.analysis_mode || analysisMode;
  const allReadoutSeries = allGraphReadoutDetailSeries();
  const hideFailData = mode === "fail" && failExceptionEnabled();
  const readoutSeries = hideFailData ? [] : selectedGraphReadoutDetailSeries();
  const hasReadoutSeries = readoutSeries.length > 0;
  const fallbackPostSelected = isPostT1Selected();
  const ml = 58, mr = hasReadoutSeries ? 180 : 26, mt = 34, mb = 58;
  const plotRight = w - mr;
  const values = hasReadoutSeries ? readoutSeries.flatMap(series => series.diff_values) : fallbackPostSelected && !hideFailData ? data.details
    .map(row => finiteNumber(row.diff))
    .filter(value => value !== null) : [];
  const passValues = hasReadoutSeries || !fallbackPostSelected ? [] : numericValues(data.pass_diff_values || []);
  const failOverlayDiffs = fallbackPostSelected ? numericValues((selectedFailItemData()?.details || []).map(row => row.diff)) : [];
  if (!values.length && !passValues.length && !failOverlayDiffs.length) return;
  const failBaselineValues = hasReadoutSeries ? values : passValues.length ? passValues : values;
  const baseValues = mode === "fail" ? failBaselineValues : values;
  const statsValues = baseValues.length ? baseValues : [...values, ...passValues, ...failOverlayDiffs];
  const allValues = [...values, ...passValues, ...failOverlayDiffs];
  const avg = statsValues.reduce((sum, value) => sum + value, 0) / statsValues.length;
  const sigma = Math.sqrt(statsValues.reduce((sum, value) => sum + Math.pow(value - avg, 2), 0) / statsValues.length);
  let min = avg - 6 * sigma, max = avg + 6 * sigma;
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    min = Math.min(...allValues);
    max = Math.max(...allValues);
  } else {
    min = Math.min(min, ...allValues);
    max = Math.max(max, ...allValues);
  }
  if (min === max) { min -= 1; max += 1; }
  const x = value => ml + (value - min) / (max - min) * (w - ml - mr);
  const y = cdf => mt + (1 - cdf) * (h - mt - mb);
  ctx.strokeStyle = "#cfcfcf";
  ctx.strokeRect(ml, mt, plotRight - ml, h - mt - mb);
  ctx.fillStyle = "#555";
  ctx.font = "700 16px Segoe UI";
  ctx.textAlign = "center";
  ctx.fillText(itemDisplayName(selectedItem) || "", (w - ml - mr) / 2 + ml, 22);
  ctx.font = "10px Segoe UI";
  ctx.textAlign = "left";
  [0, .25, .5, .75, 1].forEach(cdf => {
    ctx.strokeStyle = "#eee";
    ctx.beginPath(); ctx.moveTo(ml, y(cdf)); ctx.lineTo(plotRight, y(cdf)); ctx.stroke();
    ctx.fillText(fmt(cdf), 8, y(cdf) + 4);
  });
  ctx.textAlign = "center";
  [min, (min + max) / 2, max].forEach(value => ctx.fillText(fmt(value), x(value), h - mb + 18));
  if (Number.isFinite(sigma) && sigma > 0) {
    const limit = flagLimit("mea_s");
    [avg - limit * sigma, avg + limit * sigma].forEach((value, index) => {
      ctx.save();
      ctx.strokeStyle = getCss("--red");
      ctx.fillStyle = getCss("--red");
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(x(value), mt);
      ctx.lineTo(x(value), h - mb);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "10px Segoe UI";
      ctx.textAlign = index === 0 ? "left" : "right";
      ctx.fillText(`${index === 0 ? "-" : "+"}${fmt(limit)}σ`, x(value) + (index === 0 ? 4 : -4), mt + 14);
      ctx.restore();
    });
  }
  ctx.save();
  ctx.beginPath();
  ctx.rect(ml, mt, plotRight - ml, h - mt - mb);
  ctx.clip();
  if (hasReadoutSeries) {
    readoutSeries.forEach(series => drawCdf(ctx, series.diff_values, x, y, series.color));
  } else if (mode === "fail") {
    if (failBaselineValues.length) drawCdf(ctx, failBaselineValues, x, y, getCss("--blue"));
    if (!hideFailData) drawFailDirectionMarkers(ctx, data.details, "diff", x, y);
  } else {
    drawCdf(ctx, values, x, y, getCss("--blue"));
  }
  if (failOverlayDiffs.length) {
    drawFailOverlay(ctx, failOverlayDiffs.map((value, index) => ({ value, sample: index + 1 })), x, y, values.length ? values : allValues);
  }
  ctx.restore();
  if (mode === "fail" && !hideFailData && !passValues.length && !hasReadoutSeries) {
    ctx.save();
    ctx.fillStyle = "#7a4f00";
    ctx.font = "10px Segoe UI";
    ctx.textAlign = "left";
    ctx.fillText("Pass Diff data unavailable; using fail Diff values as baseline.", ml + 6, mt + 18);
    ctx.restore();
  }
  if (highlightSample) {
    if (hasReadoutSeries) {
      readoutSeries.forEach(series => {
        const point = series.points.find(entry => String(entry.sample) === String(highlightSample));
        if (!point || point.diff === null) return;
        const cdf = cdfFraction(series.diff_values, point.diff);
        drawHighlightPoint(ctx, x(point.diff), y(cdf), series.color, `#${highlightSample} ${series.label || series.key} Diff ${fmt(point.diff)}`);
      });
    } else if (fallbackPostSelected) {
      const row = data.details.find(detail => String(detail.sample) === String(highlightSample));
      const diffValue = row ? finiteNumber(row.diff) : null;
      if (diffValue !== null && sigmaOver3(row, "diff_s")) {
        const cdf = mode === "fail" ? failDirectionCdf(row) : cdfFraction(values, diffValue);
        drawHighlightPoint(ctx, x(diffValue), y(cdf), "#b00020", `#${highlightSample} Diff ${fmt(diffValue)}`);
      }
    }
  }
  if (hasReadoutSeries) drawReadoutLegend(ctx, readoutSeries, plotRight + mr / 2, mt + 18, "center");
}
function drawScatterPlot() {
  const canvas = document.getElementById("scatterCanvas");
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, 360, 260);
  const data = itemCache[selectedItem];
  if (!data) return;
  if (isBinaryGraphItem(data)) { drawBinaryGraphNotice(canvas, 360, 260); return; }
  if (!hasSelectedGraphTemps()) return;
  if (!hasSelectedReadouts()) return;
  const allReadoutSeries = allGraphReadoutDetailSeries();
  const hideFailData = (analysis?.analysis_mode || analysisMode) === "fail" && failExceptionEnabled();
  const readoutSeries = hideFailData ? [] : selectedGraphReadoutDetailSeries();
  const hasReadoutSeries = readoutSeries.length > 0;
  const fallbackPostSelected = isPostT1Selected();
  const ml = 62, mr = hasReadoutSeries ? 180 : 26, mt = 42, mb = 58;
  const left = ml, right = w - mr, top = mt, bottom = h - mb;
  ctx.strokeStyle = "#cfcfcf";
  ctx.strokeRect(left, top, right - left, bottom - top);
  ctx.fillStyle = "#555";
  ctx.font = "700 16px Segoe UI";
  ctx.textAlign = "center";
  ctx.fillText(itemDisplayName(selectedItem) || "", (left + right) / 2, 22);
  ctx.font = "700 10px Segoe UI";
  ctx.fillText("Diff_S", (left + right) / 2, h - 18);
  ctx.save();
  ctx.translate(18, (top + bottom) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Mea_S", 0, 0);
  ctx.restore();
  let rows = hasReadoutSeries ? readoutSeries.flatMap(series =>
    series.points
      .filter(point => finiteNumber(point.diff_s) !== null && finiteNumber(point.mea_s) !== null)
      .map(point => ({ ...point, series_label: series.label || series.key, color: series.color }))
  ) : fallbackPostSelected && !hideFailData ? [...data.details].filter(row =>
    finiteNumber(row.diff_s) !== null && finiteNumber(row.mea_s) !== null
  ) : [];
  const failScatterRows = fallbackPostSelected ? (selectedFailItemData()?.details || [])
    .filter(row => finiteNumber(row.diff_s) !== null && finiteNumber(row.mea_s) !== null)
    .map(row => ({ ...row, color: "#ff4d4f", overlay_fail: true })) : [];
  rows = rows.concat(failScatterRows);
  const xValues = rows.map(row => Number(row.diff_s));
  const yValues = rows.map(row => Number(row.mea_s));
  let minX = Math.min(-9, 0, ...xValues), maxX = Math.max(9, 0, ...xValues);
  let minY = Math.min(-9, 0, ...yValues), maxY = Math.max(9, 0, ...yValues);
  if (minX === maxX) { minX -= 1; maxX += 1; }
  if (minY === maxY) { minY -= 1; maxY += 1; }
  const padX = (maxX - minX) * 0.08;
  const padY = (maxY - minY) * 0.08;
  minX -= padX; maxX += padX; minY -= padY; maxY += padY;
  const x = value => left + (value - minX) / (maxX - minX) * (right - left);
  const y = value => bottom - (value - minY) / (maxY - minY) * (bottom - top);
  const xTicks = uniqueTicks([minX, -9, -6, -3, 0, 3, 6, 9, maxX]);
  const yTicks = uniqueTicks([minY, -9, -6, -3, 0, 3, 6, 9, maxY]);
  const diffLimit = flagLimit("diff_s");
  const meaLimit = flagLimit("mea_s");
  ctx.fillStyle = "rgba(31, 119, 180, 0.20)";
  ctx.fillRect(x(-diffLimit), y(meaLimit), x(diffLimit) - x(-diffLimit), y(-meaLimit) - y(meaLimit));
  ctx.font = "10px Segoe UI";
  ctx.textAlign = "center";
  xTicks.forEach(value => {
    ctx.strokeStyle = "#e8edf2";
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(x(value), top); ctx.lineTo(x(value), bottom); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#555";
    ctx.fillText(fmt(value), x(value), bottom + 18);
  });
  ctx.textAlign = "right";
  yTicks.forEach(value => {
    ctx.strokeStyle = "#e8edf2";
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(left, y(value)); ctx.lineTo(right, y(value)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#555";
    ctx.fillText(fmt(value), left - 8, y(value) + 4);
  });
  rows.forEach(row => {
    const px = x(Number(row.diff_s));
    const py = y(Number(row.mea_s));
    const fail = Math.abs(Number(row.diff_s)) > diffLimit || Math.abs(Number(row.mea_s)) > meaLimit;
    ctx.fillStyle = row.overlay_fail ? "#ff4d4f" : hasReadoutSeries ? row.color : fail ? getCss("--red") : getCss("--blue");
    ctx.beginPath(); ctx.arc(px, py, 4.2, 0, Math.PI * 2); ctx.fill();
    if (hasReadoutSeries && fail) {
      ctx.strokeStyle = getCss("--red");
      ctx.lineWidth = 1.8;
      ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2); ctx.stroke();
    }
    if (String(row.sample) === String(highlightSample)) {
      ctx.strokeStyle = "#111";
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2); ctx.stroke();
    }
  });
  if (hasReadoutSeries) drawReadoutLegend(ctx, readoutSeries, right + mr / 2, mt + 18, "center");
}
function uniqueTicks(values) {
  const ticks = [];
  values.forEach(value => {
    if (!Number.isFinite(value)) return;
    const rounded = Math.abs(value) < 1e-9 ? 0 : Number(value.toPrecision(3));
    if (!ticks.some(existing => Math.abs(existing - rounded) < 1e-6)) ticks.push(rounded);
  });
  return ticks.sort((a, b) => a - b);
}
function getCss(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function drawSpec(ctx, x, top, bottom, value, label, color, plotRight = null) {
  if (value === null || value === undefined) return;
  ctx.save(); ctx.strokeStyle = color; ctx.fillStyle = color; ctx.setLineDash([5,4]); ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(x(value), top); ctx.lineTo(x(value), bottom); ctx.stroke();
  ctx.setLineDash([]);
  const px = x(value);
  const alignRight = plotRight !== null && px > plotRight - 70;
  ctx.textAlign = alignRight ? "right" : "left";
  ctx.fillText(`${label} ${fmt(value)}`, alignRight ? px - 4 : px + 4, top + 14);
  ctx.restore();
}
function drawCdf(ctx, values, x, y, color) {
  const sorted = numericValues(values).sort((a,b) => a-b);
  const n = sorted.length;
  if (!n) return;
  ctx.fillStyle = color;
  const drawPoint = index => {
    const cdf = (index + 1) / n;
    ctx.beginPath(); ctx.arc(x(sorted[index]), y(cdf), 2.3, 0, Math.PI * 2); ctx.fill();
  };
  // Tail outliers must never be thinned away regardless of where a 3σ/Grubbs cutoff
  // falls (that threshold lives in a different branch and can change independently),
  // so the two ends are always drawn in full and only the middle is subsampled.
  const edgeCount = Math.min(50, n);
  const middleStart = edgeCount;
  const middleEnd = n - edgeCount; // exclusive
  const middleLen = Math.max(0, middleEnd - middleStart);
  const middleBudget = Math.max(1, 1200 - edgeCount * 2);
  for (let index = 0; index < middleStart; index++) drawPoint(index);
  for (let index = Math.max(middleStart, middleEnd); index < n; index++) drawPoint(index);
  if (middleLen <= middleBudget) {
    for (let index = middleStart; index < middleEnd; index++) drawPoint(index);
  } else {
    // Fractional step + rounding (not integer modulo) so the drawn count lands close
    // to middleBudget instead of jumping in whole multiples of an integer step.
    const pointStep = middleLen / middleBudget;
    let lastIndex = -1;
    for (let k = 0; ; k++) {
      const index = middleStart + Math.round(k * pointStep);
      if (index >= middleEnd) break;
      if (index !== lastIndex) { drawPoint(index); lastIndex = index; }
    }
  }
}
function failDirectionCdf(row) {
  const post = Number(row?.post_value);
  const lower = Number(row?.lower_limit);
  const upper = Number(row?.upper_limit);
  if (Number.isFinite(lower) && Number.isFinite(post) && post < lower) return 0;
  if (Number.isFinite(upper) && Number.isFinite(post) && post > upper) return 1;
  return 0.5;
}
function flagLimit(key) {
  // 항목마다 n 이 달라 Grubbs 임계값도 다르다 — 현재 선택된 item 의 payload 에 실린
  // mea_threshold/diff_threshold(§S3) 를 우선 쓰고, 없으면(구 데이터/전역 표시용) 서버가
  // 내려준 flag_limit(고정 모드 값)으로 대체한다.
  const data = itemCache[selectedItem] || analysis?.items?.[selectedItem] || {};
  const perItem = key === "diff_s" ? data.diff_threshold : data.mea_threshold;
  const value = Number(perItem);
  if (Number.isFinite(value)) return value;
  return Number(analysis?.flag_limit ?? 3);
}
function sigmaOver3(row, key) {
  return Math.abs(Number(row?.[key])) > flagLimit(key);
}
function drawFailDirectionMarkers(ctx, rows, valueKey, x, y) {
  ctx.save();
  ctx.fillStyle = "#b00020";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  rows.forEach(row => {
    const value = Number(row[valueKey]);
    if (!Number.isFinite(value)) return;
    const cy = y(failDirectionCdf(row));
    const cx = x(value);
    ctx.beginPath();
    ctx.arc(cx, cy, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });
  ctx.restore();
}
function drawShift(ctx, data, x, y, readoutSeries = null, plotLeft = 58, plotRight = 0) {
  if (!highlightSample) return;
  const d = data.details.find(row => String(row.sample) === String(highlightSample));
  if (!d) return;
  const forceSampleHighlight = highlightMode === "sample";
  if (readoutSeries && readoutSeries.length) {
    readoutSeries.forEach((series, index) => {
      const point = (series.points || []).find(entry => String(entry.sample) === String(highlightSample));
      const postValue = point ? point.post_value : finiteNumber(d[series.key]);
      if (postValue === null || postValue === undefined) return;
      const mode = analysis?.analysis_mode || analysisMode;
      const cdf = mode === "fail"
        ? failCdfForValue(postValue, point?.row || d, series.post_values || series.values || [])
        : cdfFraction(series.values, postValue);
      const color = series.color || readoutColor(series.key, index);
      const label = series.label || series.key;
      const px = x(postValue);
      const py = y(cdf);
      const showMeasurement = forceSampleHighlight || (point ? Math.abs(Number(point.mea_s)) > flagLimit("mea_s") : sigmaOver3(d, "mea_s"));
      const showShift = forceSampleHighlight || (point ? Math.abs(Number(point.diff_s)) > flagLimit("diff_s") : sigmaOver3(d, "diff_s"));
      if (showMeasurement) {
        drawHighlightPoint(ctx, px, py, color, `#${highlightSample} ${label} ${fmt(postValue)}`);
      }
      const preValue = point ? point.pre_value : finiteNumber(d.pre_value);
      if (!showShift || preValue === null || preValue === undefined) return;
      const sourceData = series.source || data;
      const preC = cdfFraction(sourceData.pre_values || data.pre_values, preValue);
      if (preC === null) return;
      const qx = x(preValue);
      const qy = y(preC);
      if (!showMeasurement) {
        drawHighlightPoint(ctx, px, py, color, `#${highlightSample} ${label} ${fmt(postValue)}`);
      }
      drawHighlightPoint(ctx, qx, qy, "#004c99", `Pre ${fmt(preValue)}`);
      const top = y(1), bottom = y(0);
      const stagger = 22 + index * 20;
      const yLine = Math.min(Math.max(py - stagger, top + 20), bottom - 20);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2.2;
      arrow(ctx, qx, yLine, px, yLine);
      const labelX = Math.min(Math.max((qx + px) / 2, plotLeft + 58), (plotRight || Math.max(qx, px)) - 58);
      ctx.font = "10px Segoe UI";
      ctx.textAlign = "center";
      ctx.fillText(`${label} Shift ${fmt(postValue - preValue)}`, labelX, yLine - 8);
      ctx.restore();
    });
    return;
  }
  const mode = analysis?.analysis_mode || analysisMode;
  const showMeasurement = forceSampleHighlight || sigmaOver3(d, "mea_s");
  const showShift = forceSampleHighlight || sigmaOver3(d, "diff_s");
  const postValue = finiteNumber(d.post_value);
  if (postValue === null) return;
  const failBaseline = numericValues(data.pass_post_values || data.post_values || []);
  const postC = mode === "fail" ? cdfFraction(failBaseline.length ? failBaseline : data.post_values, postValue) : cdfFraction(data.post_values, postValue);
  if (postC === null) return;
  const px = x(postValue), py = y(postC);
  if (showMeasurement) {
    drawHighlightPoint(ctx, px, py, "#b00020", `#${highlightSample} Post ${fmt(postValue)}`);
  }
  if (!showShift || d.pre_value === null || d.pre_value === undefined) return;
  const preValue = finiteNumber(d.pre_value);
  if (preValue === null) return;
  const preC = cdfFraction(data.pre_values, preValue);
  if (preC === null) return;
  const qx = x(preValue), qy = y(preC);
  drawHighlightPoint(ctx, qx, qy, "#004c99", `Pre ${fmt(preValue)}`);
  if (!showMeasurement) {
    drawHighlightPoint(ctx, px, py, "#b00020", `#${highlightSample} Post ${fmt(postValue)}`);
  }
  const top = y(1), bottom = y(0);
  const yLine = Math.min(Math.max(py - 28, top + 22), bottom - 22);
  ctx.save();
  ctx.strokeStyle = "#111"; ctx.fillStyle = "#111"; ctx.lineWidth = 2.5;
  arrow(ctx, qx, yLine, px, yLine);
  ctx.fillText(`Shift ${fmt(postValue - preValue)}`, Math.min(qx, px) + Math.abs(px - qx) / 2 + 6, yLine - 8);
  ctx.restore();
}
function drawHighlightPoint(ctx, x, y, color, label) {
  ctx.save();
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
  ctx.fillText(label, x + 8, y - 8);
  ctx.restore();
}
function arrow(ctx, x1, y1, x2, y2) {
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  const a = Math.atan2(y2-y1, x2-x1), len = 9;
  ctx.beginPath(); ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - len*Math.cos(a - Math.PI/6), y2 - len*Math.sin(a - Math.PI/6));
  ctx.lineTo(x2 - len*Math.cos(a + Math.PI/6), y2 - len*Math.sin(a + Math.PI/6));
  ctx.closePath(); ctx.fill();
}
function drawLegend(ctx, x, y, mode = "pass", hasPre = true, readoutMode = false, align = "left", showSpecLines = true) {
  ctx.save();
  ctx.font = "10px Segoe UI";
  let offset = 0;
  const addLine = (label, color, dashed) => {
    lineLabel(ctx, x, y + offset, label, color, dashed, align);
    offset += 26;
  };
  const addMarker = (label, color) => {
    markerLabel(ctx, x, y + offset, label, color, align);
    offset += 26;
  };
  if (readoutMode) {
    if (showSpecLines) {
      addLine("LSL", getCss("--green"), true);
      addLine("USL", getCss("--purple"), true);
    }
    if (hasPre) addLine("Pre", getCss("--blue"), false);
    ctx.restore();
    return y + offset + 16;
  }
  if (mode === "fail") {
    if (hasPre) addLine("Pre", getCss("--blue"), false);
    addLine("Post(Pass)", getCss("--red"), false);
    addMarker("Post(Fail)", "#b00020");
    if (showSpecLines) {
      addLine("LSL", getCss("--green"), true);
      addLine("USL", getCss("--purple"), true);
    }
  } else {
    if (hasPre) addLine("Pre", getCss("--blue"), false);
    addLine("Post", getCss("--red"), false);
    if (showSpecLines) {
      addLine("LSL", getCss("--green"), true);
      addLine("USL", getCss("--purple"), true);
    }
  }
  ctx.restore();
  return y + offset + 16;
}
function lineLabel(ctx, x, y, label, color, dashed, align = "left") {
  ctx.save(); ctx.strokeStyle = color; ctx.fillStyle = "#111"; ctx.lineWidth = 2; if (dashed) ctx.setLineDash([5,4]);
  const lineWidth = 24;
  const gap = 6;
  const width = lineWidth + gap + ctx.measureText(label).width;
  const startX = align === "center" ? x - width / 2 : x;
  ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(startX + lineWidth, y); ctx.stroke(); ctx.setLineDash([]);
  ctx.fillText(label, startX + lineWidth + gap, y+4); ctx.restore();
}
function markerLabel(ctx, x, y, label, color, align = "left") {
  ctx.save();
  const markerWidth = 24;
  const gap = 6;
  const width = markerWidth + gap + ctx.measureText(label).width;
  const startX = align === "center" ? x - width / 2 : x;
  ctx.fillStyle = color;
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.arc(startX + 12, y, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#111";
  ctx.fillText(label, startX + markerWidth + gap, y + 4);
  ctx.restore();
}
let chartRedrawRaf = 0;
let lastGraphBoxKey = "";
function scheduleChartRedraw() {
  if (chartRedrawRaf) return;
  chartRedrawRaf = requestAnimationFrame(() => {
    chartRedrawRaf = 0;
    if (analysis) drawCharts();
  });
}
window.addEventListener("resize", scheduleChartRedraw);
if (typeof ResizeObserver !== "undefined") {
  const graphColumn = document.querySelector(".result-graph-column");
  if (graphColumn) {
    new ResizeObserver(entries => {
      const box = entries[0] && entries[0].contentRect;
      if (!box) return;
      const key = `${Math.round(box.width)}x${Math.round(box.height)}`;
      if (key === lastGraphBoxKey) return;
      lastGraphBoxKey = key;
      scheduleChartRedraw();
    }).observe(graphColumn);
  }
}
</script>
</body>
</html>"""
HTML = HTML.replace("__APP_REVISION__", APP_REVISION)


class MultipartPart:
    def __init__(self, headers, content):
        self.headers = headers
        self.content = content
        disposition = headers.get("content-disposition", "")
        self.name = self._disposition_value(disposition, "name")
        self.filename = self._disposition_value(disposition, "filename")

    @staticmethod
    def _disposition_value(disposition, key):
        prefix = key + '="'
        start = disposition.find(prefix)
        if start < 0:
            return ""
        start += len(prefix)
        end = disposition.find('"', start)
        return disposition[start:end] if end >= 0 else ""


def parse_multipart(content_type, body):
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Invalid multipart request.")
    boundary = ("--" + content_type.split(marker, 1)[1].strip().strip('"')).encode()
    parts = {}
    for raw_part in body.split(boundary):
        raw_part = raw_part.strip(b"\r\n")
        if not raw_part or raw_part == b"--":
            continue
        header_blob, _, content = raw_part.partition(b"\r\n\r\n")
        headers = {}
        for line in header_blob.decode("utf-8", "replace").split("\r\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        if content.endswith(b"--"):
            content = content[:-2]
        part = MultipartPart(headers, content.rstrip(b"\r\n"))
        if part.name:
            parts[part.name] = part
    return parts


def write_upload(part):
    suffix = os.path.splitext(part.filename)[1] or ".csv"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(part.content)
    return path


DISALLOWED_BIN1_UNITS = (
    "pass/fail",
    "passfail",
    "pass_fail",
    "boolean",
    "binary",
    "bool",
    "logic",
    "result",
    "bin",
    "code",
    "count",
    "cnt",
    "n/a",
    "n.a",
    "none",
    "-",
)


def unit_token_is_allowed(token):
    if not token:
        return False
    if re.fullmatch(r"(f|p|n|u|m|k|meg|g)?[va]", token):
        return True
    if re.fullmatch(r"(f|p|n|u|m|k)?s(ec)?", token):
        return True
    return token.endswith("ohm")


def unit_is_allowed(unit):
    raw = str(unit or "").strip()
    if raw in {"NA", "N.A", "N/A", "N\\A"}:
        return False
    text = raw.casefold()
    if not text:
        return False
    text = text.replace("µ", "u").replace("μ", "u").replace("ω", "ohm").replace("Ω", "ohm").replace("Ω", "ohm")
    compact = re.sub(r"[\s_]+", "", text)
    if compact in DISALLOWED_BIN1_UNITS or any(bad in compact for bad in DISALLOWED_BIN1_UNITS if len(bad) > 2):
        return False
    tokens = [token for token in re.split(r"[^a-z0-9]+", text) if token]
    return any(unit_token_is_allowed(token) for token in tokens) or unit_token_is_allowed(compact)


def item_has_allowed_unit(records):
    for record in records:
        if unit_is_allowed(record.get("unit", "")):
            return True
    return False


def filter_records_by_allowed_units(pre_records, post_records):
    all_items = set(pre_records) | set(post_records)
    allowed_items = {
        item
        for item in all_items
        if item_has_allowed_unit(pre_records.get(item, []))
        or item_has_allowed_unit(post_records.get(item, []))
    }
    return (
        {item: records for item, records in pre_records.items() if item in allowed_items},
        {item: records for item, records in post_records.items() if item in allowed_items},
    )


def excluded_items_by_unit(pre_records, post_records):
    """unit_is_allowed() 에서 걸러진 항목을 item/unit 단위로 모은다 (인라인 배너용)."""
    all_items = set(pre_records) | set(post_records)
    excluded = []
    for item in all_items:
        if item_has_allowed_unit(pre_records.get(item, [])) or item_has_allowed_unit(post_records.get(item, [])):
            continue
        records = post_records.get(item) or pre_records.get(item) or []
        unit = records[0].get("unit", "") if records else ""
        excluded.append({"item": item, "unit": unit, "reason": "unit_not_allowed"})
    excluded.sort(key=lambda row: natural_key(row["item"]))
    return excluded


RECORD_CACHE = {}
RECORD_CACHE_LOCK = threading.Lock()
RECORD_PARSE_LOCKS = {}


def file_stamp(path):
    """(abspath, mtime_ns, size). 존재하지 않으면 None."""
    try:
        stat = os.stat(path)
        return (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def record_cache_key(path):
    stamp = file_stamp(path)
    if stamp is None:
        raise FileNotFoundError(path)
    return stamp


def raw_item_records(path):
    """파일 하나를 RAW 로 파싱한 결과 (last_sample 필터 적용 전). RAM(RECORD_CACHE) →
    디스크(parse cache) → 실제 파싱 순으로 조회한다. last_sample 유무는 키에 넣지 않으므로
    pass/fail 이 같은 파일을 다른 last_sample 값으로 동시에 요청해도 서로의 캐시를 축출하지 않는다.
    같은 키를 동시에 처음 요청하는 스레드끼리는 key 별 락으로 직렬화해, 콜드 캐시 상태에서
    pass/fail 이 동시에 들어와도 실제 파싱(및 read_table)이 파일당 한 번만 일어나게 한다."""
    if not path:
        return {}
    key = record_cache_key(path)
    with RECORD_CACHE_LOCK:
        cached = RECORD_CACHE.get(key)
        if cached is not None:
            return cached
        lock = RECORD_PARSE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            RECORD_PARSE_LOCKS[key] = lock
    with lock:
        with RECORD_CACHE_LOCK:
            cached = RECORD_CACHE.get(key)
            if cached is not None:
                return cached
        records = load_parse_cache(path, key)
        if records is None:
            records = extract_item_records(read_table(path))
            save_parse_cache(path, key, records)
        abs_path = key[0]
        with RECORD_CACHE_LOCK:
            for old_key in [old_key for old_key in RECORD_CACHE if old_key[0] == abs_path and old_key != key]:
                RECORD_CACHE.pop(old_key, None)
            RECORD_CACHE[key] = records
            RECORD_PARSE_LOCKS.pop(key, None)
    return records


def cached_item_records(path, last_sample=False):
    records = raw_item_records(path)
    if last_sample:
        records = filter_records_to_last_sample(records)
    return records


def make_app(pre_path, post_path, bin1_only, progress=None, include_pre=True):
    def update(percent, message):
        if progress:
            progress(percent, message)

    app = object.__new__(CdfCompareApp)
    app.include_pre = include_pre
    if include_pre:
        update(25, "Reading Pre")
        app.pre_records = cached_item_records(pre_path)
    else:
        app.pre_records = {}
    update(38, "Reading Post")
    app.post_records = cached_item_records(post_path, last_sample=True)
    if bin1_only:
        update(70, "Filtering Pass Samples")
        app.pre_records, app.post_records = filter_pass_analysis_records(app.pre_records, app.post_records)
        app.excluded_items = excluded_items_by_unit(app.pre_records, app.post_records)
        app.pre_records, app.post_records = filter_records_by_allowed_units(app.pre_records, app.post_records)
    else:
        update(70, "Excluding Fail Samples")
        app.pre_records, app.post_records = filter_pass_analysis_records(app.pre_records, app.post_records)
        app.excluded_items = []
    # pre_cdf_values_for_item() 의 PASS_SAMPLE_IDS_AUTO 센티널을 여기서 한 번만 실제 값으로
    # 치환한다. 그렇지 않으면 item_to_json() 이 항목마다 pass_sample_ids_from_records(전체
    # pre_records)를 다시 순회한다 (항목 수 x pre 레코드 수 규모로 재계산, §2 벤치에서 실측:
    # payload_with_items 866s/921s = 94%). None 은 "bin 데이터 없음 = 필터 안 함"이라는 유효한
    # 결과이므로 센티널과 구분해 그대로 저장한다.
    app.pre_pass_samples = pass_sample_ids_from_records(app.pre_records) if include_pre else None
    update(76, "Preparing Items")
    app.pre_items = {item: [record["value"] for record in records] for item, records in app.pre_records.items()}
    app.post_items = {item: [record["value"] for record in records] for item, records in app.post_records.items()}
    app.item_analysis_cache = {}
    update(84, "Calculating")
    app.results = calculate_results_vectorized(app)
    return app


def to_jsonable(value):
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        if value in (float("inf"), float("-inf")):
            return None
    return value


def natural_key(value):
    text = str(value or "").replace("_", ".")
    parts = []
    for part in text.split("."):
        try:
            parts.append((0, float(part)))
        except ValueError:
            parts.append((1, part.lower()))
    return parts


def item_sort_key(app, item):
    return (natural_key(CdfCompareApp.test_number_for_item(app, item)), item)


def item_metadata(app, item):
    metadata = {"unit": "", "lower_limit": None, "upper_limit": None}
    for records in (app.post_records.get(item, []), app.pre_records.get(item, [])):
        for record in records:
            if not metadata["unit"]:
                metadata["unit"] = record.get("unit", "")
            if metadata["lower_limit"] is None:
                metadata["lower_limit"] = record.get("lower_limit")
            if metadata["upper_limit"] is None:
                metadata["upper_limit"] = record.get("upper_limit")
            if metadata["unit"] and metadata["lower_limit"] is not None and metadata["upper_limit"] is not None:
                return metadata
    return metadata


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def records_values(records):
    return [record.get("value") for record in records if finite_number(record.get("value")) is not None]


def record_device_id(record):
    return str(record.get("device_id", "")).strip()


def record_sample_id(record):
    # Pre/Post join key: prefer DEVICE_ID (see CLAUDE.md §3-3 -- Pre and Post use
    # unrelated Serial # numbering, so every function that joins records via this
    # helper -- records_by_sample, filter_records_by_sample_ids,
    # pass_sample_ids_from_records, item_analysis -- becomes DEVICE_ID-aware for
    # free. Falls back to Serial # when this record has no DEVICE_ID value.
    device_id = record_device_id(record)
    if device_id:
        return device_id
    return str(record.get("sample", "")).strip()


def records_by_sample(records):
    by_sample = {}
    for record in records:
        sample = record_sample_id(record)
        if sample:
            by_sample[sample] = record
    return by_sample


def match_summary_for_files(pre_records_raw, post_records_raw):
    if not post_records_raw:
        return None
    ref_item = max(post_records_raw, key=lambda name: len(post_records_raw[name]))
    post_rows = post_records_raw[ref_item]
    if not post_rows:
        return None
    pre_device_ids = {
        record_device_id(record)
        for records in pre_records_raw.values()
        for record in records
        if record_device_id(record)
    }
    if pre_device_ids and any(record_device_id(record) for record in post_rows):
        matched = sum(1 for record in post_rows if record_device_id(record) in pre_device_ids)
        key = "device_id"
    else:
        pre_samples = {
            record_sample_id(record)
            for records in pre_records_raw.values()
            for record in records
            if record_sample_id(record)
        }
        matched = sum(1 for record in post_rows if record_sample_id(record) in pre_samples)
        key = "sample"
    return {
        "key": key,
        "post_units": len(post_rows),
        "matched": matched,
        "unmatched": len(post_rows) - matched,
    }


def vector_stats(values):
    # 판정용 sigma: 표본표준편차(ddof=1). §S2.
    return mean_of(values), std_of(values, ddof=1)


def vector_sigmas(values, center, spread):
    return zscore(values, center, spread)


def max_abs_finite(values):
    # 유한값이 하나도 없으면 None(정의 불가) — §S5. stats_core.max_abs_z 와 동일한 이유로
    # 0.0("이상치 없음")과 "잴 수 없음"을 구분해야 한다.
    nums = [abs(value) for value in values if value is not None and math.isfinite(value)]
    return max(nums) if nums else None


def paired_diffs_for_details(pre_values, post_values, pre_scale=None):
    count = min(len(pre_values), len(post_values))
    result = [None] * len(post_values)
    if count <= 0:
        return result, []
    pre_clean = [finite_number(value) for value in pre_values[:count]]
    post_clean = [finite_number(value) for value in post_values[:count]]
    if np is not None:
        pre = np.asarray([math.nan if value is None else value for value in pre_clean], dtype=float)
        post = np.asarray([math.nan if value is None else value for value in post_clean], dtype=float)
        valid = np.isfinite(pre) & np.isfinite(post) & (pre != 0)
        if pre_scale is not None and pre_scale > 0:
            # §S4(범위 축소판): pre 가 항목 스케일 대비 0 에 가까우면 diff_ratio 가
            # 폭발한다 — numpy 경로도 diff_ratio() 와 동일한 상대 임계로 걸러야 두 경로
            # 결과가 갈리지 않는다.
            valid &= np.abs(pre) >= (EPS_REL * pre_scale)
        diffs = np.empty(count, dtype=float)
        diffs.fill(np.nan)
        diffs[valid] = (post[valid] - pre[valid]) / np.abs(pre[valid])
        detail = diffs.tolist()
        for index, value in enumerate(detail):
            result[index] = float(value) if math.isfinite(value) else None
        return result, [float(value) for value in diffs[valid]]
    diff_values = []
    for index in range(count):
        pre_value = pre_clean[index]
        post_value = post_clean[index]
        diff = (
            diff_ratio(pre_value, post_value, pre_scale=pre_scale)
            if pre_value is not None and post_value is not None else None
        )
        result[index] = diff
        if diff is not None and math.isfinite(diff):
            diff_values.append(diff)
    return result, diff_values


def normal_cdf_value(z_value):
    if z_value is None or not math.isfinite(z_value):
        return None
    if z_value == math.inf:
        return 1.0
    if z_value == -math.inf:
        return 0.0
    return 0.5 * (1.0 + math.erf(z_value / math.sqrt(2.0)))


def item_analysis(app, item):
    cache = app.__dict__.get("item_analysis_cache")
    if cache is None:
        cache = {}
        app.item_analysis_cache = cache
    if item in cache:
        return cache[item]
    post_records = app.post_records.get(item, [])
    pre_records = app.pre_records.get(item, [])
    post_values = records_values(post_records)
    pre_values = records_values(pre_records)
    pre_by_sample = records_by_sample(pre_records)
    paired_pre_values = [
        pre_by_sample.get(record_sample_id(post_record), {}).get("value")
        for post_record in post_records
    ]
    post_mean, post_sigma = vector_stats(post_values)
    pre_mean, pre_sigma = vector_stats(pre_values)
    mea_s_values = vector_sigmas(post_values, post_mean, post_sigma)
    pre_scale = robust_pre_scale(pre_values)
    diff_detail_values, diff_values = paired_diffs_for_details(paired_pre_values, post_values, pre_scale=pre_scale)
    diff_mean, diff_sigma = vector_stats(diff_values)
    diff_s_values = vector_sigmas(diff_detail_values, diff_mean, diff_sigma)
    pre_mea_s_values = vector_sigmas(paired_pre_values, pre_mean, pre_sigma)
    mea_s_max = max_abs_finite(mea_s_values)
    diff_s_max = max_abs_finite(diff_s_values)
    n_post = len(post_values)
    n_diff = len(diff_values)
    # 판정 임계: mea_s 는 post 표본(n_post), diff_s 는 유효 diff 쌍(n_diff) 기준 — 표본이
    # 다를 수 있어 각자의 n 으로 독립 평가한다 (§S3).
    mea_threshold = threshold_for(n_post)
    diff_threshold = threshold_for(n_diff)
    result = "NO PRE ITEM"
    include_pre = app.__dict__.get("include_pre", True)
    if not include_pre:
        result = flag_result(mea_s_max, None, n_post, sigma=post_sigma, mean=post_mean, mea_threshold=mea_threshold)
    elif pre_values:
        result = flag_result(
            mea_s_max, diff_s_max, n_post, sigma=post_sigma, mean=post_mean,
            diff_n=n_diff, diff_sigma=diff_sigma, diff_mean=diff_mean,
            mea_threshold=mea_threshold, diff_threshold=diff_threshold,
        )
    metadata = item_metadata(app, item)
    details = []
    for index, post_record in enumerate(post_records):
        post_value = post_values[index] if index < len(post_values) else finite_number(post_record.get("value"))
        pre_value = paired_pre_values[index] if index < len(paired_pre_values) else None
        mea_s = mea_s_values[index] if index < len(mea_s_values) else None
        diff = diff_detail_values[index] if index < len(diff_detail_values) else None
        diff_s = diff_s_values[index] if index < len(diff_s_values) else None
        pre_mea_s = pre_mea_s_values[index] if index < len(pre_mea_s_values) else None
        detail_result = flag_result(
            mea_s, diff_s, n_post, sigma=post_sigma, mean=post_mean,
            diff_n=n_diff, diff_sigma=diff_sigma, diff_mean=diff_mean,
            mea_threshold=mea_threshold, diff_threshold=diff_threshold,
        )
        if include_pre and pre_value is None:
            detail_result = "NO PRE SAMPLE"
        details.append(
            {
                "sample": post_record.get("sample"),
                "pre_value": pre_value,
                "post_value": post_value,
                "pre_mea_s": pre_mea_s,
                "pre_cdf": normal_cdf_value(pre_mea_s),
                "post_cdf": normal_cdf_value(mea_s),
                "mea_s": mea_s,
                "diff": diff,
                "diff_s": diff_s,
                "result": detail_result,
            }
        )
    entry = {
        "result_row": {
            "test_number": CdfCompareApp.test_number_for_item(app, item),
            "item": item,
            "n_pre": len(pre_values),
            "n_post": len(post_values),
            "n_diff": n_diff if pre_values else None,
            "pre_mean": pre_mean if pre_values else None,
            "pre_sigma": pre_sigma if pre_values else None,
            "post_mean": post_mean,
            "post_sigma": post_sigma,
            "mea_s": mea_s_max,
            "mea_threshold": mea_threshold,
            "diff_mean": diff_mean if pre_values else None,
            "diff_sigma": diff_sigma if pre_values else None,
            "diff_s": diff_s_max if pre_values else None,
            "diff_threshold": diff_threshold if pre_values else None,
            "result": result,
        },
        "details": details,
        "metadata": metadata,
        "post_values": post_values,
        "pre_values": pre_values,
        "diff_values": diff_values,
    }
    cache[item] = entry
    return entry


def calculate_results_vectorized(app):
    return [item_analysis(app, item)["result_row"] for item in sorted(app.post_items)]


def calculate_post_only_results(app):
    return calculate_results_vectorized(app)


def post_only_details_for_item(app, item):
    return item_analysis(app, item)["details"]


def items_over_mea_sigma_by_sample(app):
    over = {}
    for item in app.post_records:
        for detail in item_analysis(app, item)["details"]:
            if detail.get("result") != "SELECT":
                continue
            over.setdefault(detail["sample"], []).append(item)
    return over


def items_over_sigma_by_sample_cached(app):
    over = {}
    for item in app.post_records:
        for detail in item_analysis(app, item)["details"]:
            if detail.get("result") != "SELECT":
                continue
            over.setdefault(detail["sample"], []).append(item)
    return over


def details_for_item(app, item):
    return item_analysis(app, item)["details"]


def spec_status(value, lower_limit, upper_limit):
    if value is None:
        return None
    if lower_limit is not None and value < lower_limit:
        return "low"
    if upper_limit is not None and value > upper_limit:
        return "high"
    return "pass"


def spec_margin_ratio(value, lower_limit, upper_limit):
    status = spec_status(value, lower_limit, upper_limit)
    if status == "low" and lower_limit not in (None, 0):
        return abs((lower_limit - value) / lower_limit)
    if status == "high" and upper_limit not in (None, 0):
        return abs((value - upper_limit) / upper_limit)
    return 0.0


def bin_is_pass(value):
    text = str(value or "").strip()
    if not text:
        return False
    try:
        return float(text) == 1
    except ValueError:
        return text == "1"


def record_is_spec_fail(record):
    return spec_status(
        record.get("value"),
        record.get("lower_limit"),
        record.get("upper_limit"),
    ) in ("low", "high")


def row_has_spec_fail(row):
    return any(record_is_spec_fail(record) for record in (row.get("items") or {}).values())


def row_is_pass(row):
    return bin_is_pass(row.get("bin", "")) and not row_has_spec_fail(row)


def state_is_pass(state):
    if "final_pass" in state:
        return bool(state.get("final_pass"))
    return bin_is_pass(state.get("final_bin", "")) and not row_has_spec_fail(state)


def records_have_bin_data(records):
    return any(
        str(record.get("bin", "")).strip()
        for item_records in records.values()
        for record in item_records
    )


def pass_sample_ids_from_records(records):
    if not records:
        return None
    has_bin_data = False
    sample_states = {}
    for item_records in records.values():
        for record in item_records:
            sample = record_sample_id(record)
            if not sample:
                continue
            state = sample_states.setdefault(sample, {"bin": "", "spec_fail": False})
            record_bin = str(record.get("bin", "")).strip()
            if record_bin:
                has_bin_data = True
                if not state["bin"]:
                    state["bin"] = record.get("bin", "")
            if record_is_spec_fail(record):
                state["spec_fail"] = True
    if not has_bin_data:
        return None
    return {
        sample
        for sample, state in sample_states.items()
        if bin_is_pass(state["bin"]) and not state["spec_fail"]
    }


PASS_SAMPLE_IDS_AUTO = object()


def filter_records_by_sample_ids(records, allowed_samples):
    if allowed_samples is None:
        return records
    filtered = {}
    for item, item_records in records.items():
        kept = [record for record in item_records if record_sample_id(record) in allowed_samples]
        if kept:
            filtered[item] = kept
    return filtered


def filter_pass_analysis_records(pre_records, post_records):
    pass_samples = pass_sample_ids_from_records(post_records)
    if pass_samples is None:
        return pre_records, post_records
    pre_pass_samples = pass_sample_ids_from_records(pre_records)
    if pre_pass_samples is not None:
        pass_samples = pass_samples & pre_pass_samples
    return (
        filter_records_by_sample_ids(pre_records, pass_samples),
        filter_records_by_sample_ids(post_records, pass_samples),
    )


def pre_cdf_values_for_item(pre_records, item, pass_samples=PASS_SAMPLE_IDS_AUTO):
    records = pre_records.get(item, [])
    if not records:
        return []
    if pass_samples is PASS_SAMPLE_IDS_AUTO:
        pass_samples = pass_sample_ids_from_records(pre_records)
    return [
        record["value"]
        for record in records
        if record.get("value") is not None
        and (pass_samples is None or record_sample_id(record) in pass_samples)
    ]


def rows_from_records(records, sort_by_sample=False):
    if not records:
        return []
    seed_records = max(records.values(), key=len)
    order = []
    row_map = {}
    for record in seed_records:
        sample = str(record.get("sample", "")).strip()
        if sample and sample not in row_map:
            order.append(sample)
            row_map[sample] = {
                "source_sample": sample,
                "join_key": record_sample_id(record),
                "bin": record.get("bin", ""),
                "items": {},
            }
    for item, item_records in records.items():
        for record in item_records:
            sample = str(record.get("sample", "")).strip()
            if not sample:
                continue
            if sample not in row_map:
                order.append(sample)
                row_map[sample] = {
                    "source_sample": sample,
                    "join_key": record_sample_id(record),
                    "bin": record.get("bin", ""),
                    "items": {},
                }
            if not row_map[sample].get("bin") and record.get("bin"):
                row_map[sample]["bin"] = record.get("bin", "")
            if not row_map[sample].get("join_key") and record_sample_id(record):
                row_map[sample]["join_key"] = record_sample_id(record)
            row_map[sample]["items"][item] = record
    rows = [row_map[sample] for sample in order]
    if sort_by_sample:
        rows.sort(key=lambda row: natural_key(row.get("source_sample", "")))
    return rows


def read_post_stage_rows(path, sort_by_sample=False):
    records = cached_item_records(path)
    return rows_from_records(records, sort_by_sample=sort_by_sample)


def post_history_files_by_readout(base_path, reliability_item, ft_temp, limit=3):
    post_dir = child_dir_containing(base_path, "post")
    groups = {}
    item_key = reliability_item.casefold()
    for path in data_files(post_dir):
        parsed = parse_post_file_name(path)
        if not parsed:
            continue
        if parsed["item"].casefold() != item_key:
            continue
        if ft_temp and not (ft_temp_from_code(parsed["temp_code"]) == ft_temp or file_matches_ft_temp(path, ft_temp)):
            continue
        groups.setdefault(parsed["readout"], []).append(path)
    return sorted(groups.items(), key=lambda entry: readout_sort_key(entry[0]))[:limit]


def primary_post_records_for_readout(files):
    candidates = []
    for path in files or []:
        try:
            records = cached_item_records(path)
        except Exception:
            continue
        row_count = max((len(item_records) for item_records in records.values()), default=0)
        candidates.append((row_count, stage_sort_key(path), records))
    if not candidates:
        return {}
    max_count = max(count for count, _sort_key, _records in candidates)
    for count, _sort_key, records in sorted(candidates, key=lambda entry: entry[1]):
        if count == max_count:
            return records
    return {}


def build_post_readout_history(base_path, reliability_item, ft_temp, limit=3):
    labels = []
    values = {}
    pass_values = {}
    for readout, files in post_history_files_by_readout(base_path, reliability_item, ft_temp, limit):
        column = f"post_t{len(labels) + 1}"
        labels.append(readout)
        graph_records = primary_post_records_for_readout(files)
        pass_samples = pass_sample_ids_from_records(graph_records)
        for item, item_records in graph_records.items():
            for record in item_records:
                sample = record_sample_id(record)
                if not sample:
                    continue
                if pass_samples is not None and sample not in pass_samples:
                    continue
                value = record.get("value")
                status = spec_status(value, record.get("lower_limit"), record.get("upper_limit"))
                if status not in ("low", "high"):
                    pass_values.setdefault(item, {}).setdefault(sample, {})[column] = value
        try:
            sample_states, _merged_files = merged_fail_rows(files)
        except Exception:
            continue
        for sample, state in sample_states.items():
            stage_items = {
                item
                for stage in state.get("stages", [])
                for item in stage.get("items", {})
            }
            for item in stage_items:
                record = latest_record_for_sample_item(state, item)
                if record is None:
                    continue
                values.setdefault(item, {}).setdefault(str(sample), {})[column] = record.get("value")
    return {"labels": labels, "values": values, "pass_values": pass_values}

def apply_post_readout_history_to_payload(payload, post_history):
    if not post_history:
        return payload
    labels = list(post_history.get("labels") or [])[:3]
    payload["post_readout_labels"] = labels
    values = post_history.get("values") or {}
    pass_values = post_history.get("pass_values") or {}
    fail_mode = payload.get("analysis_mode") == "fail"
    for item, item_payload in (payload.get("items") or {}).items():
        all_item_values = values.get(item, {})
        detail_item_values = all_item_values
        allowed_samples = {
            str(detail.get("sample", "")).strip()
            for detail in item_payload.get("details", [])
            if str(detail.get("sample", "")).strip()
        }
        if allowed_samples:
            detail_item_values = {
                str(sample): sample_values
                for sample, sample_values in all_item_values.items()
                if str(sample).strip() in allowed_samples
            }
        graph_item_values = pass_values.get(item, {}) if fail_mode else detail_item_values
        item_payload["post_readout_labels"] = labels

        # Join post_t{index} onto detail rows first so post_readout_series_entry below can reuse them.
        for detail_key in ("details", "normal_details"):
            detail_rows = item_payload.get(detail_key, [])
            if not detail_rows:
                continue
            row_samples = {
                str(detail.get("sample", "")).strip()
                for detail in detail_rows
                if str(detail.get("sample", "")).strip()
            }
            row_item_values = all_item_values
            if row_samples:
                row_item_values = {
                    str(sample): sample_values
                    for sample, sample_values in all_item_values.items()
                    if str(sample).strip() in row_samples
                }
            for detail in detail_rows:
                sample_values = row_item_values.get(str(detail.get("sample", "")), {})
                for index in range(1, 4):
                    detail[f"post_t{index}"] = sample_values.get(f"post_t{index}")

        pass_diff_values = item_payload.get("pass_diff_values") or []
        # §S4(범위 축소판): 이 항목의 정상(pass) pre 스케일 — normal_details 가 있으면(fail
        # 모드) 그쪽이 왜곡되지 않은 pre 모집단이고, 없으면(pass 모드) details 자체가 그것.
        detail_source = item_payload.get("normal_details") or item_payload.get("details") or []
        pre_scale = robust_pre_scale([detail.get("pre_value") for detail in detail_source])
        item_payload["post_readout_values"] = [
            post_readout_series_entry(
                index, labels, graph_item_values, item_payload.get("details", []),
                fail_mode, pass_diff_values, pre_scale,
            )
            for index in range(1, 4)
        ]
    return payload


def round_for_wire(value, sig=6):
    # UI only ever displays these via fmt()'s toPrecision(6) (see fmt() in the embedded script),
    # so shipping full float64 precision over the wire is pure payload bloat with no display
    # benefit. Rounds to `sig` significant digits instead of raw round(value, n) since these
    # per-point diff/mea_s/diff_s values span several orders of magnitude.
    if value is None or value == 0 or not math.isfinite(value):
        return value
    digits = sig - int(math.floor(math.log10(abs(value)))) - 1
    return round(value, digits)


def post_readout_series_entry(index, labels, graph_item_values, detail_rows, fail_mode, pass_diff_values, pre_scale=None):
    # detail_rows already carry sample/pre_value/post_t{index} (joined by the caller), so the
    # per-point diff/mea_s/diff_s are written back onto those same dicts instead of a separate
    # "points" array -- duplicating sample/pre_value/post_value per point blew up payload size
    # by ~44% on the 1000-item/2900-detail-row perf fixture (see v5_perf_bench.py results).
    key = f"post_t{index}"
    label = labels[index - 1] if index - 1 < len(labels) else f"T{index}"
    values = [
        value
        for value in (finite_number(sample_values.get(key)) for sample_values in graph_item_values.values())
        if value is not None
    ]
    post_mean, post_sigma = vector_stats(values)

    # Raw per-row diff ((post-pre)/abs(pre)) is NOT serialized here: it is a pure, population-independent
    # ratio the frontend can rebuild bit-for-bit from pre_value/post_t{n} (both already on the row)
    # via diffFromPre(), which is exactly diff_ratio()'s formula. This is the doc's explicit "pure
    # display/axis-range calculations may remain" carve-out -- unlike mea_s/diff_s below, which
    # depend on a population mean/sigma choice (the actual source of the original bug) and must
    # stay backend-authoritative. Skipping it here saved ~1/3 of this series' payload cost.
    rows_with_value = []
    diffs = []
    for detail in detail_rows:
        post_value = finite_number(detail.get(key))
        if post_value is None:
            continue
        pre_value = finite_number(detail.get("pre_value"))
        diff = diff_ratio(pre_value, post_value, pre_scale=pre_scale)
        rows_with_value.append((detail, post_value, diff))
        diffs.append(diff)

    # Matches the frontend's existing special case: for fail-mode post_t1, the diff
    # population is the item's own pass-baseline diffs, not this series' own points.
    if fail_mode and key == "post_t1":
        diff_population = pass_diff_values
    else:
        diff_population = [diff for diff in diffs if diff is not None]
    diff_mean, diff_sigma = vector_stats(diff_population)

    post_value_list = [post_value for _, post_value, _ in rows_with_value]
    mea_s_list = vector_sigmas(post_value_list, post_mean, post_sigma)
    diff_s_list = vector_sigmas(diffs, diff_mean, diff_sigma)
    # Short keys (m{n}/d{n} instead of post_t{n}_mea_s/post_t{n}_diff_s): these two fields alone are
    # written onto ~2.9M detail rows on the perf fixture, so key-name length is a direct payload
    # size lever (see v5_bytes_quick.py measurements: shortening these closed the last ~2.4pp gap
    # to the +10% budget).
    for (detail, _, diff), mea_s, diff_s in zip(rows_with_value, mea_s_list, diff_s_list):
        detail[f"m{index}"] = to_jsonable(round_for_wire(mea_s))
        detail[f"d{index}"] = to_jsonable(round_for_wire(diff_s)) if diff is not None else None

    return {
        "key": key,
        "label": label,
        "values": [to_jsonable(value) for value in values],
        "stats": {
            "mean": to_jsonable(post_mean),
            "sigma": to_jsonable(post_sigma),
            "diff_mean": to_jsonable(diff_mean),
            "diff_sigma": to_jsonable(diff_sigma),
            "n": len(values),
        },
    }

def has_base_analysis_selection(selection):
    required = ["device", "ver", "purpose", "lot"]
    return all(selection.get(field, "").strip() for field in required)


def has_complete_detail_selection(selection):
    return all(selection.get(field, "").strip() for field in ("item", "readout", "ft_temp"))


def normalize_analysis_selection(selection):
    normalized = dict(selection or {})
    if has_base_analysis_selection(normalized) and not has_complete_detail_selection(normalized):
        for field in ("item", "readout", "ft_temp"):
            normalized[field] = ""
    return normalized


def is_total_analysis_selection(selection):
    if not has_base_analysis_selection(selection):
        return False
    return not has_complete_detail_selection(selection)


def temp_sort_key(value):
    order = {"Room": 0, "Hot": 1, "Cold": 2}
    return order.get(value, 99), value


def reliability_sort_key(value):
    upper = value.upper()
    ordered = {item.upper(): index for index, item in enumerate(RELIABILITY_ITEMS)}
    return ordered.get(upper, 99), upper


def total_analysis_combinations(selection):
    # §W0: 조합 키에서 readout 을 뺀다 - 판정은 "분석 시점 기준 마지막 Read-out" 하나로만
    # 한다. T0~T3 (post_history) 는 추세 비교용일 뿐 판정에는 쓰지 않는다.
    base_path = selected_data_path(selection)
    post_dir = child_dir_containing(base_path, "post")
    groups = {}
    filename_warnings = []
    for path in data_files(post_dir):
        parsed = parse_post_file_name(path)
        if not parsed:
            continue
        if parsed.get("readout_missing"):
            filename_warnings.append({
                "file": os.path.basename(path),
                "reason": "readout_not_found",
                "used": parsed["readout"],
            })
        temps = file_ft_temps(path)
        if not temps:
            temp = ft_temp_from_code(parsed["temp_code"])
            temps = [temp] if temp else []
        for temp in temps:
            key = (parsed["item"], temp)
            groups.setdefault(key, {}).setdefault(parsed["readout"], []).append(path)
    combos = []
    for (item, ft_temp), readout_files in groups.items():
        # post_history_files_by_readout() 와 동일하게 readout_sort_key 로 정렬해
        # "마지막 회차"를 고른다 (재사용: 같은 정렬 기준을 두 곳에서 어긋나지 않게 유지).
        readout_history = sorted(readout_files.keys(), key=readout_sort_key)
        judged_readout = readout_history[-1]
        combos.append({
            "item": item,
            "readout": judged_readout,
            "judged_readout": judged_readout,
            "readout_history": readout_history,
            "ft_temp": ft_temp,
            "post_files": sorted(readout_files[judged_readout], key=stage_sort_key),
        })
    combos.sort(key=lambda row: (reliability_sort_key(row["item"]), temp_sort_key(row["ft_temp"])))
    return base_path, combos, filename_warnings


def pre_file_for_total_combo(base_path, ft_temp, include_pre):
    if not include_pre:
        return None
    pre_dir = child_dir_containing(base_path, "pre")
    pre_files = [path for path in data_files(pre_dir) if file_matches_ft_temp(path, ft_temp)]
    if not pre_files:
        raise ValueError(f"No {ft_temp} Pre data file was found in 00_Pre.")
    return pre_files[-1]


def total_item_key(reliability_item, ft_temp, readout, item):
    raw = json.dumps([reliability_item, ft_temp, readout, item], ensure_ascii=False)
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{item}__{suffix}"


def decorate_combo_payload(payload, reliability_item, ft_temp, readout, readout_history=None):
    history = readout_history or [readout]
    key_by_item = {}
    for row in payload.get("results", []):
        original_item = row.get("item", "")
        key = total_item_key(reliability_item, ft_temp, readout, original_item)
        key_by_item[original_item] = key
        row["item_key"] = key
        row["reliability_item"] = reliability_item
        row["ft_temp"] = ft_temp
        row["readout"] = readout
        row["judged_readout"] = readout
        row["readout_history"] = history
    for row in payload.get("selected_summary", []):
        original_item = row.get("item", "")
        key = key_by_item.get(original_item) or total_item_key(reliability_item, ft_temp, readout, original_item)
        key_by_item[original_item] = key
        row["item_key"] = key
        row["reliability_item"] = reliability_item
        row["ft_temp"] = ft_temp
        row["readout"] = readout
        row["judged_readout"] = readout
        row["readout_history"] = history
    decorated_items = {}
    for original_item, item_payload in (payload.get("items") or {}).items():
        key = key_by_item.get(original_item) or total_item_key(reliability_item, ft_temp, readout, original_item)
        enriched = dict(item_payload)
        enriched["item"] = original_item
        enriched["item_key"] = key
        enriched["reliability_item"] = reliability_item
        enriched["ft_temp"] = ft_temp
        enriched["readout"] = readout
        enriched["judged_readout"] = readout
        enriched["readout_history"] = history
        decorated_items[key] = enriched
    payload["items"] = decorated_items
    for row in payload.get("over_sigma", []):
        row["reliability_item"] = reliability_item
        row["ft_temp"] = ft_temp
        row["readout"] = readout
        row["judged_readout"] = readout
        row["readout_history"] = history
        row["items"] = [key_by_item.get(item, item) for item in row.get("items", [])]
    return payload


def merge_combo_payloads(combo_payloads, mode):
    merged = {
        "results": [],
        "selected_summary": [],
        "over_sigma": [],
        "select_count": 0,
        "items": {},
        "analysis_mode": mode,
        "total_analysis": True,
        "total_reliability_items": [],
        "total_ft_temps": [],
        "message": "",
    }
    reliability_seen = []
    temp_seen = []
    for payload in combo_payloads:
        merged["results"].extend(payload.get("results", []))
        merged["selected_summary"].extend(payload.get("selected_summary", []))
        merged["over_sigma"].extend(payload.get("over_sigma", []))
        merged["select_count"] += payload.get("select_count", 0) or 0
        merged["items"].update(payload.get("items", {}))
        for row in payload.get("results", []):
            rel = row.get("reliability_item", "")
            temp = row.get("ft_temp", "")
            if rel and rel not in reliability_seen:
                reliability_seen.append(rel)
            if temp and temp not in temp_seen:
                temp_seen.append(temp)
    merged["results"].sort(key=lambda row: (
        reliability_sort_key(row.get("reliability_item", "")),
        temp_sort_key(row.get("ft_temp", "")),
        readout_sort_key(row.get("readout", "")),
        natural_key(row.get("test_number", "")),
        row.get("item", ""),
    ))
    merged["selected_summary"].sort(key=lambda row: (
        reliability_sort_key(row.get("reliability_item", "")),
        temp_sort_key(row.get("ft_temp", "")),
        readout_sort_key(row.get("readout", "")),
        natural_key(row.get("test_number", "")),
        row.get("item", ""),
    ))
    merged["total_reliability_items"] = sorted(reliability_seen, key=reliability_sort_key)
    merged["total_ft_temps"] = sorted(temp_seen, key=temp_sort_key)
    merged["message"] = f"Total Analysis completed. Conditions {len(combo_payloads)}, Items {len(merged['selected_summary'])}"
    if mode == "pass":
        summary_counts = {"total_items": 0, "select": 0, "ok": 0, "not_evaluated": 0, "insufficient_n": 0}
        excluded_seen = {}
        item_counts_by_item = {}
        for payload in combo_payloads:
            counts = payload.get("summary_counts") or {}
            for key in ("total_items", "select", "ok", "not_evaluated", "insufficient_n"):
                summary_counts[key] += counts.get(key, 0) or 0
            for excl in payload.get("excluded_items", []):
                excluded_seen[(excl.get("item"), excl.get("unit"))] = excl
            for entry in payload.get("item_counts", []):
                item = entry.get("reliability_item", "")
                agg = item_counts_by_item.setdefault(item, {"reliability_item": item, "select": 0, "total": 0})
                agg["select"] += entry.get("select", 0) or 0
                agg["total"] += entry.get("total", 0) or 0
        summary_counts["excluded"] = len(excluded_seen)
        for item in RELIABILITY_ITEMS:
            item_counts_by_item.setdefault(item, {"reliability_item": item, "select": 0, "total": 0})
        merged["summary_counts"] = summary_counts
        merged["excluded_items"] = sorted(excluded_seen.values(), key=lambda row: natural_key(row.get("item", "")))
        merged["item_counts"] = sorted(
            item_counts_by_item.values(),
            key=lambda row: (reliability_sort_key(row["reliability_item"]), row["reliability_item"]),
        )
    elif mode == "fail":
        sample_counts = {"total": 0, "fail": 0, "pass": 0}
        item_counts_by_item = {}
        for payload in combo_payloads:
            counts = payload.get("sample_counts") or {}
            for key in ("total", "fail", "pass"):
                sample_counts[key] += counts.get(key, 0) or 0
            for entry in payload.get("item_counts", []):
                item = entry.get("reliability_item", "")
                agg = item_counts_by_item.setdefault(item, {"reliability_item": item, "select": 0, "total": 0})
                agg["select"] += entry.get("select", 0) or 0
                agg["total"] += entry.get("total", 0) or 0
        for item in RELIABILITY_ITEMS:
            item_counts_by_item.setdefault(item, {"reliability_item": item, "select": 0, "total": 0})
        merged["sample_counts"] = sample_counts
        merged["item_counts"] = sorted(
            item_counts_by_item.values(),
            key=lambda row: (reliability_sort_key(row["reliability_item"]), row["reliability_item"]),
        )
    return merged


def stage_sort_key(path):
    name = os.path.basename(path).casefold()
    if re.search(r"\b(3rd|third|3차)\b|3rd|third|3차", name):
        stage = 3
    elif re.search(r"\b(2nd|second|2차)\b|2nd|second|2차", name):
        stage = 2
    elif re.search(r"\b(1st|first|1차)\b|1st|first|1차", name):
        stage = 1
    elif "retest" in name or "r/t" in name:
        stage = 1
    else:
        stage = 0
    return (stage, natural_key(name))


def stage_history_from_records(records):
    """records(item -> [record,...], 파일 하나를 raw 파싱한 결과)에서 같은 물리적
    행(row_index)에 속한 항목별 레코드를 하나의 occurrence 로 묶고, join_key
    (record_sample_id — DEVICE_ID 우선) 별로 등장 순서를 보존한 재시험 이력을 만든다.

    §S6: 실제 데이터는 재시험이 별도 파일이 아니라 같은 파일 안에서 Serial # 가
    반복되는 행으로 나타난다 (CLAUDE.md §3-4). bin 은 행 단위 메타데이터라 그 행에
    속한 모든 item 레코드에서 동일한 값이므로, 그 행을 처음 만든 레코드의 bin 을
    그대로 쓰면 된다(항목 간 뒤섞임 없음).
    """
    rows_by_index = {}
    for item, item_records in records.items():
        for record in item_records:
            row_index = record.get("row_index")
            sample = str(record.get("sample", "")).strip()
            if row_index is None or not sample:
                continue
            row = rows_by_index.get(row_index)
            if row is None:
                row = {
                    "source_sample": sample,
                    "join_key": record_sample_id(record),
                    "bin": record.get("bin", ""),
                    "items": {},
                }
                rows_by_index[row_index] = row
            elif not row.get("join_key") and record_sample_id(record):
                row["join_key"] = record_sample_id(record)
            row["items"][item] = record
    history = {}
    for row_index in sorted(rows_by_index):
        row = rows_by_index[row_index]
        key = row.get("join_key") or row.get("source_sample")
        if not key:
            continue
        history.setdefault(key, []).append(row)
    return history


def sample_states_from_history(history_by_key):
    """stage_history_from_records() 의 결과(join_key -> 등장 순서 보존 occurrence 리스트)를
    merged_fail_rows() 가 쓰는 sample_states 형태로 변환한다. 실데이터 파일 없이도
    단위 테스트할 수 있도록 순수 함수로 분리했다 (§S6).

    대표 측정값 = 마지막 occurrence (요구사항 1, 기존 동작 유지).
    Bin 출처 통일: 이전에는 Bin=첫 회차, 측정값=마지막 회차로 출처가 어긋났다
    (CLAUDE.md §3-4). 대표 측정값이 마지막 회차이므로 Bin 도 마지막 회차로 통일한다.
    """
    sample_states = {}
    ordered_keys = sorted(
        history_by_key,
        key=lambda key: natural_key(history_by_key[key][0].get("source_sample", "")),
    )
    for key in ordered_keys:
        occurrences = history_by_key[key]
        first = occurrences[0]
        last = occurrences[-1]
        sample = str(last.get("source_sample", "")).strip() or key
        stages = [
            {
                "name": "FT" if index == 0 else f"Retest {index}",
                "items": occ["items"],
                "bin": occ.get("bin", ""),
                "spec_fail": row_has_spec_fail(occ),
            }
            for index, occ in enumerate(occurrences)
        ]
        sample_states[sample] = {
            "sample": sample,
            "serial": sample,
            "join_key": key,
            "final_bin": last.get("bin", ""),
            "final_spec_fail": row_has_spec_fail(last),
            "final_pass": row_is_pass(last),
            # 1회차 fail -> 마지막 회차 Bin1 로 회복 = Intermittent (NOTES.md P0 확정 요구사항 2).
            "is_intermittent": (not bin_is_pass(first.get("bin", ""))) and bin_is_pass(last.get("bin", "")),
            "stages": stages,
        }
    return sample_states


def merged_fail_rows(post_files):
    if not post_files:
        raise ValueError("No Post data file was found.")
    files = sorted(post_files, key=stage_sort_key)
    primary_records = cached_item_records(files[0])
    history_by_key = stage_history_from_records(primary_records)
    sample_states = sample_states_from_history(history_by_key)
    previous_retest_samples = [
        sample
        for sample in sorted(sample_states, key=natural_key)
        if not bin_is_pass(sample_states[sample].get("final_bin", ""))
    ]
    if len(files) == 1:
        return sample_states, files
    for stage_index, path in enumerate(files[1:], start=1):
        rows = read_post_stage_rows(path, sort_by_sample=False)
        next_retest_samples = []
        for sample, row in zip(previous_retest_samples, rows):
            state = sample_states.get(sample)
            if not state:
                continue
            state["final_bin"] = row.get("bin", "")
            state["final_spec_fail"] = row_has_spec_fail(row)
            state["final_pass"] = row_is_pass(row)
            state["stages"].append({"name": f"Retest {stage_index}", "items": row["items"], "bin": row.get("bin", ""), "spec_fail": row_has_spec_fail(row)})
            if not bin_is_pass(row.get("bin", "")):
                next_retest_samples.append(sample)
        previous_retest_samples = next_retest_samples
        if not previous_retest_samples:
            break
    return sample_states, files


def latest_record_for_sample_item(state, item):
    latest = None
    for stage in state.get("stages", []):
        record = stage.get("items", {}).get(item)
        if record is not None:
            latest = record
    return latest


def item_history_for_sample(state, item):
    history = []
    for index, stage in enumerate(state.get("stages", [])):
        record = stage.get("items", {}).get(item)
        if record is not None:
            history.append((index, record))
    return history


def fail_type_for_detail(
    initial_record, history, value, lower_limit, upper_limit, mea_s, diff_s,
    n, sigma, mean, diff_n=None, diff_sigma=None, diff_mean=None,
    mea_threshold=_UNSET, diff_threshold=_UNSET, unit_recovered=False,
):
    # 분류 우선순위(암묵적이던 순서를 명시): Intermittent -> Unstable -> Excessive ->
    # Slight -> Tail. §S6b.
    #   Intermittent: 유닛 레벨. 1회차 fail, 마지막 회차 Bin pass (unit_recovered ==
    #     state["is_intermittent"], bin_sequence 기준) -- 유닛이 최종적으로 살아났으므로
    #     벤치(FA) 대상에서 제외한다.
    #   Unstable: 항목(item) 레벨. 유닛은 최종 fail 이지만 이 항목의 회차별 spec_status 가
    #     fail -> pass -> fail 로 오간다 -- 스펙 경계에서 불안정하다는 신호라 벤치 대상,
    #     오히려 주목해야 한다.
    # 유닛이 회복했다면(unit_recovered) 그게 더 상위 사실이므로 Intermittent 가 우선이고,
    # 이 항목이 개별적으로 flip-flop 했는지는 더 따지지 않는다(Bin pass 는 그 회차의 모든
    # 항목이 스펙 안이라는 뜻이라 항상 참이 된다).
    if unit_recovered:
        return "Intermittent"
    initial_failed = initial_record is not None and spec_status(
        initial_record.get("value"), initial_record.get("lower_limit"), initial_record.get("upper_limit")
    ) in ("low", "high")
    if initial_failed:
        for stage_index, record in history:
            if stage_index == 0:
                continue
            if spec_status(record.get("value"), record.get("lower_limit"), record.get("upper_limit")) == "pass":
                return "Unstable"
    if spec_margin_ratio(value, lower_limit, upper_limit) >= 0.01:
        return "Excessive"
    # mea/diff 를 독립적으로 flag_result 로 평가 — pass 모집단(n, sigma, mean)의 Grubbs 임계값
    # 기준. §S3. mea_threshold/diff_threshold 를 넘기면(호출부가 루프 밖에서 한 번만 계산해둔
    # 값) grubbs_critical 재계산을 건너뛴다 — §S3 후속(성능).
    mea_status = flag_result(mea_s, None, n, sigma=sigma, mean=mean, mea_threshold=mea_threshold)
    diff_status = (
        flag_result(None, diff_s, n, sigma=sigma, mean=mean, diff_n=diff_n, diff_sigma=diff_sigma, diff_mean=diff_mean,
                    diff_threshold=diff_threshold)
        if diff_n is not None else None
    )
    if mea_status == "SELECT" and diff_status == "SELECT":
        return "Slight"
    return "Tail"


FAIL_TYPE_PRIORITY = {"Intermittent": 0, "Unstable": 1, "Excessive": 2, "Slight": 3, "Tail": 4}


def worst_fail_type(details):
    """항목의 detail 행들 중 가장 심각한 fail_type 을 고른다.

    우선순위는 fail_type_for_detail() 주석에 명시된 순서를 그대로 쓴다:
    Intermittent > Unstable > Excessive > Slight > Tail.
    """
    if not details:
        return ""
    return min(details, key=lambda detail: FAIL_TYPE_PRIORITY.get(detail.get("fail_type"), 99)).get("fail_type", "")


def selected_summary_rows(app):
    rows = []
    for row in app.results:
        if row.get("result") != "SELECT":
            continue
        metadata = item_metadata(app, row["item"])
        entry = item_analysis(app, row["item"])
        details = entry["details"]
        post_values = entry["post_values"]
        samples = [
            detail["sample"]
            for detail in details
            if detail.get("result") == "SELECT"
        ]
        n_post = row.get("n_post")
        n_diff = row.get("n_diff")
        pre_mean = row.get("pre_mean")
        pre_sigma = row.get("pre_sigma")
        post_mean = row.get("post_mean")
        post_sigma = row.get("post_sigma")
        diff_mean = row.get("diff_mean")
        diff_sigma = row.get("diff_sigma")
        shift = (post_mean - pre_mean) if (post_mean is not None and pre_mean is not None) else None
        shift_sigma = (shift / pre_sigma) if (shift is not None and pre_sigma not in (None, 0)) else None
        max_mea_s = row.get("mea_s")
        max_diff_s = row.get("diff_s")
        # 항목별 임계값(threshold_for)이 branch 마다 다를 수 있어, reason 은 mea/diff 를
        # flag_result 로 각각 독립 평가해 얻는다 — NOT EVALUATED/INSUFFICIENT N 인 branch 는
        # SELECT 사유에서 제외된다 (§S3).
        mea_status = flag_result(max_mea_s, None, n_post, sigma=post_sigma, mean=post_mean,
                                  mea_threshold=row.get("mea_threshold"))
        diff_status = (
            flag_result(None, max_diff_s, n_post, sigma=post_sigma, mean=post_mean,
                        diff_n=n_diff, diff_sigma=diff_sigma, diff_mean=diff_mean,
                        diff_threshold=row.get("diff_threshold"))
            if n_diff is not None else None
        )
        mea_s_flag = mea_status == "SELECT"
        diff_s_flag = diff_status == "SELECT"
        if mea_s_flag and diff_s_flag:
            reason = "Measured + Delta"
        elif mea_s_flag:
            reason = "Measured"
        elif diff_s_flag:
            reason = "Delta"
        else:
            reason = ""
        severity_candidates = [
            abs(value) for value in (max_mea_s, max_diff_s)
            if value is not None and math.isfinite(value)
        ]
        severity = max(severity_candidates) if severity_candidates else None
        rows.append(
            {
                "test_number": row.get("test_number", ""),
                "item": row["item"],
                "n": n_post,
                "n_pre": row.get("n_pre"),
                "unit": metadata["unit"],
                "lower_limit": metadata["lower_limit"],
                "upper_limit": metadata["upper_limit"],
                "avg": post_mean,
                "stdev": post_sigma,
                "shift": shift,
                "shift_sigma": shift_sigma,
                "diff_mean": row.get("diff_mean"),
                "min": min(post_values) if post_values else None,
                "max": max(post_values) if post_values else None,
                "max_mea_s": max_mea_s,
                "max_diff_s": max_diff_s,
                "mea_threshold": row.get("mea_threshold"),
                "diff_threshold": row.get("diff_threshold"),
                "severity": severity,
                "reason": reason,
                "qty": len(samples),
                "qty_ratio": (len(samples) / n_post) if n_post else None,
                "sample_numbers": ", ".join(str(sample) for sample in sorted(samples, key=lambda sample: CdfCompareApp.sample_sort_key(app, sample))),
            }
        )
    return sorted(rows, key=lambda row: (natural_key(row["test_number"]), row["item"]))


def compute_summary_counts(results, excluded_items):
    """results 의 확정된 result 값을 세기만 한다 (판정 로직에는 관여하지 않음).

    SELECT/OK/INSUFFICIENT N 이외의 모든 result(NOT EVALUATED, NO PRE ITEM 등
    "판정 불가" 계열)는 not_evaluated 로 묶는다 (verdict_diff.classify_result 의
    판정불가 그룹과 동일한 분류 기준). 이렇게 하면 select+ok+not_evaluated+
    insufficient_n 합이 total_items 와 항상 일치한다.
    """
    select = ok = not_evaluated = insufficient_n = 0
    for row in results:
        result = row.get("result")
        if result == "SELECT":
            select += 1
        elif result == "OK":
            ok += 1
        elif result == "INSUFFICIENT N":
            insufficient_n += 1
        else:
            not_evaluated += 1
    return {
        "total_items": len(results),
        "select": select,
        "ok": ok,
        "not_evaluated": not_evaluated,
        "insufficient_n": insufficient_n,
        "excluded": len(excluded_items),
    }


def analyze_to_json(pre_path, post_path, bin1_only, progress=None, include_pre=True):
    app = make_app(pre_path, post_path, bin1_only, progress, include_pre)
    if progress:
        progress(92, "Building Summary")
    over = items_over_sigma_by_sample_cached(app)
    over_rows = [
        {"sample": sample, "items": sorted(items, key=lambda item: item_sort_key(app, item))}
        for sample, items in sorted(over.items(), key=lambda kv: CdfCompareApp.sample_sort_key(app, kv[0]))
    ]
    app.results.sort(key=lambda row: (natural_key(row.get("test_number")), row.get("item", "")))
    results = [{k: to_jsonable(v) for k, v in row.items()} for row in app.results]
    selected_summary = [{k: to_jsonable(v) for k, v in row.items()} for row in selected_summary_rows(app)]
    excluded_items = list(getattr(app, "excluded_items", []))
    payload = {
        "results": results,
        "selected_summary": selected_summary,
        "over_sigma": over_rows,
        "select_count": CdfCompareApp.count_flags(app),
        "summary_counts": compute_summary_counts(results, excluded_items),
        "excluded_items": excluded_items,
        "flag_limit": FLAG_LIMIT,  # mode="fixed" 일 때만 쓰이는 값. grubbs 모드에서는 항목별 mea_threshold/diff_threshold 를 쓴다.
        "flag_mode": FLAG_MODE,
        "flag_alpha": FLAG_ALPHA,
    }
    if include_pre:
        match_summary = match_summary_for_files(
            cached_item_records(pre_path),
            cached_item_records(post_path, last_sample=False),
        )
        if match_summary:
            payload["match_summary"] = match_summary
            payload["message"] = f"Pre 매칭 {match_summary['matched']}/{match_summary['post_units']}"
    if progress:
        progress(98, "Finalizing")
    return app, payload


def analyze_fail_to_json(pre_path, post_files, progress=None, include_pre=True):
    def update(percent, message):
        if progress:
            progress(percent, message)

    update(28, "Reading Pre")
    pre_records = cached_item_records(pre_path) if include_pre else {}
    pre_rows = rows_from_records(pre_records, sort_by_sample=True) if include_pre else []
    pre_by_sample = {
        (row.get("join_key") or str(row.get("source_sample", "")).strip() or str(index)): row
        for index, row in enumerate(pre_rows, start=1)
    } if include_pre else {}
    pre_pass_samples = pass_sample_ids_from_records(pre_records) if include_pre else None
    update(46, "Merging Retest")
    sample_states, merged_files = merged_fail_rows(post_files)
    pass_sample_states = sample_states
    fail_samples = [
        sample
        for sample, state in sample_states.items()
        if not state_is_pass(state) or state.get("is_intermittent")
    ]
    pass_samples = [
        sample
        for sample, state in pass_sample_states.items()
        if state_is_pass(state)
    ]
    item_names = sorted(
        {
            item
            for sample in fail_samples
            for stage in sample_states[sample].get("stages", [])
            for item in stage.get("items", {})
        },
        key=lambda item: item_sort_key_for_records(sample_states, item),
    )
    update(70, "Classifying Fail Types")
    item_payloads = {}
    summary_rows = []
    results = []
    for item in item_names:
        post_records = []
        pre_values_by_sample = {}
        for sample in fail_samples:
            state = sample_states[sample]
            latest = latest_record_for_sample_item(state, item)
            if latest is None:
                continue
            lower = latest.get("lower_limit")
            upper = latest.get("upper_limit")
            if spec_status(latest.get("value"), lower, upper) not in ("low", "high"):
                # 회복(Intermittent) 유닛은 마지막 회차 값이 정상이라 이 게이트에 걸리지만,
                # 1회차에 이 항목이 실제로 실패했다면 fail_type_for_detail 이 이력을 보고
                # "Intermittent" 로 분류할 수 있도록 통과시킨다. §S6.
                if not state.get("is_intermittent"):
                    continue
                history = item_history_for_sample(state, item)
                initial_item_failed = bool(history) and spec_status(
                    history[0][1].get("value"),
                    history[0][1].get("lower_limit"),
                    history[0][1].get("upper_limit"),
                ) in ("low", "high")
                if not initial_item_failed:
                    continue
            post_records.append((sample, latest))
            join_key = state.get("join_key") or sample
            pre_record = pre_by_sample.get(join_key, {}).get("items", {}).get(item)
            pre_values_by_sample[sample] = pre_record.get("value") if pre_record else None
        if not post_records:
            continue
        post_samples = [sample for sample, _record in post_records]
        post_values = [record["value"] for _, record in post_records]
        post_pre_values = [pre_values_by_sample.get(sample) for sample in post_samples]
        pass_post_values = []
        pass_pre_values = []
        pass_pairs = []
        for sample in pass_samples:
            state = pass_sample_states[sample]
            pass_record = latest_record_for_sample_item(state, item)
            if pass_record is None:
                continue
            pass_lower = pass_record.get("lower_limit")
            pass_upper = pass_record.get("upper_limit")
            if spec_status(pass_record.get("value"), pass_lower, pass_upper) in ("low", "high"):
                continue
            join_key = state.get("join_key") or sample
            pre_record = pre_by_sample.get(join_key, {}).get("items", {}).get(item)
            pre_value = pre_record.get("value") if pre_record else None
            pass_post_values.append(pass_record["value"])
            pass_pre_values.append(pre_value)
            pass_pairs.append((sample, pass_record, pre_value))
        # pass 표본의 pre 값이 이 항목의 정상 스케일을 대표한다 — fail 표본의 pre 는 고장으로
        # 왜곡됐을 수 있어 스케일 기준으로 쓰지 않는다. §S4(범위 축소판).
        pre_scale = robust_pre_scale(pass_pre_values)
        pass_detail_diffs, pass_diff_values = paired_diffs_for_details(
            pass_pre_values, pass_post_values, pre_scale=pre_scale
        )
        post_mean = mean_of(pass_post_values)
        post_sigma = std_of(pass_post_values, ddof=1)  # 판정용 sigma. §S2.
        diff_mean = mean_of(pass_diff_values)
        diff_sigma = std_of(pass_diff_values, ddof=1)  # 판정용 sigma. §S2.
        pass_mea_s_values = vector_sigmas(pass_post_values, post_mean, post_sigma)
        pass_diff_s_values = vector_sigmas(pass_detail_diffs, diff_mean, diff_sigma)
        mea_s_values = vector_sigmas(post_values, post_mean, post_sigma)
        detail_diffs, _detail_diff_values = paired_diffs_for_details(post_pre_values, post_values, pre_scale=pre_scale)
        diff_s_values = vector_sigmas(detail_diffs, diff_mean, diff_sigma)
        metadata = metadata_from_records([record for _, record in post_records])
        details = []
        normal_details = []
        for index, (sample, record, pre_value) in enumerate(pass_pairs):
            value = pass_post_values[index] if index < len(pass_post_values) else record.get("value")
            diff = pass_detail_diffs[index] if index < len(pass_detail_diffs) else None
            mea_s = pass_mea_s_values[index] if index < len(pass_mea_s_values) else None
            diff_s = pass_diff_s_values[index] if index < len(pass_diff_s_values) else None
            normal_details.append(
                {
                    "sample": sample,
                    "pre_value": pre_value,
                    "post_value": value,
                    "unit": record.get("unit", ""),
                    "lower_limit": record.get("lower_limit"),
                    "upper_limit": record.get("upper_limit"),
                    "mea_s": mea_s,
                    "diff": diff,
                    "diff_s": diff_s,
                    "fail_type": "",
                    "result": "OK",
                }
            )
        # n_pass/diff 쌍 개수는 이 항목 안에서 고정이라 임계값을 루프 밖에서 한 번만 계산해
        # 재사용한다(§S3 후속 성능) — fail_type_for_detail 을 표본마다 부르며 매번 다시
        # grubbs_critical 을 계산하지 않도록.
        n_pass = len(pass_post_values)
        mea_threshold = threshold_for(n_pass) if n_pass else None
        diff_threshold = threshold_for(len(pass_diff_values)) if pass_diff_values else None
        for index, (sample, record) in enumerate(post_records):
            value = post_values[index]
            pre_value = post_pre_values[index]
            diff = detail_diffs[index] if index < len(detail_diffs) else None
            mea_s = mea_s_values[index] if index < len(mea_s_values) else None
            diff_s = diff_s_values[index] if index < len(diff_s_values) else None
            state = sample_states[sample]
            history = item_history_for_sample(state, item)
            initial_record = history[0][1] if history else None
            lower = record.get("lower_limit")
            upper = record.get("upper_limit")
            details.append(
                {
                    "sample": sample,
                    "pre_value": pre_value,
                    "post_value": value,
                    "unit": record.get("unit", ""),
                    "lower_limit": lower,
                    "upper_limit": upper,
                    "mea_s": mea_s,
                    "diff": diff,
                    "diff_s": diff_s,
                    "fail_type": fail_type_for_detail(
                        initial_record, history, value, lower, upper, mea_s, diff_s,
                        n_pass, post_sigma, post_mean,
                        diff_n=len(pass_diff_values), diff_sigma=diff_sigma, diff_mean=diff_mean,
                        mea_threshold=mea_threshold, diff_threshold=diff_threshold,
                        unit_recovered=bool(state.get("is_intermittent")),
                    ),
                    "result": "SELECT",
                }
            )
        sample_numbers = sorted((detail["sample"] for detail in details), key=natural_key)
        test_number = cell_text_from_records([record for _, record in post_records], "test_number")
        summary_rows.append(
            {
                "test_number": test_number,
                "item": item,
                "n": n_pass if n_pass else None,
                "unit": metadata["unit"],
                "lower_limit": metadata["lower_limit"],
                "upper_limit": metadata["upper_limit"],
                "avg": post_mean if n_pass else None,
                "stdev": post_sigma if n_pass else None,
                "shift": None,
                "shift_sigma": None,
                "diff_mean": diff_mean if pass_diff_values else None,
                "mea_threshold": mea_threshold,
                "diff_threshold": diff_threshold,
                "min": min(pass_post_values) if n_pass else None,
                "max": max(pass_post_values) if n_pass else None,
                "qty": len(details),
                "qty_ratio": (len(details) / n_pass) if n_pass else None,
                "sample_numbers": ", ".join(sample_numbers),
                "fail_type": worst_fail_type(details),
            }
        )
        results.append({"test_number": test_number, "item": item, "result": "SELECT"})
        pre_values = pre_cdf_values_for_item(pre_records, item, pre_pass_samples)
        item_payloads[item] = {
            "pre_values": [to_jsonable(value) for value in pre_values],
            "post_values": [to_jsonable(value) for value in post_values],
            "pass_post_values": [to_jsonable(value) for value in pass_post_values],
            "pass_diff_values": [to_jsonable(value) for value in pass_diff_values],
            "mea_threshold": to_jsonable(mea_threshold),
            "diff_threshold": to_jsonable(diff_threshold),
            "lower_limit": to_jsonable(metadata["lower_limit"]),
            "upper_limit": to_jsonable(metadata["upper_limit"]),
            "details": [{key: to_jsonable(value) for key, value in row.items()} for row in details],
            "normal_details": [{key: to_jsonable(value) for key, value in row.items()} for row in normal_details],
        }
    summary_rows.sort(key=lambda row: (natural_key(row["test_number"]), row["item"]))
    results.sort(key=lambda row: (natural_key(row["test_number"]), row["item"]))
    over = {}
    for item, item_payload in item_payloads.items():
        for detail in item_payload["details"]:
            if not detail.get("fail_type"):
                continue
            over.setdefault(detail["sample"], []).append(item)
    over_rows = [
        {"sample": sample, "items": sorted(items, key=lambda item: item_sort_key_for_records(sample_states, item))}
        for sample, items in over.items()
    ]
    over_rows.sort(key=lambda row: (-len(row["items"]), natural_key(row["sample"])))
    message = f"Fail Items {len(summary_rows)}, Fail Samples {len(fail_samples)}, Files {len(merged_files)}"
    match_summary = (
        match_summary_for_files(pre_records, cached_item_records(merged_files[0])) if include_pre else None
    )
    payload = {
        "results": results,
        "selected_summary": [{key: to_jsonable(value) for key, value in row.items()} for row in summary_rows],
        "over_sigma": over_rows,
        "select_count": sum(row["qty"] for row in summary_rows),
        "items": item_payloads,
        "message": message,
        "flag_limit": FLAG_LIMIT,  # mode="fixed" 일 때만 쓰이는 값. grubbs 모드에서는 항목별 mea_threshold/diff_threshold 를 쓴다.
        "flag_mode": FLAG_MODE,
        "flag_alpha": FLAG_ALPHA,
        # 유닛(Sample) 기준 요약 스트립용. fail_samples/pass_samples 는 이미 위에서
        # 판정 완료된 목록이라 새로 계산하지 않고 개수만 센다.
        "sample_counts": {
            "total": len(sample_states),
            "fail": len(fail_samples),
            "pass": len(pass_samples),
        },
    }
    if match_summary:
        payload["match_summary"] = match_summary
        payload["message"] = f"{message}, Pre 매칭 {match_summary['matched']}/{match_summary['post_units']}"
    update(98, "Finalizing")
    app = object.__new__(CdfCompareApp)
    app.pre_records = pre_records
    app.post_records = {}
    app.pre_items = {}
    app.post_items = {}
    app.results = results
    return app, payload


def metadata_from_records(records):
    metadata = {"unit": "", "lower_limit": None, "upper_limit": None}
    for record in records:
        if not metadata["unit"]:
            metadata["unit"] = record.get("unit", "")
        if metadata["lower_limit"] is None:
            metadata["lower_limit"] = record.get("lower_limit")
        if metadata["upper_limit"] is None:
            metadata["upper_limit"] = record.get("upper_limit")
    return metadata


def cell_text_from_records(records, key):
    for record in records:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def item_sort_key_for_records(sample_states, item):
    for state in sample_states.values():
        for stage in state.get("stages", []):
            record = stage.get("items", {}).get(item)
            if record:
                return (natural_key(record.get("test_number", "")), item)
    return ([], item)


def item_to_json(app, item):
    if item not in app.post_records:
        raise ValueError("Unknown Test Item.")
    analysis_entry = item_analysis(app, item)
    metadata = analysis_entry["metadata"]
    lower = metadata["lower_limit"]
    upper = metadata["upper_limit"]
    details = analysis_entry["details"]
    return {
        "pre_values": pre_cdf_values_for_item(app.pre_records, item, app.__dict__.get("pre_pass_samples", PASS_SAMPLE_IDS_AUTO)),
        "post_values": analysis_entry["post_values"],
        "lower_limit": to_jsonable(lower),
        "upper_limit": to_jsonable(upper),
        "details": [{k: to_jsonable(v) for k, v in row.items()} for row in details],
        "mea_threshold": to_jsonable(analysis_entry["result_row"].get("mea_threshold")),
        "diff_threshold": to_jsonable(analysis_entry["result_row"].get("diff_threshold")),
    }


def pre_only_item_to_json(pre_records, item, pass_samples=PASS_SAMPLE_IDS_AUTO):
    pre_values = pre_cdf_values_for_item(pre_records, item, pass_samples)
    if not pre_values:
        return None
    metadata = metadata_from_records(pre_records.get(item, []))
    return {
        "pre_values": [to_jsonable(value) for value in pre_values],
        "post_values": [],
        "lower_limit": to_jsonable(metadata["lower_limit"]),
        "upper_limit": to_jsonable(metadata["upper_limit"]),
        "details": [],
    }


def add_pre_only_items_to_payload(payload, pre_records, target_items):
    if not pre_records or not target_items:
        return payload
    items = payload.setdefault("items", {})
    pre_pass_samples = pass_sample_ids_from_records(pre_records)
    for item in sorted(set(target_items), key=natural_key):
        if item in items:
            continue
        item_payload = pre_only_item_to_json(pre_records, item, pre_pass_samples)
        if item_payload:
            items[item] = item_payload
    return payload


def app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


CACHE_SCHEMA = 20  # 19->20: cache_key_for 에 pre_stamp/post_stamps 추가 (§2)
CACHE_DIR = os.path.join(app_base_dir(), ".analysis_cache")

PARSE_CACHE_VERSION = 2  # 1->2: record 에 row_index 추가 (§S6, 파일 내 재시험 이력)
PARSE_CACHE_DIR = os.path.join(CACHE_DIR, "parse")
PARSE_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
PARSE_CACHE_LOCK = threading.Lock()


def parse_cache_key(stamp):
    abspath, mtime_ns, size = stamp
    raw = f"{abspath}|{mtime_ns}|{size}|{PARSE_CACHE_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_cache_file_path(stamp):
    return os.path.join(PARSE_CACHE_DIR, parse_cache_key(stamp) + ".npz")


def save_parse_cache(path, stamp, records):
    """records(item -> [record,...])를 디스크에 저장한다. 캐시는 최적화일 뿐이므로
    실패해도 조용히 무시하고 정상 파싱 결과는 그대로 돌려준다(호출부는 이미 records 를 들고 있음)."""
    if np is None:
        return
    try:
        items = list(records.keys())
        value_parts = []
        item_meta = []
        for item in items:
            item_records = records[item]
            value_parts.append(np.array([r["value"] for r in item_records], dtype=np.float64))
            item_meta.append({
                "count": len(item_records),
                "samples": [r.get("sample") for r in item_records],
                "device_ids": [r.get("device_id", "") for r in item_records],
                "bins": [r.get("bin") for r in item_records],
                "sites": [r.get("site") for r in item_records],
                "row_indexes": [r.get("row_index") for r in item_records],
                "test_number": item_records[0].get("test_number") if item_records else None,
                "unit": item_records[0].get("unit") if item_records else None,
                "lower_limit": item_records[0].get("lower_limit") if item_records else None,
                "upper_limit": item_records[0].get("upper_limit") if item_records else None,
            })
        value_blob = np.concatenate(value_parts) if value_parts else np.array([], dtype=np.float64)
        meta_bytes = pickle.dumps({"items": items, "item_meta": item_meta}, protocol=pickle.HIGHEST_PROTOCOL)
        meta_blob = np.frombuffer(meta_bytes, dtype=np.uint8)

        os.makedirs(PARSE_CACHE_DIR, exist_ok=True)
        final_path = parse_cache_file_path(stamp)
        tmp_path = final_path + f".{os.getpid()}.{threading.get_ident()}.tmp"
    except Exception:
        return
    try:
        with open(tmp_path, "wb") as fh:
            np.savez(fh, value_blob=value_blob, meta_blob=meta_blob)
        os.replace(tmp_path, final_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return
    enforce_parse_cache_budget()


def load_parse_cache(path, stamp):
    if np is None:
        return None
    final_path = parse_cache_file_path(stamp)
    if not os.path.isfile(final_path):
        return None
    try:
        with np.load(final_path, allow_pickle=False) as data:
            value_blob = data["value_blob"]
            meta_bytes = data["meta_blob"].tobytes()
        meta = pickle.loads(meta_bytes)
        items = meta["items"]
        item_meta = meta["item_meta"]
        records = {}
        offset = 0
        for item, m in zip(items, item_meta):
            count = m["count"]
            values = value_blob[offset:offset + count]
            offset += count
            item_records = []
            for i in range(count):
                record = {
                    "sample": m["samples"][i],
                    "value": float(values[i]),
                    "device_id": m["device_ids"][i],
                }
                if m["test_number"] is not None:
                    record["test_number"] = m["test_number"]
                if m["unit"] is not None:
                    record["unit"] = m["unit"]
                if m["lower_limit"] is not None:
                    record["lower_limit"] = m["lower_limit"]
                if m["upper_limit"] is not None:
                    record["upper_limit"] = m["upper_limit"]
                if m["bins"][i] is not None:
                    record["bin"] = m["bins"][i]
                if m["sites"][i] is not None:
                    record["site"] = m["sites"][i]
                if "row_indexes" in m and m["row_indexes"][i] is not None:
                    record["row_index"] = m["row_indexes"][i]
                item_records.append(record)
            records[item] = item_records
        return records
    except Exception:
        return None


def enforce_parse_cache_budget(max_bytes=PARSE_CACHE_MAX_BYTES):
    with PARSE_CACHE_LOCK:
        try:
            entries = []
            total = 0
            for name in os.listdir(PARSE_CACHE_DIR):
                full = os.path.join(PARSE_CACHE_DIR, name)
                if not os.path.isfile(full):
                    continue
                stat = os.stat(full)
                entries.append((stat.st_mtime, stat.st_size, full))
                total += stat.st_size
            if total <= max_bytes:
                return
            entries.sort(key=lambda entry: entry[0])
            for _mtime, size, full in entries:
                if total <= max_bytes:
                    break
                try:
                    os.remove(full)
                    total -= size
                except OSError:
                    pass
        except Exception:
            pass


def empty_analysis_payload(mode="pass", message=""):
    return {
        "results": [],
        "selected_summary": [],
        "over_sigma": [],
        "select_count": 0,
        "analysis_mode": mode,
        "message": message,
        "analysis_date": "",
        "items": {},
    }


def cache_key_for(selection, pre_path, post_path, mode, post_paths=None):
    """post_paths 를 넘기면 개별 실제 파일들의 (mtime, size) 를 키에 포함시켜, 파일 내용이
    바뀌면(파일명은 그대로여도) 캐시가 자동으로 무효화되게 한다. pass 모드도 post_files[-1]
    하나만이 아니라 전체 세트를 넘겨야 한다(호출부 책임)."""
    stamp_paths = list(post_paths) if post_paths else ([post_path] if post_path else [])
    fields = {
        "schema": CACHE_SCHEMA,
        "data_root": os.path.abspath(DATA_ROOT),
        "mode": mode,
        "pre_path": os.path.abspath(pre_path) if pre_path else "",
        "post_path": os.path.abspath(post_path) if post_path else "",
        "pre_stamp": file_stamp(pre_path) if pre_path else None,
        "post_stamps": [file_stamp(p) for p in stamp_paths],
        "device": selection.get("device", "").strip(),
        "ver": selection.get("ver", "").strip(),
        "purpose": selection.get("purpose", "").strip(),
        "lot": selection.get("lot", "").strip(),
        "item": selection.get("item", "").strip(),
        "readout": selection.get("readout", "").strip(),
        "ft_temp": selection.get("ft_temp", "").strip(),
        "include_pre": "1" if selection_includes_pre(selection) else "0",
    }
    blob = json.dumps(fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def selection_includes_pre(selection):
    return str(selection.get("include_pre", "1")).strip() not in ("0", "false", "False", "no", "No")


def cache_file_path(cache_key):
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def split_cache_dir(cache_key):
    return os.path.join(CACHE_DIR, cache_key)


def split_cache_manifest_path(cache_key):
    return os.path.join(split_cache_dir(cache_key), "manifest.json")


def split_cache_items_dir(cache_key):
    return os.path.join(split_cache_dir(cache_key), "items")


def payload_item_key(row):
    return str(row.get("item_key") or row.get("item") or "")


def cache_item_filename(item_key):
    digest = hashlib.sha256(str(item_key).encode("utf-8")).hexdigest()
    return f"{digest}.json"


def numeric_cache_values(values):
    nums = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            nums.append(number)
    return nums


def cache_stats(values):
    nums = numeric_cache_values(values)
    if not nums:
        return {"avg": None, "stdev": None, "min": None, "max": None}
    avg = sum(nums) / len(nums)
    return {
        "avg": avg,
        "stdev": math.sqrt(sum((value - avg) ** 2 for value in nums) / len(nums)),
        "min": min(nums),
        "max": max(nums),
    }


def cache_summary_values(item_payload):
    readout_series = item_payload.get("post_readout_values") or []
    values = []
    for series in readout_series:
        values.extend(series.get("values") or [])
    if values:
        return values
    return item_payload.get("post_values") or item_payload.get("pass_post_values") or []


def enrich_payload_summary_stats(payload):
    items = payload.get("items") or {}
    if not items:
        return payload
    for row in payload.get("selected_summary", []):
        item_payload = items.get(payload_item_key(row))
        if not item_payload:
            continue
        stats = cache_stats(cache_summary_values(item_payload))
        for key, value in stats.items():
            row[key] = to_jsonable(value)
        row.setdefault("unit", item_payload.get("unit", ""))
        row.setdefault("lower_limit", item_payload.get("lower_limit"))
        row.setdefault("upper_limit", item_payload.get("upper_limit"))
    return payload


def slim_payload_for_cache(cache_key, payload, item_index):
    slim = dict(payload)
    slim["items"] = {}
    slim["item_index"] = dict(item_index)
    slim["split_cache"] = True
    slim["cache_key"] = cache_key
    return slim


def write_json_file(path, payload):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_cached_analysis(cache_key):
    manifest_path = split_cache_manifest_path(cache_key)
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("schema") != CACHE_SCHEMA:
            return None
        payload = cached.get("payload") or {}
        payload["items"] = {}
        payload["cache_key"] = cache_key
        payload["split_cache"] = True
        return payload
    path = cache_file_path(cache_key)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        cached = json.load(fh)
    if cached.get("schema") != CACHE_SCHEMA:
        return None
    payload = cached.get("payload")
    if not payload:
        return None
    save_cached_analysis(None, cache_key, payload)
    return load_cached_analysis(cache_key)


def load_cached_item(cache_key, item_key):
    if not cache_key or not item_key:
        return None
    manifest_path = split_cache_manifest_path(cache_key)
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("schema") != CACHE_SCHEMA:
            return None
        payload = cached.get("payload") or {}
        filename = (payload.get("item_index") or {}).get(item_key)
        if not filename:
            return None
        item_path = os.path.join(split_cache_items_dir(cache_key), filename)
        if not os.path.isfile(item_path):
            return None
        with open(item_path, "r", encoding="utf-8") as fh:
            item_cached = json.load(fh)
        if item_cached.get("schema") != CACHE_SCHEMA:
            return None
        return item_cached.get("payload")
    path = cache_file_path(cache_key)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        cached = json.load(fh)
    if cached.get("schema") != CACHE_SCHEMA:
        return None
    return (cached.get("payload") or {}).get("items", {}).get(item_key)


def save_cached_analysis(app, cache_key, payload):
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload = enrich_payload_summary_stats(payload)
    items_dir = split_cache_items_dir(cache_key)
    os.makedirs(items_dir, exist_ok=True)
    existing_items = payload.get("items") or {}
    item_index = {}
    seen_keys = set()
    for row in payload.get("results", []):
        item_key = payload_item_key(row)
        if not item_key or item_key in seen_keys:
            continue
        seen_keys.add(item_key)
        # Build the full item set on disk (not just the SELECT-ed ones already in
        # memory) so /item lazy-loading keeps working for every item. One item is
        # computed and written at a time -- never accumulated into a big dict --
        # since that accumulation is exactly the memory blowup this change removes.
        item_payload = existing_items.get(item_key)
        if item_payload is None and app is not None:
            item_payload = item_to_json(app, row.get("item"))
        if item_payload is None:
            continue
        filename = cache_item_filename(item_key)
        item_index[item_key] = filename
        item_path = os.path.join(items_dir, filename)
        write_json_file(item_path, {"schema": CACHE_SCHEMA, "item_key": item_key, "payload": item_payload})
    slim = slim_payload_for_cache(cache_key, payload, item_index)
    write_json_file(split_cache_manifest_path(cache_key), {"schema": CACHE_SCHEMA, "format": "split-v1", "payload": slim})
    old_path = cache_file_path(cache_key)
    if os.path.isfile(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass


def delete_cached_analysis(cache_key):
    deleted = 0
    path = cache_file_path(cache_key)
    if os.path.isfile(path):
        os.remove(path)
        deleted += 1
    cache_dir = split_cache_dir(cache_key)
    if os.path.isdir(cache_dir):
        for root, dirs, files in os.walk(cache_dir, topdown=False):
            for filename in files:
                try:
                    os.remove(os.path.join(root, filename))
                except OSError:
                    pass
            for dirname in dirs:
                try:
                    os.rmdir(os.path.join(root, dirname))
                except OSError:
                    pass
        try:
            os.rmdir(cache_dir)
            deleted += 1
        except OSError:
            pass
    return deleted


def set_current_analysis_status(mode, status, message):
    CURRENT_ANALYSIS_STATUS[mode] = {
        "status": status,
        "message": message,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def prepare_current_analysis_results(run_id="", message="Analysis is running..."):
    global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS, CURRENT_ANALYSIS_RUN_ID
    with APP_LOCK:
        CURRENT_APP = None
        CURRENT_ITEMS = {}
        CURRENT_PAYLOADS = {}
        CURRENT_CACHE_KEYS = {}
        CURRENT_ANALYSIS_RUN_ID = run_id
        CURRENT_ANALYSIS_STATUS.clear()
        for mode in ("pass", "fail"):
            set_current_analysis_status(mode, "running", message)


def clear_current_analysis_results(message="Analysis Results are not available."):
    global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS, CURRENT_ANALYSIS_RUN_ID
    with APP_LOCK:
        CURRENT_APP = None
        CURRENT_ITEMS = {}
        CURRENT_PAYLOADS = {}
        CURRENT_CACHE_KEYS = {}
        CURRENT_ANALYSIS_RUN_ID = ""
        CURRENT_ANALYSIS_STATUS.clear()
        for mode in ("pass", "fail"):
            set_current_analysis_status(mode, "empty", message)


def mark_current_analysis_results(status, message, run_id=""):
    global CURRENT_ANALYSIS_RUN_ID
    with APP_LOCK:
        if run_id and not CURRENT_ANALYSIS_RUN_ID:
            CURRENT_ANALYSIS_RUN_ID = run_id
        if run_id and CURRENT_ANALYSIS_RUN_ID and run_id != CURRENT_ANALYSIS_RUN_ID:
            return
        for mode in ("pass", "fail"):
            if mode not in CURRENT_PAYLOADS and CURRENT_ANALYSIS_STATUS.get(mode, {}).get("status") != "done":
                set_current_analysis_status(mode, status, message)


def current_analysis_error_response(mode, requested_run_id=""):
    if requested_run_id and requested_run_id != CURRENT_ANALYSIS_RUN_ID:
        return {
            "error": "Analysis is starting...",
            "status": "running",
            "updated_at": "",
        }, 202
    status = CURRENT_ANALYSIS_STATUS.get(mode) or {
        "status": "empty",
        "message": "Analysis Results are not available.",
    }
    http_status = 202 if status.get("status") == "running" else 500 if status.get("status") == "error" else 409 if status.get("status") == "stopped" else 404
    return {
        "error": status.get("message") or "Analysis Results are not available.",
        "status": status.get("status", "empty"),
        "updated_at": status.get("updated_at", ""),
    }, http_status


def payload_with_items(app, payload, mode, cache_status):
    items = dict(payload.get("items") or {})
    if not items:
        for row in payload.get("selected_summary", []):
            item = row.get("item")
            if item and item not in items:
                items[item] = item_to_json(app, item)
        for over_row in payload.get("over_sigma", []):
            for item in over_row.get("items", []):
                if item and item not in items:
                    items[item] = item_to_json(app, item)
    enriched = dict(payload)
    enriched["items"] = items
    enriched["analysis_mode"] = mode
    enriched["cache_status"] = cache_status
    enriched["items_are_partial"] = True
    enriched.setdefault("analysis_date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return enriched


LOOKUP_FIELDS = ["device", "ver", "purpose", "lot", "item", "readout", "ft_temp"]
RELIABILITY_ITEMS = ["HTOL", "HAST", "uHAST", "TC", "PTC", "HTSL", "HBM", "CDM", "LU"]


def safe_child(parent, name):
    if not name:
        return parent
    candidate = os.path.abspath(os.path.join(parent, name))
    root = os.path.abspath(DATA_ROOT)
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("Invalid data path.")
    if not os.path.exists(candidate):
        raise ValueError(f"Data path not found: {name}")
    return candidate


def first_existing_child(parent, names):
    for name in names:
        candidate = os.path.join(parent, name)
        if os.path.isdir(candidate):
            return safe_child(parent, name)
    raise ValueError(f"Data folder not found: {' or '.join(names)}")


def child_dir_containing(parent, keyword):
    if not os.path.isdir(parent):
        raise ValueError(f"Data path not found: {parent}")
    target = keyword.casefold()
    matches = [
        entry.name
        for entry in os.scandir(parent)
        if entry.is_dir() and target in entry.name.casefold()
    ]
    if not matches:
        raise ValueError(f"Data folder containing '{keyword}' was not found.")
    matches.sort(key=lambda name: (0 if name.casefold() == target else 1, name.casefold()))
    return safe_child(parent, matches[0])


def child_dirs(path):
    if not os.path.isdir(path):
        return []
    return sorted(
        entry.name
        for entry in os.scandir(path)
        if entry.is_dir()
    )


def browse_data_root():
    global DATA_ROOT
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            title="Select Reliability Test Data folder",
            initialdir=DATA_ROOT if os.path.isdir(DATA_ROOT) else os.getcwd(),
        )
    finally:
        root.destroy()
    if not selected:
        return {"path": DATA_ROOT, "changed": False}
    selected = os.path.abspath(selected)
    if not os.path.isdir(selected):
        raise ValueError("Selected data path was not found.")
    DATA_ROOT = selected
    return {"path": DATA_ROOT, "changed": True, "options": child_dirs(DATA_ROOT)}


def parse_data_folder_name(name):
    parts = name.split("_", 3)
    if len(parts) != 4:
        return None
    sequence = parts[0].strip().rstrip(".")
    if not sequence.isdigit():
        return None
    _, ver, lot, purpose = parts
    return {
        "name": name,
        "ver": ver.strip(),
        "lot": lot.strip(),
        "purpose": purpose.strip(),
    }


def device_data_folders(device_path, ver=None, purpose=None, lot=None):
    matches = []
    for name in child_dirs(device_path):
        parsed = parse_data_folder_name(name)
        if not parsed:
            continue
        if ver and parsed["ver"] != ver:
            continue
        if purpose and parsed["purpose"] != purpose:
            continue
        if lot and parsed["lot"] != lot:
            continue
        matches.append(parsed)
    return matches


def selected_data_path(selection):
    device = selection.get("device", "").strip()
    ver = selection.get("ver", "").strip()
    purpose = selection.get("purpose", "").strip()
    lot = selection.get("lot", "").strip()
    if not all([device, ver, purpose, lot]):
        raise ValueError("Device, Ver., Purpose, and Lot No. are required.")
    device_path = safe_child(DATA_ROOT, device)
    matches = device_data_folders(device_path, ver, purpose, lot)
    if not matches:
        raise ValueError("Matching reliability data folder was not found.")
    return safe_child(device_path, matches[0]["name"])


def data_files(path):
    if not os.path.isdir(path):
        return []
    return sorted(
        entry.path
        for entry in os.scandir(path)
        if entry.is_file() and os.path.splitext(entry.name)[1].lower() in (".csv", ".xlsx")
    )


def _token_looks_like_readout(token):
    # 리드아웃 토큰(1000hrs, 168h, 500)은 항상 숫자를 포함한다. 반대로
    # RELIABILITY_ITEMS(HTOL, HAST, uHAST, TC, PTC, HTSL, HBM, CDM, LU)에는
    # 숫자를 포함하는 이름이 하나도 없어 이 기준과 절대 충돌하지 않는다.
    return bool(re.search(r"\d", token))


def parse_post_file_name(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = [part.strip() for part in stem.split("_") if part.strip()]
    if not parts:
        return None
    temp_code = parts[1] if len(parts) > 1 else ""
    last = parts[-1]
    if len(parts) >= 2 and _token_looks_like_readout(last):
        item = parts[-2]
        readout = last
        readout_missing = False
    else:
        # 리드아웃 토큰이 없다 (예: "..._HTOL.CSV"). 파일을 버리지 않고
        # 기본 리드아웃 "Post" 하나로 취급한다 - 판정은 이 파일 하나로 한다.
        item = last
        readout = "Post"
        readout_missing = True
    if not item:
        return None
    return {
        "stem": stem,
        "temp_code": temp_code,
        "item": item,
        "readout": readout,
        "readout_missing": readout_missing,
    }


def post_file_contains_item(path, item):
    if not item:
        return False
    parsed = parse_post_file_name(path)
    return bool(parsed and parsed["item"].casefold() == item.casefold())


def post_file_matches(path, item, readout):
    parsed = parse_post_file_name(path)
    if not parsed:
        return False
    return post_file_contains_item(path, item) and parsed["readout"].casefold() == readout.casefold()


def ft_temp_from_code(value):
    text = value.casefold()
    code = re.sub(r"[^a-z0-9]", "", text)
    if "room" in text or code.startswith(("rr", "er")):
        return "Room"
    if "hot" in text or code.startswith(("rh", "eh")):
        return "Hot"
    if "cold" in text or code.startswith(("rc", "ec")):
        return "Cold"
    return None


def file_matches_ft_temp(path, ft_temp):
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = [part.strip() for part in re.split(r"[_\-\s]+", stem) if part.strip()]
    candidates = parts or [stem]
    return any(ft_temp_from_code(part) == ft_temp for part in candidates)


def file_ft_temps(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = [part.strip() for part in re.split(r"[_\-\s]+", stem) if part.strip()]
    temps = []
    for part in parts or [stem]:
        temp = ft_temp_from_code(part)
        if temp and temp not in temps:
            temps.append(temp)
    return temps


def post_file_matches_ft_temp(path, item, readout, ft_temp):
    parsed = parse_post_file_name(path)
    if not parsed:
        return False
    if not post_file_contains_item(path, item):
        return False
    if parsed["readout"].casefold() != readout.casefold():
        return False
    return ft_temp_from_code(parsed["temp_code"]) == ft_temp or file_matches_ft_temp(path, ft_temp)


def readout_sort_key(value):
    parts = re.split(r"(\d+)", value)
    return [int(part) if part.isdigit() else part.casefold() for part in parts]


def post_file_readouts(path, item):
    if not item:
        return []
    readouts = set()
    for file_path in data_files(path):
        parsed = parse_post_file_name(file_path)
        if parsed and post_file_contains_item(file_path, item):
            readouts.add(parsed["readout"])
    return sorted(readouts, key=readout_sort_key)


def post_file_ft_temps(path, item, readout):
    if not item or not readout:
        return []
    available_temps = set()
    for file_path in data_files(path):
        parsed = parse_post_file_name(file_path)
        if not parsed:
            continue
        if parsed["item"].casefold() == item.casefold() and parsed["readout"].casefold() == readout.casefold():
            for temp in file_ft_temps(file_path):
                available_temps.add(temp)
    order = {"Room": 0, "Hot": 1, "Cold": 2}
    return sorted(available_temps, key=lambda temp: order.get(temp, 99))


AUTO_LATEST_READOUT = "__latest__"


def resolve_auto_readout(post_dir, item, readout):
    # "최신 자동" 선택(sentinel) 이면 그 시점에 존재하는 회차 중 readout_sort_key
    # 기준 마지막 것으로 해석한다. 특정 회차를 고른 경우는 그대로 통과시켜
    # "500hrs 시점으로 다시 판정" 같은 기존 동작을 유지한다.
    if readout != AUTO_LATEST_READOUT:
        return readout
    options = post_file_readouts(post_dir, item)
    return options[-1] if options else ""


def resolve_selection_files(selection):
    pre_path, post_files, base = resolve_selection_file_set(selection)
    return pre_path, post_files[-1], base


def resolve_selection_file_set(selection):
    base = selected_data_path(selection)
    item = selection.get("item", "").strip()
    ft_temp = selection.get("ft_temp", "").strip()
    if not item or not ft_temp:
        raise ValueError("Reliability Items, Read-out, and FT Temp. are required.")
    post_dir = child_dir_containing(base, "post")
    readout = resolve_auto_readout(post_dir, item, selection.get("readout", "").strip())
    selection["readout"] = readout
    if not readout:
        raise ValueError("Reliability Items, Read-out, and FT Temp. are required.")
    include_pre = selection_includes_pre(selection)
    pre_files = []
    if include_pre:
        pre_dir = child_dir_containing(base, "pre")
        pre_files = [path for path in data_files(pre_dir) if file_matches_ft_temp(path, ft_temp)]
    post_files = [path for path in data_files(post_dir) if post_file_matches_ft_temp(path, item, readout, ft_temp)]
    if include_pre and not pre_files:
        raise ValueError(f"No {ft_temp} Pre data file was found in 00_Pre.")
    if not post_files:
        raise ValueError("선택 된 시험의 Data가 없습니다.")
    return pre_files[-1] if pre_files else None, sorted(post_files, key=stage_sort_key), base


def lookup_options(query):
    field = query.get("field", ["ver"])[0]
    if field not in LOOKUP_FIELDS:
        raise ValueError("Invalid lookup field.")
    if field == "device":
        return {"path": DATA_ROOT, "options": child_dirs(DATA_ROOT)}
    device = query.get("device", [""])[0].strip()
    if not device:
        return {"path": DATA_ROOT, "options": []}
    device_path = safe_child(DATA_ROOT, device)
    if field == "ver":
        options = sorted({entry["ver"] for entry in device_data_folders(device_path)})
        return {"path": device_path, "options": options}
    ver = query.get("ver", [""])[0].strip()
    if not ver:
        return {"path": device_path, "options": []}
    if field == "lot":
        options = sorted({entry["lot"] for entry in device_data_folders(device_path, ver=ver)})
        return {"path": device_path, "options": options}
    lot = query.get("lot", [""])[0].strip()
    if not lot:
        return {"path": device_path, "options": []}
    if field == "purpose":
        options = sorted({entry["purpose"] for entry in device_data_folders(device_path, ver=ver, lot=lot)})
        return {"path": device_path, "options": options}
    purpose = query.get("purpose", [""])[0].strip()
    matches = device_data_folders(device_path, ver, purpose, lot)
    data_path = safe_child(device_path, matches[0]["name"]) if matches else device_path
    if field == "item":
        return {"path": data_path, "options": RELIABILITY_ITEMS}
    item = query.get("item", [""])[0].strip()
    if field == "readout":
        try:
            post_path = child_dir_containing(data_path, "post")
        except ValueError:
            return {"path": data_path, "options": []}
        return {"path": data_path, "options": post_file_readouts(post_path, item)}
    readout = query.get("readout", [""])[0].strip()
    if field == "ft_temp":
        try:
            post_path = child_dir_containing(data_path, "post")
        except ValueError:
            return {"path": data_path, "options": []}
        readout = resolve_auto_readout(post_path, item, readout)
        return {"path": data_path, "options": post_file_ft_temps(post_path, item, readout)}
    return {"path": data_path, "options": []}


def update_job(job_id, **updates):
    with JOB_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)


def get_job(job_id):
    with JOB_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def decorate_selected_summary_condition(payload, reliability_item, ft_temp, readout):
    """단일 조건 분석의 selected_summary 행에 Total 분석과 동일한 식별 필드를 싣는다.

    decorate_combo_payload() 와 달리 item_key 재발급이나 items dict 재구성은 하지
    않는다 (§U1에서 없앤 화면 열의 값만 복구하면 되고, items 키 구조를 바꾸면
    프런트엔드 단일 조건 표시 로직에 영향을 줄 수 있어 범위를 넘어선다).
    """
    if not reliability_item and not ft_temp and not readout:
        return payload
    for row in payload.get("selected_summary", []):
        row["reliability_item"] = reliability_item
        row["ft_temp"] = ft_temp
        row["judged_readout"] = readout
    return payload


def run_analyze_job(job_id, pre_path, post_path, bin1_only, cleanup_files=True, cache_key=None, mode="pass", include_pre=True, reliability_item="", run_id="", post_history=None, ft_temp="", readout=""):
    def progress(percent, message):
        update_job(job_id, progress=percent, message=message)

    try:
        progress(22, "Starting")
        app, payload = analyze_to_json(pre_path, post_path, bin1_only, progress, include_pre)
        payload = payload_with_items(app, payload, mode, "saved" if cache_key else "none")
        apply_post_readout_history_to_payload(payload, post_history)
        decorate_selected_summary_condition(payload, reliability_item, ft_temp, readout)
        if mode == "pass":
            summary_counts = payload.get("summary_counts") or {}
            payload["item_counts"] = [
                {
                    "reliability_item": reliability_item,
                    "select": summary_counts.get("select", 0),
                    "total": summary_counts.get("total_items", 0),
                }
            ]
        payload["reliability_item"] = reliability_item
        payload["analysis_run_id"] = run_id
        if cache_key:
            save_cached_analysis(app, cache_key, payload)
        global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                CURRENT_APP = app
                CURRENT_ITEMS = payload.get("items", {})
                CURRENT_PAYLOADS[mode] = payload
                if cache_key:
                    CURRENT_CACHE_KEYS[mode] = cache_key
                set_current_analysis_status(mode, "done", "Done")
        update_job(job_id, status="done", progress=100, message="Done")
    except Exception as exc:
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                set_current_analysis_status(mode, "error", str(exc))
        update_job(job_id, status="error", progress=100, message=str(exc))
    finally:
        for path in (pre_path, post_path):
            if cleanup_files and path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


def run_fail_analyze_job(job_id, pre_path, post_files, cache_key=None, include_pre=True, reliability_item="", run_id="", post_history=None, ft_temp="", readout=""):
    def progress(percent, message):
        update_job(job_id, progress=percent, message=message)

    try:
        progress(22, "Starting")
        app, payload = analyze_fail_to_json(pre_path, post_files, progress, include_pre)
        payload = payload_with_items(app, payload, "fail", "saved" if cache_key else "none")
        apply_post_readout_history_to_payload(payload, post_history)
        decorate_selected_summary_condition(payload, reliability_item, ft_temp, readout)
        # Fail 모드 시험항목 탭 배지: 유닛(Sample) 기준 Fail 수 / 전체 수
        fail_sample_counts = payload.get("sample_counts") or {}
        payload["item_counts"] = [
            {
                "reliability_item": reliability_item,
                "select": fail_sample_counts.get("fail", 0),
                "total": fail_sample_counts.get("total", 0),
            }
        ]
        payload["reliability_item"] = reliability_item
        payload["analysis_run_id"] = run_id
        if cache_key:
            save_cached_analysis(app, cache_key, payload)
        global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                CURRENT_APP = None
                CURRENT_ITEMS = payload.get("items", {})
                CURRENT_PAYLOADS["fail"] = payload
                if cache_key:
                    CURRENT_CACHE_KEYS["fail"] = cache_key
                set_current_analysis_status("fail", "done", "Done")
        update_job(job_id, status="done", progress=100, message="Done")
    except Exception as exc:
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                set_current_analysis_status("fail", "error", str(exc))
        update_job(job_id, status="error", progress=100, message=str(exc))


def total_target_items_by_reliability(combos):
    target_items = {}
    for combo in combos:
        items = target_items.setdefault(combo["item"], set())
        for path in combo.get("post_files", []):
            try:
                records = cached_item_records(path, last_sample=True)
            except Exception:
                continue
            items.update(records.keys())
    return target_items


def analyze_total_combo(base_path, combo, mode="pass", cache_key=None, include_pre=True, target_items=None):
    pre_path = pre_file_for_total_combo(base_path, combo["ft_temp"], include_pre)
    post_history = build_post_readout_history(base_path, combo["item"], combo["ft_temp"])
    if mode == "fail":
        app, payload = analyze_fail_to_json(pre_path, combo["post_files"], None, include_pre)
        payload = payload_with_items(app, payload, "fail", "saved" if cache_key else "none")
        fail_sample_counts = payload.get("sample_counts") or {}
        payload["item_counts"] = [
            {
                "reliability_item": combo["item"],
                "select": fail_sample_counts.get("fail", 0),
                "total": fail_sample_counts.get("total", 0),
            }
        ]
    else:
        app, payload = analyze_to_json(pre_path, combo["post_files"][-1], True, None, include_pre)
        payload = payload_with_items(app, payload, "pass", "saved" if cache_key else "none")
        summary_counts = payload.get("summary_counts") or {}
        payload["item_counts"] = [
            {
                "reliability_item": combo["item"],
                "select": summary_counts.get("select", 0),
                "total": summary_counts.get("total_items", 0),
            }
        ]
    if include_pre:
        add_pre_only_items_to_payload(payload, app.pre_records, target_items or [])
    apply_post_readout_history_to_payload(payload, post_history)
    decorate_combo_payload(payload, combo["item"], combo["ft_temp"], combo["readout"], combo.get("readout_history"))
    return payload


def run_total_analyze_job(job_id, selection, mode="pass", cache_key=None, include_pre=True, run_id=""):
    def progress(percent, message):
        update_job(job_id, progress=percent, message=message)

    try:
        progress(18, "Scanning Total Analysis data")
        base_path, combos, filename_warnings = total_analysis_combinations(selection)
        if not combos:
            raise ValueError("Total Analysis data was not found.")
        target_items_by_reliability = total_target_items_by_reliability(combos) if include_pre else {}
        combo_payloads = []
        total = len(combos)
        worker_count = max(1, min(4, total, os.cpu_count() or 1))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    analyze_total_combo,
                    base_path,
                    combo,
                    mode,
                    cache_key,
                    include_pre,
                    target_items_by_reliability.get(combo["item"], set()),
                ): combo
                for combo in combos
            }
            for index, future in enumerate(as_completed(futures), start=1):
                combo = futures[future]
                progress(18 + (index / max(total, 1)) * 70, f"{combo['item']} {combo['ft_temp']} {combo['readout']}")
                try:
                    combo_payloads.append(future.result())
                except Exception:
                    continue
        if not combo_payloads:
            raise ValueError("No Total Analysis condition could be analyzed.")
        payload = merge_combo_payloads(combo_payloads, mode)
        payload["reliability_item"] = "Total"
        payload["analysis_run_id"] = run_id
        payload["cache_status"] = "saved" if cache_key else "none"
        payload["filename_warnings"] = filename_warnings
        if cache_key:
            save_cached_analysis(None, cache_key, payload)
        global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                CURRENT_APP = None
                CURRENT_ITEMS = payload.get("items", {})
                CURRENT_PAYLOADS[mode] = payload
                if cache_key:
                    CURRENT_CACHE_KEYS[mode] = cache_key
                set_current_analysis_status(mode, "done", "Done")
        update_job(job_id, status="done", progress=100, message="Done")
    except Exception as exc:
        with APP_LOCK:
            if not run_id or run_id == CURRENT_ANALYSIS_RUN_ID:
                set_current_analysis_status(mode, "error", str(exc))
        update_job(job_id, status="error", progress=100, message=str(exc))


EXPORT_RAW_COLUMNS = [
    "Mode", "Reliability", "FT Temp.", "Read-out", "Test No.", "Item",
    "Sample No.", "Detail Type", "Sample Result", "Spec.-Out Type", "Unit", "LL", "UL",
    "Pre", "Post", "T1", "T2", "T3", "Mea_S", "Delta", "Diff_S", "Need Bench", "Analysis Date",
]


def xml_escape(value):
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def xlsx_col_name(index):
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xlsx_cell(row_index, col_index, value):
    if value is None:
        return ""
    ref = f"{xlsx_col_name(col_index)}{row_index}"
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return f'<c r="{ref}"><v>{format(value, ".15g")}</v></c>'
    text = xml_escape(value)
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def xlsx_sheet_xml(rows):
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(xlsx_cell(row_index, col_index, value) for col_index, value in enumerate(row, start=1))
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        '</worksheet>'
    )


def safe_sheet_name(name, used):
    clean = re.sub(r"[\\/\?\*\[\]:]", " ", str(name or "Sheet")).strip() or "Sheet"
    clean = clean[:31]
    candidate = clean
    index = 2
    while candidate in used:
        suffix = f" {index}"
        candidate = clean[: 31 - len(suffix)] + suffix
        index += 1
    used.add(candidate)
    return candidate


def create_xlsx_workbook(sheets):
    buffer = io.BytesIO()
    used_names = set()
    normalized = [(safe_sheet_name(name, used_names), rows) for name, rows in sheets]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        overrides = [
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        ]
        for index, _sheet in enumerate(normalized, start=1):
            overrides.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'{"".join(overrides)}'
            '</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        )
        sheet_entries = []
        rel_entries = []
        for index, (name, rows) in enumerate(normalized, start=1):
            sheet_entries.append(f'<sheet name="{xml_escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rel_entries.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            zf.writestr(f"xl/worksheets/sheet{index}.xml", xlsx_sheet_xml(rows))
        zf.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets>{"".join(sheet_entries)}</sheets>'
            '</workbook>',
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(rel_entries)}'
            '</Relationships>',
        )
    return buffer.getvalue()


def payload_item_lookup(payload):
    lookup = {}
    for row in list(payload.get("results") or []) + list(payload.get("selected_summary") or []):
        key = payload_item_key(row)
        if key and key not in lookup:
            lookup[key] = row
        item = str(row.get("item", ""))
        if item and item not in lookup:
            lookup[item] = row
    return lookup


def payload_items_for_export(mode, payload, cache_key=""):
    items = dict(payload.get("items") or {})
    item_index = payload.get("item_index") or {}
    for item_key in item_index:
        if item_key in items:
            continue
        item_payload = load_cached_item(cache_key, item_key)
        if item_payload:
            items[item_key] = item_payload
    return items


def detail_type_for_export(mode, detail_key, detail):
    result = str(detail.get("result", "")).strip()
    if mode == "fail":
        return "Normal Data" if detail_key == "normal_details" else "Fail Data"
    return "Abnormal Pass" if result == "SELECT" else "Normal Data"


def export_detail_rows(mode, payload, items):
    rows = []
    context_lookup = payload_item_lookup(payload)
    mode_label = "Fail" if mode == "fail" else "Pass"
    for item_key in sorted(items, key=natural_key):
        item_payload = items.get(item_key) or {}
        context = context_lookup.get(item_key) or context_lookup.get(str(item_payload.get("item", ""))) or {}
        item_name = item_payload.get("item") or context.get("item") or item_key
        test_number = context.get("test_number", "")
        reliability = item_payload.get("reliability_item") or context.get("reliability_item", "")
        ft_temp = item_payload.get("ft_temp") or context.get("ft_temp", "")
        readout = item_payload.get("readout") or context.get("readout", "")
        analysis_date = payload.get("analysis_date", "")
        detail_groups = [("details", item_payload.get("details") or [])]
        detail_groups.append(("normal_details", item_payload.get("normal_details") or []))
        for detail_key, details in detail_groups:
            for detail in details:
                rows.append([
                    mode_label,
                    reliability,
                    ft_temp,
                    readout,
                    test_number,
                    item_name,
                    detail.get("sample", ""),
                    detail_type_for_export(mode, detail_key, detail),
                    detail.get("result", ""),
                    detail.get("fail_type", ""),
                    detail.get("unit") or context.get("unit", ""),
                    detail.get("lower_limit", item_payload.get("lower_limit", context.get("lower_limit"))),
                    detail.get("upper_limit", item_payload.get("upper_limit", context.get("upper_limit"))),
                    detail.get("pre_value"),
                    detail.get("post_value"),
                    detail.get("post_t1"),
                    detail.get("post_t2"),
                    detail.get("post_t3"),
                    detail.get("mea_s"),
                    detail.get("diff"),
                    detail.get("diff_s"),
                    detail.get("need_bench", ""),
                    analysis_date,
                ])
    return rows


def export_summary_rows(mode, payload):
    rows = []
    mode_label = "Fail" if mode == "fail" else "Pass"
    keys = [
        "test_number", "item", "n", "unit", "lower_limit", "upper_limit", "avg", "stdev",
        "shift", "shift_sigma", "diff_mean", "min", "max", "qty", "qty_ratio", "sample_numbers", "result",
    ]
    rows.append(["Mode", *keys])
    for row in payload.get("selected_summary") or []:
        rows.append([mode_label, *[row.get(key, "") for key in keys]])
    return rows


def current_export_payloads(run_id=""):
    with APP_LOCK:
        payloads = {
            mode: dict(payload)
            for mode, payload in CURRENT_PAYLOADS.items()
            if payload and (not run_id or payload.get("analysis_run_id") == run_id)
        }
        cache_keys = dict(CURRENT_CACHE_KEYS)
    return payloads, cache_keys


def build_raw_export_workbook(run_id=""):
    payloads, cache_keys = current_export_payloads(run_id)
    if not payloads:
        raise ValueError("Analysis result is not available.")
    raw_rows = [EXPORT_RAW_COLUMNS]
    summary_rows = [["Mode", "Test No.", "Item", "N", "Unit", "LL", "UL", "Avg.", "Stdev.", "Shift", "Shift/σ", "Δ Mean", "Min.", "Max.", "Q'ty", "%", "Sample No.", "Result"]]
    info_rows = [["Field", "Value"], ["Exported At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")], ["Run ID", run_id]]
    for mode in ("fail", "pass"):
        payload = payloads.get(mode)
        if not payload:
            continue
        cache_key = payload.get("cache_key") or cache_keys.get(mode, "")
        items = payload_items_for_export(mode, payload, cache_key)
        raw_rows.extend(export_detail_rows(mode, payload, items))
        for row in export_summary_rows(mode, payload)[1:]:
            summary_rows.append(row)
        info_rows.append([f"{mode.title()} Analysis Date", payload.get("analysis_date", "")])
        info_rows.append([f"{mode.title()} Items", len(items)])
        info_rows.append([f"{mode.title()} Cache Status", payload.get("cache_status", "")])
    if len(raw_rows) == 1:
        raise ValueError("Exportable raw data was not found.")
    workbook = create_xlsx_workbook([
        ("Raw Data", raw_rows),
        ("Summary", summary_rows),
        ("Export Info", info_rows),
    ])
    filename = f"Raw_Data_Export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return filename, workbook

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html", "/results-window"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
            return
        if parsed.path == "/export-raw-data":
            try:
                query = parse_qs(parsed.query)
                filename, workbook = build_raw_export_workbook(query.get("run", [""])[0])
                self.send_download(
                    workbook,
                    filename,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/latest-analysis":
            query = parse_qs(parsed.query)
            mode = query.get("mode", ["pass"])[0]
            mode = "fail" if mode == "fail" else "pass"
            requested_run_id = query.get("run", [""])[0]
            with APP_LOCK:
                payload = CURRENT_PAYLOADS.get(mode)
                if requested_run_id and payload and payload.get("analysis_run_id") != requested_run_id:
                    payload = None
                error_payload, error_status = current_analysis_error_response(mode, requested_run_id)
            if payload:
                self.send_json(payload)
            else:
                self.send_json(error_payload, status=error_status)
            return
        if parsed.path == "/item":
            try:
                query = parse_qs(parsed.query)
                item = query.get("name", [""])[0]
                mode = query.get("mode", [""])[0]
                mode = "fail" if mode == "fail" else "pass" if mode == "pass" else ""
                with APP_LOCK:
                    app = CURRENT_APP
                    payload = CURRENT_PAYLOADS.get(mode) if mode else None
                    cached_item = (payload.get("items", {}) if payload else {}).get(item) or CURRENT_ITEMS.get(item)
                    cache_key = (payload or {}).get("cache_key") or (CURRENT_CACHE_KEYS.get(mode) if mode else "")
                if cached_item:
                    self.send_json(cached_item)
                    return
                split_item = load_cached_item(cache_key, item)
                if split_item:
                    with APP_LOCK:
                        target_payload = CURRENT_PAYLOADS.get(mode) if mode else None
                        if target_payload is not None:
                            target_payload.setdefault("items", {})[item] = split_item
                        CURRENT_ITEMS[item] = split_item
                    self.send_json(split_item)
                    return
                if app is None:
                    raise ValueError("Analyze first.")
                self.send_json(item_to_json(app, item))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/progress":
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            job = get_job(job_id)
            if not job:
                self.send_json({"error": "Unknown analyze job."}, status=404)
                return
            self.send_json({
                "job_id": job_id,
                "status": job.get("status"),
                "progress": job.get("progress"),
                "message": job.get("message"),
            })
            return
        if parsed.path == "/lookup":
            try:
                self.send_json(lookup_options(parse_qs(parsed.query)))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        else:
            self.send_error(404)
            return

    def do_POST(self):
        global CURRENT_APP, CURRENT_ITEMS, CURRENT_PAYLOADS, CURRENT_CACHE_KEYS
        if self.path == "/browse-data-root":
            try:
                self.send_json(browse_data_root())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if self.path == "/shutdown":
            self.send_json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path == "/prepare-analysis-results":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                prepare_current_analysis_results(payload.get("run_id", ""))
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if self.path == "/analysis-results-status":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                status = payload.get("status", "error")
                if status not in ("error", "stopped"):
                    status = "error"
                mark_current_analysis_results(status, payload.get("message", "Analyze failed."), payload.get("run_id", ""))
                self.send_json({"ok": True})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if self.path == "/initialize-analysis":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                selection = normalize_analysis_selection(json.loads(self.rfile.read(length).decode("utf-8")))
                deleted = 0
                if is_total_analysis_selection(selection):
                    deleted += delete_cached_analysis(cache_key_for(selection, "", "TOTAL_ANALYSIS", "pass"))
                    deleted += delete_cached_analysis(cache_key_for(selection, "", "TOTAL_ANALYSIS", "fail"))
                else:
                    include_pre = selection_includes_pre(selection)
                    pre_path, post_files, _base_path = resolve_selection_file_set(selection)
                    post_path = post_files[-1]
                    fail_post_key = "\n".join(post_files)
                    deleted += delete_cached_analysis(cache_key_for(selection, pre_path, post_path, "pass", post_paths=post_files))
                    deleted += delete_cached_analysis(cache_key_for(selection, pre_path, fail_post_key, "fail", post_paths=post_files))
                clear_current_analysis_results()
                self.send_json({"ok": True, "deleted": deleted})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if self.path == "/analyze-selection":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                selection = normalize_analysis_selection(json.loads(self.rfile.read(length).decode("utf-8")))
                mode = selection.get("analysis_mode", "pass")
                reliability_item = selection.get("item", "").strip()
                run_id = selection.get("analysis_run_id", "")
                include_pre = selection_includes_pre(selection)
                if is_total_analysis_selection(selection):
                    base_path = selected_data_path(selection)
                    cache_key = cache_key_for(selection, "", "TOTAL_ANALYSIS", mode)
                    job_id = uuid.uuid4().hex
                    cached_payload = load_cached_analysis(cache_key)
                    if cached_payload:
                        cached_payload = dict(cached_payload)
                        cached_payload["cache_status"] = "loaded"
                        cached_payload["analysis_run_id"] = run_id
                        with APP_LOCK:
                            CURRENT_APP = None
                            CURRENT_ITEMS = cached_payload.get("items", {})
                            CURRENT_PAYLOADS[mode] = cached_payload
                            CURRENT_CACHE_KEYS[mode] = cache_key
                            set_current_analysis_status(mode, "done", "Loaded saved result")
                        update_job(job_id, status="done", progress=100, message="Loaded saved result")
                        self.send_json({"job_id": job_id, "base_path": base_path, "pre_path": "", "post_path": "TOTAL_ANALYSIS"})
                        return
                    with APP_LOCK:
                        CURRENT_PAYLOADS.pop(mode, None)
                        CURRENT_CACHE_KEYS.pop(mode, None)
                        set_current_analysis_status(mode, "running", "Total Analysis is running...")
                    update_job(
                        job_id,
                        status="running",
                        progress=15,
                        message="Total Analysis selected",
                        base_path=base_path,
                        pre_path="",
                        post_path="TOTAL_ANALYSIS",
                    )
                    threading.Thread(
                        target=run_total_analyze_job,
                        args=(job_id, selection, mode, cache_key, include_pre, run_id),
                        daemon=True,
                    ).start()
                    self.send_json({"job_id": job_id, "base_path": base_path, "pre_path": "", "post_path": "TOTAL_ANALYSIS"})
                    return
                pre_path, post_files, base_path = resolve_selection_file_set(selection)
                post_path = post_files[-1]
                try:
                    post_history = build_post_readout_history(base_path, reliability_item, selection.get("ft_temp", "").strip())
                except Exception:
                    post_history = {"labels": [], "values": {}}
                cache_post_key = "\n".join(post_files) if mode == "fail" else post_path
                cache_key = cache_key_for(selection, pre_path, cache_post_key, mode, post_paths=post_files)
                job_id = uuid.uuid4().hex
                cached_payload = load_cached_analysis(cache_key)
                if cached_payload:
                    cached_payload = dict(cached_payload)
                    cached_payload["cache_status"] = "loaded"
                    cached_payload["reliability_item"] = cached_payload.get("reliability_item") or reliability_item
                    cached_payload["analysis_run_id"] = run_id
                    with APP_LOCK:
                        CURRENT_APP = None
                        CURRENT_ITEMS = cached_payload.get("items", {})
                        CURRENT_PAYLOADS[mode] = cached_payload
                        CURRENT_CACHE_KEYS[mode] = cache_key
                        set_current_analysis_status(mode, "done", "Loaded saved result")
                    update_job(job_id, status="done", progress=100, message="Loaded saved result")
                    self.send_json({"job_id": job_id, "base_path": base_path, "pre_path": pre_path, "post_path": post_path})
                    return
                with APP_LOCK:
                    CURRENT_PAYLOADS.pop(mode, None)
                    CURRENT_CACHE_KEYS.pop(mode, None)
                    set_current_analysis_status(mode, "running", "Analysis is running...")
                if mode == "fail":
                    update_job(
                        job_id,
                        status="running",
                        progress=20,
                        message="Files selected",
                        base_path=base_path,
                        pre_path=pre_path,
                        post_path=post_path,
                    )
                    threading.Thread(
                        target=run_fail_analyze_job,
                        args=(job_id, pre_path, post_files, cache_key, include_pre, reliability_item, run_id, post_history, selection.get("ft_temp", "").strip(), selection.get("readout", "")),
                        daemon=True,
                    ).start()
                    self.send_json({"job_id": job_id, "base_path": base_path, "pre_path": pre_path, "post_path": post_path})
                    return
                update_job(
                    job_id,
                    status="running",
                    progress=20,
                    message="Files selected",
                    base_path=base_path,
                    pre_path=pre_path,
                    post_path=post_path,
                )
                threading.Thread(
                    target=run_analyze_job,
                    args=(job_id, pre_path, post_path, True, False, cache_key, "pass", include_pre, reliability_item, run_id, post_history, selection.get("ft_temp", "").strip(), selection.get("readout", "")),
                    daemon=True,
                ).start()
                self.send_json({"job_id": job_id, "base_path": base_path, "pre_path": pre_path, "post_path": post_path})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=400)
            return
        if self.path != "/analyze":
            self.send_error(404)
            return
        pre_path = None
        post_path = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            parts = parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
            if "pre_file" not in parts or "post_file" not in parts:
                raise ValueError("Pre/Post files are required.")
            pre_path = write_upload(parts["pre_file"])
            post_path = write_upload(parts["post_file"])
            bin1_only = parts.get("bin1_only") and parts["bin1_only"].content.decode("utf-8", "ignore") == "1"
            job_id = uuid.uuid4().hex
            update_job(job_id, status="running", progress=20, message="Uploaded")
            threading.Thread(
                target=run_analyze_job,
                args=(job_id, pre_path, post_path, bool(bin1_only)),
                daemon=True,
            ).start()
            pre_path = None
            post_path = None
            self.send_json({"job_id": job_id})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)
        finally:
            for path in (pre_path, post_path):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_download(self, body, filename, content_type):
        safe_filename = re.sub(r'[^A-Za-z0-9_.-]+', "_", filename or "download.xlsx")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt_text, *args):
        return


def open_browser():
    time.sleep(0.6)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def create_server():
    global PORT
    last_error = None
    for port in range(PORT, PORT_END + 1):
        try:
            server = ThreadingHTTPServer((HOST, port), Handler)
            PORT = port
            return server
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"No available port from {PORT} to {PORT_END}.") from last_error


def main():
    server = create_server()
    threading.Thread(target=open_browser, daemon=True).start()
    print(f"{APP_TITLE} HTML UI: http://{HOST}:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
