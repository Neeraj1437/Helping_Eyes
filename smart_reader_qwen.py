import cv2
import time
import threading
import os
import re
import numpy as np
import pythoncom
import win32com.client
from win32com.client import constants as c
from openai import OpenAI
from ultralytics import YOLO
from dotenv import load_dotenv
from PIL import Image
import speech_recognition as sr
import queue
import logging
import base64
import io
from typing import Tuple, Optional
from collections import deque

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
load_dotenv()
PHONE_IP = os.getenv("PHONE_IP")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")

if not PHONE_IP:
    raise RuntimeError("PHONE_IP missing from .env")

# ================= QWEN 3B MODEL =================
"""
Install Qwen 3B model using:
    ollama pull qwen:3b
or
    ollama pull qwen:3b-instruct

Start Ollama server:
    ollama serve

The model will be downloaded and available at the configured OLLAMA_HOST
"""

try:
    # client = Client(host=OLLAMA_HOST)
    client = OpenAI(
        base_url=f"{OLLAMA_HOST}/v1",
        api_key="lm-studio",
        timeout=50.0
    )
    logger.info(f"✅ Ollama client connected at {OLLAMA_HOST}")
except Exception as e:
    logger.error(f"❌ Failed to connect to Ollama: {e}")
    logger.info("Please ensure Ollama is running and Qwen 3B model is installed")

MODEL_NAME = "qwen/qwen3-v1-4b"  # Lightweight instruct model
MAX_TOKENS = 1024
TEMPERATURE = 0.3

# ================= API CONTROL =================
LAST_API_CALL = 0
API_COOLDOWN = 10  
MAX_RETRIES = 3
RETRY_DELAY = 1
LAST_SUCCESSFUL_READ = 0
MIN_READ_INTERVAL = 15  # seconds

# ================= CAMERA ROTATION =================
CAMERA_ROTATION = -90

# ================= YOLO =================
finder_ai = YOLO("yolov8n.pt")
TARGET_CLASSES = [73, 63, 65]  # Book, Laptop, Remote

# ================= SPEECH (SAFE ASYNC MODE) =================
_speech_queue = queue.Queue(maxsize=50)
_speech_lock = threading.Lock()
_speech_event = threading.Event()
_stop_signal = threading.Event()
_stop_worker = threading.Event()
is_speaking = False

def _speech_worker():
    """Speech synthesis worker with robust error handling"""
    global is_speaking
    try:
        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        logger.info("✅ Speech worker initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize speech: {e}")
        return
    
    while not _stop_worker.is_set():
        try:
            _speech_event.wait(timeout=1)
            
            if _stop_worker.is_set():
                break
            
            _speech_event.clear()
            
            try:
                text = _speech_queue.get(block=False)
            except queue.Empty:
                continue
            
            if text is None:  # Stop signal
                try:
                    voice.Speak("", 3)
                    _speech_queue.queue.clear()
                except:
                    pass
                is_speaking = False
                _stop_signal.clear()
                continue
            
            is_speaking = True
            try:
                voice.Speak(text, 1)
                
                while voice.Status.RunningState == 2:
                    if _stop_signal.is_set():
                        try:
                            voice.Speak("", 3)
                        except:
                            pass
                        _stop_signal.clear()
                        break
                    time.sleep(0.05)
            except Exception as e:
                logger.error(f"⚠️ Speech error: {e}")
            finally:
                is_speaking = False
                
        except Exception as e:
            logger.error(f"❌ Speech worker error: {e}")
            time.sleep(1)

_speech_thread = threading.Thread(target=_speech_worker, daemon=True)
_speech_thread.start()

def speak(text: str, priority: bool = False) -> None:
    """Queue text for speech synthesis with overflow handling"""
    if not text or not text.strip():
        return
    
    try:
        clean = re.sub(r"[*#_`~]", "", text)
        clean = clean.strip()
        
        if not clean:
            return
        
        print(f"🗣️ {clean[:120]}")
        logger.info(f"Speaking: {clean[:80]}")
        
        try:
            _speech_queue.put(clean, block=False)
        except queue.Full:
            logger.warning("⚠️ Speech queue full, skipping")
            return
        
        _speech_event.set()
    except Exception as e:
        logger.error(f"❌ Speak error: {e}")

