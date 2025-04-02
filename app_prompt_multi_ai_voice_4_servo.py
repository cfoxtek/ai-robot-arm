# eezybot_openai_gui.py
import tkinter as tk
from threading import Thread
import time
import os
from dotenv import load_dotenv
import openai
import speech_recognition as sr
from maestro import MaestroController

# === Load API Key ===
load_dotenv()
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === Maestro Settings ===
SERVO_PORT = "COM4"
servo_channels = [0, 1, 2, 3]
MIN_PULSE = [4000, 4000, 5000, 4000]
MAX_PULSE = [8000, 8000, 5000, 6000]
NEUTRAL = [6000, 6000, 5000, 5000]
STEP_DELAY = 0.01
INTERPOLATION_STEPS = 20
WAKE_WORD = "terminator"

# === Track current position ===
current_position = NEUTRAL.copy()

# === Init Maestro ===
servo = MaestroController(SERVO_PORT)
for ch, pos in enumerate(current_position):
    servo.set_target(ch, pos)

# === GUI Setup ===
root = tk.Tk()
root.title("EEZYbotArm (4 Servo) + OpenAI Voice")

sliders = {}

def update_servo(channel, value):
    pulse = int(value)
    servo.set_target(channel, pulse)
    sliders[channel].set(pulse)

def reset_all_servos():
    for ch in servo_channels:
        update_servo(ch, NEUTRAL[ch])
        current_position[ch] = NEUTRAL[ch]

for ch in servo_channels:
    frame = tk.Frame(root)
    frame.pack(pady=10)
    label = tk.Label(frame, text=f"Servo {ch}")
    label.pack()
    slider = tk.Scale(
        frame,
        from_=MIN_PULSE[ch],
        to=MAX_PULSE[ch],
        orient=tk.HORIZONTAL,
        resolution=100,
        length=300
    )
    slider.set(current_position[ch])
    slider.pack()
    sliders[ch] = slider

reset_btn = tk.Button(root, text="Reset to Neutral", command=reset_all_servos)
reset_btn.pack(pady=10)

def on_closing():
    servo.close()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

# === GPT Prompt Generator ===
def translate_natural_language_to_positions(prompt):
    claw, base, fixed, reach = current_position

    system_prompt = f"""
    You control a 4-servo robotic arm. Output movement sequences as pipe-delimited numbers in the format:
    <number0>,<number1>,<number2>,<number3> | ...

    Each step must contain **exactly four comma-separated values**, even if only one servo changes.
    Do NOT omit any values. Do NOT shorten the output.

    Servo meanings:

    - Servo 0 = Claw:
        - 4000 = closed
        - 8000 = open

    - Servo 1 = Base (left/right):
        - 4000 = left
        - 8000 = right

    - Servo 2 = Fixed (always 5000):
        - This servo should ALWAYS be 5000. Never change it.

    - Servo 3 = Forward/backward reach:
        - 4000 = fully back
        - 6000 = fully forward

    Only output multiple steps if the user uses phrases like "then", "after that", "slowly", etc.

    The current starting position is: {claw},{base},{fixed},{reach}
    The default/neutral position is: 6000,6000,5000,5000

    Examples:
    - "Open the claw" => "8000,6000,5000,5000"
    - "Move forward then back" => "6000,6000,5000,6000 | 6000,6000,5000,4000"
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": prompt.strip()}
        ],
        temperature=0
    )
    return response.choices[0].message.content.strip()

# === Interpolated Motion ===
def move_to_position(targets):
    global current_position
    for i in range(len(servo_channels)):
        # Skip servo 2 — it's always 5000
        if i == 2:
            update_servo(i, 5000)
            current_position[i] = 5000
            continue

        start = current_position[i]
        end = targets[i]
        steps = [
            int(start + (end - start) * (s / INTERPOLATION_STEPS))
            for s in range(1, INTERPOLATION_STEPS + 1)
        ]
        for step in steps:
            update_servo(i, step)
            time.sleep(STEP_DELAY)
        current_position[i] = end

# === Handle prompt (text or voice) ===
def handle_prompt(prompt):
    print(f"🎙️ Interpreting: {prompt}")
    try:
        response = translate_natural_language_to_positions(prompt)
        print(f"🤖 Translated: {response}")
        steps = response.strip().split("|")
        for step in steps:
            values = [int(val.strip()) for val in step.strip().split(",")]
            if len(values) != len(servo_channels):
                print(f"⚠️ Invalid step: {step}")
                continue
            # Clamp and validate
            clamped = []
            for ch, pulse in enumerate(values):
                if ch == 2:
                    clamped.append(5000)
                else:
                    pulse = max(MIN_PULSE[ch], min(MAX_PULSE[ch], pulse))
                    clamped.append(pulse)
            move_to_position(clamped)
    except Exception as e:
        print("❌ Error processing prompt:", e)

# === Text Thread ===
def listen_for_text():
    print("💬 Type a natural language prompt:")
    while True:
        user_input = input(">> ")
        if user_input.strip():
            handle_prompt(user_input)

# === Voice Thread with Wake Word ===
def listen_for_voice():
    recognizer = sr.Recognizer()
    mic = sr.Microphone()
    print(f"🎧 Listening for voice commands with wake word '{WAKE_WORD}'...")

    with mic as source:
        recognizer.adjust_for_ambient_noise(source)

    while True:
        try:
            with mic as source:
                print("🎙️ Speak a command...")
                audio = recognizer.listen(source, timeout=5)
            text = recognizer.recognize_google(audio).lower().strip()
            print(f"🗣️ Heard: {text}")

            if text.startswith(WAKE_WORD):
                command = text[len(WAKE_WORD):].strip(",. ")
                handle_prompt(command)
            else:
                print("⚠️ Wake word not detected — ignoring.")

        except sr.WaitTimeoutError:
            continue
        except sr.UnknownValueError:
            print("🤷 Didn’t catch that.")
        except sr.RequestError as e:
            print(f"❌ Speech recognition error: {e}")

# === Start Threads ===
Thread(target=listen_for_text, daemon=True).start()
Thread(target=listen_for_voice, daemon=True).start()

# === Run GUI ===
root.mainloop()
