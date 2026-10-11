"""LOTIEM / LOTWPS Broadcast Message Handler.

This application consumes live public NWS data and provides local Tkinter monitoring,
draft composition, and local text-to-speech. It does not transmit RF, generate SAME/EAS
headers/tones, issue warnings, or connect to public alerting infrastructure.
"""
from __future__ import annotations

import json
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import requests

APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
DRAFTS_FILE = APP_DIR / "drafts.json"
NWS_API = "https://api.weather.gov"
DEFAULT_CONFIG: dict[str, Any] = {
    "latitude": 41.4675,
    "longitude": -87.0600,
    "timezone": "America/Chicago",
    "nws_user_agent": "LOTIEM-BMH/0.1 (https://github.com/nicholasgville23/LOTIEM-and-LOTWPS)",
    "station_host": "127.0.0.1",
    "station_port": 6000,
    "language": "en",
    "preferred_voice": "",
    "refresh_minutes": 5,
    "stations": [
        {"id": "WXK89", "city": "Valparaiso, Indiana", "frequency_mhz": 162.400, "enabled": True},
        {"id": "KBB57", "city": "Gary, Indiana", "frequency_mhz": 162.425, "enabled": True},
    ],
}
PRIORITY_ORDER = {"Emergency": 0, "Warning": 1, "Watch": 2, "Advisory": 3, "Statement": 4}
EVENT_CHOICES = [
    "Tornado Warning", "Severe Thunderstorm Warning", "Flash Flood Warning",
    "Extreme Wind Warning", "Special Weather Statement", "Severe Thunderstorm Watch",
    "Tornado Watch", "Winter Weather Advisory", "Flood Watch", "Civil Emergency Message",
]
SUPPORTED_LANGUAGES = {
    "English": "en", "Türkçe": "tr", "Deutsch": "de", "Español": "es", "Français": "fr"
}


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return config


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def classify_priority(event: str, severity: str = "") -> str:
    """Map an NWS event into the requested display/queue priority."""
    name = (event or "").casefold()
    if any(term in name for term in (
        "emergency action notification", "national emergency message",
        "civil danger warning", "evacuation immediate", "civil emergency message",
    )):
        return "Emergency"
    if "warning" in name:
        return "Warning"
    if "watch" in name:
        return "Watch"
    if "advisory" in name:
        return "Advisory"
    # Preserve the source event name; severity is a secondary sort hint only.
    return "Statement"


def alert_sort_key(feature: dict[str, Any]) -> tuple[int, str]:
    props = feature.get("properties") or {}
    priority = classify_priority(str(props.get("event", "")), str(props.get("severity", "")))
    return PRIORITY_ORDER.get(priority, 99), str(props.get("effective") or props.get("sent") or "")


