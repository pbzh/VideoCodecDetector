# VideoCodecDetector

A desktop GUI tool that scans a folder for video files, detects each file's codec, tag, profile and level using **ffprobe**, lets you filter results by codec tag, and move selected files to another folder.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

- Recursively scans a folder for video files
- Detects **codec**, **codec tag** (e.g. `avc1`, `hev1`), **profile**, **level**, **resolution**, **duration**, and **file size** via ffprobe
- Color-coded results table per codec
- Filter visible files by codec tag using live checkboxes
- Select individual files via checkbox column, or use **All / None**
- Move selected files to a destination folder with automatic name-collision handling
- Non-blocking scan with a **Stop** button and live progress bar
- Works on retina / HiDPI displays and over RDP

## Requirements

**Python packages**
```
pip install customtkinter
```

**ffprobe** (part of FFmpeg) must be on your PATH.

| Platform | Install |
|---|---|
| Windows | [ffmpeg.org/download.html](https://ffmpeg.org/download.html) — extract and add the `bin` folder to PATH |
| macOS | `brew install ffmpeg` |
| Linux | `sudo apt install ffmpeg` |

Verify with:
```
ffprobe -version
```

## Usage

```
python VideoCodecDetector.py
```

1. Set the **Source** folder — the tool will scan it recursively
2. Click **Scan**
3. Use the **Filter** checkboxes to show/hide files by codec tag
4. Check the **☑** column to select files
5. Set a **Destination** folder and click **Move Selected**

## Supported formats

`.mov` `.mp4` `.mkv` `.avi` `.m4v` `.mpg` `.mpeg` `.m2ts` `.mts` `.ts` `.wmv` `.flv` `.webm` `.3gp` `.f4v`

## Table columns

| Column | Description |
|---|---|
| ☑ | Selection checkbox |
| File Name | File name |
| Codec | Internal codec name (e.g. `H264`, `HEVC`) |
| Tag | FourCC codec tag (e.g. `avc1`, `hev1`, `mp4v`) |
| Profile / Level | Codec profile and level (e.g. `High @ L4.1`) |
| Resolution | Width × Height in pixels |
| Duration | `HH:MM:SS` or `MM:SS` |
| Size | File size |
| Folder | Parent directory |
