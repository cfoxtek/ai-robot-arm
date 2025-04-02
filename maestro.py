# maestro.py
import serial

class MaestroController:
    def __init__(self, port="COM4"):
        self.ser = serial.Serial(port)

    def set_target(self, channel, target):
        command = bytearray([
            0x84,                # Command: Set Target
            channel,             # Channel number
            target & 0x7F,       # Lower 7 bits
            (target >> 7) & 0x7F # Upper 7 bits
        ])
        self.ser.write(command)

    def close(self):
        self.ser.close()