class NWSClient:
    """Small client for documented, public api.weather.gov endpoints."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": str(config.get("nws_user_agent") or DEFAULT_CONFIG["nws_user_agent"]),
            "Accept": "application/geo+json, application/ld+json;version=1",
        })

    def _json(self, url: str) -> dict[str, Any]:
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("NWS returned an unexpected response format.")
        return data

    def active_alerts(self) -> list[dict[str, Any]]:
        lat = float(self.config["latitude"])
        lon = float(self.config["longitude"])
        data = self._json(f"{NWS_API}/alerts/active?point={lat:.4f},{lon:.4f}")
        features = data.get("features", [])
        if not isinstance(features, list):
            return []
        return sorted(
            [x for x in features if isinstance(x, dict)],
            key=alert_sort_key,
        )

    def forecasts(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        lat = float(self.config["latitude"])
        lon = float(self.config["longitude"])
        point = self._json(f"{NWS_API}/points/{lat:.4f},{lon:.4f}")
        props = point.get("properties") or {}
        daily_url, hourly_url = props.get("forecast"), props.get("forecastHourly")
        if not daily_url:
            raise ValueError("NWS did not provide a forecast URL for this point.")
        daily = self._json(daily_url)
        hourly = self._json(hourly_url) if hourly_url else {"properties": {"periods": []}}
        daily_periods = ((daily.get("properties") or {}).get("periods") or [])
        hourly_periods = ((hourly.get("properties") or {}).get("periods") or [])
        return daily_periods, hourly_periods


def format_alert(feature: dict[str, Any]) -> str:
    p = feature.get("properties") or {}
    event = str(p.get("event") or "NWS alert")
    headline = str(p.get("headline") or "")
    area = str(p.get("areaDesc") or "area not supplied")
    description = str(p.get("description") or "").strip()
    instruction = str(p.get("instruction") or "").strip()
    pieces = [event + ".", headline, "Affected area: " + area + "."]
    if description:
        pieces.append(description)
    if instruction:
        pieces.append("Instructions: " + instruction)
    return " ".join(x for x in pieces if x)


def short_alert(feature: dict[str, Any]) -> str:
    p = feature.get("properties") or {}
    return str(p.get("headline") or p.get("event") or "NWS alert").replace("\n", " ").strip()


class SpeechService:
    """Local OS speech only; it has no transmitter or EAS/SAME output path."""

    @staticmethod
    def voices() -> list[tuple[str, str]]:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            result = []
            for voice in engine.getProperty("voices") or []:
                name = str(getattr(voice, "name", "") or voice.id)
                result.append((name, str(voice.id)))
            engine.stop()
            return result
        except Exception:
            return []

    @staticmethod
    def speak(text: str, voice_id: str = "") -> None:
        import pyttsx3
        engine = pyttsx3.init()
        try:
            if voice_id:
                engine.setProperty("voice", voice_id)
            engine.say(text)
            engine.runAndWait()
        finally:
            engine.stop()


class LOTIEMApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = load_config()
        self.client = NWSClient(self.config)
        self.alerts: list[dict[str, Any]] = []
        self.daily_periods: list[dict[str, Any]] = []
        self.hourly_periods: list[dict[str, Any]] = []
        self._refreshing = False
        self._loop_thread: threading.Thread | None = None
        self._loop_stop = threading.Event()
        self.voice_options = SpeechService.voices()
        self.root.title("BMH — NOAA Weather Radio / LOTIEM & LOTWPS")
        self.root.geometry("1360x880")
        self.root.minsize(1050, 700)
        self._build_ui()
        self._tick_clock()
        self.refresh_data()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=(12, 8))
        top.pack(fill="x")
        ttk.Label(top, text="KLOT  |  LOTIEM TEXT WORKSTATION + BMH",
                  font=("Segoe UI", 17, "bold")).pack(side="left")
        self.clock_var = tk.StringVar(value="America/Chicago")
        ttk.Label(top, textvariable=self.clock_var, font=("Consolas", 11)).pack(side="right")

        warning = ttk.Label(
            self.root,
            text="LIVE NWS DATA • LOCAL MONITORING / LOCAL SPEECH ONLY • NO RF, SAME OR EAS TRANSMISSION",
            foreground="#a12622", font=("Segoe UI", 10, "bold"), padding=(12, 4),
        )
        warning.pack(fill="x")

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=8)
        self.overview_tab = ttk.Frame(self.notebook, padding=10)
        self.text_tab = ttk.Frame(self.notebook, padding=10)
        self.network_tab = ttk.Frame(self.notebook, padding=10)
        self.settings_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.overview_tab, text="Live NWS Overview")
        self.notebook.add(self.text_tab, text="KLOT Text Workstation")
        self.notebook.add(self.network_tab, text="BMH Network Monitor")
        self.notebook.add(self.settings_tab, text="System Settings")
        self._build_overview()
        self._build_text_workstation()
        self._build_network()
        self._build_settings()

        status_bar = ttk.Frame(self.root, padding=(10, 4))
        status_bar.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready — data has not been refreshed yet.")
        ttk.Label(status_bar, textvariable=self.status_var).pack(side="left")
        ttk.Label(status_bar, text="Source: api.weather.gov",
                  foreground="#4a5a68").pack(side="right")

    def _build_overview(self) -> None:
        controls = ttk.Frame(self.overview_tab)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Refresh Official NWS Data", command=self.refresh_data).pack(side="left")
        ttk.Button(controls, text="Open weather.gov", command=lambda: webbrowser.open("https://www.weather.gov/lot/")).pack(side="left", padx=6)
        self.overview_location = ttk.Label(controls, text=self._location_text())
        self.overview_location.pack(side="right")

        panes = ttk.Panedwindow(self.overview_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.LabelFrame(panes, text="Active alerts at configured point", padding=6)
        right = ttk.LabelFrame(panes, text="Official NWS forecast", padding=6)
        panes.add(left, weight=3)
        panes.add(right, weight=2)

        columns = ("priority", "event", "expires")
        self.alert_tree = ttk.Treeview(left, columns=columns, show="headings", height=14, selectmode="browse")
        self.alert_tree.heading("priority", text="Priority")
        self.alert_tree.heading("event", text="Event / headline")
        self.alert_tree.heading("expires", text="Expires")
        self.alert_tree.column("priority", width=85, stretch=False)
        self.alert_tree.column("event", width=390)
        self.alert_tree.column("expires", width=135, stretch=False)
        self.alert_tree.pack(fill="both", expand=True)
        self.alert_tree.bind("<<TreeviewSelect>>", self._show_selected_alert)
        self.alert_tree.tag_configure("Emergency", foreground="#a10000")
        self.alert_tree.tag_configure("Warning", foreground="#b34b00")
        self.alert_tree.tag_configure("Watch", foreground="#916900")
        ttk.Label(left, text="Select an alert for source details and local speech.").pack(anchor="w", pady=(5, 0))

        forecast_buttons = ttk.Frame(right)
        forecast_buttons.pack(fill="x")
        self.forecast_mode = tk.StringVar(value="daily")
        ttk.Radiobutton(forecast_buttons, text="7-day", value="daily", variable=self.forecast_mode, command=self._render_forecast).pack(side="left")
        ttk.Radiobutton(forecast_buttons, text="Hourly", value="hourly", variable=self.forecast_mode, command=self._render_forecast).pack(side="left")
        self.forecast_text = tk.Text(right, wrap="word", height=20, width=54, state="disabled")
        self.forecast_text.pack(fill="both", expand=True, pady=(5, 0))

        detail = ttk.LabelFrame(self.overview_tab, text="Selected official alert", padding=6)
        detail.pack(fill="x", pady=(8, 0))
        self.alert_detail = tk.Text(detail, wrap="word", height=5, state="disabled")
        self.alert_detail.pack(fill="x")
        detail_actions = ttk.Frame(detail)
        detail_actions.pack(fill="x", pady=(5, 0))
        ttk.Button(detail_actions, text="Speak Selected Alert Locally", command=self.speak_selected).pack(side="left")
        ttk.Button(detail_actions, text="Copy Alert Text", command=self.copy_selected).pack(side="left", padx=6)

    def _build_text_workstation(self) -> None:
        info = ttk.Label(
            self.text_tab,
            text="Compose a LOCAL DRAFT for review. Saving does not issue, forward, or broadcast a weather product.",
            foreground="#a12622", wraplength=1100,
        )
        info.pack(anchor="w", pady=(0, 8))
        header = ttk.LabelFrame(self.text_tab, text="AWIPS-style WMO header preview (draft only)", padding=8)
        header.pack(fill="x")
        fields = ttk.Frame(header)
        fields.pack(fill="x")
        self.ttaa_var = tk.StringVar(value="WUUS53")
        self.cccc_var = tk.StringVar(value="KLOT")
        self.bbb_var = tk.StringVar(value="NOR")
        self.wsfo_var = tk.StringVar(value="CHI")
        self.designator_var = tk.StringVar(value="LOT")
        self.addressee_var = tk.StringVar(value="ALL")
        for label, var, width in (
            ("TTAAii", self.ttaa_var, 10), ("CCCC", self.cccc_var, 8),
            ("BBB (optional)", self.bbb_var, 8), ("WSFO ID", self.wsfo_var, 8),
            ("Product", self.designator_var, 8), ("Addressee", self.addressee_var, 8),
        ):
            cell = ttk.Frame(fields)
            cell.pack(side="left", padx=(0, 12))
            ttk.Label(cell, text=label).pack(anchor="w")
            ttk.Entry(cell, textvariable=var, width=width).pack()
        ttk.Button(fields, text="Generate Header Preview", command=self.generate_header).pack(side="left", padx=8, pady=(14, 0))
        self.header_preview = tk.StringVar(value="Draft header has not been generated.")
        ttk.Label(header, textvariable=self.header_preview, font=("Consolas", 11, "bold")).pack(anchor="w", pady=(8, 0))

        content = ttk.Frame(self.text_tab)
        content.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.LabelFrame(content, text="Message routing preferences", padding=10)
        right.pack(side="right", fill="y", padx=(10, 0))
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Label(row, text="Product / hazard category").pack(side="left")
        self.category_var = tk.StringVar(value="Special Weather Statement")
        ttk.Combobox(row, textvariable=self.category_var, values=EVENT_CHOICES, state="readonly", width=34).pack(side="left", padx=8)
        ttk.Label(left, text="Message text / call to action").pack(anchor="w", pady=(8, 3))
        self.message_text = tk.Text(left, wrap="word", height=12, undo=True)
        self.message_text.pack(fill="both", expand=True)
        segment_bar = ttk.Frame(left)
        segment_bar.pack(fill="x", pady=6)
        ttk.Button(segment_bar, text="Add Segment", command=self.add_segment).pack(side="left")
        ttk.Button(segment_bar, text="Edit Segment", command=self.edit_segment).pack(side="left", padx=4)
        ttk.Button(segment_bar, text="Remove Segment", command=self.remove_segment).pack(side="left")
        ttk.Button(segment_bar, text="Combine Segments", command=self.combine_segments).pack(side="left", padx=4)
        ttk.Button(segment_bar, text="Add Hazard Segment", command=self.add_hazard_segment).pack(side="left")
        ttk.Button(segment_bar, text="View Saved Drafts", command=self.view_drafts).pack(side="right")

        self.send_bmh_var = tk.BooleanVar(value=True)
        self.send_email_var = tk.BooleanVar(value=False)
        self.send_iembot_var = tk.BooleanVar(value=False)
        self.send_web_var = tk.BooleanVar(value=False)
        ttk.Label(right, text="Destination intent (not connected)").pack(anchor="w")
        ttk.Checkbutton(right, text="Send to BMH", variable=self.send_bmh_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(right, text="Send to Email", variable=self.send_email_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(right, text="Send to IEMBOT", variable=self.send_iembot_var).pack(anchor="w", pady=2)
        ttk.Checkbutton(right, text="Send to websites / outlets", variable=self.send_web_var).pack(anchor="w", pady=2)
        ttk.Separator(right).pack(fill="x", pady=8)
        ttk.Label(right, text="These options are saved with the draft only.\nNo destination is contacted by this build.", wraplength=210).pack(anchor="w")
        ttk.Button(right, text="Save Local Draft", command=self.save_draft).pack(fill="x", pady=(12, 4))
        ttk.Button(right, text="Speak Draft Locally", command=self.speak_draft).pack(fill="x")

    def _build_network(self) -> None:
        ttk.Label(
            self.network_tab,
            text="BMH station monitor • station controllers are not presumed online; RF transmitters are not controlled here.",
            foreground="#a12622", wraplength=1100,
        ).pack(anchor="w", pady=(0, 8))
        top = ttk.Frame(self.network_tab)
        top.pack(fill="x")
        ttk.Button(top, text="Refresh NWS Alerts", command=self.refresh_data).pack(side="left")
        self.loop_button = ttk.Button(top, text="Start Local Alert Speech Loop", command=self.toggle_loop)
        self.loop_button.pack(side="left", padx=6)
        ttk.Label(top, text="Polling only; new alerts are spoken on local computer audio.").pack(side="right")

        station_frame = ttk.LabelFrame(self.network_tab, text="Configured station inventory (not a live transmitter-status claim)", padding=8)
        station_frame.pack(fill="x", pady=8)
        self.station_tree = ttk.Treeview(station_frame, columns=("city", "freq", "state"), show="headings", height=3)
        for col, title, width in (("city", "Location", 260), ("freq", "Reference frequency", 180), ("state", "Connection state", 330)):
            self.station_tree.heading(col, text=title)
            self.station_tree.column(col, width=width)
        self.station_tree.pack(fill="x")
        for station in self.config.get("stations", []):
            self.station_tree.insert("", "end", values=(
                station.get("city", ""), f'{float(station.get("frequency_mhz", 0)):.3f} MHz',
                "Not connected / monitoring only",
            ))
        live = ttk.LabelFrame(self.network_tab, text="Current official alerts and local queue", padding=8)
        live.pack(fill="both", expand=True)
        self.network_alert_list = tk.Listbox(live, height=12)
        self.network_alert_list.pack(fill="both", expand=True)
        ttk.Label(
            live,
            text="START TX / STOP TX, SAME header repetition, 1050 Hz alerting tones and EOM are intentionally not implemented.",
            foreground="#a12622", wraplength=1100,
        ).pack(anchor="w", pady=(6, 0))

    def _build_settings(self) -> None:
        grid = ttk.Frame(self.settings_tab)
        grid.pack(anchor="nw", fill="x")
        self.lat_var = tk.StringVar(value=str(self.config["latitude"]))
        self.lon_var = tk.StringVar(value=str(self.config["longitude"]))
        self.tz_var = tk.StringVar(value=str(self.config["timezone"]))
        self.agent_var = tk.StringVar(value=str(self.config["nws_user_agent"]))
        self.host_var = tk.StringVar(value=str(self.config.get("station_host", "127.0.0.1")))
        self.port_var = tk.StringVar(value=str(self.config.get("station_port", 6000)))
        self.refresh_var = tk.StringVar(value=str(self.config.get("refresh_minutes", 5)))
        self.voice_var = tk.StringVar(value=str(self.config.get("preferred_voice", "")))
        rows = [
            ("Latitude", self.lat_var), ("Longitude", self.lon_var),
            ("Local time zone", self.tz_var), ("NWS User-Agent / contact URL", self.agent_var),
            ("Station host (configuration only)", self.host_var), ("Station port (configuration only)", self.port_var),
            ("Refresh interval in minutes", self.refresh_var),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(grid, textvariable=var, width=62).grid(row=i, column=1, sticky="ew", pady=5)
        ttk.Label(grid, text="Installed TTS voice").grid(row=len(rows), column=0, sticky="w", padx=(0, 12), pady=5)
        voice_names = [name for name, _ in self.voice_options]
        self.voice_combo = ttk.Combobox(grid, textvariable=self.voice_var, values=voice_names, width=59)
        self.voice_combo.grid(row=len(rows), column=1, sticky="w", pady=5)
        ttk.Label(
            grid,
            text="Paul, David and Zira appear only if those voices are installed and exposed by Windows SAPI. A voice name is never assumed.",
            wraplength=780,
        ).grid(row=len(rows) + 1, column=1, sticky="w", pady=5)
        ttk.Button(grid, text="Save Settings", command=self.save_settings).grid(row=len(rows) + 2, column=1, sticky="w", pady=12)
        ttk.Label(
            self.settings_tab,
            text="The configured host/port are stored for future integration. This version does not open a network listener or send traffic to other stations.",
            foreground="#a12622", wraplength=1000,
        ).pack(anchor="w", pady=(14, 0))

    def _location_text(self) -> str:
        return f'Configured point: {self.config.get("latitude")}, {self.config.get("longitude")}'

    def _tick_clock(self) -> None:
        try:
            local_now = datetime.now(ZoneInfo(str(self.config.get("timezone", "America/Chicago"))))
            self.clock_var.set(local_now.strftime("%A, %B %d %Y  %I:%M:%S %p %Z"))
        except (ZoneInfoNotFoundError, ValueError):
            self.clock_var.set(datetime.now().astimezone().strftime("%A, %B %d %Y  %I:%M:%S %p %Z"))
        self.root.after(1000, self._tick_clock)

    def refresh_data(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        self.status_var.set("Connecting to the official NWS API…")
        def worker() -> None:
            try:
                client = NWSClient(self.config)
                alerts = client.active_alerts()
                daily, hourly = client.forecasts()
                self.root.after(0, lambda: self._apply_refresh(alerts, daily, hourly, None))
            except Exception as exc:
                self.root.after(0, lambda err=str(exc): self._apply_refresh([], [], [], err))
        threading.Thread(target=worker, daemon=True, name="nws-refresh").start()

    def _apply_refresh(self, alerts: list[dict[str, Any]], daily: list[dict[str, Any]],
                       hourly: list[dict[str, Any]], error: str | None) -> None:
        self._refreshing = False
        if error:
            self.status_var.set("NWS refresh failed — showing no new data.")
            messagebox.showerror("NWS data refresh failed", f"{error}\n\nCheck internet access and the configured User-Agent.")
            return
        self.alerts, self.daily_periods, self.hourly_periods = alerts, daily, hourly
        for tree in (self.alert_tree,):
            for item in tree.get_children():
                tree.delete(item)
        for i, feature in enumerate(self.alerts):
            p = feature.get("properties") or {}
            event = str(p.get("event") or "NWS alert")
            priority = classify_priority(event, str(p.get("severity") or ""))
            expires = str(p.get("ends") or p.get("expires") or "Not supplied")
            expires = expires.replace("T", " ").replace("+00:00", "Z")
            self.alert_tree.insert("", "end", iid=str(i), values=(priority, short_alert(feature), expires), tags=(priority,))
        self.network_alert_list.delete(0, "end")
        for feature in self.alerts:
            p = feature.get("properties") or {}
            priority = classify_priority(str(p.get("event") or ""), str(p.get("severity") or ""))
            self.network_alert_list.insert("end", f'[{priority}] {short_alert(feature)}')
        self._render_forecast()
        self.overview_location.configure(text=self._location_text())
        self.status_var.set(f"Updated from api.weather.gov — {len(self.alerts)} active alert(s); {datetime.now().astimezone():%H:%M:%S} local system time.")
        if not self.alerts:
            self.alert_detail.configure(state="normal")
            self.alert_detail.delete("1.0", "end")
            self.alert_detail.insert("1.0", "No active NWS alerts were returned for the configured point. This is a live result, not a generated test alert.")
            self.alert_detail.configure(state="disabled")

    def _render_forecast(self) -> None:
        self.forecast_text.configure(state="normal")
        self.forecast_text.delete("1.0", "end")
        mode = self.forecast_mode.get() if hasattr(self, "forecast_mode") else "daily"
        items = self.daily_periods if mode == "daily" else self.hourly_periods[:24]
        if not items:
            self.forecast_text.insert("1.0", "No forecast periods loaded yet.")
        else:
            for period in items:
                name = str(period.get("name") or period.get("startTime") or "Forecast")
                temp = period.get("temperature")
                unit = str(period.get("temperatureUnit") or "")
                short = str(period.get("shortForecast") or "")
                wind = str(period.get("windSpeed") or "")
                direction = str(period.get("windDirection") or "")
                detail = str(period.get("detailedForecast") or "")
                line = f"{name}: "
                if temp is not None:
                    line += f"{temp}°{unit}; "
                if short:
                    line += short + "; "
                if wind:
                    line += f"Wind {wind} {direction}; "
                self.forecast_text.insert("end", line.rstrip("; ") + "\n")
                if mode == "daily" and detail:
                    self.forecast_text.insert("end", detail + "\n")
                self.forecast_text.insert("end", "\n")
        self.forecast_text.configure(state="disabled")

    def _selected_alert(self) -> dict[str, Any] | None:
        selection = self.alert_tree.selection()
        if not selection:
            return None
        try:
            return self.alerts[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def _show_selected_alert(self, _event: Any = None) -> None:
        feature = self._selected_alert()
        self.alert_detail.configure(state="normal")
        self.alert_detail.delete("1.0", "end")
        if feature:
            p = feature.get("properties") or {}
            priority = classify_priority(str(p.get("event") or ""), str(p.get("severity") or ""))
            text = f'Priority: {priority}\nSource: National Weather Service API\n\n{format_alert(feature)}'
            self.alert_detail.insert("1.0", text)
        self.alert_detail.configure(state="disabled")

    def copy_selected(self) -> None:
        feature = self._selected_alert()
        if not feature:
            messagebox.showinfo("Select an alert", "Select an active NWS alert first.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(format_alert(feature))
        self.status_var.set("Selected official alert copied to clipboard.")

    def _chosen_voice_id(self) -> str:
        selected_name = self.voice_var.get() if hasattr(self, "voice_var") else str(self.config.get("preferred_voice", ""))
        for name, voice_id in self.voice_options:
            if name == selected_name:
                return voice_id
        return ""

    def _speak_async(self, text: str) -> None:
        voice_id = self._chosen_voice_id()
        def worker() -> None:
            try:
                SpeechService.speak(text, voice_id)
                self.root.after(0, lambda: self.status_var.set("Local speech playback finished."))
            except Exception as exc:
                self.root.after(0, lambda err=str(exc): messagebox.showerror("Local speech failed", err))
        threading.Thread(target=worker, daemon=True, name="local-speech").start()

    def speak_selected(self) -> None:
        feature = self._selected_alert()
        if not feature:
            messagebox.showinfo("Select an alert", "Select an active NWS alert first.")
            return
        self._speak_async(format_alert(feature))

    def add_segment(self) -> None:
        text = simpledialog.askstring("Add Segment", "Enter the message segment:", parent=self.root)
        if text and text.strip():
            current = self.message_text.get("1.0", "end").strip()
            joined = (current + "\n\n" if current else "") + text.strip()
            self.message_text.delete("1.0", "end")
            self.message_text.insert("1.0", joined)

    def edit_segment(self) -> None:
        current = self.message_text.get("1.0", "end").strip()
        if not current:
            messagebox.showinfo("Edit Segment", "There is no draft text to edit.")
            return
        replacement = simpledialog.askstring("Edit Segment", "Edit the complete draft text:", initialvalue=current, parent=self.root)
        if replacement is not None:
            self.message_text.delete("1.0", "end")
            self.message_text.insert("1.0", replacement)

    def remove_segment(self) -> None:
        self.message_text.delete("1.0", "end")

    def combine_segments(self) -> None:
        text = self.message_text.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Combine Segments", "Add at least one segment first.")
            return
        segments = [part.strip() for part in text.split("\n\n") if part.strip()]
        self.message_text.delete("1.0", "end")
        self.message_text.insert("1.0", " ".join(segments))

    def add_hazard_segment(self) -> None:
        category = self.category_var.get()
        hazard = simpledialog.askstring("Build Hazard Segment — draft only", "Hazard / event label:", initialvalue=category, parent=self.root)
        if hazard:
            area = simpledialog.askstring("Build Hazard Segment — draft only", "Affected area (plain text):", parent=self.root)
            action = simpledialog.askstring("Build Hazard Segment — draft only", "Recommended protective action:", parent=self.root)
            segment = f"{hazard.strip()}. Affected area: {(area or 'not specified').strip()}. {('Action: ' + action.strip()) if action and action.strip() else ''}".strip()
            existing = self.message_text.get("1.0", "end").strip()
            self.message_text.insert("end" if existing else "1.0", ("\n\n" if existing else "") + segment)

    def generate_header(self) -> None:
        ttaaii, cccc, bbb = self.ttaa_var.get().strip().upper(), self.cccc_var.get().strip().upper(), self.bbb_var.get().strip().upper()
        if len(tt aaii := ttaaii) != 6 or not ttaaii.isalnum():
            messagebox.showerror("Header preview", "TTAAii must be exactly six letters/numbers for this preview.")
            return
        if len(cccc) != 4 or not cccc.isalnum():
            messagebox.showerror("Header preview", "CCCC must be a four-character identifier, such as KLOT.")
            return
        if bbb and (len(bbb) != 3 or not bbb.isalnum()):
            messagebox.showerror("Header preview", "BBB must be blank or three letters/numbers.")
            return
        now_utc = datetime.now(timezone.utc)
        header = f"{ttaaii} {cccc} {now_utc:%d%H%M}" + (f" {bbb}" if bbb else "")
        extra = f"WSFO ID: {self.wsfo_var.get().strip().upper()} | Product: {self.designator_var.get().strip().upper()} | Addressee: {self.addressee_var.get().strip().upper()}"
        self.header_preview.set(header + "  —  DRAFT PREVIEW ONLY")
        self.status_var.set(extra)

    def _draft_body(self) -> str:
        return self.message_text.get("1.0", "end").strip()

    def save_draft(self) -> None:
        body = self._draft_body()
        if not body:
            messagebox.showinfo("Save Draft", "Enter message text before saving.")
            return
        draft = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "category": self.category_var.get(),
            "wmo_header_preview": self.header_preview.get(),
            "wsfo_id": self.wsfo_var.get().strip().upper(),
            "product_designator": self.designator_var.get().strip().upper(),
            "addressee": self.addressee_var.get().strip().upper(),
            "body": body,
            "destination_intent": {
                "bmh": self.send_bmh_var.get(), "email": self.send_email_var.get(),
                "iembot": self.send_iembot_var.get(), "websites": self.send_web_var.get(),
            },
            "dispatch_status": "LOCAL DRAFT — NOT SENT",
        }
        try:
            drafts = json.loads(DRAFTS_FILE.read_text(encoding="utf-8")) if DRAFTS_FILE.exists() else []
            if not isinstance(drafts, list):
                drafts = []
            drafts.append(draft)
            save_json(DRAFTS_FILE, drafts)
            self.status_var.set(f"Saved local draft #{len(drafts)}. No external destination was contacted.")
            messagebox.showinfo("Draft saved", "Draft saved locally. It was not transmitted or submitted to the NWS.")
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Draft could not be saved", str(exc))

    def speak_draft(self) -> None:
        body = self._draft_body()
        if not body:
            messagebox.showinfo("Speak Draft", "Enter draft text first.")
            return
        self._speak_async(body)

    def view_drafts(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Saved Drafts — local only")
        window.geometry("900x500")
        tree = ttk.Treeview(window, columns=("saved", "category", "status"), show="headings")
        for col, title, width in (("saved", "Saved (UTC)", 210), ("category", "Category", 250), ("status", "Dispatch status", 320)):
            tree.heading(col, text=title)
            tree.column(col, width=width)
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        try:
            drafts = json.loads(DRAFTS_FILE.read_text(encoding="utf-8")) if DRAFTS_FILE.exists() else []
        except (OSError, json.JSONDecodeError):
            drafts = []
        for i, draft in enumerate(drafts if isinstance(drafts, list) else []):
            tree.insert("", "end", iid=str(i), values=(draft.get("saved_at", ""), draft.get("category", ""), draft.get("dispatch_status", "LOCAL DRAFT")))
        body_view = tk.Text(window, height=8, wrap="word")
        body_view.pack(fill="x", padx=8, pady=(0, 8))
        def load_selected(_event: Any = None) -> None:
            selection = tree.selection()
            if not selection:
                return
            data = drafts[int(selection[0])]
            body_view.delete("1.0", "end")
            body_view.insert("1.0", data.get("body", ""))
        tree.bind("<<TreeviewSelect>>", load_selected)

    def save_settings(self) -> None:
        try:
            lat, lon = float(self.lat_var.get()), float(self.lon_var.get())
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Latitude must be −90 to 90 and longitude −180 to 180.")
            port = int(self.port_var.get())
            if not (1 <= port <= 65535):
                raise ValueError("Port must be between 1 and 65535.")
            minutes = int(self.refresh_var.get())
            if not (1 <= minutes <= 60):
                raise ValueError("Refresh interval must be 1–60 minutes.")
            tz_name = self.tz_var.get().strip()
            ZoneInfo(tz_name)
            agent = self.agent_var.get().strip()
            if not agent:
                raise ValueError("Please provide an identifying NWS User-Agent/contact URL.")
            self.config.update({
                "latitude": lat, "longitude": lon, "timezone": tz_name,
                "nws_user_agent": agent, "station_host": self.host_var.get().strip() or "127.0.0.1",
                "station_port": port, "refresh_minutes": minutes,
                "preferred_voice": self.voice_var.get().strip(),
            })
            save_json(CONFIG_FILE, self.config)
            self.client = NWSClient(self.config)
            self.overview_location.configure(text=self._location_text())
            self.status_var.set("Settings saved locally. Refreshing official NWS data…")
            self.refresh_data()
        except (ValueError, ZoneInfoNotFoundError, OSError) as exc:
            messagebox.showerror("Invalid settings", str(exc))

    def toggle_loop(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_stop.set()
            self.loop_button.configure(text="Start Local Alert Speech Loop")
            self.status_var.set("Stopping local speech loop…")
            return
        self._loop_stop.clear()
        self._loop_thread = threading.Thread(target=self._local_alert_loop, daemon=True, name="local-alert-loop")
        self._loop_thread.start()
        self.loop_button.configure(text="Stop Local Alert Speech Loop")
        self.status_var.set("Local alert speech loop started. This is not an RF transmitter.")

    def _local_alert_loop(self) -> None:
        announced: set[str] = set()
        while not self._loop_stop.is_set():
            try:
                client = NWSClient(self.config)
                for feature in client.active_alerts():
                    if self._loop_stop.is_set():
                        break
                    p = feature.get("properties") or {}
                    identifier = str(feature.get("id") or p.get("id") or short_alert(feature))
                    if identifier not in announced:
                        announced.add(identifier)
                        SpeechService.speak(format_alert(feature), self._chosen_voice_id())
                wait_seconds = max(60, int(self.config.get("refresh_minutes", 5)) * 60)
            except Exception as exc:
                self.root.after(0, lambda err=str(exc): self.status_var.set(f"Speech loop data error: {err}"))
                wait_seconds = 60
            self._loop_stop.wait(wait_seconds)
        self.root.after(0, lambda: self.loop_button.configure(text="Start Local Alert Speech Loop"))
        self.root.after(0, lambda: self.status_var.set("Local alert speech loop stopped."))

    def on_close(self) -> None:
        self._loop_stop.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        app = LOTIEMApp(root)
    except Exception as exc:
        messagebox.showerror("Startup error", str(exc))
        root.destroy()
        raise
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
