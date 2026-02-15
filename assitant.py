import cv2
import numpy as np
import google.generativeai as genai
import threading
import time
import os
import subprocess
from dotenv import load_dotenv
from PIL import Image
from ultralytics import YOLO

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("API_KEY")

if not API_KEY:
    print("Error: API_KEY is missing.")
    exit()

# 1. SETUP GEMINI
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# 2. SETUP YOLO
print("Loading AI Vision Model...")
finder_ai = YOLO('yolov8n.pt') 

# --- AUDIO SYSTEM ---
def speak(text):
    clean_text = text.replace('*', '').replace('#', '').replace('_', '')
    print(f"🗣️ {clean_text[:100]}...") 
    
    def _run():
        safe_text = clean_text.translate(str.maketrans({
            '"': '', "'": '', '’': '', '‘': '', '`': '', '\n': ' '
        }))
        cmd = f'PowerShell -Command "Add-Type –AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak(\'{safe_text}\');"'
        try:
            subprocess.run(cmd, shell=True) 
        except Exception as e:
            print(f"Audio Error: {e}")
            
    threading.Thread(target=_run).start()

def analyze_image(frame):
    speak("Hold on. Reading.")
    
    # Resize for upload speed
    height, width = frame.shape[:2]
    if width > 1024:
        ratio = 1024 / width
        frame = cv2.resize(frame, (1024, int(height * ratio)))

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    
    try:
        # We ask Gemini specifically to provide clean text
        prompt = "Read all the text in this image clearly. Output only the text found."
        response = model.generate_content([prompt, pil_img])
        
        if response.text:
            # --- NEW CMD PRINTING LOGIC ---
            print("\n" + "="*50)
            print("EXTRACTED TEXT:")
            print("-" * 50)
            print(response.text) # This prints the FULL text to CMD
            print("="*50 + "\n")
            # ------------------------------
            
            speak(response.text)
        else:
            print("No text detected by Gemini.")
            speak("No text found.")
    except Exception as e:
        print(f"Error: {e}")
        speak("Connection lost.")
        
def main():
    phone_ip = os.getenv("PHONE_IP")

    if not phone_ip:
        print("Error: PHONE_IP is missing in .env file.")
        return

    phone_ip_url = f"http://{phone_ip}:8080/video"
    print(f"Connecting to camera at: {phone_ip_url}")

    cap = cv2.VideoCapture(phone_ip_url)

    if not cap.isOpened():
        print("Error: Could not connect to the phone. Check if both devices are on the same Wi-Fi.")
        return


    speak("System Online. Show me a book.")
    
    last_guidance_time = 0
    stable_start_time = 0
    is_stable = False
    
    # TARGET: Book (73)
    TARGET_CLASSES = [73] 

    while True:
        ret, frame = cap.read()
        if not ret: break

        display_frame = cv2.flip(frame, 1)
        
        # Run AI on CPU (Avoids 5080 error)
        results = finder_ai(display_frame, verbose=False, conf=0.3, device='cpu') 
        
        target_found = False
        
        for r in results:
            for box in r.boxes:
                if int(box.cls[0]) in TARGET_CLASSES:
                    target_found = True
                    
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    
                    # Draw Box
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (255, 100, 0), 3)
                    
                    # --- CALCULATE CENTERS ---
                    obj_center_x = (x1 + x2) // 2
                    obj_center_y = (y1 + y2) // 2
                    
                    frame_center_x = display_frame.shape[1] // 2
                    frame_center_y = display_frame.shape[0] // 2
                    
                    offset_x = obj_center_x - frame_center_x
                    offset_y = obj_center_y - frame_center_y
                    
                    # Check Size (Is it too far?)
                    box_area = (x2 - x1) * (y2 - y1)
                    frame_area = display_frame.shape[0] * display_frame.shape[1]
                    coverage = box_area / frame_area
                    
                    # --- GUIDANCE LOGIC ---
                    TOLERANCE = 100 # Pixels
                    
                    msg = "Aligning..."
                    is_centered = True
                    
                    # 1. Horizontal Check
                    if abs(offset_x) > TOLERANCE:
                        is_centered = False
                        if time.time() - last_guidance_time > 2.5:
                            if offset_x > 0: speak("Move Left") 
                            else: speak("Move Right")
                            last_guidance_time = time.time()
                            
                    # 2. Vertical Check (Only if X is okay-ish)
                    elif abs(offset_y) > TOLERANCE:
                        is_centered = False
                        if time.time() - last_guidance_time > 2.5:
                            # Note: Y coordinates grow downwards
                            if offset_y > 0: speak("Move Up")  # Object is low -> Move Up
                            else: speak("Move Down")           # Object is high -> Move Down
                            last_guidance_time = time.time()
                    
                    # 3. Distance Check
                    elif coverage < 0.15: # If book covers less than 15% of screen
                        is_centered = False
                        if time.time() - last_guidance_time > 2.5:
                            speak("Bring Closer")
                            last_guidance_time = time.time()

                    # --- SUCCESS STATE ---
                    if is_centered:
                        if not is_stable:
                            is_stable = True
                            stable_start_time = time.time()
                        
                        time_held = time.time() - stable_start_time
                        
                        if time_held < 2.0:
                            msg = f"HOLD STILL: {2.0 - time_held:.1f}s"
                            color = (0, 255, 255)
                        else:
                            msg = "CAPTURING..."
                            color = (0, 255, 0)
                        
                        cv2.putText(display_frame, msg, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
                        
                        if time_held >= 2.0:
                            # Send RAW frame (Unflipped)
                            analyze_image(frame) 
                            is_stable = False
                            stable_start_time = 0
                            time.sleep(5) 
                            speak("Ready.")
                    else:
                        is_stable = False
                    
                    break # Found book, stop checking

        if not target_found:
             is_stable = False
             cv2.putText(display_frame, "Searching...", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        cv2.imshow("Smart Reader", display_frame)
        if cv2.waitKey(1) == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()