def stop_speech() -> None:
    """Stop all speech and clear queue"""
    try:
        print("🛑 Stopping speech")
        _stop_signal.set()
        
        try:
            while not _speech_queue.empty():
                _speech_queue.get_nowait()
        except queue.Empty:
            pass
        
        _speech_event.set()
        time.sleep(0.2)
    except Exception as e:
        logger.error(f"❌ Stop speech error: {e}")

def restart_capture():
    """Stop speech and restart capture flow"""
    global _restart_capture

    print("🔄 Restarting capture")

    stop_speech()

    _restart_capture = True

# ================= VOICE CONTROL =================
_voice_thread_running = True
_force_next_capture = False
_restart_capture = False

def voice_listener(get_last_text_callback) -> None:
    """Voice command listener with error recovery"""
    global _force_next_capture, _voice_thread_running

    try:
        recognizer = sr.Recognizer()
        mic = sr.Microphone()

        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=1)

        print("🎤 Voice control active...")
        logger.info("Voice listener started")

    except Exception as e:
        logger.error(f"❌ Voice listener initialization failed: {e}")
        return

    while _voice_thread_running:
        try:
            if is_speaking:
                time.sleep(0.1)
                continue

            with mic as source:
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=2)

            try:
                command = recognizer.recognize_google(audio).lower()
                print(f"🎤 Heard: {command}")
                logger.info(f"Command: {command}")

                if "stop" in command or "stop speaking" in command:
                    stop_speech()
                elif "repeat" in command:
                    stop_speech()
                    time.sleep(0.5)
                    last_text = get_last_text_callback()
                    if last_text and last_text.strip():
                        speak(last_text)
                    else:
                        speak("Nothing to repeat")
                elif "next" in command:
                    stop_speech()
                    time.sleep(0.5)
                    _force_next_capture = True
                    speak("Next content")
            except sr.UnknownValueError:
                pass
            except sr.RequestError as e:
                logger.warning(f"⚠️ Google API error: {e}")

        except sr.WaitTimeoutError:
            continue
        except Exception as e:
            logger.error(f"❌ Voice error: {e}")
            time.sleep(1)

