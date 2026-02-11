import cv2
import threading
import numpy as np
import time
from tkinter import Tk, Label, Frame, Button
from PIL import Image, ImageTk
from datetime import datetime
import socket  # New import for UDP
import pyttsx3  # New import for TTS

class RTSPViewerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RTSP Multi-Camera Viewer")
        self.root.geometry("1024x590")
        self.root.overrideredirect(True)
        self.root.attributes("-fullscreen", True)

        # Initialize TTS engine
        self.voice_engine = pyttsx3.init()
        self.voice_engine.setProperty('rate', 150)
        
        # UDP configuration
        self.udp_ip = "0.0.0.0"  # Listen on all interfaces
        self.udp_port = 5005
        self.running = True
        
        # Create a grid layout
        self.top_frame = Frame(root)
        self.top_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        
        self.bottom_frame = Frame(root)
        self.bottom_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        
        # Create footer frame with dark blue background
        self.footer_frame = Frame(root, bg="#00008B", height=50)
        self.footer_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        
        # Configure grid weights
        root.grid_rowconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        root.grid_rowconfigure(2, weight=0)
        root.grid_columnconfigure(0, weight=1)
        root.grid_columnconfigure(1, weight=1)

        # Create 4 camera display frames
        self.frames = [
            Frame(self.top_frame, width=500, height=280, bg="white"),
            Frame(self.top_frame, width=500, height=280, bg="white"),
            Frame(self.bottom_frame, width=500, height=280, bg="white"),
            Frame(self.bottom_frame, width=500, height=280, bg="white")
        ]
        
        # Position frames in grid
        self.frames[0].grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.frames[1].grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.frames[2].grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.frames[3].grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        # Create labels for each frame
        self.labels = []
        for i in range(4):
            label = Label(self.frames[i], bg="white")
            label.pack(fill="both", expand=True)
            self.labels.append(label)

        # Left side of footer - Driver ID and Time
        self.left_footer_frame = Frame(self.footer_frame, bg="#00008B")
        self.left_footer_frame.pack(side="left", padx=20, pady=5)

        # Driver ID
        self.driver_id = "DRV12345"
        driver_frame = Frame(self.left_footer_frame, bg="#00008B")
        driver_frame.pack(side="left", padx=10)
        Label(driver_frame, text="Driver ID:", bg="#00008B", fg="white", font=("Helvetica", 12)).pack(side="left", padx=2)
        self.driver_id_label = Label(driver_frame, text=self.driver_id, bg="#00008B", fg="white", font=("Helvetica", 12, "bold"))
        self.driver_id_label.pack(side="left")

        # Date and Time
        time_frame = Frame(self.left_footer_frame, bg="#00008B")
        time_frame.pack(side="left", padx=10)
        Label(time_frame, text="Date & Time:", bg="#00008B", fg="white", font=("Helvetica", 12)).pack(side="left", padx=2)
        self.time_label = Label(time_frame, text="", bg="#00008B", fg="white", font=("Helvetica", 12, "bold"))
        self.time_label.pack(side="left")
        self.update_time()

        # Right side of footer - Buttons
        self.button_frame = Frame(self.footer_frame, bg="#00008B")
        self.button_frame.pack(side="right", padx=20, pady=5)

        # Enroll button
        self.enroll_button = Button(self.button_frame, text="Enroll", command=self.enroll_action, 
                                 bg="green", fg="white", font=("Helvetica", 12))
        self.enroll_button.pack(side="left", padx=10)

        # Exit button
        self.exit_button = Button(self.button_frame, text="Exit", command=self.stop_streams, 
                                bg="red", fg="white", font=("Helvetica", 12))
        self.exit_button.pack(side="left", padx=10)

        # RTSP stream configurations
        self.stream_urls = [
            "rtsp://localhost:8554/mystream1",
            "rtsp://localhost:8554/mystream2",
            "rtsp://localhost:8554/mystream3",
            "rtsp://localhost:8554/mystream4"
        ]

        self.caps = [None] * 4
        self.threads = []
        self.last_received_times = [time.time()] * 4
        self.connection_states = [False] * 4
        
        # Start all streams
        for i in range(4):
            thread = threading.Thread(target=self.receive_stream, args=(i,))
            thread.daemon = True
            self.threads.append(thread)
            thread.start()
            
        # Start watchdog thread
        self.watchdog_thread = threading.Thread(target=self.watchdog)
        self.watchdog_thread.daemon = True
        self.watchdog_thread.start()
        
        # Start UDP listener thread
        self.udp_thread = threading.Thread(target=self.listen_for_alerts, daemon=True)
        self.udp_thread.start()

    def listen_for_alerts(self):
        """Listen for UDP alerts and speak them"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.udp_ip, self.udp_port))
        
        while self.running:
            try:
                data, _ = sock.recvfrom(1024)
                message = data.decode()
                print(f"ALERT: {message}")
                
                # Speak the alert
                self.voice_engine.say(message)
                self.voice_engine.runAndWait()
                
            except Exception as e:
                if self.running:  # Only print errors if we're supposed to be running
                    print(f"UDP Error: {e}")
        
        sock.close()

    def receive_stream(self, stream_index):
        url = self.stream_urls[stream_index]
        cap = None
        frame_width = 500
        frame_height = 280
        
        while self.running:
            try:
                if cap is None or not cap.isOpened():
                    self.set_connecting_state(stream_index, True)
                    if cap is not None:
                        cap.release()
                    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not cap.isOpened():
                        self.show_connection_error(stream_index)
                        time.sleep(1)
                        continue
                
                ret, frame = cap.read()
                if not ret:
                    self.show_connection_error(stream_index)
                    cap.release()
                    cap = None
                    time.sleep(1)
                    continue
                
                self.last_received_times[stream_index] = time.time()
                if not self.connection_states[stream_index]:
                    self.set_connecting_state(stream_index, False)
                
                frame = cv2.resize(frame, (frame_width, frame_height))
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame)
                img_tk = ImageTk.PhotoImage(image=img)
                
                self.root.after(0, self.update_label, stream_index, img_tk)
                
            except Exception as e:
                self.show_connection_error(stream_index)
                if cap is not None:
                    cap.release()
                    cap = None
                time.sleep(1)
                continue
            
            cv2.waitKey(30)
        
        if cap is not None and cap.isOpened():
            cap.release()

    def set_connecting_state(self, stream_index, connecting):
        self.connection_states[stream_index] = not connecting
        if connecting:
            self.root.after(0, self.labels[stream_index].config, {
                "bg": "white",
                "image": "",
                "text": f"Stream {stream_index+1}\nConnecting...",
                "fg": "black",
                "font": ("Helvetica", 16),
                "compound": "center"
            })
        else:
            self.root.after(0, self.labels[stream_index].config, {
                "bg": "black",
                "text": ""
            })

    def show_connection_error(self, stream_index):
        self.set_connecting_state(stream_index, True)
        self.root.after(0, self.labels[stream_index].config, {
            "text": f"Stream {stream_index+1}\nConnection Lost\nRetrying...",
            "fg": "black"
        })

    def watchdog(self):
        while self.running:
            current_time = time.time()
            for i in range(4):
                if current_time - self.last_received_times[i] > 5 and self.connection_states[i]:
                    print(f"Stream {i+1} timeout - triggering reconnection")
                    self.show_connection_error(i)
                    if self.caps[i] is not None:
                        self.caps[i].release()
                        self.caps[i] = None
            
            time.sleep(1)

    def update_label(self, stream_index, img_tk):
        if self.connection_states[stream_index]:
            self.labels[stream_index].config(
                image=img_tk,
                bg="black",
                text=""
            )
            self.labels[stream_index].image = img_tk

    def update_time(self):
        now = datetime.now()
        self.time_label.config(text=now.strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self.update_time)

    def enroll_action(self):
        print("Enroll button clicked")

    def stop_streams(self):
        self.running = False
        for thread in self.threads:
            thread.join()
        if hasattr(self, 'watchdog_thread'):
            self.watchdog_thread.join()
        if hasattr(self, 'udp_thread'):
            self.udp_thread.join()
        self.voice_engine.stop()
        self.root.destroy()

if __name__ == "__main__":
    root = Tk()
    app = RTSPViewerApp(root)
    root.mainloop()
