# Helping Eyes — Computer Vision-Based Document Reading System for the Visually Impaired

> **Mini Project (CS3905) — RV University, School of Computer Science and Engineering**

> **Team Members:**
> | Roll No. | Name |
> |---|---|
> | 1RVU23CSE304 | Neeraj Rajiv Shivam |
> | 1RVU23CSE504 | Tanmay M S |
> | 1RVU23CSE098 | Ayush R |
> | 1RVU23CSE503 | Tanmay |

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Introduction](#introduction)
3. [Objectives](#objectives)
4. [System Architecture](#system-architecture)
5. [Design Approach](#design-approach)
6. [Hardware Design & 3D-Printed Module](#hardware-design--3d-printed-module)
7. [Software Pipeline](#software-pipeline)
8. [Hardware & Software Requirements](#hardware--software-requirements)
9. [Repository Structure](#repository-structure)
10. [Environment Setup](#environment-setup)
11. [Installation](#installation)
12. [Running the System](#running-the-system)
13. [Usage & Controls](#usage--controls)
14. [Performance & Evaluation](#performance--evaluation)
15. [Testing & Validation](#testing--validation)
16. [Innovations](#innovations)
17. [Future Work](#future-work)
18. [Literature Survey](#literature-survey)
19. [References](#references)
20. [Troubleshooting](#troubleshooting)

---

## Problem Statement

Visually impaired individuals face significant barriers when accessing printed materials such as books, documents, and signage. Current assistive solutions suffer from several limitations:

- **Cost:** Most commercially available reading aids are expensive and out of reach for many users.
- **Portability:** Existing devices are bulky and not designed for everyday carry.
- **Low-light performance:** Real-time document reading in poor lighting conditions remains a challenge for traditional OCR-based systems.
- **Accuracy:** Conventional OCR pipelines struggle with blurred images, complex backgrounds, and varied fonts.

Helping Eyes addresses all of these gaps by delivering an affordable, compact, autonomous, and embedded reading solution.

---

## Introduction

**Helping Eyes** is an AI-powered assistive reading device designed specifically for visually impaired users. It combines embedded hardware with state-of-the-art AI software to create a seamless, hands-free reading experience.

Core capabilities:

- Captures printed documents in real time using an **ESP32-CAM** module.
- Enhances captured frames using **OpenCV** image preprocessing techniques.
- Detects document boundaries automatically before passing the image forward.
- Extracts text intelligently using a **Vision Language Model (VLM)** — replacing conventional OCR for dramatically improved accuracy.
- Converts the extracted text to natural speech via a **Text-to-Speech (TTS)** engine and delivers it through a speaker or earphone.

The entire pipeline runs with minimal user interaction, making the device highly accessible.

---

## Objectives

- Detect printed documents automatically from a live camera feed.
- Enhance captured images using OpenCV (denoising, contrast adjustment, perspective correction).
- Integrate a Vision Language Model (VLM) for context-aware, accurate text extraction.
- Convert extracted text into clear speech output.
- Package the complete system into a compact, wearable, and embedded assistive device.

---

## System Architecture

The end-to-end pipeline follows a linear flow from image capture to audio output:

```
Printed Document
      │
      ▼
ESP32-CAM (Image Acquisition)
      │
      ▼
Image Processing & Enhancement (OpenCV)
      │
      ▼
Document Detection (boundary / contour detection)
      │
      ▼
VLM Model — Text Extraction (Qwen3-VI-8B / Google Gemini)
      │
      ▼
Extracted Text
      │
      ▼
Text-to-Speech (TTS)
      │
      ▼
Audio Output (Speaker / Earphone)
```

---

## Design Approach

### Hardware Design

The physical device is housed in a **custom 3D-printed module** designed specifically for this project. The enclosure was modelled in Fusion 360 and offers:

- **Portability** — lightweight enough to be worn on the chest or clipped to clothing.
- **Device protection** — fully encloses the ESP32-CAM and power electronics.
- **User comfort** — ergonomic shape that sits flush against the body.
- **Compactness & stability** — all components (camera, battery, converter, charging module) integrated into a single unit.

### Software Design

| Stage | Component | Description |
|---|---|---|
| Image Acquisition | ESP32-CAM | Captures continuous document frames over Wi-Fi HTTP stream |
| Image Processing | OpenCV | Applies denoising, sharpening, adaptive thresholding, perspective warp |
| Document Detection | Contour / YOLO heuristics | Detects and crops the printed document region |
| Text Extraction | VLM (Qwen3-VI-8B or Gemini) | Context-aware, high-accuracy text recognition from the cropped image |
| Text-to-Speech | pyttsx3 / Windows SAPI | Converts extracted text to natural speech |
| Audio Output | Speaker / 3.5 mm jack | Delivers speech to the user |

---

## Hardware Design & 3D-Printed Module

The Fusion 360 enclosure houses all electronics and is designed to be 3D-printed. Below are renders and photos of the module:

### Fusion 360 Model Renders

| View | Image |
|---|---|
| Front View | *(add `docs/images/fusion360_front.png` here)* |
| Side View | *(add `docs/images/fusion360_side.png` here)* |
| Isometric View | *(add `docs/images/fusion360_iso.png` here)* |
| Exploded View | *(add `docs/images/fusion360_exploded.png` here)* |

To add your own renders, export images from Fusion 360 and place them in the `docs/images/` folder, then update the table above.

**Example (once images are added):**

```markdown
| Front View | ![Front](docs/images/fusion360_front.png) |
| Side View  | ![Side](docs/images/fusion360_side.png)  |
```

### Assembled Device

| Photo | Description |
|---|---|
| *(add `docs/images/device_assembled.jpg`)* | Fully assembled device with ESP32-CAM mounted |
| *(add `docs/images/device_wearable.jpg`)* | Device worn by a user during testing |

### Component Layout

The 3D-printed module integrates:
- **ESP32-CAM** — camera and Wi-Fi SoC
- **3.7V LiPo 600mAh battery** — portable power supply
- **MT3608 Boost Converter** — steps 3.7V up to the 5V required by the ESP32-CAM
- **TP4056 Battery Charging Module** — USB-C charging for the LiPo cell

---

## Hardware & Software Requirements

### Hardware

| Component | Specification |
|---|---|
| ESP32-CAM | AI-Thinker module with OV2640 camera |
| Battery | 3.7V LiPo, 600mAh |
| Boost Converter | MT3608, output 5V |
| Charging Module | TP4056 with USB-C input |
| Speaker / Earphone | 3.5mm jack or small 8Ω speaker |

### Software

| Component | Purpose |
|---|---|
| OpenCV | Image capture, preprocessing, document detection |
| NumPy | Array and matrix operations |
| Qwen3-VI-8B (via Ollama) | Local Vision Language Model for text extraction |
| Google Gemini API | Cloud VLM alternative (via `google-generativeai`) |
| pyttsx3 / pywin32 (SAPI) | Text-to-Speech engine (Windows) |
| Ultralytics YOLOv8 | Object/document detection (uses `yolov8n.pt`) |

> **Note:** Speech output currently uses Windows SAPI. Linux/macOS users should replace the TTS backend with `espeak` or another suitable library.

---

## Repository Structure

```
helping-eyes/
├── assitant.py                        # Gemini-cloud reader (simple version)
├── smart_reader_qwen_detection_fix.py # Full local Qwen pipeline with hybrid detection
├── test_hybrid.py                     # Experimental hybrid detection utilities
├── yolov8n.pt                         # YOLOv8 nano weights (required, keep in root)
├── requirment.txt                     # Python dependency list
├── .env                               # Environment variables (create this — see below)
├── docs/
│   └── images/                        # ← Place Fusion 360 renders and device photos here
│       ├── fusion360_front.png
│       ├── fusion360_side.png
│       ├── fusion360_iso.png
│       ├── fusion360_exploded.png
│       ├── device_assembled.jpg
│       └── device_wearable.jpg
└── README.md
```

---

## Environment Setup

Create a `.env` file in the project root:

```env
# IP address of the ESP32-CAM or phone IP camera
PHONE_IP=192.168.x.x

# --- For Gemini cloud reader (assitant.py) ---
API_KEY=<YOUR_GOOGLE_GENERATIVE_AI_KEY>

# --- For local Qwen via Ollama (smart_reader_qwen_detection_fix.py) ---
OLLAMA_HOST=http://localhost:11434
```

Camera stream URLs used by each script:
- `assitant.py` → `http://{PHONE_IP}:8080/video`
- `smart_reader_qwen_detection_fix.py` → `http://{PHONE_IP}:81/stream`

Adjust the URL constants inside each script if your camera app uses a different port or path.

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-org>/helping-eyes.git
cd helping-eyes

# 2. (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# 3. Install dependencies
python -m pip install -r requirment.txt

# 4. (Local Qwen only) Install and start Ollama, then pull the model
#    https://ollama.com/download
ollama pull qwen:3b-instruct    # or whichever Qwen vision model you prefer
ollama serve
```

Make sure `yolov8n.pt` is present in the project root (it is included in the repository).

---

## Running the System

### Option A — Gemini Cloud Reader (simple, requires internet + API key)

```bash
python assitant.py
```

### Option B — Local Qwen Reader (fully offline, more robust pipeline)

```bash
python smart_reader_qwen_detection_fix.py
```

---

## Usage & Controls

| Input | Action |
|---|---|
| `q` | Quit the application |
| `s` | Stop current speech output |
| `r` | Restart camera capture |
| Voice: `"stop"` / `"stop speaking"` | Stop speech (microphone must be active) |
| Voice: `"repeat"` | Repeat the last extracted text |
| Voice: `"next"` | Move to the next detected document region |

A window titled **Smart Reader** (or **Smart Reader - Qwen**) will display the live camera feed with detection overlays.

---

## Performance & Evaluation

### VLM vs. Traditional OCR (EasyOCR)

The system was benchmarked against EasyOCR on blurred real-world captures taken with the ESP32-CAM:

| Metric | EasyOCR | VLM (Qwen3-VI-8B) |
|---|---|---|
| Character Error Rate (CER) | 0.957 | **0.017** |
| Word Error Rate (WER) | 1.000 | **0.089** |
| Character Accuracy (%) | 4.28 | **98.26** |
| Word Accuracy (%) | 0.00 | **91.06** |
| Similarity (%) | 8.11 | **99.00** |

The VLM approach achieves near-perfect character accuracy (98.26%) vs. essentially 0% for EasyOCR on the same blurred images, demonstrating the decisive advantage of contextual vision-language understanding over traditional pixel-level OCR.

### Pipeline Latency

| Operation | Average Time |
|---|---|
| Frame Capture | 0.03 s |
| Document Detection | 0.10 s |
| Image Preprocessing | 0.15 s |
| VLM Processing | 10.0 s |
| Speech Generation | 1.0 s |

Total end-to-end latency is approximately **~11.3 seconds** per document read. The dominant cost is VLM inference; this can be reduced with a faster GPU, quantised models, or by switching to the Gemini cloud API.

---

## Testing & Validation

Three levels of testing were performed:

**Unit Testing** — Each module (camera capture, document detection, image preprocessing, VLM text extraction, speech generation) was tested in isolation to verify correct individual behaviour and expected output format.

**Integration Testing** — The communication between modules was validated end-to-end: ESP32-CAM → OpenCV preprocessing → VLM text extraction → TTS conversion, ensuring data passed cleanly across every boundary.

**System Testing** — The complete Helping Eyes pipeline was evaluated on real printed documents under realistic conditions (varying lighting, distances, and document types) to measure document detection rate, text extraction quality, and audio output clarity.

---

## Innovations

### 1. Vision Language Models Instead of Traditional OCR
Rather than relying solely on rule-based OCR (e.g. Tesseract, EasyOCR), Helping Eyes employs a VLM (Qwen3-VI-8B) that brings contextual understanding to text recognition. This yields dramatically higher accuracy on blurred, low-contrast, and real-world camera images — as confirmed by the evaluation metrics above.

### 2. Custom 3D-Printed Assistive Module
A purpose-built enclosure was designed in Fusion 360 and 3D-printed to create a wearable, compact form factor. The housing integrates all electronics and can be worn on the chest, providing a true hands-free experience without any commercially available housing.

### 3. Autonomous Document Reading Pipeline
The system detects, enhances, extracts, and reads aloud with minimal user interaction. No button presses or menu navigation are required — the device identifies when a document is in view and begins reading automatically, making it genuinely accessible for users with no or limited vision.

---

## Future Work

- **Improved low-light performance** — enhanced image capture with IR support or adaptive exposure tuning for challenging lighting and blurred/complex backgrounds.
- **Multilingual support** — extend TTS and VLM prompting to handle regional Indian languages (Kannada, Hindi, Tamil, etc.) and other international scripts.
- **Custom fine-tuned detection model** — train a domain-specific document detector to improve accuracy and reduce latency compared to the general-purpose YOLOv8 baseline.
- **Mobile app connectivity** — a companion smartphone app for remote monitoring, configuration, and speech relay over Bluetooth.
- **On-device inference** — explore lighter VLMs (e.g. Qwen-0.5B, moondream2) suitable for running directly on a Raspberry Pi Zero 2W to eliminate the Wi-Fi dependency.

---

## Literature Survey

| Title | Authors | Year | Methodology | Key Features | Limitations |
|---|---|---|---|---|---|
| Novel ML-based Text-To-Speech Device for Visually Impaired | U. Gawande et al. | 2023 | Raspberry Pi + Camera, OCR, TTS | Portable, low-cost | OCR accuracy depends on image quality |
| Smart Reader for Blind People | Deepti S R et al. | 2023 | Raspberry Pi, 5MP camera, offline pyttsx3 TTS | Offline TTS, Kannada + English | High processing time (~26 s), accuracy drops on blur |
| Assistive Reading System using OCR and TTS | Akshay Sharma et al. | 2014 | OCR with connected component labelling, concatenative synthesis TTS | Printed text to speech, saveable audio | Printed text only, quality depends on image |
| EasyOCR: Ready-to-use OCR with Deep Learning | JaidedAI | 2020 | Deep learning OCR | Multi-language text extraction | Performance degrades on blurred images |

---

## References

1. U. Gawande, N. Rathod, P. Bodkhe, P. Kolhe, H. Amlani and C. Thaokar, "Novel Machine Learning based Text-To-Speech Device for Visually Impaired People," *2023 2nd International Conference on Smart Technologies and Systems for Next Generation Computing (ICSTSN)*, Villupuram, India, 2023, pp. 1–5. doi: 10.1109/ICSTSN57873.2023.10151637

2. D. S R, V. K. Gowda, R. Rai R, S. Kumar S and V. K P, "Smart Reader for Blind People," *2025 International Conference in Advances in Power, Signal, and Information Technology (APSIT)*, Bhubaneswar, India, 2025, pp. 1–4. doi: 10.1109/APSIT63993.2025.11086193

3. A. Sharma, A. Srivastava, and A. Vashishth, "An Assistive Reading System for Visually Impaired using OCR and TTS," *International Journal of Computer Applications*, vol. 95, no. 2, pp. 13–18, Jun. 2014. doi: 10.5120/16566-6231

4. JaidedAI, "EasyOCR: Ready-to-use OCR with 80+ supported languages." GitHub. https://github.com/JaidedAI/EasyOCR

---

## Troubleshooting

| Issue | Solution |
|---|---|
| Cannot connect to camera stream | Verify `PHONE_IP` in `.env`. Confirm the camera app / ESP32 is streaming at the URL printed on startup. |
| Ollama / Qwen errors | Ensure `ollama serve` is running and the model is pulled: `ollama pull qwen:3b-instruct` |
| Google Gemini API failures | Check `API_KEY` in `.env` and network connectivity. |
| No speech output | Confirm Windows SAPI is installed. On Linux/macOS, replace the TTS backend with `espeak` or `pyttsx3` with a compatible driver. |
| `yolov8n.pt` not found | The weights file must be present in the project root. Download from [Ultralytics](https://github.com/ultralytics/assets/releases) if missing. |
| Very slow VLM inference | Use a GPU if available. Alternatively switch to the Gemini cloud API for faster response times. |

---

*Helping Eyes — School of Computer Science and Engineering, RV University, Bangalore.*
