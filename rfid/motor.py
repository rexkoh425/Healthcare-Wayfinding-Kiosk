import RPi.GPIO as GPIO
# -----------------------
# Dispensing Setup
# -----------------------
MOTOR_PIN1 = 17  # Change to your GPIO pin number
MOTOR_PIN2 = 27
GPIO.setmode(GPIO.BCM)
GPIO.setup(MOTOR_PIN1, GPIO.OUT)
GPIO.setup(MOTOR_PIN2, GPIO.OUT)


# -----------------------
# Dispensing Functions
# -----------------------
def motor_on():
    """Turn motor on"""
    GPIO.output(MOTOR_PIN1, GPIO.HIGH)
    GPIO.output(MOTOR_PIN2, GPIO.LOW)

def motor_off():
    """Turn motor off"""
    GPIO.output(MOTOR_PIN1, GPIO.LOW)
    GPIO.output(MOTOR_PIN2, GPIO.LOW)

def rotate_x(seconds):
    motor_on()
    time.sleep(seconds)
    motor_off()
motor_off()