# ================= IMAGE PREPROCESSING =================
def preprocess_image(frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Advanced image preprocessing for better OCR results
    Returns: (original, preprocessed)
    """
    try:
        if len(frame.shape) == 2:
            processed = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            processed = frame.copy()
        
        # 1. CONTRAST & BRIGHTNESS ADJUSTMENT
        lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        processed = cv2.merge([l, a, b])
        processed = cv2.cvtColor(processed, cv2.COLOR_LAB2BGR)
        
        # 2. DENOISE
        try:
            processed = cv2.fastNlMeansDenoisingColored(
                processed, 
                None, 
                h=10,
                templateWindowSize=7, 
                searchWindowSize=21
            )
        except TypeError:
            pass
        
        # 3. SHARPENING
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]]) / 1.0
        processed = cv2.filter2D(processed, -1, kernel)
        
        # 4. GAMMA CORRECTION
        gamma = 1.2
        inv_gamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        processed = cv2.LUT(processed, table)
        
        # 5. BILATERAL FILTER
        processed = cv2.bilateralFilter(processed, 9, 75, 75)
        
        logger.debug("✅ Image preprocessing completed successfully")
        return frame, processed
    
    except Exception as e:
        logger.error(f"⚠️ Preprocessing error: {e}, returning original frame")
        return frame, frame

# ================= IMAGE TO BASE64 =================
def image_to_base64(image: np.ndarray) -> str:
    """Convert numpy array image to base64 string"""
    try:
        # Convert BGR to RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        # Convert to PIL Image
        pil_image = Image.fromarray(image_rgb)
        # Convert to base64
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return img_base64
    except Exception as e:
        logger.error(f"❌ Image to base64 conversion error: {e}")
        return None

# ================= TEXT UTILS =================
def normalize_text(t: str) -> str:
    """Normalize text for comparison"""
    t = re.sub(r"[^a-z0-9\s]", "", t.lower())
    return re.sub(r"\s+", " ", t).strip()

def similarity(a: str, b: str) -> float:
    """Calculate Jaccard similarity between two texts"""
    if not a or not b:
        return 0.0
    sa, sb = set(normalize_text(a).split()), set(normalize_text(b).split())
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0

# ================= OCR ANALYSIS WITH QWEN =================
IGNORE_THRESHOLD = 0.96
PARTIAL_THRESHOLD = 0.80

def analyze_image(frame: np.ndarray, last_text: str) -> str:
    """
    Analyze image with Qwen 3B model using vision capabilities
    """
    global LAST_API_CALL, _force_next_capture
    global LAST_SUCCESSFUL_READ

    if time.time() - LAST_SUCCESSFUL_READ < MIN_READ_INTERVAL:
        logger.info("⏳ Read interval active")
        return last_text

    max_wait = 0
    while is_speaking and max_wait < 30:
        time.sleep(0.05)
        max_wait += 1

    elapsed = time.time() - LAST_API_CALL
    if elapsed < API_COOLDOWN:
        logger.info(f"⏳ Cooldown ({API_COOLDOWN - elapsed:.1f}s remaining)")
        return last_text

    speak("Reading")
    
    original, preprocessed = preprocess_image(frame)
    
    h, w = preprocessed.shape[:2]
    if w > 1280:
        scale = 1280 / w
        preprocessed = cv2.resize(preprocessed, (1280, int(h * scale)))
        logger.info(f"📐 Resized image to {preprocessed.shape[1]}x{preprocessed.shape[0]}")

    # Convert image to base64
    img_base64 = image_to_base64(preprocessed)
    if not img_base64:
        speak("Image conversion failed")
        return last_text

    text = None
    for attempt in range(MAX_RETRIES):
        try:
            LAST_API_CALL = time.time()
            
            # Prepare message with image for Qwen
            message = {
                "role": "user",
                "content": "Extract ALL visible text exactly as it appears. Include all words, numbers, punctuation. Preserve formatting and line breaks where possible. If text is upside down or rotated, correct the orientation first. Return ONLY the extracted text without any explanation.",
                "images": [img_base64]
            }
            
            logger.info(f"🔄 Sending request to Qwen (attempt {attempt + 1}/{MAX_RETRIES})")
            
            # response = client.chat(
            #     model=MODEL_NAME,
            #     messages=[message],
            #     stream=False,
            #     options={
            #         "temperature": TEMPERATURE,
            #         "num_predict": MAX_TOKENS,
            #     }
            # )
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract ALL visible text exactly as it appears."
                                # "text": """
                                #     Extract all visible text exactly as written.

                                #     Rules:
                                #     - Preserve line order
                                #     - Preserve punctuation
                                #     - Preserve paragraphs
                                #     - Do not summarize
                                #     - Do not explain
                                #     - Do not hallucinate
                                #     - Do not repeat text
                                #     - If unclear write [unclear]

                                #     After OCR provide:
                                #     1. Short scene description
                                #     2. Important obstacles if visible
                                #     """
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_base64}"
                                }
                            }
                        ]
                    }
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS
            )

            text = response.choices[0].message.content
            
            # if response and response.get("message") and response["message"].get("content"):
            #     extracted_text = response["message"]["content"].strip()
                
            #     if len(extracted_text) >= 5:
            #         text = extracted_text
            #         LAST_SUCCESSFUL_READ = time.time()
            #         logger.info(f"✅ OCR successful (attempt {attempt + 1})")
            #         logger.debug(f"Extracted text preview: {text[:100]}...")
            #         break
            #     else:
            #         logger.warning(f"⚠️ Empty or very short response (attempt {attempt + 1})")
            # else:
            #     logger.warning(f"⚠️ Invalid response structure (attempt {attempt + 1})")
        
        except Exception as e:
            error_str = str(e)
            logger.error(f"❌ Model error (attempt {attempt + 1}): {error_str[:100]}")
            
            if "connection" in error_str.lower():
                logger.error("❌ Cannot connect to Ollama. Is it running?")
                speak("Cannot connect to AI model. Is Ollama running?")
                return last_text
            elif "model" in error_str.lower() or "not found" in error_str.lower():
                logger.error("❌ Qwen model not found. Pull it with: ollama pull qwen:3b-instruct")
                speak("AI model not found. Please install it.")
                return last_text
            else:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
    
    if not text:
        logger.warning("❌ All retry attempts failed")
        speak("Could not read text. Try again.")
        return last_text

    if _force_next_capture:
        _force_next_capture = False
        speak(text)
        return text

    sim = similarity(text, last_text)
    logger.info(f"📊 Similarity: {sim:.2f}")

    if sim >= IGNORE_THRESHOLD:
        speak("Same content")
        return last_text

    if PARTIAL_THRESHOLD <= sim < IGNORE_THRESHOLD:
        delta_words = [
            w for w in normalize_text(text).split()
            if w not in normalize_text(last_text).split()
        ]
        if len(delta_words) >= 5:
            delta = " ".join(delta_words)
            speak("New text")
            speak(delta)
            return last_text + " " + delta
        return last_text

    speak(text)
    return text

