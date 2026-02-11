import cv2
import numpy as np
import threading
import pyttsx3
import imutils
import os
import time
import subprocess
import signal
import sys
from queue import Queue
import csv
import socket  # New import for UDP
import base64  # Added for base64 encoding

# Global queue for TTS requests
tts_queue = Queue()

# Configuration
KNOWN_DISTANCE = 24.0
KNOWN_WIDTH = 11.0
JETSON_IP = "192.168.0.102"  # Jetson's IP
FRAME_WIDTH = 500
FRAME_HEIGHT = 280
DEVICE = "/dev/video0"  # Camera device
UDP_PORT_DATA = 5005  # New: UDP port for audio alerts
UPD_PORT_AUDIO =5006

# Object classes MobileNet SSD detects
CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car", "cat", "chair", "person",
           "diningtable", "dog", "horse", "motorbike", "person", "pottedplant", "sheep", "sofa", "train", "tvmonitor", "truck"]

IGNORE = set(
    ["background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus","cat", "chair", "diningtable",
     "dog", "horse","motorbike", "pottedplant", "sheep", "sofa", "train", "tvmonitor"])

COLORS = np.random.uniform(0, 255, size=(len(CLASSES), 3))



# Initialize voice engine
def init_voice_engine():
    try:
        engine = pyttsx3.init()
        engine.setProperty('rate', 150)
        return engine
    except Exception as e:
        print(f"Voice engine warning: {str(e)}")
        return None

# Initialize UDP socket
def init_udp_socket():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return sock
    except Exception as e:
        print(f"UDP socket error: {str(e)}")
        return None

voice_engine = init_voice_engine()
udp_socket = init_udp_socket()  # New UDP socket

def tts_loop():
    while True:
        message = tts_queue.get()
        if message is None:
            break  # Exit loop
        voice_engine.say(message)
        voice_engine.runAndWait()

voice_thread = threading.Thread(target=tts_loop, daemon=True)
voice_thread.start()

# Load the model
prototxt = "MobileNetSSD_deploy.prototxt.txt"
model = "MobileNetSSD_deploy.caffemodel"
net = cv2.dnn.readNetFromCaffe(prototxt, model)

# Initialize video capture
cap = cv2.VideoCapture(DEVICE)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

if not cap.isOpened():
    print("Error: Could not open webcam.")
    sys.exit(1)

# Distance calculation functions
def distance_to_camera(knownWidth, focalLength, perWidth):
    return (knownWidth * focalLength) / perWidth

def find_marker(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(gray, 35, 125)
    cnts = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = imutils.grab_contours(cnts)
    c = max(cnts, key=cv2.contourArea)
    return cv2.minAreaRect(c)

# Focal length calculation
image = cv2.imread("images/2ft.png")
if image is not None:
    marker = find_marker(image)
    focalLength = (marker[1][0] * KNOWN_DISTANCE) / KNOWN_WIDTH
else:
    print("Warning: Could not load reference image, using default focal length")
    focalLength = 1000

# CSV Logging setup
log_filename = "detection_log.csv"
image_log_filename = "image_log.csv"  # New CSV for image data

# Initialize detection log
if not os.path.isfile(log_filename):
    with open(log_filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "Machine_id", "CxD_id", "Sensor_id", "Class", "Confidence", 
            "Distance (m)", "Technical", "Emergency_status", "sensor_position", 
            "sensor_health"
        ])

# Initialize image log
if not os.path.isfile(image_log_filename):
    with open(image_log_filename, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "Machine_id", "CxD_id", "Sensor_id", "Class", "Confidence", 
            "Distance (m)", "Technical", "Emergency_status", "sensor_position", 
            "sensor_health", "timestamp", "image_base64"
        ])

screenshot_folder = "screenshots"
if not os.path.exists(screenshot_folder):
    os.makedirs(screenshot_folder)

def save_screenshot(frame):
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    screenshot_filename = os.path.join(screenshot_folder, f"person_{timestamp}.jpg")
    cv2.imwrite(screenshot_filename, frame)
    
    # Convert image to base64
    _, buffer = cv2.imencode('.jpg', frame)
    image_base64 = base64.b64encode(buffer).decode('utf-8')
    
    print(f"Screenshot saved: {screenshot_filename}")
    return timestamp, image_base64

