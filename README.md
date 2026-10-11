# BMH — NOAA Weather Radio / LOTIEM & LOTWPS

A Python/Tkinter starting point for the KLOT LOTWPS Text Workstation and BMH monitoring concept. This build retrieves **real, live public National Weather Service data**. It is not a generated-weather demo, but it is also **not an authorized NOAA Weather Radio transmitter or public warning-originating system**.

## What works in this first build

- Live NWS active-alert lookup for the configured latitude/longitude, using the official api.weather.gov service.
- Official NWS 7-day and hourly point forecasts.
- Priority-sorted alert list: Emergency, Warning, Watch, Advisory, Statement.
- Alert details, copy-to-clipboard, and local text-to-speech.
- Windows SAPI voices are discovered from voices actually installed on the computer. Paul, David, and Zira are available only if Windows exposes them; the app will not falsely claim an unavailable voice is installed.
- A Tkinter KLOT Text Workstation for draft composition, editable message segments, an AWIPS-style WMO-header preview, and local JSON draft storage.
- A BMH monitor for configured station inventory (WXK89 / Valparaiso and KBB57 / Gary), plus an optional loop that polls live NWS alerts and speaks newly seen alerts locally.
- Settings for coordinates, timezone, NWS User-Agent, voice, refresh interval, and station host/port metadata.
- Automatic local-time display using America/Chicago, including daylight-saving transitions via Python's zoneinfo.

## Explicitly not implemented

This repository is an application foundation, not a drop-in replacement for an NWS Weather Forecast Office or licensed broadcast chain. It does not:

- key an RF transmitter or claim that a physical transmitter is online;
- create or transmit SAME/EAS headers, the 1050 Hz attention tone, EOM bursts, or repeated alerting sequences;
- issue or submit warnings, watches, advisories, or civil/emergency messages to the NWS, IPAWS, IEMBOT, email, news outlets, or other public destinations;
- connect to an actual AWIPS, WarnGen, WatchGen, HazCollect, LOTIEM server, or station controller;
- fabricate climate normals/records, radar data, storm polygons, or model guidance;
- automatically translate official NWS warning text into Turkish, German, Spanish, or French.

The routing checkboxes are **saved draft intent only**. START/STOP RF transmission controls are intentionally absent. Station entries are inventory/configuration—not evidence of a live connected transmitter. Use authorized, certified, vendor-supported alerting equipment and procedures for real public alert transmission.

## Install on Windows

Python 3.10+ is recommended. Tkinter is included with the standard Windows Python installer.

    git clone https://github.com/nicholasgville23/LOTIEM-and-LOTWPS.git
    cd LOTIEM-and-LOTWPS
    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    copy config.example.json config.json
    python main.py

If PowerShell blocks activation, you can run the environment's interpreter directly: .\.venv\Scripts\python.exe main.py

On first launch the app contacts api.weather.gov over HTTPS. Keep the nws_user_agent identifying the application and linking to a maintained contact page. Set the coordinates to the point you want to monitor. The provided point is an approximate Valparaiso, Indiana reference; it is not a substitute for a station's commissioned coverage configuration.

## Voice setup

Open System Settings and choose one of the voices actually listed. The app uses pyttsx3 with the local operating system speech engine. An external VoiceText executable such as VTEditor_ENG.exe is not launched because its command-line/audio-control interface is not established here. Use the vendor's documented interface if you separately integrate that software.

## Configuration

config.example.json is a template. The running app writes local settings to config.json and draft messages to drafts.json. These files are intentionally ignored by git. Station host/port values are stored as future integration settings; this build does not open a listener.

- latitude / longitude: forecast and active-alert point.
- timezone: defaults to America/Chicago.
- nws_user_agent: identifiable application/contact string for NWS API requests.
- stations: editable local inventory of station IDs and reference frequencies.

## Tests

    python -m unittest discover -s tests -v

## Data provenance

NWS data is fetched on demand from the public NWS API. The source alert/forecast wording is retained as supplied by NWS; this first build does not rewrite official alert text. A network error is reported rather than replaced with synthetic weather data.

- API docs: https://www.weather.gov/documentation/services-web-API
- NWS alerts docs: https://www.weather.gov/documentation/services-web-alerts
