import cv2
import time
import threading
import os
import re
import numpy as np
import pythoncom
import win32com.client
from win32com.client import constants as c
import google.generativeai as genai
from ultralytics import YOLO
from dotenv import load_dotenv
from PIL import Image
import speech_recognition as sr
import queue
import logging
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
API_KEY = os.getenv("API_KEY")
PHONE_IP = os.getenv("PHONE_IP")
if not API_KEY or not PHONE_IP:
    raise RuntimeError("API_KEY or PHONE_IP missing")

# ================= GEMINI =================
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ================= API CONTROL =================
LAST_API_CALL = 0
API_COOLDOWN = 10
MAX_RETRIES = 3
RETRY_DELAY = 2
LAST_SUCCESSFUL_READ = 0
MIN_READ_INTERVAL = 15  # seconds

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

# ================= VOICE CONTROL =================
_voice_thread_running = True
_force_next_capture = False

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

# ================= OCR ANALYSIS =================
IGNORE_THRESHOLD = 0.96
PARTIAL_THRESHOLD = 0.80

def analyze_image(frame: np.ndarray, last_text: str) -> str:
    """
    Analyze image with Gemini API with robust error handling
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

    try:
        img = Image.fromarray(cv2.cvtColor(preprocessed, cv2.COLOR_BGR2RGB))
    except Exception as e:
        logger.error(f"❌ Image conversion error: {e}")
        speak("Image conversion failed")
        return last_text

    text = None
    for attempt in range(MAX_RETRIES):
        try:
            LAST_API_CALL = time.time()
            
            resp = model.generate_content(
                [
                    "Extract ALL visible text exactly as it appears. "
                    "Include all words, numbers, punctuation. "
                    "Preserve formatting and line breaks where possible. "
                    "If text is upside down or rotated, correct the orientation first.",
                    img
                ]
            )
            
            if resp and resp.text and len(resp.text.strip()) >= 5:
                text = resp.text.strip()
                LAST_SUCCESSFUL_READ = time.time()
                logger.info(f"✅ OCR successful (attempt {attempt + 1})")
                break
            else:
                logger.warning(f"⚠️ Empty response (attempt {attempt + 1})")
        
        except Exception as e:
            error_str = str(e)
            logger.error(f"❌ API error (attempt {attempt + 1}): {error_str[:100]}")
            
            if "429" in error_str or "quota" in error_str.lower():
                logger.error("❌ Gemini rate limit hit")
                speak("API rate limit reached")
                return last_text
            elif "500" in error_str or "503" in error_str:
                speak("Service temporarily unavailable. Retrying...")
                time.sleep(RETRY_DELAY)
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
        
    def connect(self) -> bool:
        """Connect to camera stream"""
        try:
            self.cap = cv2.VideoCapture(self.stream_url)
            
            # Minimize buffer and set camera properties
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            # Test connection
            ret, frame = self.cap.read()
            if ret and frame is not None:
                logger.info(f"✅ Background reader connected")
                self.connected = True
                self.consecutive_failures = 0
                with self.buffer_lock:
                    self.buffer.append(frame)
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Background reader connection error: {e}")
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
                
                if ret and frame is not None:
                    with self.buffer_lock:
                        self.buffer.append(frame)
                    self.consecutive_failures = 0
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
    global _force_next_capture, _voice_thread_running, LAST_API_CALL

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
    HOLD_TIME = 0.15
    
    # ================= GUIDE BOX CONFIG =================
    DISPLAY_W, DISPLAY_H = 960, 540
    GUIDE_MARGIN_X = 120
    GUIDE_MARGIN_Y = 60
    GUIDE_X1, GUIDE_Y1 = GUIDE_MARGIN_X, GUIDE_MARGIN_Y
    GUIDE_X2, GUIDE_Y2 = DISPLAY_W - GUIDE_MARGIN_X, DISPLAY_H - GUIDE_MARGIN_Y
    
    GUIDE_COLOR_IDLE   = (80, 80, 80)
    GUIDE_COLOR_DETECT = (0, 200, 255)
    GUIDE_COLOR_HOLD   = (0, 165, 255)
    GUIDE_COLOR_READY  = (0, 255, 0)

    last_spoken_hint = ""
    last_hint_time = 0
    HINT_COOLDOWN = 2.0

    frame_skip_counter = 0
    FRAME_SKIP = 2

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
                
                no_frame_counter = 0
                frame_count += 1
                display = cv2.flip(frame, 1)
                display = cv2.resize(display, (DISPLAY_W, DISPLAY_H))

                if is_speaking:
                    draw_guide_box(display, GUIDE_COLOR_IDLE, "READING...")
                    cv2.imshow("Smart Reader", display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                    continue

                # Skip frames to reduce detection load
                frame_skip_counter += 1
                if frame_skip_counter < FRAME_SKIP:
                    draw_guide_box(display, GUIDE_COLOR_IDLE, "READY")
                    cv2.imshow("Smart Reader", display)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
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
                    
                    # Fallback to Edge Detection if YOLO fails
                    if not book_found:
                        gray = cv2.cvtColor(display, cv2.COLOR_BGR2GRAY)
                        edged = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 75, 200)
                        cnts, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        if cnts:
                            largest = max(cnts, key=cv2.contourArea)
                            if cv2.contourArea(largest) > 35000:
                                bx, by, bw, bh = cv2.boundingRect(largest)
                                x1, y1, x2, y2 = bx, by, bx + bw, by + bh
                                book_found = True
                except Exception as e:
                    logger.error(f"❌ Detection error: {e}")
                    book_found = False

                if book_found:
                    cv2.rectangle(display, (x1, y1), (x2, y2), (255, 100, 0), 2)
                    hints = get_placement_guidance(x1, y1, x2, y2)
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

                cv2.imshow("Smart Reader", display)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

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