def start_stream():
    if not os.path.exists('/tmp/vidpipe'):
        os.mkfifo('/tmp/vidpipe')
    ffmpeg_cmd = [
        'ffmpeg',
        '-re',
        '-f', 'mjpeg',
        '-i', '/tmp/vidpipe',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-f', 'rtsp',
        '-b:v', '500k',
        f'rtsp://{JETSON_IP}:8554/mystream4'
    ]
    return subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

def main():
    print(f"Starting {FRAME_WIDTH}x{FRAME_HEIGHT} stream to {JETSON_IP}")
    stream_process = start_stream()
    pipe = open('/tmp/vidpipe', 'wb')
    
    alert_sent = False  # Initialize the flag here

    def cleanup():
        print("\nClosing resources...")
        if 'stream_process' in locals():
            stream_process.stdin.close()
            stream_process.terminate()
        cap.release()
        cv2.destroyAllWindows()
        if voice_engine:
            voice_engine.stop()
        if udp_socket:  # Close UDP socket
            udp_socket.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, lambda s, f: cleanup())

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Could not read frame")
                break

            # Detection processing
            (h, w) = frame.shape[:2]
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
            net.setInput(blob)
            detections = net.forward()

            detection_made = False
            border_color = (0, 0, 0)
            border_thickness = 15
            
            # A flag to check if any person/car/truck is detected in the current frame
            is_object_in_range = False

            for i in np.arange(0, detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.8:
                    idx = int(detections[0, 0, i, 1])
                    if CLASSES[idx] in IGNORE:
                        continue

                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")
                    inches = distance_to_camera(KNOWN_WIDTH, focalLength, endX - startX)
                    
                    # Condition for sending an alert
                    if inches * 0.0254 > 0.1 and inches * 0.0254 < 5.0 and (CLASSES[idx] == "person" or CLASSES[idx] == "car" or CLASSES[idx] == "truck"):
                        is_object_in_range = True #Object is detected
                        if not alert_sent:
                            distance_meters = inches * 0.0254
                            alert_message = f"{CLASSES[idx]} On The Right Slow Down"
                            tts_queue.put(alert_message)  # Local TTS
                            if udp_socket:
                                try:
                                    # This will now only be sent once
                                    udp_socket.sendto(alert_message.encode(), (JETSON_IP, UPD_PORT_AUDIO))
                                    
                                    udp_message = f"class={CLASSES[idx]} right={distance_meters:.1f}"
                                    udp_socket.sendto(udp_message.encode(), (JETSON_IP, UDP_PORT_DATA))
                                except Exception as e:
                                    print(f"UDP send error: {e}")
                            
                            alert_sent = True # Set the flag to prevent re-sending
                            border_color = (0, 0, 255)
                            detection_made = True
                            timestamp, image_base64 = save_screenshot(frame)
                            
                            # Log to image CSV
                            with open(image_log_filename, 'a', newline='') as csvfile:
                                writer = csv.writer(csvfile)
                                writer.writerow([
                                    "ADT_RIVERSIDE_1", "CxD_RIVERSIDE_1", "RIGHT_RIVERSIDE_1",
                                    CLASSES[idx], f"{confidence * 100:.2f}", 
                                    f"{inches * 0.0254:.2f}", "No", "No", "RIGHT", "GOOD",
                                    timestamp, image_base64
                                ])

                    label_text = f"{CLASSES[idx]}: {confidence * 100:.2f}% {inches * 0.0254:.2f}m"
                    with open(log_filename, 'a', newline='') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow([
                            "ADT_RIVERSIDE_1", "CxD_RIVERSIDE_1", "RIGHT_RIVERSIDE_1", 
                            CLASSES[idx], f"{confidence * 100:.2f}", 
                            f"{inches * 0.0254:.2f}", "No", "No", "RIGHT", "GOOD"
                        ])

                    cv2.rectangle(frame, (startX, startY), (endX, endY), COLORS[idx], 2)
                    y = startY - 15 if startY - 15 > 15 else startY + 15
                    cv2.putText(frame, label_text, (startX, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS[idx], 2)

            # After checking all detections, if no object was in range, reset the flag
            if not is_object_in_range:
                alert_sent = False

            if detection_made:
                cv2.rectangle(frame, (0, 0), (w - 1, h - 1), border_color, border_thickness)

            try:
                _, jpeg_frame = cv2.imencode('.jpg', frame)
                pipe.write(jpeg_frame.tobytes())
            except BrokenPipeError:
                print("Stream connection broken - restarting...")
                stream_process = start_stream()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup()

if __name__ == "__main__":
    main()
