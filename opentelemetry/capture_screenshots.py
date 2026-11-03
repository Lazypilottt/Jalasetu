#!/usr/bin/env python3
"""
Capture Grafana screenshots of JalaSetu's OpenTelemetry data with headless Firefox.

usage: capture_screenshots.py <success_trace_id> <error_trace_id> [out_dir]
Requires: ./grafana-local.sh up, Firefox, `pip install selenium`.
"""
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options

GRAFANA = "http://localhost:3001"
OK_TRACE, ERR_TRACE = sys.argv[1], sys.argv[2]
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else Path(__file__).parent / "screenshots")
OUT.mkdir(parents=True, exist_ok=True)
ONLY = [x for x in os.getenv("SHOTS", "").split(",") if x]  # e.g. SHOTS=07,09

DS = {
    "tempo": {"type": "tempo", "uid": "tempo"},
    "loki": {"type": "loki", "uid": "loki"},
    "prometheus": {"type": "prometheus", "uid": "prometheus"},
}


def explore(ds, query, extra=None, rng="now-30m"):
    q = {"refId": "A", "datasource": DS[ds]}
    if ds == "tempo":
        q.update(queryType="traceql", query=query, limit=20, tableType="traces")
    else:
        q.update(expr=query)
    q.update(extra or {})
    panes = {"a": {"datasource": DS[ds]["uid"], "queries": [q], "range": {"from": rng, "to": "now"}}}
    return f"{GRAFANA}/explore?schemaVersion=1&orgId=1&panes={urllib.parse.quote(json.dumps(panes))}"


def click_text(drv, text, last=False, contains=False):
    cond = f"contains(text(),'{text}')" if contains else f"normalize-space(text())='{text}'"
    els = drv.find_elements(By.XPATH, f"//*[{cond}]")
    for el in reversed(els) if last else els:
        try:
            el.click()
            return True
        except Exception:
            continue
    return False


def shot(drv, name, url, height=1100, wait=9, actions=None):
    if ONLY and name[:2] not in ONLY:
        return
    drv.set_window_size(1600, height)
    drv.get(url)
    time.sleep(wait)
    if actions:
        actions(drv)
        time.sleep(3)
    path = OUT / f"{name}.png"
    drv.save_screenshot(str(path))
    print("saved", path)


def expand_raw_results(drv):
    drv.execute_script("""
      const lbl = [...document.querySelectorAll('*')].find(e => e.textContent.trim() === 'Expand results' && e.children.length === 0);
      let box = lbl; for (let i = 0; i < 4 && box; i++) { const sw = box.querySelector('input[type=checkbox]'); if (sw) { sw.click(); return; } box = box.parentElement; }
    """)


def open_log_details(drv):
    click_text(drv, "sys4 request failed", contains=True)


def open_span(name, last=False):
    return lambda drv: click_text(drv, name, last=last)


opts = Options()
opts.add_argument("-headless")
opts.set_preference("browser.cache.disk.enable", False)  # keep the temp profile small
drv = webdriver.Firefox(options=opts)
try:
    shot(drv, "01_dashboard_overview", f"{GRAFANA}/d/jalasetu-otel?orgId=1&from=now-30m&to=now&kiosk", height=1900, wait=12)
    shot(drv, "02_tempo_trace_search", explore("tempo", '{ name = "analyze_contour" }'), height=900)
    shot(drv, "03_tempo_trace_waterfall", explore("tempo", OK_TRACE), height=1500, wait=10)
    shot(drv, "04_tempo_span_attributes", explore("tempo", OK_TRACE), height=1500, wait=10,
         actions=open_span("analyze_contour"))
    shot(drv, "05_tempo_error_trace", explore("tempo", ERR_TRACE), height=1400, wait=10,
         actions=open_span("POST /analyzeContour", last=True))
    shot(drv, "06_loki_logs", explore("loki", '{service_name=~"jalasetu-.*"} != "Failed to export"'), height=1150)
    shot(drv, "07_loki_error_log_trace_link",
         explore("loki", f'{{service_name="jalasetu-sys4-gateway"}} | trace_id="{ERR_TRACE}"', rng="now-1h"),
         height=1750, actions=open_log_details)
    shot(drv, "10_tempo_node_graph", explore("tempo", OK_TRACE), height=1100, wait=10,
         actions=open_span("Node graph", last=True))
    shot(drv, "08_prometheus_stage_durations",
         explore("prometheus",
                 "sum by (service_name, stage) (jalasetu_stage_duration_seconds_sum) / "
                 "sum by (service_name, stage) (jalasetu_stage_duration_seconds_count)",
                 extra={"instant": True, "range": False, "format": "table"}),
         height=900)
    shot(drv, "09_prometheus_raw_series", explore("prometheus", "jalasetu_analyses_total",
                                                  extra={"instant": True, "range": False}), height=850,
         actions=expand_raw_results)
finally:
    drv.quit()
