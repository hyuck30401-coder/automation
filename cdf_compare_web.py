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
APP_REVISION = "Rev.0.036"
# R-026/R-029 실용적 유의성 게이트 — **표시 전용이며 판정에 관여하지 않는다.**
# 판정(Grubbs, §11)은 "통계적으로 튀는가"만 본다. 그래서 능력이 과한 항목(Cp 가 큰 항목)
# 에서는 스펙폭의 1% 도 안 움직인 샘플이 z-score 만 커져 SELECT 가 된다. 이 상수는 그런
# 건들을 화면에서만 접기 위한 임계다 — result 필드도 골든 스냅샷도 바뀌지 않는다(§5-1).
#
# 판정을 만든 축의 "스펙 대비 크기" 가 tau 미만이면 접는다 (R-029):
#     Mea 축(값이 집단에서 튐) → |값 - 표본평균| / 스펙폭
#     Delta 축(변화가 튐)      → |Post - Pre|   / 스펙폭
# Mea 축을 풀어쓰면 |값-평균|/스펙폭 = z·sigma/(UL-LL) = z/(6·Cp) 이므로,
# "크기 > tau" 는 곧 "z > tau·6·Cp" 다 — 즉 이 한 값이 Cp 에 정비례하는 가중 임계를
# 그대로 구현한다. 능력이 과한 항목일수록 자동으로 더 큰 z 를 요구한다.
# R-026 은 Delta 축에만 1% 를 적용한 특수 케이스였고 R-029 가 두 축으로 일반화했다.
try:
    SPEC_GATE_TAU = float(os.environ.get("CDFTOOL_SPEC_GATE_TAU", "0.05"))
except (TypeError, ValueError):
    SPEC_GATE_TAU = 0.05