# ================= BACKGROUND FRAME READER =================
class BackgroundFrameReader(threading.Thread):
    """
    Continuously reads frames in background to prevent buffer overflow
    Stores latest frame in a ring buffer
    """
    
    def __init__(self, phone_ip: str, buffer_size: int = 5):
        super().__init__(daemon=True)
        self.phone_ip = phone_ip
        self.stream_url = f"http://{phone_ip}:81/stream"
        self.cap = None
        self.buffer = deque(maxlen=buffer_size)
        self.buffer_lock = threading.Lock()
        self.running = True
        self.connected = False
        self.consecutive_failures = 0
        self.max_failures = 10
        self.frame_delay = 1.0 / 15.0  # avoid overloading the ESP32-CAM
        
    def connect(self) -> bool:
        """Connect to camera stream"""
        try:
            self.cap = cv2.VideoCapture(self.stream_url)
            
            # Minimize buffer and avoid forcing unsupported HTTP MJPEG properties
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Test connection
            ret, frame = self.cap.read()
            if ret and frame is not None and frame.size > 0:
                h, w = frame.shape[:2]
                logger.info(f"✅ Background reader connected at {w}x{h}")
                self.connected = True
                self.consecutive_failures = 0
                with self.buffer_lock:
                    self.buffer.append(frame)
                return True
            logger.warning("⚠️ Background reader connected but no valid frame returned")
            self.close()
            return False
        except Exception as e:
            logger.error(f"❌ Background reader connection error: {e}")
            self.close()
            return False
    
    def run(self):
        """Continuously read frames in background"""
        logger.info("🔄 Background frame reader started")
        
        while self.running:
            try:
                if self.cap is None or not self.connected:
                    if not self.connect():
                        time.sleep(2)
                        continue
                
                ret, frame = self.cap.read()
                
                if ret and frame is not None and frame.size > 0:
                    with self.buffer_lock:
                        self.buffer.append(frame)
                    self.consecutive_failures = 0
                    time.sleep(self.frame_delay)
                else:
                    self.consecutive_failures += 1
                    logger.warning(f"⚠️ Background read failure {self.consecutive_failures}/{self.max_failures}")
                    
                    if self.consecutive_failures >= self.max_failures:
                        logger.info("🔄 Background reader reconnecting...")
                        self.close()
                        time.sleep(2)
                        if not self.connect():
                            time.sleep(2)
            
            except Exception as e:
                logger.error(f"❌ Background reader error: {e}")
                self.consecutive_failures += 1
                time.sleep(1)
    
    def get_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Get latest frame from buffer"""
        try:
            with self.buffer_lock:
                if len(self.buffer) > 0:
                    return True, self.buffer[-1]
            return False, None
        except Exception as e:
            logger.error(f"❌ Error getting frame: {e}")
            return False, None
    
    def close(self):
        """Close connection safely"""
        try:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
            self.connected = False
            logger.info("✅ Background reader disconnected")
        except Exception as e:
            logger.error(f"⚠️ Error closing background reader: {e}")
    
    def stop(self):
        """Stop the background reader"""
        self.running = False
        time.sleep(0.5)
        self.close()

# ================= MAIN =================
def main():
    """Main application loop with background frame reading"""
    global _force_next_capture, _voice_thread_running, LAST_API_CALL, _restart_capture

    # Start background frame reader
    frame_reader = BackgroundFrameReader(PHONE_IP)
    frame_reader.start()
    
    # Give reader time to connect
    time.sleep(2)
    
    if not frame_reader.connected:
        logger.error("❌ Failed to start background frame reader")
        frame_reader.stop()
        return

    speak("System online. Show me a document.")

    last_text = ""
    
    # Start voice listener
    voice_thread = threading.Thread(
        target=voice_listener,
        args=(lambda: last_text,),
        daemon=True
    )
    voice_thread.start()

    stable_start = 0
    is_stable = False
    HOLD_TIME = 0.3
    
    # ================= GUIDE BOX CONFIG =================
    DISPLAY_W, DISPLAY_H = 720, 1280
    GUIDE_MARGIN_X = 30
    GUIDE_MARGIN_Y = 20
    GUIDE_X1, GUIDE_Y1 = GUIDE_MARGIN_X, GUIDE_MARGIN_Y
    GUIDE_X2, GUIDE_Y2 = DISPLAY_W - GUIDE_MARGIN_X, DISPLAY_H - GUIDE_MARGIN_Y
    
    GUIDE_COLOR_IDLE   = (180, 180, 180)
    GUIDE_COLOR_DETECT = (0, 200, 255)
    GUIDE_COLOR_HOLD   = (0, 165, 255)
    GUIDE_COLOR_READY  = (0, 255, 0)

    last_spoken_hint = ""
    last_hint_time = 0
    HINT_COOLDOWN = 2.0

    frame_skip_counter = 0
    FRAME_SKIP = 1

    # ================= HELPER FUNCTIONS =================
    def draw_guide_box(img, color, label=None):
        corner_len = 30
        thickness = 2
        corners = [(GUIDE_X1, GUIDE_Y1, 1, 1), (GUIDE_X2, GUIDE_Y1, -1, 1),
                   (GUIDE_X1, GUIDE_Y2, 1, -1), (GUIDE_X2, GUIDE_Y2, -1, -1)]
        for (cx, cy, dx, dy) in corners:
            cv2.line(img, (cx, cy), (cx + dx * corner_len, cy), color, thickness + 1)
            cv2.line(img, (cx, cy), (cx, cy + dy * corner_len), color, thickness + 1)
        cv2.rectangle(img, (GUIDE_X1, GUIDE_Y1), (GUIDE_X2, GUIDE_Y2), color, 1)
        if label:
            cv2.putText(img, label, (GUIDE_X1, GUIDE_Y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    def book_inside_guide(x1, y1, x2, y2):
        overlap_x1, overlap_y1 = max(x1, GUIDE_X1), max(y1, GUIDE_Y1)
        overlap_x2, overlap_y2 = min(x2, GUIDE_X2), min(y2, GUIDE_Y2)
        if overlap_x2 <= overlap_x1 or overlap_y2 <= overlap_y1:
            return 0.0
        overlap_area = (overlap_x2 - overlap_x1) * (overlap_y2 - overlap_y1)
        book_area = (x2 - x1) * (y2 - y1)
        return overlap_area / book_area if book_area > 0 else 0.0

    MIN_DOC_COVERAGE = 0.10

    def get_placement_guidance(x1, y1, x2, y2):
        book_cx, book_cy = (x1 + x2) // 2, (y1 + y2) // 2
        guide_cx, guide_cy = (GUIDE_X1 + GUIDE_X2) // 2, (GUIDE_Y1 + GUIDE_Y2) // 2
        hints = []
        if book_cx > guide_cx + 40:
            hints.append("Move Left")
        elif book_cx < guide_cx - 40:
            hints.append("Move Right")
        if book_cy > guide_cy + 40:
            hints.append("Move Up")
        elif book_cy < guide_cy - 40:
            hints.append("Move Down")
        return hints

    def get_distance_guidance(x1, y1, x2, y2, frame_w, frame_h):
        area = max(0, x2 - x1) * max(0, y2 - y1)
        coverage = area / float(frame_w * frame_h)
        if coverage < MIN_DOC_COVERAGE:
            return "Move closer"
        return ""

    def find_document_region(img: np.ndarray, min_area: int = 25000) -> Tuple[bool, int, int, int, int]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        thresh = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            25,
            10
        )

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 21))
        processed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        processed = cv2.dilate(processed, kernel, iterations=2)
        processed = cv2.erode(processed, kernel, iterations=1)

        contours, _ = cv2.findContours(processed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_box = None
        best_area = 0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            ratio = w / float(h) if h else 0
            if ratio < 0.3 or ratio > 3.5:
                continue

            if area > best_area:
                best_area = area
                best_box = (x, y, x + w, y + h)

        if best_box is not None:
            return True, best_box[0], best_box[1], best_box[2], best_box[3]

        edges = cv2.Canny(blurred, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            if cv2.contourArea(largest) > min_area:
                x, y, w, h = cv2.boundingRect(largest)
                return True, x, y, x + w, y + h

        return False, 0, 0, 0, 0

    def find_text_cluster_region(img: np.ndarray, min_area: int = 15000) -> Tuple[bool, int, int, int, int]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
        merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        merged = cv2.morphologyEx(merged, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=1)

        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_box = None
        best_score = 0.0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            ratio = w / float(h) if h else 0.0
            if ratio < 0.4 or ratio > 5.0:
                continue

            roi = merged[y:y + h, x:x + w]
            density = cv2.countNonZero(roi) / float(max(1, w * h))
            score = area * density

            if score > best_score:
                best_score = score
                best_box = (x, y, x + w, y + h)

        if best_box is not None:
            return True, best_box[0], best_box[1], best_box[2], best_box[3]

        return False, 0, 0, 0, 0

    def find_near_document_region(img: np.ndarray, min_text_density: float = 0.08) -> Tuple[bool, int, int, int, int]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        text_pixels = cv2.countNonZero(binary)
        total_pixels = img.shape[0] * img.shape[1]
        text_density = text_pixels / float(max(1, total_pixels))

        edges = cv2.Canny(blurred, 50, 150)
        edge_density = np.count_nonzero(edges) / float(max(1, total_pixels))

        if text_density >= min_text_density and edge_density >= 0.015:
            return True, 0, 0, img.shape[1], img.shape[0]

        return False, 0, 0, 0, 0

    # ================= MAIN LOOP =================
    logger.info("🎬 Starting main loop")
    frame_count = 0
    no_frame_counter = 0
    
    try:
        while True:
            try:
                # Get frame from background reader
                ret, frame = frame_reader.get_frame()
                
                if not ret or frame is None:
                    no_frame_counter += 1
                    if no_frame_counter > 30:  # 30 attempts = ~1 second
                        logger.warning("⚠️ No frames available for 1 second, waiting for reconnect...")
                        time.sleep(1)
                        no_frame_counter = 0
                    else:
                        time.sleep(0.033)  # ~30 FPS
                    continue
                
                if _restart_capture:
                    is_stable = False
                    stable_start = 0
                    _force_next_capture = True
                    _restart_capture = False

                    speak("Ready for next capture")
                    
                # Fix camera orientation
                if CAMERA_ROTATION == 90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                elif CAMERA_ROTATION == -90:
                    frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                elif CAMERA_ROTATION == 180:
                    frame = cv2.rotate(frame, cv2.ROTATE_180)
                
                no_frame_counter = 0
                frame_count += 1
                display = frame.copy()  # No horizontal flip
                
                # ===== STRETCH TO FILL ENTIRE WINDOW (No black bars) =====
                display = cv2.resize(display, (DISPLAY_W, DISPLAY_H))

                if is_speaking:
                    draw_guide_box(display, GUIDE_COLOR_IDLE, "READING...")
                    cv2.imshow("Smart Reader - Qwen", display)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break

                    elif key == ord('s'):
                        stop_speech()

                    elif key == ord('r'):
                        restart_capture()
                    continue

                # Skip frames to reduce detection load
                frame_skip_counter += 1
                if frame_skip_counter < FRAME_SKIP:
                    draw_guide_box(display, GUIDE_COLOR_IDLE, "READY")
                    cv2.imshow("Smart Reader - Qwen", display)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break

                    elif key == ord('s'):
                        stop_speech()

                    elif key == ord('r'):
                        restart_capture()
                    continue
                frame_skip_counter = 0

                # --- HYBRID DETECTION ---
                try:
                    results = finder_ai(display, conf=0.25, verbose=False)
                    book_found = False
                    x1, y1, x2, y2 = 0, 0, 0, 0

                    for r in results:
                        for box in r.boxes:
                            if int(box.cls[0]) in TARGET_CLASSES:
                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                                book_found = True
                                break
                    
                    # Fallback to document/text-cluster detection if YOLO fails
                    if not book_found:
                        gray = cv2.cvtColor(display, cv2.COLOR_BGR2GRAY)

                        # ===== LOW LIGHT DETECTION =====
                        brightness = np.mean(gray)

                        if brightness < 50:
                            cv2.putText(
                                display,
                                "LOW LIGHT",
                                (20, 50),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                1,
                                (0, 0, 255),
                                2
                            )

                            # Speak only occasionally
                            if time.time() - last_hint_time > 5:
                                speak("Low light detected")
                                last_hint_time = time.time()

                        found, bx, by, bx2, by2 = find_document_region(display)
                        if not found:
                            found, bx, by, bx2, by2 = find_text_cluster_region(display)
                        if not found:
                            found, bx, by, bx2, by2 = find_near_document_region(display)

                        if found:
                            x1, y1, x2, y2 = bx, by, bx2, by2
                            book_found = True
                except Exception as e:
                    logger.error(f"❌ Detection error: {e}")
                    book_found = False

                if book_found:
                    cv2.rectangle(display, (x1, y1), (x2, y2), (255, 100, 0), 2)
                    hints = get_placement_guidance(x1, y1, x2, y2)
                    distance_hint = get_distance_guidance(x1, y1, x2, y2, DISPLAY_W, DISPLAY_H)
                    if distance_hint:
                        hints.insert(0, distance_hint)
                    overlap = book_inside_guide(x1, y1, x2, y2)
                    
                    if overlap >= 0.65 and not hints:
                        if not is_stable:
                            is_stable = True
                            stable_start = time.time()
                        held = time.time() - stable_start
                        if held < HOLD_TIME:
                            draw_guide_box(display, GUIDE_COLOR_HOLD, f"HOLD {HOLD_TIME - held:.1f}s")
                        else:
                            draw_guide_box(display, GUIDE_COLOR_READY, "CAPTURING...")
                            last_text = analyze_image(frame, last_text)
                            is_stable = False
                    else:
                        is_stable = False
                        draw_guide_box(display, GUIDE_COLOR_DETECT, "ADJUST POSITION")
                        if hints:
                            hint_str = hints[0]
                            now = time.time()
                            if (hint_str != last_spoken_hint or now - last_hint_time > HINT_COOLDOWN):
                                speak(hint_str)
                                last_spoken_hint, last_hint_time = hint_str, now
                else:
                    is_stable = False
                    draw_guide_box(display, GUIDE_COLOR_IDLE, "PLACE DOCUMENT HERE")

                cv2.imshow("Smart Reader - Qwen", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break

                elif key == ord('s'):
                    stop_speech()

                elif key == ord('r'):
                    restart_capture()

            except KeyboardInterrupt:
                logger.info("⏹️ Keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"❌ Main loop error: {e}")
                time.sleep(0.5)
                continue

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
    finally:
        logger.info("🔴 Shutting down...")
        _voice_thread_running = False
        _stop_worker.set()
        try:
            frame_reader.stop()
            cv2.destroyAllWindows()
        except:
            pass
        logger.info("✅ Cleanup complete")

if __name__ == "__main__":
    main()