CURRENT_APP = None
# 모드별 항목 캐시: {"pass": {항목명: payload}, "fail": {...}}. 같은 항목이라도 pass 는
# 양품 표본, fail 은 불량 표본을 보므로 모집단이 다르다 — 이름만으로 캐시를 공유하면
# 다른 모드의 결과가 그대로 나간다 (R-017).
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
      --head: #17427f;
      --head-dark: #0f2f5c;
      --head2: #f8fafc;
      --nav: #06244c;
      --nav2: #041b3b;
      --accent: #02a2b8;
      --text: #071f49;
      --muted: #5b6b81;
      --danger: #d93025;
      --select: #fff0f0;
      --blue: #1f77b4;
      --red: #d62728;
      --green: #2ca02c;
      --purple: #9467bd;
      --acc:#2b5fb8; --acc-d:#17427f; --acc-s:#eaf1fb; --acc-b:#c9dcf4;
      --ink:#1c2534; --ink2:#5b6b81; --ink3:#93a1b3;
      --line:#e5ebf2; --line2:#f0f4f8; --bg:#eff3f8;
      --neg:#c2413a; --pos:#1c7a4b; --warn:#a06a08;
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
      display: block;
      min-height: 100vh;
      background: var(--bg);
    }
    .top {
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      height: 58px;
      padding: 0 20px;
      gap: 14px;
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }
    .ttl { display: flex; flex-direction: column; gap: 1px; flex: 0 0 auto; }
    .ttl b { font-size: 15.5px; font-weight: 800; letter-spacing: -.015em; line-height: 1.15; color: var(--text); }
    .ttl small { font-size: 10.5px; color: var(--muted); letter-spacing: .01em; }
    .vr { width: 1px; height: 24px; background: var(--line); flex: 0 0 auto; }
    .cond {
      display: flex;
      align-items: center;
      gap: 10px;
      height: 36px;
      padding: 0 13px;
      border: 0;
      border-radius: 9px;
      background: transparent;
      white-space: nowrap;
      transition: background .12s;
    }
    .cond:hover { background: var(--bg); }
    .cond .n {
      width: 18px;
      height: 18px;
      border-radius: 5px;
      background: rgba(2,162,184,.14);
      color: var(--head-dark);
      font-size: 10.5px;
      font-weight: 800;
      display: grid;
      place-items: center;
      flex: 0 0 auto;
    }
    .cond .t { font-size: 12.5px; font-weight: 700; color: var(--text); }
    .cond .m {
      font-size: 11.5px;
      color: var(--muted);
      max-width: 380px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .cond .c { display: inline-block; flex: 0 0 auto; font-size: 9px; color: var(--muted); transition: transform .15s ease; }
    #rdaView.condition-collapsed .cond .c { transform: rotate(-90deg); }
    .rt { margin-left: auto; display: flex; align-items: center; gap: 12px; flex: 0 0 auto; }
    .pathtxt {
      font-size: 11.5px;
      color: var(--muted);
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .lnk {
      height: 30px;
      padding: 0 12px;
      border: 0;
      border-radius: 8px;
      background: transparent;
      font-size: 11.5px;
      font-weight: 700;
      color: var(--muted);
    }
    .lnk:hover { background: var(--bg); color: var(--text); }
    .lnk:disabled { opacity: .45; cursor: default; }
    .lnk:disabled:hover { background: transparent; }
    body.results-window .top { display: none !important; }
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
      /* WCAG AA(4.5:1) 미달(사이드바 배경 대비 실측 3.96~4.06) 이라 명도만 낮췄다. 색상 계열은 유지. */
      background: linear-gradient(90deg, rgba(6,145,167,.85), rgba(6,145,167,.35));
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
    .content {
      padding: 0; min-width: 0; overflow: hidden; height: 100vh;
      display: flex; flex-direction: column;
    }
    .view { display: none; }
    .view.active { display: block; flex: 1 1 auto; min-height: 0; overflow: auto; }
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
      /* 조건 7개(Device·Ver·Lot·Purpose·Reliability Items·Read-out·FT Temp.)를
         한 줄에 놓는다. 화면이 좁아지면 아래 미디어쿼리가 2열로 접는다. */
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 18px 20px;
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
    /* 분석 실행 전에는 결과 영역 '바깥 상자'까지 접는다.
       안쪽 그리드(#passResultsGrid)만 숨기면, 이 상자가 flex:1 1 auto 로 남은
       화면 높이를 전부 차지해서 커다란 흰 여백이 생긴다. */
    body:not(.results-window) .analysis-results-section:has(#passResultsGrid.results-hidden) {
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
      /* WCAG AA 미달(밝은 쪽 정지점 대비 2.48:1) 이라 명도만 낮춤, 색상 계열 유지 */
      background: linear-gradient(180deg, #0c8281, #006661);
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
    /* 분석 실행 전에는 결과 영역을 통째로 감춘다.
       !important 가 필요한 이유: 아래쪽(2106줄 부근)에 `.grid{display:grid}` 가
       또 선언되어 있는데 특이도가 같아서 나중 규칙이 이긴다. 그 탓에 여기서
       display:none 을 줘도 무시되어 빈 패널이 그대로 보였다. */
    .results-hidden { display: none !important; }
    .panel {
      min-width: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      min-height: 150px;
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(7,31,73,.05);
    }
    /* 좌측은 탭 패널(요약/Fail/이상 샘플) : 상세 를 4:1 비율로 나눈다. over-panel 은
       메인 화면에서는 항상 숨김(§updatePanelMode, popup 전용으로 남겨둠)이라
       flex 계산에서 제외된다.
       목록표는 174행, 상세표는 선택 항목 1건(내용 실측 32px)뿐이라 목록 쪽에 크게
       배분한다. (이전 값 1:2 는 정확히 반대여서 목록 스크롤 창이 41px 까지 눌렸다) */
    .summary-panel { flex: 4 1 0; min-height: 220px; }
    .over-panel { flex: 4 1 0; min-height: 220px; }
    .detail-panel { flex: 1 1 0; min-height: 90px; }
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
    td.sample-excluded {
      color: #9aa7b2;
      text-decoration: line-through;
      cursor: default;
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
      grid-template-columns: minmax(0, 4fr) minmax(0, 3fr);  /* 본창과 동일한 4:3 */
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
      /* 본창과 동일하게 세로 flex. grid 로 두면 .ctl(KPI 상자)까지 행을 배정받아
         늘어나면서 본창(54px)과 달리 334px 로 벌어졌다. */
      display: flex;
      flex-direction: column;
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
    /* 새 창에서 Abnormal Shift Sample 을 강제 표시하던 규칙을 뺐다.
       본창과 동일한 형식으로 맞추기 위해 updatePanelMode() 의 판단에 맡긴다. */
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
    /* 열 폭은 본창과 동일하게 JS 가 계산한다 (R-023) */
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
      /* WCAG AA 미달(밝은 쪽 정지점 대비 4.02:1) 이라 명도만 낮춤, 색상 계열 유지 */
      background: linear-gradient(180deg, #07828e, #056976);
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
    .detail-col-wrap { margin-left: auto; }
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
      position: fixed;
      z-index: 200;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(20, 40, 70, 0.15);
      padding: 8px;
      min-width: 160px;
      max-height: min(420px, 60vh);
      overflow-y: auto;
    }
    .column-toggle-menu.open { display: block; }
    .column-menu-head {
      position: sticky;
      top: -8px;
      margin: -8px -8px 4px;
      padding: 8px 8px 6px;
      background: #fff;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      z-index: 1;
    }
    .column-menu-head .column-toggle-item { padding: 0; font-weight: 700; }
    .column-menu-reset {
      background: none;
      border: 1px solid #bdd3df;
      border-radius: 12px;
      padding: 3px 9px;
      font-size: 11px;
      font-weight: 700;
      color: #0b6070;
      cursor: pointer;
      white-space: nowrap;
    }
    .column-menu-reset:hover { background: #eef6fa; }
    .column-menu-body { display: flex; flex-direction: column; }
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
      /* WCAG AA 미달(밝은 쪽 정지점 대비 2.3:1, 실제 렌더링에서 이 규칙이 우선 적용됨) 이라 명도만 낮춤, 색상 계열 유지 */
      background: linear-gradient(90deg, #0e80a1, #104d9b);
      box-shadow: inset 4px 0 0 rgba(60,235,255,.85), 0 8px 20px rgba(1,87,187,.35);
      color: #fff;
    }
    .side-exit {
      border-top: 1px solid rgba(255,255,255,.18);
      padding-bottom: 28px;
    }
    .content {
      padding: 0;
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
      /* WCAG AA 미달(밝은 쪽 정지점 대비 2.48:1) 이라 명도만 낮춤, 색상 계열 유지 */
      background: linear-gradient(180deg, #0c8281, #006661);
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
      min-height: 36px;
      padding: 7px 18px;
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
      /* WCAG AA 미달(밝은 쪽 정지점 대비 2.87:1) 이라 명도만 낮춤, 색상 계열 유지 */
      background: linear-gradient(180deg, #0c837f, #056a68);
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
    .content {
      height: 100vh;
      padding: 0;
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
    .status-pill.st-ok   { background: #e6f5ec; color: #14683f; }
    .status-pill.st-warn { background: #fff4e0; color: #8a5a00; }
    .status-pill.st-err  { background: #fbecee; color: #8c1020; }
    .analyze-error {
      display: none;
      flex: 0 0 auto;
      margin: 10px 0 0;
      padding: 10px 14px;
      border: 1px solid #f0c8ce;
      border-left: 4px solid #b00020;
      border-radius: 6px;
      background: #fbecee;
      color: #8c1020;
      font-size: 13px;
      font-weight: 600;
      white-space: pre-wrap;
    }
    .analyze-error.open { display: block; }
    .field.invalid select,
    .field.invalid input { border-color: #b00020; background: #fff6f7; }
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

    /* ── W4-2~4 : 표/그래프 컨트롤 카드 통합 레이아웃 (source-order로 위 정의를 override) ── */
    :root{
      --acc:#2b5fb8; --acc-d:#17427f; --acc-s:#eaf1fb; --acc-b:#c9dcf4;
      --ink:#1c2534; --ink2:#5b6b81; --ink3:#93a1b3;
      --line:#e5ebf2; --line2:#f0f4f8; --bg:#eff3f8;
      --neg:#c2413a; --pos:#1c7a4b; --warn:#a06a08;
    }

    /* ── 2열 : 표 5 : 그래프 3 ── */
    .grid{
      display:grid;
      grid-template-columns:minmax(0,4fr) minmax(0,3fr);
      grid-template-rows:minmax(0,1fr);
      grid-template-areas:"resulttab graphtab";
      gap:14px; flex:1 1 auto; min-height:560px;
      padding:0; border:0; background:transparent; align-items:stretch;
    }
    .result-table-column,.result-graph-column{
      display:flex; flex-direction:column; gap:12px; min-width:0; min-height:0;
    }
    .summary-panel{ flex:1 1 0; min-height:0; }
    .over-panel   { flex:1 1 0; min-height:0; }
    .detail-panel { flex:1 1 0; min-height:0; }

    #analysisFilterBar, #graphFilterBar{ display:contents; }

    .ctl{ flex:0 0 auto; height:auto; min-height:134px; display:flex; flex-direction:column;
      background:#fff; border:1px solid var(--line); border-radius:11px; overflow:hidden; }
    /* 134px 는 KPI(52) + 시험항목 탭(40) + 하단 필터(40) 가 모두 있을 때의 높이다.
       단일 시험 항목을 고르면 필터 바가 비는데, 고정 높이 탓에 그만큼 빈 칸이 남았다.
       비어 있을 때만 내용 높이에 맞춘다. */
    .ctl:has(> .analysis-filter-bar:empty){ height:auto; }
    .crow{ display:flex; align-items:center; gap:14px; padding:0 14px; min-width:0; }
    .crow+.crow{ border-top:1px solid var(--line2); }
    .crow.tabs{ border-top:1px solid var(--line2); }
    .crow.foot{ border-top:1px solid var(--line2); }
    .crow.kpi{ height:52px } .crow.foot{ height:40px }
    /* 시험 항목이 많으면 한 줄에 다 안 들어가 오른쪽이 잘렸다. 여러 줄로 접는다. */
    .crow.tabs{ height:auto; min-height:40px; padding:4px 0 4px 8px; align-items:flex-start }
    .crow.tabs .tabwrap{ height:auto }
    .crow.tabs .tabwrap::after{ display:none }
    /* 아래쪽 `.item-tabs,.graph-tabs` 규칙이 nowrap 을 걸기 때문에
       특이도를 한 단계 높여서(.crow.tabs 하위) 확실히 이긴다. */
    .crow.tabs .item-tabs{ flex-wrap:wrap; overflow:visible; height:auto; row-gap:2px }
    .crow.tabs .item-tab{ height:32px }
    .crow.tabs .item-tab-badge{ min-width:0 }
    .tail2{ margin-left:auto; display:flex; align-items:center; gap:12px; flex:0 0 auto; padding-left:12px }
    .lbl{ font-size:11px; font-weight:700; color:var(--ink3); letter-spacing:.03em; flex:0 0 auto }
    .gsum{ gap:0 }
    .gname{ display:flex; flex-direction:column; gap:2px; min-width:0 }
    .gname b{ font-size:14px; font-weight:800; letter-spacing:-.01em; line-height:1.2 }
    .gname span{ font-size:11px; color:var(--ink3) }

    .summary-strip{ display:flex; align-items:center; gap:0; height:100%; margin:0; flex:1 1 auto; min-width:0 }
    /* 카드 폭을 140px 로 균등하게. 예전에는 글자 길이대로 폭이 정해져서
       구분선 간격이 들쭉날쭉했다(102/138/77/105px). */
    .summary-card{ display:flex; align-items:baseline; gap:6px; padding:0 0 0 16px; margin:0;
      border:0; border-right:1px solid var(--line2); border-radius:0; background:none;
      min-width:140px; flex:0 0 auto; }
    .summary-card:first-of-type{ padding-left:0 }
    .summary-card:last-of-type{ border-right:0 }
    .summary-card-value{ font-size:20px; font-weight:800; letter-spacing:-.02em;
      font-variant-numeric:tabular-nums; line-height:1 }
    .summary-card-label{ font-size:11px; font-weight:600; color:var(--ink2) }
    .summary-card-flag .summary-card-value{ color:var(--neg) }
    .summary-card-ok   .summary-card-value{ color:var(--pos) }
    .summary-card-warn{ background:none; border-color:var(--line2) }
    .summary-card-warn .summary-card-value{ color:var(--warn) }
    .judgment-footnote{ margin-left:auto; text-align:right; font-size:10.5px; color:var(--ink3);
      line-height:1.55; flex:0 0 auto; white-space:normal }

    .tabwrap{ position:relative; flex:1 1 auto; min-width:0; display:flex; height:100% }
    .tabwrap::after{ content:""; position:absolute; right:0; top:0; bottom:0; width:24px;
      pointer-events:none; background:linear-gradient(to right,rgba(255,255,255,0),#fff) }
    .item-tabs,.graph-tabs{ display:flex; align-items:stretch; gap:0; height:100%;
      flex-wrap:nowrap; overflow-x:auto; overflow-y:hidden;
      scrollbar-width:none; min-width:0; flex:1 1 auto; border:0; margin:0 }
    .item-tabs::-webkit-scrollbar,.graph-tabs::-webkit-scrollbar{ display:none }
    .item-tab,.graph-tabs button{ display:inline-flex; align-items:center; gap:6px; padding:0 12px;
      flex:0 0 auto; position:relative; height:100%; min-height:0; min-width:0;
      border:0; border-radius:0; background:none; box-shadow:none;
      font-size:12.5px; font-weight:700; color:var(--ink2); white-space:nowrap }
    .item-tab.active,.graph-tabs button.active{ color:var(--acc-d); background:none }
    .item-tab.active::after,.graph-tabs button.active::after{ content:""; position:absolute;
      left:10px; right:10px; bottom:0; height:2.5px; background:var(--acc); border-radius:2px 2px 0 0 }
    .item-tab-badge{ font-size:10.5px; font-weight:700; color:var(--ink3);
      font-variant-numeric:tabular-nums; min-width:46px; text-align:right;
      padding:0; border-radius:0; background:none }
    .item-tab.active .item-tab-badge{ color:var(--acc); background:none }
    .item-tab-empty{ color:var(--ink3); opacity:.55 }

    .pill{ display:inline-flex; align-items:center; height:26px; padding:2px;
      border-radius:8px; background:var(--bg); flex:0 0 auto }
    .pill button{ height:22px; padding:0 12px; border:0; border-radius:6px; background:none;
      font-size:11.5px; font-weight:700; color:var(--ink2); white-space:nowrap }
    .pill button.active{ background:#fff; color:var(--acc-d); box-shadow:0 1px 2px rgba(20,40,70,.10) }
    .filter-chip{ height:22px; min-height:0; padding:0 12px; border:0; border-radius:6px;
      background:none; font-size:11.5px; font-weight:700; color:var(--ink2) }
    .filter-chip.active{ background:#fff; color:var(--acc-d);
      box-shadow:0 1px 2px rgba(20,40,70,.10); border:0 }
    /* FT TEMP. 은 알약 배경 대신 탭과 같은 밑줄로 표시한다 */
    .temp-filter-group .filter-chip{ height:40px; border-radius:0; padding:0 12px;
      position:relative; font-size:12.5px; min-width:0 }
    .temp-filter-group .filter-chip.active{ background:none; box-shadow:none; color:var(--acc-d) }
    .temp-filter-group .filter-chip.active::after{ content:""; position:absolute;
      left:10px; right:10px; bottom:0; height:2.5px; background:var(--acc);
      border-radius:2px 2px 0 0 }
    .readout-toggle,.filter-check{ height:26px; min-height:0; padding:0 4px; border:0; background:none;
      font-size:11.5px; font-weight:700; color:var(--ink2) }
    .readout-toggle input,.filter-check input{ accent-color:var(--acc) }

    .panel{ background:#fff; border:1px solid var(--line); border-radius:11px; box-shadow:none;
      display:flex; flex-direction:column; min-height:0; overflow:hidden }
    .ptabs{ flex:0 0 auto; display:flex; height:40px; background:#fafcfe;
      border-bottom:1px solid var(--line) }
    .pt{ display:inline-flex; align-items:center; gap:7px; padding:0 18px; border:0; background:none;
      font-size:12.5px; font-weight:700; color:var(--ink2); white-space:nowrap }
    .pt+.pt{ border-left:1px solid var(--line2) }
    .pt.active{ background:#fff; color:var(--acc-d); box-shadow:inset 0 2.5px 0 var(--acc) }
    .pt .c{ font-size:10.5px; font-weight:800; color:var(--ink3); font-variant-numeric:tabular-nums }
    .pt.active .c{ color:var(--acc) }
    .pt .tab-count-badge,.pt .fail-count-badge{ font-size:10.5px; font-weight:800; color:var(--ink3);
      font-variant-numeric:tabular-nums; margin-left:4px; padding:0; background:none; border-radius:0 }
    .pt.active .tab-count-badge,.pt.active .fail-count-badge{ color:var(--acc) }
    .ptool{ flex:0 0 auto; display:flex; align-items:center; gap:10px; height:38px; padding:0 12px;
      border-bottom:1px solid var(--line2) }
    .ptool .r{ margin-left:auto; display:flex; align-items:center; gap:8px }
    .chead{ flex:0 0 auto; display:flex; align-items:center; gap:10px; height:40px; padding:0 14px;
      border-bottom:1px solid var(--line2); background:none }
    .chead h2,.chead h3{ margin:0; font-size:12.5px; font-weight:800; color:var(--ink); white-space:nowrap }
    .chead .s{ font-size:11px; color:var(--ink3) }
    /* R-027: 이상 카드에 샘플 수를 작게 병기한다 (항목 수가 주, 샘플 수가 보조). */
    .summary-card-sub{ font-size:11px; font-weight:600; color:var(--ink3) }
    /* R-026: 기준 탭은 화면 전체의 필터 스위치다. 노트는 이동량 기준에서 몇 건이 빠졌는지. */
    #detailBasisBar, #failBasisBar{ flex:0 0 auto }
    /* R-033: .pill 의 display:inline-flex 가 브라우저 기본 [hidden]{display:none} 을 이겨서
       두 바가 동시에 보였다(우선순위가 같으면 작성자 스타일이 이긴다). ID+속성 선택자로
       확실히 눌러준다 — 안 그러면 현재 탭과 무관한 바가 떠서 눌러도 안 먹는 것처럼 보인다. */
    #detailBasisBar[hidden], #failBasisBar[hidden]{ display:none !important }
    /* R-035: 기준 바가 .chead(선택 항목 상세) 를 떠나 결과 패널 툴바로 올라갔다.
       .chead .s 후손 선택자를 더는 못 타므로 글자 크기를 여기서 직접 준다.
       툴바 폭이 모자라면 노트만 줄어들게 한다 — 버튼은 절대 줄지 않는다. */
    #shiftGateNote{ font-size:11px; color:var(--ink3); white-space:nowrap;
      flex:0 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis }
    #shiftGateNote.is-on{ color:var(--acc-d) }
    .gbtn{ height:28px; padding:0 12px; border-radius:8px; border:1px solid var(--line);
      background:#fff; font-size:11.5px; font-weight:700; color:var(--ink2) }
    .gbtn:hover{ border-color:var(--acc-b); color:var(--acc-d); background:var(--acc-s) }

    .table-wrap{ flex:1 1 auto; min-height:0; overflow:auto;
      background:linear-gradient(to left,rgba(28,37,52,.05),rgba(28,37,52,0) 20px) right center/20px 100% no-repeat;
      background-attachment:local,scroll }
    table{ border-collapse:separate; border-spacing:0; width:max-content; min-width:100%; font-size:11.5px }
    th{ position:sticky; top:0; z-index:2; background:#fafcfe; color:var(--ink2);
      font-weight:700; font-size:10.5px; letter-spacing:.02em; padding:8px 10px;
      text-align:center; white-space:nowrap; border:0; border-bottom:1px solid var(--line);
      box-shadow:0 1px 0 var(--line); cursor:pointer; user-select:none }
    td{ padding:6.5px 10px; text-align:center; white-space:nowrap; border:0;
      border-bottom:1px solid var(--line2); font-variant-numeric:tabular-nums; color:var(--ink) }
    td.item,td.over-item{ text-align:left; font-weight:600 }
    tbody tr:nth-child(even) td{ background:none }
    tbody tr:hover td{ background:#fafcfe }
    tr.active td,td.over-item.active{ background:var(--acc-s); box-shadow:none }
    tr.active td:first-child{ box-shadow:inset 2.5px 0 0 var(--acc) }
    td.sigma-fail{ background:none; color:var(--neg); font-weight:800 }

    /* 그래프 4종은 탭으로 하나만 표시 */
    .chart-panel,.diff-cdf-panel,.ppf-panel,.scatter-panel{
      display:none; flex:1 1 0; min-height:0 }
    .chart-panel.active-graph,.diff-cdf-panel.active-graph,
    .ppf-panel.active-graph,.scatter-panel.active-graph{ display:flex }
    /* Wafer Map 은 상시 표시. 활성 그래프와 세로 1 : 1 (flex-basis 0 이어야 정확히 1:1) */
    .wafer-panel{ display:flex; flex:1 1 0; min-height:0 }

    #detailPanelMeta.is-loading{ color:var(--acc); opacity:.85 }

    /* 그래프에서 뺀 샘플이 있다는 표시. 체크해놓고 잊으면 "왜 점이 안 보이지"가 된다. */
    .graph-exclude-note{ display:none; margin-left:10px; font-size:11.5px; color:#B26A00;
      background:#FFF4E0; border:1px solid #F0C987; border-radius:10px; padding:1px 8px }
    .graph-exclude-note.on{ display:inline-flex; align-items:center; gap:6px }
    .graph-exclude-note button{ border:0; background:none; color:#8A5200; font-size:11.5px;
      text-decoration:underline; cursor:pointer; padding:0 }

    /* ── 선택 항목 상세 표: 열 폭 고정 ─────────────────────────
       예전에는 본창에만 table-layout 지정이 없어서 브라우저가 내용 길이에 맞춰
       매번 열 폭을 다시 계산했다. 그래서 상단 표에서 항목을 바꿀 때마다 상세 표의
       열이 좌우로 흔들렸다(실측 최대 11px, 실제 데이터에서는 더 큼).
       새 창에는 이미 같은 규칙이 있었는데 본창에는 빠져 있었다.
       detailColumns() 는 pass·fail 모드 모두 항상 13열을 반환한다.
       ★ 열을 추가하면 아래 nth-child 폭도 함께 고쳐야 한다(합이 100%). */
    .detail-panel .table-wrap{ overflow-x:hidden }
    #detailTable{ width:100%; min-width:0; table-layout:fixed }
    #detailTable th, #detailTable td{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
    #detailTable th{ line-height:1.15; white-space:normal; word-break:keep-all }
    /* 열 폭은 R-023 부터 표시 중인 열에 맞춰 JS(detailColumnWidths)가 계산한다.
       열을 켜고 끌 수 있게 되면서 nth-child 고정 규칙으로는 감당이 안 된다. */

    /* ── 샘플 기준 표: 열 폭 고정 ──────────────────────────────
       이 표는 열 개수가 데이터에 따라 달라진다(한 샘플이 가진 최대 항목 수).
       기본 `table{ min-width:100% }` 때문에 열이 적은 Fail 탭에서는 남는 폭을
       열들이 나눠 가져, 같은 표인데도 Abnormal Pass 탭보다 훨씬 넓어 보였다.
       폭을 고정해 열 개수와 무관하게 두 탭이 같은 모양이 되게 한다.
       잘린 이름은 renderOverSampleTable() 이 title 로 전체를 보여준다. */
    #overSampleTable{ table-layout:fixed; width:max-content; min-width:0 }
    #overSampleTable th, #overSampleTable td{
      width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }
    #overSampleTable th:first-child, #overSampleTable td:first-child{ width:88px }
    /* R-031: 항목 수 열. 숫자라 좁게 두고 오른쪽 정렬한다. */
    #overSampleTable th:nth-child(2), #overSampleTable td:nth-child(2){ width:84px }
    #overSampleTable td.over-count{ text-align:right; padding-right:14px; color:var(--ink2) }
  </style>
</head>
<body>
  <main>
    <section class="app-shell">
      <div class="content">
        <header class="top">
          <div class="ttl"><b>Reliability Data Analysis</b><small>__APP_REVISION__</small></div>
          <div class="vr"></div>
          <button type="button" class="cond" id="conditionSecBtn" aria-expanded="true">
            <span class="n">1</span><span class="t">분석 조건</span>
            <span class="m" id="conditionSummaryLine"></span><span class="c">▾</span>
          </button>
          <div class="rt">
            <button type="button" class="lnk" id="openResultsWindowBtn" title="Open Analysis Results in a new window" disabled>결과 새 창</button>
            <div class="vr"></div>
            <span class="pathtxt" id="dataPath">-</span>
            <button type="button" class="lnk" id="browseDataPathBtn">경로 변경</button>
          </div>
        </header>
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
          <section class="rda-card condition-card" id="conditionCard">
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
        <div id="analyzeError" class="analyze-error" role="alert"></div>
        <section class="analysis-results-section">
          <div class="analysis-results-scroll">
        <section id="passResultsGrid" class="grid results-hidden">
      <div class="result-table-column">
      <div class="condition-title results-window-title"><span class="filter-icon"></span><span class="title-text">2. Analysis Results</span></div>
      <section class="ctl">
        <div class="crow kpi"><section id="summaryStrip" class="summary-strip"></section></div>
        <section id="analysisFilterBar" class="analysis-filter-bar"></section>
      </section>
      <section class="panel summary-panel">
        <div class="ptabs" id="resultModeBar" title="Abnormal Shift Items (Mea_S or Diff_S &gt; Grubbs threshold)">
          <button id="failModeBtn" class="pt" type="button" data-mode="fail">Fail 항목</button>
          <button id="passModeBtn" class="pt active" type="button" data-mode="pass">Abnormal Pass</button>
        </div>
        <div class="ptool">
          <div class="pill" id="resultViewBar">
            <button id="itemViewBtn" class="active" type="button" data-view="item">항목 기준</button>
            <button id="sampleViewBtn" type="button" data-view="sample">샘플 기준</button>
          </div>
          <div class="pill" id="detailBasisBar" title="판정에 걸린 것 중 무엇을 보여줄지 고른다. 판정 자체는 바뀌지 않는다."><button id="basisShiftBtn" class="active" type="button" data-basis="shift">스펙 대비 기준</button><button id="basisSigmaBtn" type="button" data-basis="sigma">산포 기준</button></div><div class="pill" id="failBasisBar" title="Marginal = 규격은 벗어났지만 이동량이 집단의 일반적 범위 안인 건(Tail). 판정 자체는 바뀌지 않는다." hidden><button id="basisNoTailBtn" class="active" type="button" data-fail-basis="no-tail">Marginal 제외</button><button id="basisAllFailBtn" type="button" data-fail-basis="all">전체</button></div><span id="shiftGateNote"></span>
          <span id="flagAlphaLabel" class="flag-alpha-label"></span>
          <div class="r"><div class="column-toggle-wrap" id="columnToggleWrap"><button id="columnToggleBtn" class="gbtn column-toggle-btn" type="button">＋ 열</button><div id="columnToggleMenu" class="column-toggle-menu"></div></div></div>
        </div>
        <div class="table-wrap" id="resultTableWrap"><table id="resultTable"></table></div>
        <div class="table-wrap" id="overSampleTableWrap"><table id="overSampleTable"></table></div>
      </section>
      <section class="panel over-panel">
        <h2><span class="panel-label"><span class="panel-icon icon-sample"></span>Abnormal Shift Sample</span></h2>
        <div class="table-wrap"><table id="overTable"></table></div>
      </section>
      <section class="panel detail-panel">
        <div class="chead"><h2>선택 항목 상세</h2><span class="s" id="detailPanelMeta"></span><div class="column-toggle-wrap detail-col-wrap" id="detailColumnToggleWrap"><button id="detailColumnToggleBtn" class="gbtn column-toggle-btn" type="button">＋ 열</button><div id="detailColumnToggleMenu" class="column-toggle-menu"></div></div></div>
        <div class="table-wrap"><table id="detailTable"></table></div>
      </section>
      </div>
      <div class="result-graph-column">
      <section class="ctl">
        <div class="crow kpi gsum">
          <div class="gname"><b id="graphItemName">—</b><span id="graphItemMeta"></span><span id="graphExcludeNote" class="graph-exclude-note"></span></div>
          <div class="tail2"><select id="itemSelect"></select><button class="gbtn copy-chart-btn" type="button" data-canvas="cdfCanvas">복사</button></div>
        </div>
        <section id="graphFilterBar" class="graph-filter-bar"></section>
      </section>
      <section class="panel chart-panel">
        <div class="chart-box"><canvas id="cdfCanvas"></canvas></div>
      </section>
      <section class="panel diff-cdf-panel">
        <div class="chart-box"><canvas id="diffCdfCanvas"></canvas></div>
      </section>
      <section class="panel ppf-panel">
        <div class="chart-box"><canvas id="ppfCanvas"></canvas></div>
      </section>
      <section class="panel scatter-panel">
        <div class="scatter-box"><canvas id="scatterCanvas"></canvas></div>
      </section>
      <section class="panel wafer-panel">
        <div class="chead"><h2>Wafer Map</h2><span class="s" id="waferPanelMeta"></span></div>
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
let sortState = { column: "qty", reverse: true };
let detailSortState = { column: null, reverse: false };
let analysisMode = "pass";
let resultViewMode = "item";
let modePayloads = {};
let stopAnalysisRequested = false;
let activeAnalysisRunId = "";
let activeGraphTab = "cdf";
let needBenchState = {};
/* 그래프에서만 빼는 샘플. 판정·통계·표의 숫자에는 절대 손대지 않는다 (CLAUDE.md §5-1).
   키 형태는 needBenchState 와 동일 — 분석을 다시 돌리거나 항목/모드를 바꾸면 자연히 풀린다. */
let graphExcludeState = {};
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
// 표의 열 순서는 이 배열 순서를 그대로 따른다("+ 열" 로 켠 열도 여기 위치에 끼어든다).
// 앞의 10개가 기본 표시이고, 뒤쪽은 "+ 열" 메뉴에서 켜야 보인다.
const passColumns = [
  // ── 기본 표시 (R-020) ──
  // 읽는 순서: 식별(Test No.·Item) → 규격(Unit·LL·UL) → 중심값(Avg.) → 변화율(Delta Mean) → 개수(Q'ty)
  // 산포·범위(Stdev.·Min.·Max.)와 Pre 쪽 분포는 항목을 더블클릭해 Pre / Post 비교 새 창에서 본다. (R-022)
  ["test_number", "Test No."], ["item", "Item"], ["unit", "Unit"],
  ["lower_limit", "LL"], ["upper_limit", "UL"], ["avg", "Avg."],
  ["diff_mean", "Delta Mean"], ["qty", "Q'ty"],
  // ── 기본 숨김: "+ 열" 에서 켠다 ──
  ["sample_numbers", "Sample No."]
];
// Fail 목록도 Abnormal Pass 와 완전히 같은 열 구성을 쓴다 -- 두 탭을 오갈 때 열 위치가
// 바뀌지 않게 하기 위해서다. R-020 에서 Fail 행에 값이 없어 늘 N/A 로 뜨던 열
// (Shift·Shift/σ·Max |σ|)과 중복·오해 소지가 있던 열(Reason·N (σ n-1)·%)을 제거했다.
// 판정축은 선택 항목 상세의 Fail Type / Reason 열에서 본다.
const failColumns = passColumns;
// 기본으로 보여줄 열. 두 탭이 같은 목록을 쓴다.
const DEFAULT_COLUMN_KEYS = [
  "test_number", "item", "unit", "lower_limit", "upper_limit", "avg",
  "diff_mean", "qty"
];
const DEFAULT_VISIBLE_COLUMNS_PASS = DEFAULT_COLUMN_KEYS;
const DEFAULT_VISIBLE_COLUMNS_FAIL = DEFAULT_COLUMN_KEYS;
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
let pendingLookup = null;   // 진행 중인 refreshLookup 체인
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
  if (!target) return;
  target.textContent = text;
  if (!target.classList.contains("status-pill")) return;
  target.classList.remove("st-ok", "st-warn", "st-err");
  target.classList.add(
    /fail|error|실패/i.test(text) ? "st-err"
    : /running|searching|initial|stopp|preparing|\d%/i.test(text) ? "st-warn"
    : "st-ok");
}
function showAnalyzeError(message, missingKeys = []) {
  const el = document.getElementById("analyzeError");
  if (el) { el.textContent = message; el.classList.add("open"); }
  document.querySelectorAll(".field.invalid").forEach(f => f.classList.remove("invalid"));
  const ID = { device: "deviceInput", ver: "verSelect", lot: "lotSelect", purpose: "purposeSelect" };
  missingKeys.forEach(k => document.getElementById(ID[k])?.closest(".field")?.classList.add("invalid"));
}
function clearAnalyzeError() {
  document.getElementById("analyzeError")?.classList.remove("open");
  document.querySelectorAll(".field.invalid").forEach(f => f.classList.remove("invalid"));
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
  const task = _refreshLookupInner(field);
  pendingLookup = task;
  try { return await task; }
  finally { if (pendingLookup === task) pendingLookup = null; }
}
async function _refreshLookupInner(field) {
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
      clearAnalyzeError();
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
  const label = labels[index - 1];
  // 회차를 먼저 읽게 t1/t2/t3 를 앞에 두고, 실제 리드아웃 이름이 있으면 괄호로 병기한다. (R-020)
  return label ? `t${index} (${label})` : `t${index}`;
}
/* ── R-023: 상세 표 열 선택 ────────────────────────────────────
   Z-Score 두 열은 판정 근거라 늘 필요하진 않다 — 기본은 숨기고 "＋ 열"에서 켠다.
   열 폭은 표시 중인 열의 가중치를 100% 로 정규화해 계산한다. */
const DETAIL_OPTIONAL_KEYS = ["mea_s", "diff_s"];
const DETAIL_COLUMN_WEIGHT = {
  sample: 8, spec_out_type: 11, pre_value: 8.5, post_t1: 8.5, post_t2: 8, post_t3: 8,
  unit: 6, mea_s: 9, diff: 8, diff_s: 9, graph_exclude: 7, need_bench: 9
};
let detailColumnVisibility = null;   // 첫 렌더에서 기본값으로 채운다
function defaultDetailColumnKeys() {
  return detailColumns().map(([key]) => key).filter(key => !DETAIL_OPTIONAL_KEYS.includes(key));
}
function ensureDetailColumnVisibility() {
  if (!detailColumnVisibility) detailColumnVisibility = new Set(defaultDetailColumnKeys());
  return detailColumnVisibility;
}
function visibleDetailColumns() {
  const visible = ensureDetailColumnVisibility();
  const cols = detailColumns().filter(([key]) => visible.has(key));
  return cols.length ? cols : detailColumns();   // 전부 끄면 빈 표가 되므로 방어
}
function detailColumnWidths(cols) {
  const weights = cols.map(([key]) => DETAIL_COLUMN_WEIGHT[key] || 8);
  const total = weights.reduce((a, c) => a + c, 0) || 1;
  return weights.map(w => (w / total * 100));
}
/* ── R-023: 열 선택 메뉴 열고 닫는 배선. 결과 목록과 선택 항목 상세가 같이 쓴다.
   .panel 이 overflow:hidden 이라 absolute 메뉴가 잘린다 — body 로 옮기고
   position:fixed 로 버튼 기준 좌표를 계산해 배치한다. */
function wireColumnToggleMenu(btnId, menuId) {
  const btn = document.getElementById(btnId);
  const menu = document.getElementById(menuId);
  if (!btn || !menu) return;
  document.body.appendChild(menu);
  const place = () => {
    const b = btn.getBoundingClientRect(), m = menu.getBoundingClientRect();
    let left = b.right - m.width;
    let top = b.bottom + 6;
    left = Math.max(8, Math.min(left, window.innerWidth - m.width - 8));
    if (top + m.height > window.innerHeight - 8) top = Math.max(8, b.top - m.height - 6);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  };
  const close = () => menu.classList.remove("open");
  btn.addEventListener("click", event => {
    event.stopPropagation();
    if (menu.classList.contains("open")) { close(); return; }
    menu.classList.add("open");
    place();
  });
  document.addEventListener("click", event => {
    if (!menu.classList.contains("open")) return;
    if (menu.contains(event.target) || event.target === btn) return;
    close();
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu.classList.contains("open")) close();
  });
  window.addEventListener("resize", () => { if (menu.classList.contains("open")) place(); });
  window.addEventListener("scroll", () => { if (menu.classList.contains("open")) place(); }, true);
}
let detailMenuSignature = null;
/* 체크 상태만 맞춘다. 열을 켜고 끌 때마다 메뉴를 통째로 다시 만들면 방금 누른
   체크박스가 DOM 에서 떨어져 나가, 연속으로 두 개를 켜면 두 번째가 먹히지 않는다. */
function syncDetailMenuChecks(menu, allCols, visible) {
  const boxes = Array.from(menu.querySelectorAll(".column-menu-body input"));
  boxes.forEach((box, i) => { if (allCols[i]) box.checked = visible.has(allCols[i][0]); });
  const allBox = menu.querySelector(".column-menu-head input");
  if (allBox) {
    const checked = allCols.filter(([key]) => visible.has(key)).length;
    allBox.checked = checked === allCols.length;
    allBox.indeterminate = checked > 0 && checked < allCols.length;
  }
}
function renderDetailColumnToggleMenu() {
  const menu = document.getElementById("detailColumnToggleMenu");
  if (!menu) return;
  const allCols = detailColumns();
  const visible = ensureDetailColumnVisibility();
  // 헤더 라벨은 탭(Fail Type / Reason)과 리드아웃 이름에 따라 바뀐다 — 그때만 다시 만든다.
  const signature = allCols.map(([key, label]) => `${key}|${label}`).join(",");
  if (detailMenuSignature === signature && menu.childElementCount) {
    syncDetailMenuChecks(menu, allCols, visible);
    return;
  }
  detailMenuSignature = signature;
  menu.innerHTML = "";
  const head = document.createElement("div");
  head.className = "column-menu-head";
  const allItem = document.createElement("label");
  allItem.className = "column-toggle-item";
  const allBox = document.createElement("input");
  allBox.type = "checkbox";
  const syncAll = () => {
    const checked = allCols.filter(([key]) => visible.has(key)).length;
    allBox.checked = checked === allCols.length;
    allBox.indeterminate = checked > 0 && checked < allCols.length;
  };
  allBox.addEventListener("change", () => {
    if (allBox.checked) allCols.forEach(([key]) => visible.add(key));
    else allCols.forEach(([key]) => visible.delete(key));
    renderDetailTable();
  });
  allItem.appendChild(allBox);
  allItem.appendChild(document.createTextNode("전체 선택"));
  head.appendChild(allItem);
  const reset = document.createElement("button");
  reset.type = "button";
  reset.className = "column-menu-reset";
  reset.textContent = "기본값으로";
  reset.addEventListener("click", () => {
    visible.clear();
    defaultDetailColumnKeys().forEach(key => visible.add(key));
    renderDetailTable();
  });
  head.appendChild(reset);
  menu.appendChild(head);
  const body = document.createElement("div");
  body.className = "column-menu-body";
  allCols.forEach(([key, label]) => {
    const item = document.createElement("label");
    item.className = "column-toggle-item";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = visible.has(key);
    box.addEventListener("change", () => {
      if (box.checked) visible.add(key); else visible.delete(key);
      syncAll();
      renderDetailTable();
    });
    item.appendChild(box);
    item.appendChild(document.createTextNode(label));
    body.appendChild(item);
  });
  menu.appendChild(body);
  syncAll();
}
function detailColumns() {
  // 같은 열에 담기는 값의 성격이 탭마다 다르다 — Fail 탭은 이탈 유형(Excessive·Slight…),
  // Abnormal Pass 탭은 판정축(Measured·Delta). 한 이름으로 묶으면 같은 종류로 오해된다. (R-020)
  const specOutHeader = (analysis?.analysis_mode || analysisMode) === "fail" ? "Fail Type" : "Reason";
  return [
    ["sample", "Sample No."], ["spec_out_type", specOutHeader],
    ["pre_value", "Pre"], ["post_t1", postReadoutHeader(1)], ["post_t2", postReadoutHeader(2)], ["post_t3", postReadoutHeader(3)],
    ["unit", "Unit"], ["mea_s", "Z-Score (Value)"], ["diff", "Delta"],
    ["diff_s", "Z-Score (Delta)"], ["graph_exclude", "Exclude"], ["need_bench", "Need Bench?"]
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
    // 결과 새 창도 본창과 같은 형식으로 통일한다.
    // (예전에는 새 창만 "1./2./3." 번호가 붙은 보고서 형식이었고 Fail 목록과
    //  Abnormal Pass 목록을 별도 패널로 분리했다 — 두 화면을 오갈 때 혼란스러웠다.)
    if (summaryTitle) summaryTitle.lastChild.textContent = "Fail & Abnormal Data Lists - All";
    if (detailTitle) detailTitle.lastChild.textContent = "Fail & Abnormal Data Analysis Result";
    if (overPanel) {
      overPanel.style.display = "none";
      const overTitle = overPanel.querySelector(".panel-label");
      if (overTitle) overTitle.lastChild.textContent = "Abnormal Shift Sample";
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
let itemNameMapCache = null;
let itemNameMapSource = null;
function itemNameMap() {
  // 전체 분석에서 item_key 는 "{item}__{sha1[:10]}" 형태라 그대로 표시하면 안 된다.
  // analysis 응답의 각 행에 깨끗한 item 이름이 함께 오므로 여기서 키->이름 표를 만든다.
  // analysis 객체가 교체되면(새 분석/모드 전환/초기화) 자동으로 다시 만들어진다.
  if (itemNameMapCache && itemNameMapSource === analysis) return itemNameMapCache;
  const map = new Map();
  for (const list of [analysis?.results, analysis?.selected_summary]) {
    for (const row of (list || [])) {
      const key = itemKey(row);
      if (key && row?.item && !map.has(key)) map.set(key, row.item);
    }
  }
  itemNameMapCache = map;
  itemNameMapSource = analysis;
  return map;
}
function itemDisplayName(key) {
  const data = itemCache[key];
  if (data?.item) return data.item;
  if (data?.display_item) return data.display_item;
  // 아직 클릭하지 않아 itemCache 에 없는 항목: payload 에서 이름을 찾는다.
  const name = itemNameMap().get(key);
  if (name) return name;
  // 최후 방어 — 그래도 못 찾으면 해시 접미사만 떼어낸다.
  return String(key || "").replace(/__[0-9a-f]{10}$/, "");
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
  const nameNode = document.getElementById("graphItemName");
  if (nameNode) nameNode.textContent = itemName || "—";
  renderItemThresholdLabel();
}
function updateGraphPanels() {
  const panelMap = {
    cdf: "chart-panel",
    diff: "diff-cdf-panel",
    ppf: "ppf-panel",
    scatter: "scatter-panel"
  };
  const canvasMap = {
    cdf: "cdfCanvas",
    diff: "diffCdfCanvas",
    ppf: "ppfCanvas",
    scatter: "scatterCanvas",
    wafer: "waferCanvas"
  };
  document.querySelectorAll(".graph-tabs button").forEach(button => {
    button.classList.toggle("active", button.dataset.graph === activeGraphTab);
  });
  Object.entries(panelMap).forEach(([key, className]) => {
    document.querySelectorAll(`.${className}`).forEach(panel => {
      panel.classList.toggle("active-graph", key === activeGraphTab);
    });
  });
  const copyBtn = document.querySelector(".crow.gsum .copy-chart-btn");
  if (copyBtn) copyBtn.dataset.canvas = canvasMap[activeGraphTab] || "cdfCanvas";
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
/* ── R-026: 실용적 유의성 게이트 ─────────────────────────────────────────
   판정(Grubbs)은 "통계적으로 튀는가"만 본다. 산포가 극히 작은 항목에서는 스펙폭의
   0.01% 밖에 안 움직인 샘플도 z-score 가 커져 SELECT 가 된다. 여기서는 그런 건들을
   화면에서만 접는다 — 서버의 result 필드도 골든 스냅샷도 바뀌지 않는다.

   행 단위 비율은 여기서 계산하고(상세 표), 항목 단위 집계는 서버가 payload.shift_gate 로
   내려준다(항목 표·요약). 항목 표는 첫 화면에 전 항목을 그려야 하는데 상세는 /item 으로
   지연 로딩돼서, 프런트가 항목 판정을 하려면 항목 수만큼 왕복해야 하기 때문이다.
   상세 행의 pre/post 와 항목의 LL/UL 은 반올림 없이 float64 원본이 오므로 서버 집계와
   여기 계산이 비트 단위로 일치한다. */
let detailBasis = "shift";   // pass 모드: "shift" = 스펙 대비(기본) | "sigma" = 산포(기존 Grubbs)
/* R-032: fail 모드 기준. "no-tail" = Marginal(Tail) 제외(기본) | "all" = 전체.
   Tail 은 규격은 벗어났지만 이탈량이 1% 미만이고 Mea·Diff 가 함께 임계를 넘지도 않은 건 —
   신뢰성 시험 후 모집단이 열화로 통째로 밀리면서 원래 경계에 있던 유닛이 딸려 넘어간 경우가
   여기 모인다. 혼자 유독 많이 움직여서 넘어간 것(Excessive/Slight)과 구분해 접는다. */
let failBasis = "no-tail";
function failGateInfo(payload = analysis) {
  const info = payload?.fail_gate;
  return (info && info.items) ? info : null;
}
function failGateOn(payload = analysis) {
  if (failBasis !== "no-tail") return false;
  if ((payload?.analysis_mode || analysisMode) !== "fail") return false;
  return !!failGateInfo(payload);
}
function failKeptSamples(key, payload = analysis) {
  const entry = failGateInfo(payload)?.items?.[key];
  return entry ? (entry.kept || []).map(String) : null;
}
function failItemFolded(key, payload = analysis) {
  const kept = failKeptSamples(key, payload);
  return kept !== null && kept.length === 0;
}
function failMarginalType(payload = analysis) {
  return failGateInfo(payload)?.excluded_type || "Tail";
}
function shiftGateInfo(payload = analysis) {
  const info = payload?.shift_gate;
  return (info && info.items) ? info : null;
}
function shiftGateTau(payload = analysis) {
  const tau = Number(shiftGateInfo(payload)?.tau);
  return Number.isFinite(tau) && tau > 0 ? tau : 0.05;
}
// Fail 탭에는 적용하지 않는다 — 이미 규격을 벗어난 유닛이라 "스펙 대비 미미"가 성립 안 함.
// 게이트 정보가 없는 payload(구 캐시 등)도 비활성 = 아무것도 접지 않는다.
function shiftGateOn(payload = analysis) {
  if (detailBasis !== "shift") return false;
  if ((payload?.analysis_mode || analysisMode) === "fail") return false;
  return !!shiftGateInfo(payload);
}
function specWidthOf(itemData) {
  const ll = Number(itemData?.lower_limit);
  const ul = Number(itemData?.upper_limit);
  if (!Number.isFinite(ll) || !Number.isFinite(ul)) return null;
  const width = Math.abs(ul - ll);
  return width || null;
}
function shiftSpecRatio(row, itemData) {
  const width = specWidthOf(itemData);
  if (width === null) return null;
  const pre = Number(row?.pre_value);
  const post = Number(row?.post_value);
  if (!Number.isFinite(pre) || !Number.isFinite(post)) return null;
  return Math.abs(post - pre) / width;
}
/* R-029: SELECT 를 만든 축의 "스펙 대비 크기". 서버 spec_relative_size() 와 같은 식이다.
   Mea 축 → |값-평균|/스펙폭,  Delta 축 → |Post-Pre|/스펙폭, 둘 다면 큰 쪽.
   Mea 축은 |값-평균|/스펙폭 = z/(6·Cp) 이므로 tau 하나가 Cp 비례 가중 임계가 된다. */
function specRelativeSize(row, itemData, resultRow) {
  const width = specWidthOf(itemData);
  if (width === null) return null;
  const sizes = [];
  const meaS = Number(row?.mea_s);
  const meaTh = Number(resultRow?.mea_threshold ?? itemData?.mea_threshold);
  const mean = Number(resultRow?.post_mean);
  const post = Number(row?.post_value);
  if (Number.isFinite(meaS) && Number.isFinite(meaTh) && meaTh > 0 && Math.abs(meaS) > meaTh
      && Number.isFinite(mean) && Number.isFinite(post)) {
    sizes.push(Math.abs(post - mean) / width);
  }
  const diffS = Number(row?.diff_s);
  const diffTh = Number(resultRow?.diff_threshold ?? itemData?.diff_threshold);
  if (Number.isFinite(diffS) && Number.isFinite(diffTh) && diffTh > 0 && Math.abs(diffS) > diffTh) {
    const ratio = shiftSpecRatio(row, itemData);
    if (ratio !== null) sizes.push(ratio);
  }
  const finite = sizes.filter(Number.isFinite);
  return finite.length ? Math.max(...finite) : null;
}
function detailRowFolded(row, itemData, resultRow) {
  const size = specRelativeSize(row, itemData, resultRow);
  return size !== null && size < shiftGateTau();
}
function itemGateCounts(key, payload = analysis) {
  return shiftGateInfo(payload)?.items?.[key] || null;
}
function itemFoldedByGate(key, payload = analysis) {
  const counts = itemGateCounts(key, payload);
  return !!counts && !counts.kept;
}
function gateTotals(payload = analysis) {
  // 현재 필터·기준 상태에서 화면이 말해야 할 "항목 / 샘플" 수 (R-027 요약 병기용).
  const rows = (payload?.selected_summary || []).filter(row => rowMatchesPayloadFilters(row, payload));
  const on = shiftGateOn(payload);
  let items = 0, samples = 0, foldedItems = 0, foldedSamples = 0;
  rows.forEach(row => {
    const key = itemKey(row);
    const counts = itemGateCounts(key, payload);
    const total = Number(row.qty) || 0;
    if (on && counts) {
      if (counts.kept) { items += 1; samples += counts.kept; }
      else foldedItems += 1;
      foldedSamples += counts.folded || 0;
    } else {
      items += 1;
      samples += total;
    }
  });
  return { items, samples, foldedItems, foldedSamples };
}
function renderShiftGateNote() {
  const node = document.getElementById("shiftGateNote");
  if (!node) return;
  updateBasisBars();
  if ((analysis?.analysis_mode || analysisMode) === "fail" && failBasis === "no-tail"
      && (analysis?.selected_summary || []).length && !failGateInfo()) {
    node.classList.remove("is-on");                       // R-034 안전망 (fail 쪽)
    node.textContent = "이 결과에는 기준 정보가 없습니다 — 다시 분석하세요 (옛 캐시)";
    return;
  }
  if (failGateOn()) {
    // R-032: fail 모드에서는 접힌 Marginal 건수를 표시한다.
    const info = failGateInfo();
    const folded = Object.values(info?.items || {}).reduce((sum, x) => sum + (x.folded || 0), 0);
    node.classList.toggle("is-on", !!folded);
    node.textContent = folded
      ? `Marginal ${folded}건 제외 (${failMarginalType()} — 이동량이 집단 범위 안)`
      : `Marginal 제외 없음`;
    return;
  }
  if (!shiftGateOn()) {
    // R-034 안전망: 게이트 정보가 없는 payload(옛 캐시 등)면 탭이 조용히 안 먹는다.
    // 왜 안 되는지 화면에 말해준다 — 이게 없어서 진단이 오래 걸렸다.
    const stale = detailBasis === "shift"
      && (analysis?.analysis_mode || analysisMode) !== "fail"
      && (analysis?.selected_summary || []).length
      && !shiftGateInfo();
    node.classList.remove("is-on");
    node.textContent = stale ? "이 결과에는 기준 정보가 없습니다 — 다시 분석하세요 (옛 캐시)" : "";
    return;
  }
  const { foldedItems, foldedSamples } = gateTotals();
  node.classList.add("is-on");
  const pct = (shiftGateTau() * 100).toFixed(shiftGateTau() < 0.01 ? 2 : 0);
  node.textContent = foldedSamples
    ? `스펙 대비 미미 ${foldedSamples}건 제외 (항목 ${foldedItems}개 · 스펙폭의 ${pct}% 미만)`
    : `스펙 대비 미미 제외 없음 (기준 ${pct}%)`;
}
function updateBasisBars() {
  // R-032: pass 모드는 "스펙 대비/산포", fail 모드는 "Marginal 제외/전체" — 성격이 달라 바를 나눈다.
  const isFail = (analysis?.analysis_mode || analysisMode) === "fail";
  const passBar = document.getElementById("detailBasisBar");
  const failBar = document.getElementById("failBasisBar");
  if (passBar) passBar.hidden = isFail;
  if (failBar) failBar.hidden = !isFail;
  document.querySelectorAll("#failBasisBar button").forEach(button => {
    button.classList.toggle("active", button.dataset.failBasis === failBasis);
  });
}
function setFailBasis(basis) {
  const next = basis === "all" ? "all" : "no-tail";
  if (next === failBasis) return;
  failBasis = next;
  updateBasisBars();
  ensureSelectedItemVisibleForActiveTab();
  renderSummary();
  renderDetailTable();
  drawCharts();
}
function setDetailBasis(basis) {
  const next = basis === "sigma" ? "sigma" : "shift";
  if (next === detailBasis) return;
  detailBasis = next;
  document.querySelectorAll("#detailBasisBar button").forEach(button => {
    button.classList.toggle("active", button.dataset.basis === detailBasis);
  });
  // 기준이 바뀌면 지금 보던 항목이 사라질 수 있다 — 목록에 남는 항목으로 옮긴다.
  ensureSelectedItemVisibleForActiveTab();
  renderSummary();
  renderDetailTable();
  drawCharts();
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
  return (analysis?.results || [])
    .filter(rowMatchesAnalysisFilters)
    // R-026 / R-032: 목록에서 뺀 항목이 자동 선택되지 않도록 같은 기준을 적용한다.
    .filter(row => !(shiftGateOn() && itemFoldedByGate(itemKey(row))))
    .filter(row => !(failGateOn() && failItemFolded(itemKey(row))));
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
/* R-030: 서버 CdfCompareApp.sample_sort_key 와 같은 규칙 — 숫자로 읽히면 숫자 우선,
   아니면 문자열. 두 탭이 같은 순서를 쓰게 하려고 프런트에서 맞춘다. */
function sampleSortKey(sample) {
  const text = String(sample ?? "").trim();
  const number = Number(text);
  return (text !== "" && Number.isFinite(number)) ? [0, number] : [1, text.toLowerCase()];
}
function compareSamples(a, b) {
  const ka = sampleSortKey(a), kb = sampleSortKey(b);
  if (ka[0] !== kb[0]) return ka[0] - kb[0];
  if (ka[1] < kb[1]) return -1;
  if (ka[1] > kb[1]) return 1;
  return 0;
}
/* R-038: 배지·칩·Q'ty 가 모두 "게이트 적용 후 고유 유닛 수" 를 쓴다.
   over_sigma 는 샘플당 한 행이라 행 수가 곧 유닛 수다 — Q'ty 합(항목x샘플 쌍)과 다르고,
   "총 - Select = No Select" 가 성립하려면 반드시 유닛 기준이어야 한다.
   payload 를 인자로 받는 이유: 칩이 지금 보는 탭이 아닌 쪽 숫자도 함께 그린다. */
function gateKeptSamples(itemKeyValue, payload = analysis) {
  const mode = payload?.analysis_mode || analysisMode;
  if (mode === "fail") return failKeptSamples(itemKeyValue, payload);
  const entry = shiftGateInfo(payload)?.items?.[itemKeyValue];
  return entry ? (entry.kept_samples || []).map(String) : null;
}
function gateOnFor(payload = analysis) {
  return ((payload?.analysis_mode || analysisMode) === "fail")
    ? failGateOn(payload) : shiftGateOn(payload);
}
function selectUnitRows(payload = analysis) {
  const rows = (payload?.over_sigma || []).filter(row => rowMatchesPayloadFilters(row, payload));
  if (!gateOnFor(payload)) return rows;
  return rows
    .map(row => ({
      ...row,
      items: (row.items || []).filter(item => {
        const kept = gateKeptSamples(item, payload);
        return kept === null || kept.includes(String(row.sample));
      }),
    }))
    .filter(row => row.items.length);
}
/* 온도가 여러 개 선택되면 같은 유닛이 Room·Hot 두 행으로 온다. Serial # 은 파일마다
   다시 매겨지므로(§3-3) join_key(DEVICE_ID)로 묶어야 유닛 수가 맞는다 (R-038). */
function unitIdOf(row, payload = analysis) {
  const map = payload?.unit_join_map || {};
  const key = `${row.reliability_item || ""}||${row.ft_temp || ""}||${row.sample}`;
  return map[key] || `${row.reliability_item || ""}||${row.ft_temp || ""}||${row.sample}`;
}
function selectUnitCount(payload = analysis) {
  const seen = new Set();
  selectUnitRows(payload).forEach(row => seen.add(unitIdOf(row, payload)));
  return seen.size;
}
function selectUnitCountByReliability(payload) {
  const seen = {};
  selectUnitRows(payload).forEach(row => {
    const key = row.reliability_item || "";
    (seen[key] = seen[key] || new Set()).add(unitIdOf(row, payload));
  });
  const counts = {};
  Object.keys(seen).forEach(key => { counts[key] = seen[key].size; });
  return counts;
}
function unitTotalsFor(reliabilityItem, payload = analysis) {
  // 분모. 총 샘플 수는 "시험이 된 총 수량" 이라 온도·리드아웃과 무관하다 (서버가 합집합으로 센다).
  const info = payload?.unit_counts;
  if (!info) return null;
  if (reliabilityItem) return (info.by_reliability || {})[reliabilityItem] || null;
  return info;
}
function overSigmaRowsRaw() {
  // R-030: Fail 모드는 서버가 sample 정렬을 하지 않는다 — analyze_fail_to_json 의 over_rows 가
  // over.items() 를 그대로 순회해서 항목 순회 순서가 그대로 나온다(pass 모드는 sample_sort_key
  // 로 정렬한다). over_sigma 는 골든 스냅샷 비교 대상이라 서버 순서를 바꾸면 회귀가 깨지므로
  // 표시 계층에서 정렬한다. pass 모드는 이미 같은 규칙이라 이 정렬이 멱등이다.
  // filter() 가 새 배열을 주므로 sort() 가 analysis.over_sigma 를 건드리지 않는다.
  return (analysis?.over_sigma || [])
    .filter(rowMatchesAnalysisFilters)
    .sort((a, b) => compareSamples(a.sample, b.sample));
}
function overSigmaRows() {
  // R-038: 두 모드를 같은 규칙으로 거른다. 예전에는 fail 만 걸러서, pass 에서 기준 탭을
  // 바꿔도 샘플 기준 표가 그대로였다 (shift_gate 에 kept 개수만 있어 어떤 샘플이 접혔는지
  // 알 수 없었기 때문 — 이제 kept_samples 가 온다).
  if (!gateOnFor()) return overSigmaRowsRaw();
  return selectUnitRows().sort((a, b) => compareSamples(a.sample, b.sample));
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
  document.querySelectorAll("#resultModeBar button").forEach(button => {
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
  const showOver = resultViewMode === "sample";
  if (resultWrap) resultWrap.style.display = showOver ? "none" : "";
  if (overWrap) overWrap.style.display = showOver ? "block" : "none";
  if (toggleWrap) toggleWrap.style.display = showOver ? "none" : "";
}
function setResultViewMode(view) {
  resultViewMode = view === "sample" ? "sample" : "item";
  updateResultTabButtons();
  updateResultTabVisibility();
  ensureSelectedItemVisibleForActiveTab();
  refreshSelectedItem();
}
function renderAnalysisFilterBar() {
  const bar = document.getElementById("analysisFilterBar");
  if (!bar) return;
  // 본창과 동일한 조건. 예전에는 새 창이면 무조건 그려서, 단일 항목만 분석해도
  // HAST·uHAST·TC 처럼 데이터 없는 빈 탭이 줄줄이 뜨고 그만큼 여백도 남았다.
  if (!analysis || !analysis.total_analysis) {
    bar.classList.remove("active");
    bar.innerHTML = "";
    return;
  }
  bar.classList.add("active");
  bar.innerHTML = "";
  const reliabilityRow = document.createElement("div");
  reliabilityRow.className = "crow tabs";
  const secondaryRow = document.createElement("div");
  secondaryRow.className = "crow foot";
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
  /* R-039: 칩은 "Select 수 / 총 수량" 이다. 두 숫자 모두 유닛(샘플) 기준이고,
     Select 는 기준 탭(게이트)을 따른다. 배지와 같은 규칙으로 탭마다 값이 바뀐다 —
     Fail 항목 탭이면 Fail Select 수 / 시험 투입 총 수량,
     Abnormal Pass 탭이면 Abnormal Pass Select 수 / Total Pass 샘플 수.
     (칩 합계가 배지 숫자와 맞아야 하므로 분모도 탭을 따른다.) */
  const selectUnits = selectUnitCountByReliability(analysis);
  const unitTotals = (analysis?.unit_counts?.by_reliability) || {};
  const hasUnitInfo = !!analysis?.unit_counts?.by_reliability;
  const itemCounts = {};
  (analysis?.item_counts || []).forEach(entry => { itemCounts[entry.reliability_item] = entry; });
  const makeItemTab = (value, label, count) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "item-tab";
    button.dataset.item = value;
    const isEmpty = hasUnitInfo
      ? !((analysisMode === "fail" ? unitTotals[value]?.total : unitTotals[value]?.pass) || 0)
      : (count && count.total === 0);
    button.classList.toggle("item-tab-empty", !!isEmpty);
    if (isEmpty) button.disabled = true;
    button.classList.toggle("active", (analysisFilters.reliability_item || "") === value);
    const labelSpan = document.createElement("span");
    labelSpan.className = "item-tab-label";
    labelSpan.textContent = label;
    button.appendChild(labelSpan);
    if (hasUnitInfo) {
      // 데이터가 없는 항목도 같은 모양(0 / 0)으로 그린다 — 표기가 섞이면 읽기 어렵다.
      const unitTotal = unitTotals[value] || { total: 0, pass: 0 };
      const denom = (analysisMode === "fail" ? unitTotal.total : unitTotal.pass) || 0;
      const selectN = selectUnits[value] || 0;
      const badge = document.createElement("span");
      badge.className = "item-tab-badge";
      badge.textContent = `${selectN} / ${denom}`;
      badge.title = analysisMode === "fail"
        ? `Fail Select ${selectN}대 / 총 샘플 ${denom}대`
        : `Abnormal Pass Select ${selectN}대 / 총 샘플(양품) ${denom}대`;
      button.appendChild(badge);
    } else if (count) {
      const badge = document.createElement("span");
      badge.className = "item-tab-badge";
      badge.textContent = `${count.select}/${count.total}`;
      badge.title = "이 결과에는 샘플 수 정보가 없습니다 — 다시 분석하세요 (옛 캐시)";
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
  const reliabilityOptions = analysis?.total_analysis ? reliabilityItems : (analysis.total_reliability_items?.length ? analysis.total_reliability_items : reliabilityItems);
  // 「전체」 탭을 없앴으므로, 선택이 비었거나 0건 항목이면 건수가 있는 첫 항목으로 이동
  const hasData = it => (hasUnitInfo
    ? ((analysisMode === "fail" ? unitTotals[it]?.total : unitTotals[it]?.pass) || 0)
    : (itemCounts[it]?.total || 0)) > 0;
  const firstWithData = reliabilityOptions.find(hasData);
  const cur = analysisFilters.reliability_item || "";
  if (!cur || !hasData(cur)) {
    analysisFilters.reliability_item = firstWithData || reliabilityOptions[0] || "";
  }
  reliabilityOptions.forEach(item => reliabilityGroup.appendChild(makeItemTab(item, item, itemCounts[item] || null)));
  const reliabilityTabwrap = document.createElement("div");
  reliabilityTabwrap.className = "tabwrap";
  reliabilityTabwrap.appendChild(reliabilityGroup);
  reliabilityRow.appendChild(reliabilityTabwrap);
  bar.appendChild(reliabilityRow);

  const tempGroup = document.createElement("div");
  tempGroup.className = "filter-group temp-filter-group";
  tempGroup.innerHTML = "<span class=\"lbl\">FT TEMP.</span>";
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
  bar.appendChild(secondaryRow);
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
  // Wafer Map 은 탭이 아니라 그래프 아래에 상시 표시한다
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
  const tabsRow = document.createElement("div");
  tabsRow.className = "crow tabs";
  const graphTabs = document.createElement("div");
  graphTabs.className = "graph-tabs";
  graphTabs.setAttribute("role", "tablist");
  graphTabs.setAttribute("aria-label", "Graph Type");
  graphTabOptions().forEach(([key, label]) => graphTabs.appendChild(makeGraphTabButton(key, label)));
  const graphTabwrap = document.createElement("div");
  graphTabwrap.className = "tabwrap";
  graphTabwrap.appendChild(graphTabs);
  tabsRow.appendChild(graphTabwrap);
  bar.appendChild(tabsRow);

  const footRow = document.createElement("div");
  footRow.className = "crow foot";
  const readoutGroup = document.createElement("div");
  readoutGroup.className = "graph-filter-group";
  readoutGroup.innerHTML = "<strong>Read-out</strong>";
  [["pre_t0", "T0"], ["post_t1", "T1"], ["post_t2", "T2"], ["post_t3", "T3"]].forEach(([key, label]) => {
    readoutGroup.appendChild(makeGraphCheckbox(label, analysisFilters.readouts[key] !== false, checked => {
      analysisFilters.readouts[key] = checked;
      drawCharts();
    }));
  });
  footRow.appendChild(readoutGroup);
  const graphGroup = document.createElement("div");
  graphGroup.className = "graph-filter-group graph-option-group";
  graphGroup.innerHTML = "<strong>Graph</strong>";
  graphGroup.appendChild(makeGraphCheckbox("Fail 항목 제외", analysisFilters.fail_exception, async checked => {
    analysisFilters.fail_exception = checked;
    drawCharts();
  }));
  footRow.appendChild(graphGroup);
  bar.appendChild(footRow);
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
  sortState = { column: "qty", reverse: true };
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
  sortState = { column: "qty", reverse: true };
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
  clearAnalyzeError();
  // 텍스트 입력의 change 는 blur 시점에 늦게 발생한다. Analyze 버튼 클릭이 그 blur 를
  // 유발하면 lookupState 가 비워진 채 payload 가 만들어진다 — 먼저 확정시킨다.
  document.getElementById("deviceInput")?.blur();
  await new Promise(r => setTimeout(r, 0));
  if (pendingLookup) { try { await pendingLookup; } catch (_) {} }
  // 화면의 select 값을 정본으로 삼아 lookupState 를 재동기화
  const deviceEl = document.getElementById("deviceInput");
  if (deviceEl && deviceEl.value.trim()) lookupState.device = deviceEl.value.trim();
  lookupOrder.forEach(([key, selectId]) => {
    const el = document.getElementById(selectId);
    if (el && el.value) lookupState[key] = el.value;
  });
  const stopBtn = document.getElementById("stopAnalyzeBtn");
  const displayMode = analysisMode;
  activeAnalysisRunId = createAnalysisRunId();
  // 결과 새 창은 사용자가 "결과 새 창" 버튼을 눌렀을 때만 띄운다.
  // 예전에는 Analyze 를 누르면 매번 자동으로 팝업이 떠서 방해가 됐다.
  // (버튼은 분석 결과가 준비되면 활성화된다 — setResultPanelsVisible 참조)
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
      const sel = normalizedAnalysisSelection();
      const missing = ["device", "ver", "purpose", "lot"].filter(k => !(sel[k] || "").trim());
      showAnalyzeError(err.message || "Analyze failed.", missing);
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
  document.querySelectorAll("#resultModeBar button").forEach(button => {
    button.addEventListener("click", () => setAnalysisMode(button.dataset.mode));
  });
  document.querySelectorAll("#resultViewBar button").forEach(button => {
    button.addEventListener("click", () => setResultViewMode(button.dataset.view));
  });
  document.querySelectorAll("#detailBasisBar button").forEach(button => {
    button.addEventListener("click", () => setDetailBasis(button.dataset.basis));   // R-026
  });
  document.querySelectorAll("#failBasisBar button").forEach(button => {
    button.addEventListener("click", () => setFailBasis(button.dataset.failBasis));  // R-032
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
  wireColumnToggleMenu("detailColumnToggleBtn", "detailColumnToggleMenu");   // R-023
  const columnToggleBtn = document.getElementById("columnToggleBtn");
  const columnToggleMenu = document.getElementById("columnToggleMenu");
  if (columnToggleBtn && columnToggleMenu) {
    // .panel 은 overflow:hidden 이라 absolute 메뉴가 잘린다. body 로 옮기고
    // position:fixed 로 버튼 기준 좌표를 계산해 배치한다.
    document.body.appendChild(columnToggleMenu);
    const positionColumnMenu = () => {
      const btnRect = columnToggleBtn.getBoundingClientRect();
      const menuRect = columnToggleMenu.getBoundingClientRect();
      let left = btnRect.right - menuRect.width;
      let top = btnRect.bottom + 6;
      left = Math.max(8, Math.min(left, window.innerWidth - menuRect.width - 8));
      if (top + menuRect.height > window.innerHeight - 8) {
        top = Math.max(8, btnRect.top - menuRect.height - 6);
      }
      columnToggleMenu.style.left = `${Math.round(left)}px`;
      columnToggleMenu.style.top = `${Math.round(top)}px`;
    };
    const closeColumnMenu = () => columnToggleMenu.classList.remove("open");
    columnToggleBtn.addEventListener("click", event => {
      event.stopPropagation();
      if (columnToggleMenu.classList.contains("open")) {
        closeColumnMenu();
      } else {
        columnToggleMenu.classList.add("open");
        positionColumnMenu();
      }
    });
    document.addEventListener("click", event => {
      if (!columnToggleMenu.classList.contains("open")) return;
      if (columnToggleMenu.contains(event.target) || event.target === columnToggleBtn) return;
      closeColumnMenu();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && columnToggleMenu.classList.contains("open")) closeColumnMenu();
    });
    window.addEventListener("resize", () => {
      if (columnToggleMenu.classList.contains("open")) positionColumnMenu();
    });
    window.addEventListener("scroll", () => {
      if (columnToggleMenu.classList.contains("open")) positionColumnMenu();
    }, true);
  }
}

function bindParentControls() {
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
  if (!rdaView) return;
  rdaView.classList.toggle("condition-collapsed", collapsed);
  const toggle = document.getElementById("conditionSecBtn");
  if (toggle) toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
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
  document.getElementById("conditionSecBtn")?.addEventListener("click", () => {
    const view = document.getElementById("rdaView");
    const next = !view.classList.contains("condition-collapsed");
    setConditionCollapsed(next);
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
  renderShiftGateNote();   // R-035: 기준 바·노트가 결과 패널로 올라왔다 — 요약을 그릴 때도 갱신한다.
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
  let itemCount = Array.isArray(payload.selected_summary) ? payload.selected_summary.length : null;
  let detailCount = payload.select_count;
  if (failGateOn(payload)) {
    // R-032: 화면이 접은 만큼 배지도 같이 줄인다(R-027 과 같은 원칙 — 화면은 한 기준으로 말한다).
    const entries = Object.values(failGateInfo(payload)?.items || {});
    itemCount = entries.filter(x => (x.kept || []).length).length;
    detailCount = entries.reduce((sum, x) => sum + (x.kept || []).length, 0);
  }
  return {
    items: Number.isFinite(itemCount) ? itemCount : null,
    details: Number.isFinite(detailCount) ? detailCount : null,
  };
}
function passSelectCount() {
  // R-027: 지금까지 항목 수만 셌다. 이상 샘플이 몇 건인지가 화면 어디에도 없어서 함께 낸다.
  // 샘플 수는 sum(selected_summary[].qty) 로 구한다 — 서버 payload 변경 없이 SELECT 상세
  // 쌍 수와 정확히 일치함을 실측 확인(138항목 / 158샘플). R-026 기준 탭 상태도 함께 반영된다.
  const payload = modePayloads.pass;
  if (!payload) return null;
  const totals = gateTotals(payload);
  const fallback = payload?.summary_counts?.select;
  if (!(payload.selected_summary || []).length && Number.isFinite(fallback)) {
    return { items: fallback, samples: null };
  }
  return { items: totals.items, samples: totals.samples };
}
function formatItemsSamples(counts) {
  if (!counts) return null;
  if (!Number.isFinite(counts.samples)) return `${counts.items}`;
  return `${counts.items} 항목 / ${counts.samples} 샘플`;
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
  const failBtn = document.getElementById("failModeBtn");
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
  const passCount = passSelectCount();
  // 배지는 좁아서 항목 수만 띄우고, 샘플 수는 마우스오버로 병기한다 (R-027).
  setTabBadge(
    document.getElementById("passModeBtn"),
    passCount ? passCount.items : null,
    passCount ? `이상 데이터 식별 ${formatItemsSamples(passCount)}` : "",
  );
  if (!strip) return;
  strip.innerHTML = "";
  /* R-038: 배지를 유닛(샘플) 기준 3장으로 통일한다 — 총 / Select / No Select.
     라벨이 위, 숫자가 아래다. 분모가 탭마다 다른 이유:
       Fail 탭        총 샘플 수      = 그 시험에 투입된 총 수량
       Abnormal Pass  총 샘플 수      = 그중 양품 수 (이상 이동 판정은 양품만 본다)
     Eden 님 확인 2026-09-05. Select 는 기준 탭(게이트) 적용 후 고유 유닛 수라,
     "총 - Select = No Select" 가 항상 맞아떨어진다. */
  const isFailMode = analysisMode === "fail";
  const totals = unitTotalsFor(analysisFilters.reliability_item || "");
  if (!totals) {
    // 옛 캐시 등 unit_counts 가 없는 payload — 조용히 0을 그리지 말고 이유를 말한다.
    const warn = document.createElement("div");
    warn.className = "summary-card summary-card-warn";
    warn.textContent = "이 결과에는 샘플 수 정보가 없습니다 — 다시 분석하세요 (옛 캐시)";
    strip.appendChild(warn);
    const footnoteEl = document.createElement("div");
    footnoteEl.id = "judgmentFootnote";
    footnoteEl.className = "judgment-footnote";
    strip.appendChild(footnoteEl);
    renderJudgmentFootnote();
    return;
  }
  const totalUnits = isFailMode ? (totals.total || 0) : (totals.pass || 0);
  const selectUnits = selectUnitCount();
  const cards = [
    { label: "총 샘플 수", value: totalUnits },
    { label: isFailMode ? "Fail Select 샘플 수" : "Abnormal Pass Select 샘플 수",
      value: selectUnits, cls: "flag" },
    { label: isFailMode ? "No Fail Select 샘플 수" : "No Abnormal Pass Select 샘플 수",
      value: Math.max(totalUnits - selectUnits, 0), cls: "ok" },
  ];
  cards.forEach(card => {
    const div = document.createElement("div");
    div.className = `summary-card${card.cls ? " summary-card-" + card.cls : ""}`;
    const labelEl = document.createElement("div");
    labelEl.className = "summary-card-label";
    labelEl.textContent = card.label;
    const valueEl = document.createElement("div");
    valueEl.className = "summary-card-value";
    valueEl.textContent = `${card.value}`;
    div.appendChild(labelEl);
    div.appendChild(valueEl);
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
  const el = document.getElementById("graphItemMeta");
  if (!el) return;
  const data = itemCache[selectedItem] || analysis?.items?.[selectedItem] || {};
  const mea = Number(data.mea_threshold);
  const diff = Number(data.diff_threshold);
  const parts = [];
  if (Number.isFinite(mea)) parts.push(`Mea threshold=${mea.toFixed(4)}`);
  if (Number.isFinite(diff)) parts.push(`Diff threshold=${diff.toFixed(4)}`);
  el.textContent = parts.join("  /  ");
  renderGraphExcludeNote();
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

    // 상세 표를 미리 그리지 않는다.
    // 예전에는 데이터가 오기 전에 한 번 그려서 헤더 + "Loading..." 한 줄로 표가
    // 접혔다가, 로드가 끝나면 다시 펼쳐졌다. 그 사이 패널 높이가 요동쳐서
    // 항목을 처음 고를 때마다 깜빡이는 것처럼 보였다(실측 173 → 70 → 173px).
    //   - 이미 캐시에 있으면 즉시 그린다 (서버 왕복이 없어 깜빡일 일이 없다)
    //   - 표가 아직 비어 있으면 그려준다 (접힐 내용이 없으므로 안전하고,
    //     첫 분석 직후 빈 패널만 보이는 것을 막는다)
    //   - 그 외에는 직전 내용을 그대로 두고 제목 옆에만 로딩 표시를 띄운다
    const detailCached = !!itemCache[selectedItem];
    const detailHasRows = !!document.querySelector("#detailTable tbody tr");
    if (detailCached || !detailHasRows) renderDetailTable();
    else setDetailLoading(true);

    try {
      await loadItem(selectedItem);
      await loadRelatedGraphItems();
    } finally {
      setDetailLoading(false);
    }
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
function gateQty(row, payload = analysis) {
  // R-038: Q'ty 도 기준 탭을 따른다. 게이트가 꺼져 있거나 이 항목의 게이트 정보가
  // 없으면 서버 값(row.qty)을 그대로 쓴다.
  if (!gateOnFor(payload)) return null;
  const kept = gateKeptSamples(itemKey(row), payload);
  return kept === null ? null : kept.length;
}
function summaryCellValue(row, key, payload = analysis) {
  const data = (payload?.items || itemCache)[itemKey(row)] || {};
  if (key === "qty") {
    const kept = gateQty(row, payload);
    return kept === null ? row.qty : kept;
  }
  if (key === "qty_ratio") {
    // §S5: null(정의 불가, n_pass=0)을 Number()로 강제 변환하면 0 이 되어 "0.0%"로
    // 새어나간다 -- null 은 계산 전에 걸러 N/A(fmtCell)로 떨어지게 한다.
    if (row.qty_ratio === null || row.qty_ratio === undefined) return null;
    let ratio = Number(row.qty_ratio);
    // R-038: Q'ty 가 게이트로 줄면 비율도 같은 분모(n_pass)로 다시 낸다.
    const kept = gateQty(row, payload);
    if (kept !== null && Number(row.qty) > 0) ratio = ratio * (kept / Number(row.qty));
    return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}%` : "";
  }
  if (key === "diff_mean") {
    if (row.diff_mean === null || row.diff_mean === undefined) return null;
    const ratio = Number(row.diff_mean);
    return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(2)}%` : "";
  }
  // Fail 행에는 reason 이 없다 -- 같은 성격의 fail_type(이탈 유형)으로 대체한다.
  if (key === "reason") return row.reason || row.fail_type || "";
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
  const rows = [...(payload?.selected_summary || [])]
    .filter(row => rowMatchesPayloadFilters(row, payload))
    // R-026: SELECT 샘플이 모두 게이트에 걸린 항목만 뺀다. 하나라도 남으면 목록에 둔다.
    .filter(row => !(shiftGateOn(payload) && itemFoldedByGate(itemKey(row), payload)))
    // R-032: fail 상세가 전부 Marginal 인 항목을 뺀다. 같은 규칙(하나라도 남으면 유지).
    .filter(row => !(failGateOn(payload) && failItemFolded(itemKey(row), payload)));
  if (sortState.column) {
    rows.sort((a, b) => compareSummaryValues(a, b, sortState.column, payload) * (sortState.reverse ? -1 : 1));
  }
  return rows;
}
function sortedDetails(details) {
  const mode = analysis?.analysis_mode || analysisMode;
  let rows = mode === "fail" ? details.filter(d => d.fail_type) : details.filter(d => d.result === "SELECT");
  if (failGateOn()) {
    // 행마다 fail_type 이 있으므로 서버 집계 없이 바로 거른다. (R-032)
    const marginal = failMarginalType();
    rows = rows.filter(row => row.fail_type !== marginal);
  }
  if (shiftGateOn()) {
    // LL/UL 은 항목 payload 에, 평균·임계값은 결과 행에 있다 (pass 모드 상세 행에는 없다).
    const itemData = itemCache[selectedItem];
    const resultRow = selectedResultRow() || {};
    rows = rows.filter(row => !detailRowFolded(row, itemData, resultRow));
  }
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
  // 새 창도 본창과 동일하게 현재 모드(Fail / Abnormal Pass)의 목록을 그린다.
  // 예전에는 새 창이 항상 Fail 목록만 그려서, 같은 분석인데 표 내용이 달랐다.
  const table = document.getElementById("resultTable");
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
  const defaultCols = resultMode === "fail" ? DEFAULT_VISIBLE_COLUMNS_FAIL : DEFAULT_VISIBLE_COLUMNS_PASS;
  const visible = columnVisibility[resultMode] || new Set(defaultCols);
  menu.innerHTML = "";

  const head = document.createElement("div");
  head.className = "column-menu-head";
  const selectAllItem = document.createElement("label");
  selectAllItem.className = "column-toggle-item";
  const selectAllBox = document.createElement("input");
  selectAllBox.type = "checkbox";
  const updateSelectAllState = () => {
    const total = allCols.length;
    const checkedCount = allCols.filter(([key]) => visible.has(key)).length;
    selectAllBox.checked = total > 0 && checkedCount === total;
    selectAllBox.indeterminate = checkedCount > 0 && checkedCount < total;
  };
  selectAllBox.addEventListener("change", () => {
    if (selectAllBox.checked) allCols.forEach(([key]) => visible.add(key));
    else allCols.forEach(([key]) => visible.delete(key));
    renderResultTable();
    renderOverTable();
  });
  selectAllItem.appendChild(selectAllBox);
  selectAllItem.appendChild(document.createTextNode("전체 선택"));
  head.appendChild(selectAllItem);

  const resetBtn = document.createElement("button");
  resetBtn.type = "button";
  resetBtn.className = "column-menu-reset";
  resetBtn.textContent = "기본값으로";
  resetBtn.addEventListener("click", () => {
    visible.clear();
    defaultCols.forEach(key => visible.add(key));
    renderResultTable();
    renderOverTable();
  });
  head.appendChild(resetBtn);
  menu.appendChild(head);

  const body = document.createElement("div");
  body.className = "column-menu-body";
  allCols.forEach(([key, label]) => {
    const item = document.createElement("label");
    item.className = "column-toggle-item";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = visible.has(key);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) visible.add(key); else visible.delete(key);
      updateSelectAllState();
      renderResultTable();
      renderOverTable();
    });
    item.appendChild(checkbox);
    item.appendChild(document.createTextNode(label));
    body.appendChild(item);
  });
  menu.appendChild(body);
  updateSelectAllState();
}
/* ── R-021: Pre / Post 비교 새 창 ───────────────────────────────
   항목 기준 표에서 뺀 Stdev./Min./Max. 와, 목록에 아예 없던 Pre 쪽 분포를
   한 화면에서 대조한다. 계산은 툴 본체와 같은 ddof=1 표본표준편차다. */
function prePostSeriesStats(values) {
  const nums = [];
  (values || []).forEach(v => { const n = Number(v); if (Number.isFinite(n)) nums.push(n); });
  if (!nums.length) return null;
  const n = nums.length;
  const mean = nums.reduce((a, c) => a + c, 0) / n;
  const sigma = n > 1
    ? Math.sqrt(nums.reduce((a, c) => a + (c - mean) * (c - mean), 0) / (n - 1))
    : null;
  let min = nums[0], max = nums[0];
  for (const v of nums) { if (v < min) min = v; if (v > max) max = v; }
  return { n, mean, sigma, min, max };
}
function prePostEscape(text) {
  return String(text ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function prePostCell(value, digits) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return digits === undefined ? fmt(value) : Number(value).toFixed(digits);
}
function openPrePostCompareWindow(itemName) {
  const data = itemCache[itemName];
  if (!data) { alert("항목 데이터를 먼저 불러온 뒤 다시 시도하세요."); return; }
  const rows = analysis?.selected_summary || analysis?.results || [];
  const summary = rows.find(r => itemKey(r) === itemName) || {};
  const unit = summary.unit || data.unit || "";
  const ll = summary.lower_limit ?? data.lower_limit;
  const ul = summary.upper_limit ?? data.upper_limit;
  const span = (Number.isFinite(Number(ll)) && Number.isFinite(Number(ul))) ? Number(ul) - Number(ll) : null;

  const series = [];
  const pre = prePostSeriesStats(data.pre_values);
  if (pre) series.push({ label: "Pre", stats: pre, diffMean: null });
  (data.post_readout_values || []).forEach(entry => {
    const stats = prePostSeriesStats(entry?.values);
    if (stats) series.push({ label: entry.label || entry.key, stats, diffMean: entry?.stats?.diff_mean ?? null });
  });
  if (series.length <= (pre ? 1 : 0)) {
    const post = prePostSeriesStats(data.post_values);
    if (post) series.push({ label: "Post", stats: post, diffMean: summary.diff_mean ?? null });
  }

  const distRows = series.map(s => {
    const shift = pre && s.label !== "Pre" ? s.stats.mean - pre.mean : null;
    return `<tr${s.label === "Pre" ? ' class="pre"' : ""}>
      <td class="k">${prePostEscape(s.label)}</td>
      <td>${s.stats.n}</td>
      <td>${prePostCell(s.stats.mean)}</td>
      <td>${prePostCell(s.stats.sigma)}</td>
      <td>${prePostCell(s.stats.min)}</td>
      <td>${prePostCell(s.stats.max)}</td>
      <td>${shift === null ? "—" : (shift > 0 ? "+" : "") + prePostCell(shift)}</td>
      <td>${s.diffMean === null || s.diffMean === undefined ? "—"
            : (Number(s.diffMean) > 0 ? "+" : "") + (Number(s.diffMean) * 100).toFixed(2) + "%"}</td>
    </tr>`;
  }).join("");

  const marginRows = series.map(s => {
    const low = Number.isFinite(Number(ll)) ? s.stats.min - Number(ll) : null;
    const high = Number.isFinite(Number(ul)) ? Number(ul) - s.stats.max : null;
    return `<tr${s.label === "Pre" ? ' class="pre"' : ""}>
      <td class="k">${prePostEscape(s.label)}</td>
      <td>${prePostCell(low)}</td>
      <td>${prePostCell(high)}</td>
      <td>${span && low !== null ? (low / span * 100).toFixed(1) + "%" : "—"}</td>
      <td>${span && high !== null ? (high / span * 100).toFixed(1) + "%" : "—"}</td>
    </tr>`;
  }).join("");

  const cond = document.getElementById("conditionSummaryLine")?.textContent?.trim() || "";
  const mea = Number(data.mea_threshold), diff = Number(data.diff_threshold);
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>Pre / Post 비교 — ${prePostEscape(itemName)}</title><style>
 body{font:13px "Segoe UI","맑은 고딕",sans-serif;color:#1b2430;margin:0;padding:22px;background:#f7f9fc}
 h1{font-size:19px;margin:0 0 4px}
 .sub{color:#5a6b7b;font-size:12px;margin-bottom:16px}
 .card{background:#fff;border:1px solid #d8e0e8;border-radius:8px;padding:14px 16px;margin-bottom:14px}
 .card h2{font-size:13px;margin:0 0 10px;color:#065a82;letter-spacing:.3px}
 table{border-collapse:collapse;width:100%}
 th,td{border:1px solid #e3e9ef;padding:6px 10px;text-align:right;white-space:nowrap}
 th{background:#1f3864;color:#fff;font-weight:600;text-align:center}
 td.k{text-align:left;font-weight:600;color:#21295c}
 tr.pre td{background:#f3f7fa}
 .spec span{display:inline-block;margin-right:22px}
 .spec b{color:#065a82}
 .foot{color:#5a6b7b;font-size:11.5px;margin-top:2px}
</style></head><body>
<h1>${prePostEscape(itemName)}${summary.test_number ? ` <span style="color:#5a6b7b;font-weight:400">· Test No. ${prePostEscape(summary.test_number)}</span>` : ""}</h1>
<div class="sub">${prePostEscape(cond)}</div>
<div class="card spec"><h2>규격</h2>
  <span>LL <b>${prePostCell(ll)}</b></span><span>UL <b>${prePostCell(ul)}</b></span>
  <span>스펙폭 <b>${prePostCell(span)}</b></span><span>단위 <b>${prePostEscape(unit) || "—"}</b></span></div>
<div class="card"><h2>분포 비교</h2>
  <table><thead><tr><th>구분</th><th>N</th><th>평균</th><th>표준편차</th><th>Min.</th><th>Max.</th><th>Δ 평균</th><th>Δ %</th></tr></thead>
  <tbody>${distRows}</tbody></table>
  <div class="foot">표준편차는 표본표준편차(ddof = 1) — 판정에 쓰이는 σ 와 같은 값입니다. (항목 기준 표의 Stdev. 는 ddof = 0 이라 미세하게 다릅니다 — R-024)</div></div>
<div class="card"><h2>규격 여유</h2>
  <table><thead><tr><th>구분</th><th>하한까지 (Min − LL)</th><th>상한까지 (UL − Max)</th><th>하한 여유 %</th><th>상한 여유 %</th></tr></thead>
  <tbody>${marginRows}</tbody></table>
  <div class="foot">여유 % 는 스펙폭 대비 비율입니다. 값이 음수면 그 방향으로 규격을 벗어난 유닛이 있다는 뜻입니다.</div></div>
<div class="card"><h2>판정 기준</h2>
  <div>Grubbs 검정 · alpha ${prePostEscape(analysis?.flag_alpha ?? 0.01)} · 표본표준편차(ddof = 1)</div>
  <div class="foot">Mea 임계 ${Number.isFinite(mea) ? mea.toFixed(4) : "—"} / Delta 임계 ${Number.isFinite(diff) ? diff.toFixed(4) : "—"} — 임계값은 표본 수 n 에 따라 항목마다 다릅니다.</div></div>
</body></html>`;

  const win = window.open("", "prePostCompareWindow", "width=980,height=760,resizable=yes,scrollbars=yes");
  if (!win) { alert("새 창이 브라우저에서 차단됐습니다."); return; }
  win.document.open(); win.document.write(html); win.document.close(); win.focus();
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
    th.textContent = label + (sortState.column === key ? (sortState.reverse ? " ▼" : " ▲") : "");
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
    // 목록에서 뺀 Stdev./Min./Max. 와 Pre 쪽 분포는 여기서 본다. (R-021)
    tr.title = "더블클릭하면 Pre / Post 비교 표가 새 창으로 열립니다";
    tr.ondblclick = async () => {
      if (!activatePayloadMode(mode, key)) return;
      selectedItem = key;
      await refreshSelectedItem();
      openPrePostCompareWindow(key);
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
  renderOverSampleTable(document.getElementById("overSampleTable"));
}
function renderOverSampleTable(table) {
  if (!table) return;
  table.innerHTML = "";
  const overRows = overSigmaRows();
  const maxItems = Math.max(1, ...overRows.map(r => r.items.length));
  const head = table.createTHead().insertRow();
  // 탭에 따라 목록의 성격이 다르다 — Fail 탭은 규격 이탈 항목, Abnormal Pass 탭은 통계 판정 항목.
  const isFailMode = (analysis?.analysis_mode || analysisMode) === "fail";
  const sampleItemsLabel = isFailMode ? "Fail Items" : "Abnormal Shift Items";
  // R-031: 그 샘플이 몇 개 항목에서 걸렸는지. 두 탭 모두에 둔다 — R-014 에서 열 폭을 두 탭에
  // 맞춰놨으므로 한쪽에만 열을 더하면 그 정렬이 깨진다.
  const countLabel = isFailMode ? "Fail 항목 수" : "이상 항목 수";
  ["Sample #", countLabel,
   ...Array.from({ length: maxItems }, (_, i) => i === 0 ? sampleItemsLabel : "")].forEach(label => {
    const th = document.createElement("th");
    th.textContent = label;
    head.appendChild(th);
  });
  const body = table.createTBody();
  overRows.forEach(row => {
    const tr = body.insertRow();
    tr.insertCell().textContent = row.sample;
    const countCell = tr.insertCell();          // R-031
    countCell.textContent = (row.items || []).filter(Boolean).length;
    countCell.className = "over-count";
    for (let i = 0; i < maxItems; i++) {
      const td = tr.insertCell();
      const item = row.items[i] || "";
      const name = itemDisplayName(item);
      td.textContent = name;
      // 열 폭이 고정이라 긴 이름은 잘린다 -- 전체 이름은 툴팁으로 남긴다.
      if (name) td.title = name;
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
function graphExcludeKey(row) {
  return needBenchKey(row);
}
/** 이 샘플을 그래프에서 뺐는가. row 든 point 든 sample 만 있으면 된다. */
function isGraphExcluded(entry) {
  if (!entry || entry.sample === undefined || entry.sample === null) return false;
  return !!graphExcludeState[graphExcludeKey(entry)];
}
/** 현재 항목에서 그래프에 안 그리기로 한 샘플 수 */
function graphExcludedCount() {
  const data = itemCache[selectedItem];
  if (!data) return 0;
  return (data.details || []).filter(isGraphExcluded).length;
}
function clearGraphExcludes() {
  const data = itemCache[selectedItem];
  (data?.details || []).forEach(row => { delete graphExcludeState[graphExcludeKey(row)]; });
  renderGraphExcludeNote();
  renderDetailTable();
  drawCharts();
}
function renderGraphExcludeNote() {
  const el = document.getElementById("graphExcludeNote");
  if (!el) return;
  const n = graphExcludedCount();
  el.innerHTML = "";
  el.classList.toggle("on", n > 0);
  if (!n) return;
  el.appendChild(document.createTextNode(`그래프 제외 ${n}건`));
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "되돌리기";
  btn.addEventListener("click", clearGraphExcludes);
  el.appendChild(btn);
}
function detailCellValue(row, key) {
  const data = itemCache[selectedItem] || {};
  const summary = selectedResultRow() || {};
  if (key === "result") return detailResultLabel(row);
  if (key === "spec_out_type") return detailSpecOutType(row);
  // 항목 기준 표의 Delta Mean 이 % 라 여기도 % 로 맞춘다 — 같은 diff_ratio 인데
  // 한쪽은 비율 원값이라 표기가 어긋나 있었다. 정렬은 원값 기준 그대로다. (R-020)
  if (key === "diff") {
    if (row.diff === null || row.diff === undefined) return null;
    const ratio = Number(row.diff);
    return Number.isFinite(ratio) ? `${(ratio * 100).toFixed(2)}%` : "";
  }
  if (["post_t1", "post_t2", "post_t3"].includes(key)) return detailReadoutValue(row, key);
  if (key === "unit") return row.unit || summary.unit || data.unit || "";
  return row[key];
}
// 상세 표를 다시 그리지 않고 제목 옆에만 로딩 상태를 보여준다.
// 끄는 것은 곧바로 이어지는 renderDetailTable() 이 문구를 덮어쓰며 처리한다.
function setDetailLoading(on) {
  const meta = document.getElementById("detailPanelMeta");
  if (!meta) return;
  meta.classList.toggle("is-loading", !!on);
  if (on) meta.textContent = `${selectedItemTitleName()} · 불러오는 중…`;
}
function renderDetailTable() {
  renderShiftGateNote();   // R-026
  const metaNode = document.getElementById("detailPanelMeta");
  if (metaNode) {
    // R-028: 지금까지 이 자리의 "N건" 은 표에 보이는 행 수가 아니라 항목의 전체 샘플 수였다.
    // 표에는 SELECT 된 행만 나오므로 둘이 크게 어긋난다(표 1행인데 "287건"). 보이는 행 수를
    // 앞에 두고 판정 모집단은 괄호로 병기한다.
    const item = itemCache[selectedItem];
    const allRows = item?.details || [];
    const shown = item ? sortedDetails(allRows).length : 0;
    const suffix = (allRows.length && allRows.length !== shown) ? ` (전체 ${allRows.length})` : "";
    metaNode.textContent = selectedItem ? `${selectedItemTitleName()} · ${shown}건${suffix}` : "";
  }
  const table = document.getElementById("detailTable");
  table.innerHTML = "";
  const head = table.createTHead().insertRow();
  const cols = visibleDetailColumns();
  const widths = detailColumnWidths(cols);
  renderDetailColumnToggleMenu();
  cols.forEach(([key, label], index) => {
    const th = document.createElement("th");
    th.style.width = `${widths[index].toFixed(3)}%`;
    th.textContent = label + (detailSortState.column === key ? (detailSortState.reverse ? " ▼" : " ▲") : "");
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
      if (key === "graph_exclude") {
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = isGraphExcluded(d);
        checkbox.title = "체크하면 이 샘플을 그래프에서 뺍니다 (판정·표의 숫자는 그대로)";
        checkbox.addEventListener("change", event => {
          event.stopPropagation();
          if (checkbox.checked) graphExcludeState[graphExcludeKey(d)] = true;
          else delete graphExcludeState[graphExcludeKey(d)];
          // 그래프에서 뺀 샘플이 하이라이트 중이면 하이라이트도 같이 푼다 — 안 그러면
          // 점과 Shift 화살표만 남아 좁혀진 축 밖으로 뻗는다. (R-016 후속)
          if (checkbox.checked && String(highlightSample) === String(d.sample)) {
            highlightSample = null;
            highlightMode = null;
          }
          renderGraphExcludeNote();
          renderDetailTable();
          drawCharts();
        });
        td.appendChild(checkbox);
        return;
      }
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
        if (isGraphExcluded(d)) {
          // 그래프에서 뺀 샘플은 하이라이트 대상이 아니다 — 눌러도 안 된다는 걸 눈으로 알린다.
          td.classList.add("sample-excluded");
          td.title = "그래프에서 제외된 샘플입니다 (Exclude 를 풀면 클릭할 수 있습니다)";
        } else {
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
/** Fail 마커로 실제 찍히는 값들. 축 범위 계산과 그리기가 같은 값을 보게 한다. */
function failReadoutMarkerValues(readoutSeries) {
  const out = [];
  (readoutSeries || []).forEach(series => {
    (series.points || []).forEach(point => {
      if (isGraphExcluded(point)) return;          // 그래프에서 뺀 샘플은 축도 늘리지 않는다
      const value = finiteNumber(point.post_value);
      if (value !== null) out.push(value);
    });
  });
  return out;
}
function drawFailReadoutMarkers(ctx, readoutSeries, x, y) {
  ctx.save();
  readoutSeries.forEach(series => {
    ctx.fillStyle = series.color || getCss("--red");
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.4;
    (series.points || []).forEach(point => {
      if (isGraphExcluded(point)) return;
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
  /* Fail 마커는 series.points[].post_value 로 그리는데, 축 범위는 series.values 만
     보고 있었다. Fail 샘플은 CDF 곡선용 값 집합에 없으므로 축이 늘어나지 않아
     규격을 벗어난 Fail 값이 플롯 영역 밖에 찍혔다(실측: LSL 4.976 인데 Fail 4.8427).
     그리는 값은 전부 축 계산에 넣는다. */
  /* 그리는 조건과 **똑같이** 걸어야 한다. 안 그러면 마커를 그리지도 않는
     Abnormal Pass 그래프까지 축이 넓어진다. */
  const failMarkerValues = (mode === "fail" && !hideFailData && hasReadoutSeries)
    ? failReadoutMarkerValues(readoutSeries) : [];
  const all = [...preAxisValues, ...postAxisValues, ...failOverlayValues, ...failMarkerValues];
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
  const metaEl = document.getElementById("waferPanelMeta");
  if (metaEl) {
    const data0 = itemCache[selectedItem];
    const row0 = data0?.details?.find(r => String(r.sample) === String(highlightSample)) || data0?.details?.[0] || {};
    const wafer = row0.wafer || row0.wafer_no || data0?.wafer_no || "W--";
    const sample = highlightSample || row0.sample;
    metaEl.textContent = `Wafer ${wafer}` + (sample != null && sample !== "" ? ` · Sample ${sample}` : "");
  }
  const canvas = document.getElementById("waferCanvas");
  if (!canvas) return;
  const { ctx, w, h } = setupHiResCanvas(canvas, 520, 300);
  const data = itemCache[selectedItem];
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "#0b438c";
  ctx.font = "800 16px Segoe UI";
  const selectedDetail = data?.details?.find(row => String(row.sample) === String(highlightSample)) || data?.details?.[0] || {};
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
        if (isGraphExcluded(point)) return;   // R-016 후속
        const cdf = cdfFraction(series.diff_values, point.diff);
        drawHighlightPoint(ctx, x(point.diff), y(cdf), series.color, `#${highlightSample} ${series.label || series.key} Diff ${fmt(point.diff)}`);
      });
    } else if (fallbackPostSelected) {
      const row = data.details.find(detail => String(detail.sample) === String(highlightSample));
      const diffValue = row ? finiteNumber(row.diff) : null;
      if (diffValue !== null && !isGraphExcluded(row) && sigmaOver3(row, "diff_s")) {   // R-016 후속
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
      .filter(point => !isGraphExcluded(point))
      .filter(point => finiteNumber(point.diff_s) !== null && finiteNumber(point.mea_s) !== null)
      .map(point => ({ ...point, series_label: series.label || series.key, color: series.color }))
  ) : fallbackPostSelected && !hideFailData ? [...data.details].filter(row =>
    !isGraphExcluded(row) && finiteNumber(row.diff_s) !== null && finiteNumber(row.mea_s) !== null
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
  // 그래프에서 뺀 샘플은 하이라이트도 그리지 않는다 — 체크박스 쪽에서 하이라이트를
  // 풀어주지만, 다른 경로로 들어와도 어긋나지 않도록 여기서도 막는다. (R-016 후속)
  if (isGraphExcluded(d)) return;
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


def sample_join_map_from_records(records, wanted=None):
    """화면 sample(Serial #) -> join_key(DEVICE_ID) 표 (R-038).

    over_sigma 행은 Serial # 로 샘플을 가리키는데, Serial # 은 파일마다 새로 매겨진다
    (§3-3). 전체 분석에서 Room/Hot 은 같은 유닛을 다시 측정한 것이라, 유닛 수를 셀 때
    Serial # 로 묶으면 다른 유닛이 합쳐지거나 같은 유닛이 두 번 세어진다.
    over_sigma 자체는 골든 비교 대상이라 행에 필드를 못 늘리므로 표를 따로 싣는다.
    """
    mapping = {}
    for item_records in (records or {}).values():
        for record in item_records:
            sample = record.get("sample")
            if sample is None:
                continue
            key = str(sample)
            if wanted is not None and key not in wanted:
                continue
            join_key = record_sample_id(record)
            if join_key and key not in mapping:
                mapping[key] = str(join_key)
    return mapping


def merge_records_for_units(paths):
    """여러 post 파일의 레코드를 하나로 합친다 — 유닛 인구조사 전용 (R-038)."""
    merged = {}
    for path in (paths or []):
        try:
            records = cached_item_records(path, last_sample=False)
        except Exception:
            continue
        for item, item_records in records.items():
            merged.setdefault(item, []).extend(item_records)
    return merged


def unit_join_key(sample_states, sample):
    """fail 경로의 Serial # 를 join_key(DEVICE_ID 우선)로 바꾼다 (R-038)."""
    state = (sample_states or {}).get(sample) or {}
    return str(state.get("join_key") or sample)


def unit_id_sets_from_records(records):
    """유닛 id 집합을 total / pass / fail 로 나눈다 (R-038).

    id 는 record_sample_id — CLAUDE.md §3-3 에 따라 DEVICE_ID 우선이다.
    개수가 아니라 집합을 만드는 이유: 온도(Room/Hot/Cold)는 같은 유닛을 다시 측정한
    것이라, 전체 분석에서 조합별 개수를 더하면 같은 유닛을 2~3번 센다. 실측으로도
    HTOL 은 Room 80 / Hot 80 / Cold 82 인데 합집합은 85 다 (교집합 77).
    """
    total = set()
    for item_records in (records or {}).values():
        for record in item_records:
            sample = record_sample_id(record)
            if sample:
                total.add(str(sample))
    pass_ids = pass_sample_ids_from_records(records)
    if pass_ids is None:
        # Bin 정보가 없는 데이터 — 전부 양품으로 본다 (pass_sample_ids_from_records 규약).
        pass_set = set(total)
    else:
        pass_set = {str(sample) for sample in pass_ids} & total
    return total, pass_set, (total - pass_set)


def unit_id_payload(records):
    total, pass_set, fail_set = unit_id_sets_from_records(records)
    return (
        {"total": sorted(total), "pass": sorted(pass_set), "fail": sorted(fail_set)},
        {"total": len(total), "pass": len(pass_set), "fail": len(fail_set)},
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
    for path in data_files(post_dir):
        parsed = parse_post_file_name(path)
        if not parsed:
            continue
        # R-037: 대소문자·별칭(HTS=HTSL)을 흡수해야 HTSL 을 골랐을 때 HTS 파일이 잡힌다.
        if not reliability_item_equal(parsed["item"], reliability_item):
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
            # R-037: 조합 키를 화면 표기로 맞춘다. 이 이름이 그대로 row["reliability_item"]
            # 과 item_counts 의 키가 되므로, 여기서 어긋나면 필터 바가 그 항목을 못 찾는다.
            key = (canonical_reliability_item(parsed["item"]), temp)
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
    # R-037: 화면 목록(RELIABILITY_ITEMS)에 없는 이름은 필터 바에 칩이 안 생겨서
    # 그 데이터가 화면에서 사라진다. 조용히 넘어가지 말고 경고로 띄운다.
    known = {name.upper() for name in RELIABILITY_ITEMS}
    for name in sorted({combo["item"] for combo in combos}):
        if name.upper() not in known:
            filename_warnings.append({"file": "", "reason": "unknown_reliability_item", "used": name})
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
    payload["reliability_item"] = reliability_item   # R-038: merge_unit_counts 가 이 키로 묶는다
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
    # R-036: 게이트 집계(shift_gate / fail_gate)는 조합 단위에서 "항목 이름" 으로 키가 잡혀
    # 있다. 전체 분석에서는 위에서 행의 item_key 를 "{item}__{sha1[:10]}" 로 다시 발급하므로,
    # 게이트만 옛 키로 남으면 프런트가 itemKey(row) 로 찾을 때 전부 빗나가 기준 탭
    # (스펙 대비 / Marginal 제외)이 아무것도 안 접는다. 같은 key_by_item 표로 맞춰준다.
    for gate_name in ("shift_gate", "fail_gate"):
        gate = payload.get(gate_name)
        if not isinstance(gate, dict) or not gate.get("items"):
            continue
        rekeyed = {}
        for original_item, counts in gate["items"].items():
            key = key_by_item.get(original_item) or total_item_key(
                reliability_item, ft_temp, readout, original_item
            )
            rekeyed[key] = counts
        gate["items"] = rekeyed
    for row in payload.get("over_sigma", []):
        row["reliability_item"] = reliability_item
        row["ft_temp"] = ft_temp
        row["readout"] = readout
        row["judged_readout"] = readout
        row["readout_history"] = history
        row["items"] = [key_by_item.get(item, item) for item in row.get("items", [])]
    # R-038: Serial # 은 조합마다 1번부터 다시 매겨지므로 조합을 키에 포함해야 충돌하지 않는다.
    payload["unit_join_map"] = {
        f"{reliability_item}||{ft_temp}||{sample}": join_key
        for sample, join_key in (payload.get("unit_join_map") or {}).items()
    }
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
        # R-026: 조합별 게이트 집계를 항목 단위로 합친다. 같은 항목이 여러 조합에 나오면
        # 각 조합의 kept/folded 를 더한다 — 한 조합에서라도 남으면 목록에 남아야 한다.
        combo_gate = payload.get("shift_gate") or {}
        if combo_gate.get("items"):
            merged.setdefault("shift_gate", {"tau": combo_gate.get("tau", SPEC_GATE_TAU), "items": {}})
            for item_key, counts in combo_gate["items"].items():
                agg = merged["shift_gate"]["items"].setdefault(
                    item_key, {"kept": 0, "folded": 0, "kept_samples": []}
                )
                agg["kept"] += counts.get("kept", 0) or 0
                agg["folded"] += counts.get("folded", 0) or 0
                agg["kept_samples"].extend(counts.get("kept_samples") or [])   # R-038
        # R-036: fail_gate 는 합치는 코드가 아예 없어서 전체 분석 fail 결과에는
        # 키 자체가 실리지 않았다 -> failGateOn() 이 항상 false. kept 는 샘플 번호
        # 목록이므로 더하지 말고 이어붙인다.
        combo_fail_gate = payload.get("fail_gate") or {}
        if combo_fail_gate.get("items"):
            merged.setdefault("fail_gate", {
                "excluded_type": combo_fail_gate.get("excluded_type", FAIL_MARGINAL_TYPE),
                "items": {},
            })
            for item_key, counts in combo_fail_gate["items"].items():
                agg = merged["fail_gate"]["items"].setdefault(item_key, {"kept": [], "folded": 0})
                agg["kept"].extend(counts.get("kept") or [])
                agg["folded"] += counts.get("folded", 0) or 0
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
    merge_unit_counts(merged, combo_payloads)
    join_map = {}
    for payload in combo_payloads:
        join_map.update(payload.get("unit_join_map") or {})
    merged["unit_join_map"] = join_map   # R-038
    return merged


def merge_unit_counts(merged, combo_payloads):
    """조합별 유닛 id 집합을 신뢰성 항목 단위로 합집합해 개수로 바꾼다 (R-038).

    개수를 더하면 안 되는 이유는 unit_id_sets_from_records() 주석 참조 — 온도는 같은
    유닛의 재측정이다. fail 이 우선이다: 어느 온도에서든 한 번 fail 이면 그 유닛은 fail.
    id 목록 자체는 화면에서 쓰지 않으므로 병합 결과에는 개수만 남긴다(payload 비대화 방지).
    """
    by_item = {}
    for payload in combo_payloads:
        ids = payload.get("unit_ids") or {}
        item = payload.get("reliability_item") or ""
        entry = by_item.setdefault(item, {"total": set(), "fail": set()})
        entry["total"] |= {str(value) for value in (ids.get("total") or [])}
        entry["fail"] |= {str(value) for value in (ids.get("fail") or [])}
        payload.pop("unit_ids", None)
    all_total, all_fail = set(), set()
    by_reliability = {}
    for item, entry in by_item.items():
        total, fail = entry["total"], entry["fail"] & entry["total"]
        all_total |= total
        all_fail |= fail
        by_reliability[item] = {"total": len(total), "fail": len(fail), "pass": len(total - fail)}
    merged["unit_counts"] = {
        "total": len(all_total),
        "fail": len(all_fail),
        "pass": len(all_total - all_fail),
        "by_reliability": by_reliability,
    }
    merged.pop("unit_ids", None)


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

# R-032: Fail 목록에서 접을 "Marginal" 의 정의 — fail_type 이 Tail 인 건.
# Tail 은 fail_type_for_detail() 의 마지막 분기, 즉 규격은 벗어났지만 이탈량이 1% 미만
# (Excessive 아님)이고 Mea_S·Diff_S 가 함께 임계를 넘지도 않은(Slight 아님) 건이다.
# 신뢰성 시험 후에는 열화로 모집단 전체가 이동하는데, 그때 원래 규격 경계에 있던 유닛이
# 딸려 넘어간 경우가 여기 모인다 — 혼자 유독 많이 움직여서 넘어간 것과 구분해야 한다.
# 실측(Test Data, 상세 24건): Tail 17건의 이탈/스펙폭 중앙 0.500%, Diff_S 임계 초과는 1건뿐.
# (Excessive 32.667% · Slight 13.000% 와 자릿수가 다르다.)
FAIL_MARGINAL_TYPE = "Tail"


def fail_marginal_gate(item_payloads):
    """항목별로 Marginal 이 아닌 fail 샘플 목록과 접히는 건수. payload 최상위 키로 나간다.

    kept 를 샘플 번호 목록으로 주는 이유: 프런트가 이 하나로 세 곳을 다 처리한다 —
    항목 기준 표(kept 가 비면 항목을 접는다), 샘플 기준 표(각 샘플에서 어떤 항목이 남는지),
    요약 숫자(kept 합계). 상세 표는 행마다 fail_type 이 있어 프런트가 직접 거른다.

    최상위 키인 이유는 shift_gate 와 같다 — 골든 스냅샷 비교 대상(results /
    selected_summary / over_sigma / items[].details)에 필드를 늘리면 회귀가 깨진다.
    """
    items = {}
    for item, item_payload in item_payloads.items():
        kept, folded = [], 0
        for detail in item_payload.get("details") or []:
            if not detail.get("fail_type"):
                continue
            if detail.get("fail_type") == FAIL_MARGINAL_TYPE:
                folded += 1
            else:
                kept.append(detail.get("sample"))
        items[item] = {"kept": kept, "folded": folded}
    return {"excluded_type": FAIL_MARGINAL_TYPE, "items": items}


def worst_fail_type(details):
    """항목의 detail 행들 중 가장 심각한 fail_type 을 고른다.

    우선순위는 fail_type_for_detail() 주석에 명시된 순서를 그대로 쓴다:
    Intermittent > Unstable > Excessive > Slight > Tail.
    """
    if not details:
        return ""
    return min(details, key=lambda detail: FAIL_TYPE_PRIORITY.get(detail.get("fail_type"), 99)).get("fail_type", "")


def spec_width(lower_limit, upper_limit):
    if lower_limit is None or upper_limit is None:
        return None
    try:
        width = abs(float(upper_limit) - float(lower_limit))
    except (TypeError, ValueError):
        return None
    return width if (math.isfinite(width) and width) else None


def shift_spec_ratio(pre_value, post_value, lower_limit, upper_limit):
    """|Post - Pre| / 스펙폭.  구할 수 없으면 None. Delta 축의 스펙 대비 크기이자
    Raw Data Export 의 "Shift/Spec %" 열 값이다. (R-026)"""
    width = spec_width(lower_limit, upper_limit)
    if width is None or pre_value is None or post_value is None:
        return None
    try:
        shift = abs(float(post_value) - float(pre_value))
    except (TypeError, ValueError):
        return None
    return (shift / width) if math.isfinite(shift) else None


def spec_relative_size(detail, result_row, lower_limit, upper_limit):
    """SELECT 를 만든 축의 "스펙 대비 크기". 구할 수 없으면 None(= 접지 않는다). (R-029)

    두 축이 모두 걸렸으면 큰 쪽을 쓴다 — 어느 한 축에서라도 스펙 대비 유의미하면 남긴다.
    프런트엔드가 상세 표 행마다 같은 식을 그대로 계산한다. 여기 쓰는 값(pre_value/
    post_value/mea_s/diff_s/post_mean/임계값/LL/UL)은 전부 round_for_wire 를 타지 않고
    float64 원본이 그대로 나가므로 서버 집계와 프런트 계산이 비트 단위로 일치한다 —
    경계값(정확히 tau)에서 양쪽이 엇갈리지 않는다.
    """
    width = spec_width(lower_limit, upper_limit)
    if width is None:
        return None
    sizes = []
    mea_s = detail.get("mea_s")
    mea_threshold = (result_row or {}).get("mea_threshold")
    post_mean = (result_row or {}).get("post_mean")
    post_value = detail.get("post_value")
    if (mea_s is not None and mea_threshold and abs(mea_s) > mea_threshold
            and post_mean is not None and post_value is not None):
        try:
            sizes.append(abs(float(post_value) - float(post_mean)) / width)
        except (TypeError, ValueError):
            pass
    diff_s = detail.get("diff_s")
    diff_threshold = (result_row or {}).get("diff_threshold")
    if diff_s is not None and diff_threshold and abs(diff_s) > diff_threshold:
        ratio = shift_spec_ratio(detail.get("pre_value"), post_value, lower_limit, upper_limit)
        if ratio is not None:
            sizes.append(ratio)
    sizes = [x for x in sizes if math.isfinite(x)]
    return max(sizes) if sizes else None


def shift_gate_summary(app):
    """항목별 SELECT 샘플 중 게이트 통과(kept)/차단(folded) 개수. payload 최상위 키로 나간다.

    왜 서버가 미리 세는가: 항목 기준 표와 요약 카드는 첫 화면에 전 항목을 그려야 하는데
    상세는 /item 으로 지연 로딩된다. 프런트가 항목 단위 판정을 하려면 항목 수만큼 왕복해야
    하므로 여기서 한 번에 집계한다.

    왜 최상위 키인가: 골든 스냅샷 비교 대상(results / selected_summary / over_sigma /
    items[].details)에 필드를 하나라도 늘리면 회귀 게이트가 깨진다 —
    tools/_regression_lib.py 의 _compare_dict 가 키의 **합집합**을 돌며 한쪽에만 있는 키를
    <missing> 불일치로 잡는다. 최상위 새 키는 비교 대상이 아니라 골든이 그대로 유지된다.

    LL/UL 은 item_metadata() 를 쓴다 — item_to_json() 이 항목 payload 의 lower_limit/
    upper_limit 를 채울 때 쓰는 것과 같은 출처라, 프런트가 읽는 값과 동일하다.
    (pass 모드 상세 행 자체에는 LL/UL 이 없다.)
    """
    items = {}
    for row in app.results:
        if row.get("result") != "SELECT":
            continue
        item = row.get("item")
        if not item or item in items:
            continue
        metadata = item_metadata(app, item)
        entry = item_analysis(app, item)
        result_row = entry.get("result_row") or {}
        kept_samples, folded = [], 0
        for detail in entry["details"]:
            if detail.get("result") != "SELECT":
                continue
            size = spec_relative_size(
                detail, result_row, metadata["lower_limit"], metadata["upper_limit"],
            )
            if size is not None and size < SPEC_GATE_TAU:
                folded += 1
            else:
                kept_samples.append(str(detail.get("sample")))
        # R-038: kept 는 개수 그대로 두고(기존 호출부 유지) 샘플 목록을 따로 싣는다.
        # 개수만으로는 "이 샘플이 접혔는지"를 알 수 없어 샘플 기준 표와 유닛 수 집계에서
        # 게이트를 정확히 적용할 수 없었다. fail_gate 의 kept 와 같은 모양이다.
        items[item] = {"kept": len(kept_samples), "folded": folded, "kept_samples": kept_samples}
    return {"tau": SPEC_GATE_TAU, "items": items}


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
        "shift_gate": shift_gate_summary(app),  # R-026 (표시 전용)
    }
    # R-038: 배지가 유닛(샘플) 기준으로 바뀐다. pass payload 에는 지금까지 항목 수만
    # 있어서 "총 샘플 수"를 낼 수 없었다. 최상위 키라 골든 비교 대상이 아니다.
    unit_ids, unit_counts = unit_id_payload(cached_item_records(post_path, last_sample=False))
    payload["unit_ids"] = unit_ids
    payload["unit_counts"] = unit_counts
    payload["unit_join_map"] = sample_join_map_from_records(
        app.post_records, {str(row["sample"]) for row in over_rows}
    )
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
    marginal_gate = fail_marginal_gate(item_payloads)   # R-032 (표시 전용)
    fail_unit_ids, fail_unit_counts = unit_id_payload(merge_records_for_units(post_files))  # R-038
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
        "fail_gate": marginal_gate,  # R-032 (표시 전용)
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
        # R-038: 전체 분석에서 온도별로 같은 유닛을 다시 세지 않도록 id 집합도 싣는다.
        # sample_counts 와 달리 합집합을 취할 수 있다.
        # R-038: 유닛 인구조사는 두 탭이 같은 숫자를 내야 한다("시험이 된 총 수량"은
        # 어느 탭에서 보든 같은 값이다). 그래서 fail 판정 경로(sample_states)가 아니라
        # pass 쪽과 똑같이 post 파일 레코드에서 센다. 키도 join_key(DEVICE_ID 우선) —
        # Serial # 은 파일마다 새로 매겨져(§3-3) 온도 간 합집합이 성립하지 않는다.
        "unit_ids": fail_unit_ids,
        "unit_counts": fail_unit_counts,
        "unit_join_map": {
            str(row["sample"]): unit_join_key(sample_states, row["sample"]) for row in over_rows
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


CACHE_SCHEMA = 24  # 23->24: unit_counts·shift_gate.kept_samples 추가 (R-038).
# 스키마를 올리는 이유: 이 키들이 없던 시절 저장된 캐시를 그대로 불러오면 payload 에
# 게이트 정보가 없어 프런트의 기준 탭이 조용히 비활성된다 — 눌러도 아무것도 안 접히는데
# 화면에는 아무 경고도 없어서 "반영이 안 됐다"로 보인다. 실제로 그렇게 진단이 한참 헤맸다.
# payload 구조를 늘릴 때는 반드시 이 값을 함께 올린다.
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
        # 판정에 쓰는 sigma 와 같은 표본표준편차(ddof=1, §11-4)로 통일한다. 이전에는
        # n 으로 나눈 모표준편차(ddof=0)라, 화면의 stdev 로 옆 칸 Z-Score 를 손으로
        # 검산하면 답이 맞지 않았다 (R-024). n 이 작을수록 차이가 커진다.
        "stdev": std_of(nums, ddof=1),
        "min": min(nums),
        "max": max(nums),
    }


def cache_summary_values(item_payload):
    # 회차(t1/t2/t3)를 하나로 합쳐서 통계를 내면 안 된다 — 회차마다 모집단이 다르므로
    # 합친 표본의 평균·표준편차는 어느 회차도 설명하지 못하고, 판정 sigma 와도 어긋난다.
    # 항목 요약 행은 항목당 한 줄이므로 "분석 대상 리드아웃"(판정에 쓰는 바로 그 표본
    # = post_values, n_post/post_sigma 의 모집단) 하나만 쓴다. 회차별 통계가 필요하면
    # post_readout_values[].stats 에 회차별로 이미 들어 있고, Item 더블클릭 시 뜨는
    # Pre / Post 비교 창(R-021)이 그것을 회차별로 보여준다. (R-025)
    values = item_payload.get("post_values") or item_payload.get("pass_post_values") or []
    if values:
        return values
    # post_values 가 없는 payload(구 캐시 등)면 마지막 회차 하나로 대체한다 — 합치지 않는다.
    for series in reversed(item_payload.get("post_readout_values") or []):
        series_values = series.get("values") or []
        if series_values:
            return series_values
    return []


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

# R-037: 파일명 표기와 화면 표기가 다른 신뢰성 항목의 별칭 (키·값 모두 대문자 기준).
# 실데이터에서 UHAST(대소문자만 다름)와 HTS(약어가 다름)가 화면 목록과 어긋나
# 두 항목 2,264건이 필터 바에서 통째로 사라지고, 항목별 합이 전체와 안 맞았다.
# 새 표기가 나오면 여기 한 줄만 추가한다.
RELIABILITY_ITEM_ALIASES = {"HTS": "HTSL"}


def canonical_reliability_item(name):
    """파일명에서 읽은 신뢰성 항목 이름을 화면 표기로 맞춘다.

    별칭 -> 대소문자 -> 그대로. 마지막이 "그대로"인 이유는, 모르는 약어를 버리면
    그 데이터가 화면에서 조용히 사라지기 때문이다 (R-037 이 정확히 그 사고였다).
    """
    text = str(name or "").strip()
    if not text:
        return ""
    upper = RELIABILITY_ITEM_ALIASES.get(text.upper(), text.upper())
    for canonical in RELIABILITY_ITEMS:
        if canonical.upper() == upper:
            return canonical
    return text


def reliability_item_equal(left, right):
    """신뢰성 항목 이름 비교. 대소문자와 별칭을 흡수한다 (R-037)."""
    return canonical_reliability_item(left).upper() == canonical_reliability_item(right).upper()


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
    return bool(parsed and reliability_item_equal(parsed["item"], item))   # R-037


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
        if reliability_item_equal(parsed["item"], item) and parsed["readout"].casefold() == readout.casefold():   # R-037
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
    # R-038: 단일 조건에서도 전체 분석과 같은 모양의 unit_counts 를 만든다 —
    # 프런트가 by_reliability 하나만 보고 두 경로를 똑같이 처리하게 하려는 것.
    counts = payload.get("unit_counts") or {}
    if counts and "by_reliability" not in counts:
        payload["unit_counts"] = dict(counts, by_reliability={reliability_item or "": dict(counts)})
    payload.pop("unit_ids", None)
    payload["unit_join_map"] = {
        f"{reliability_item}||{ft_temp}||{sample}": join_key
        for sample, join_key in (payload.get("unit_join_map") or {}).items()
    }
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
                CURRENT_ITEMS[mode] = payload.get("items", {})
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
                CURRENT_ITEMS["fail"] = payload.get("items", {})
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
                CURRENT_ITEMS[mode] = payload.get("items", {})
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
    "Pre", "Post", "T1", "T2", "T3", "Mea_S", "Delta", "Diff_S", "Need Bench",
    # R-026: 화면은 기준 탭에 따라 접히지만 내보낸 데이터에서는 아무것도 빠지지 않는다.
    # 대신 판단 근거 두 열을 붙여 엑셀에서 각자 기준으로 다시 거를 수 있게 한다
    # (데이터를 빼버리면 되돌릴 방법이 없다).
    "Shift/Spec %", "Practically Insignificant",
    "Analysis Date",
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


def export_shift_gate_cells(mode, detail, item_payload, context):
    """Raw Data Export 의 R-026 두 열: Shift/Spec % 와 실용적 무의미(Y/N).

    Fail 모드에는 게이트를 적용하지 않으므로(이미 규격을 벗어난 유닛이라 "스펙 대비 미미"가
    성립하지 않는다) 비율만 참고로 채우고 판정 칸은 비운다. 비율을 구할 수 없으면(스펙폭
    없음/0, pre·post 결측) 두 칸 모두 빈칸이며, 이는 화면에서 접지 않는 것과 같은 뜻이다.
    """
    lower = detail.get("lower_limit", item_payload.get("lower_limit", context.get("lower_limit")))
    upper = detail.get("upper_limit", item_payload.get("upper_limit", context.get("upper_limit")))
    ratio = shift_spec_ratio(detail.get("pre_value"), detail.get("post_value"), lower, upper)
    if ratio is None:
        return ["", ""]
    percent = round(ratio * 100, 4)
    if mode == "fail":
        return [percent, ""]
    return [percent, "Y" if ratio < SPEC_GATE_TAU else "N"]


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
                    *export_shift_gate_cells(mode, detail, item_payload, context),   # R-026
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
                    # 모드가 다르면 캐시를 쓰지 않는다 — pass/fail 은 모집단이 다른
                    # 별개의 결과다 (R-017).
                    mode_items = CURRENT_ITEMS.get(mode, {}) if mode else {}
                    cached_item = (payload.get("items", {}) if payload else {}).get(item) or mode_items.get(item)
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
                        if mode:
                            CURRENT_ITEMS.setdefault(mode, {})[item] = split_item
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
                            CURRENT_ITEMS[mode] = cached_payload.get("items", {})
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
                        CURRENT_ITEMS[mode] = cached_payload.get("items", {})
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
