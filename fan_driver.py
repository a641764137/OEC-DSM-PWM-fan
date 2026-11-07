#!/usr/bin/env python3
"""PWM Fan Driver for OEC-Turbo — software PWM via libgpiod, temp-based + manual control."""
import time
import json
import os
import signal
import threading
import gpiod

# ── Config ──────────────────────────────────────────────
PWM_CHIP   = 0      
PWM_PIN    = 30     #pin30是空的，用作占位符，因为DSM7锁定了pin25，因此只能通过pin24来读取风扇转速，不能控制风扇转速
TACH_CHIP  = 0
TACH_PIN   = 24     #gpio0 pin24对应主板上的RX接口，风扇检测线连这里
PWM_FREQ   = 100
TEMP_ZONE  = "/sys/class/thermal/thermal_zone1/temp"
STATUS_FILE = "/tmp/pwm-fan-status.json"
CTRL_FILE   = "/tmp/pwm-fan-ctrl.json"

TEMP_MIN   = 35000
TEMP_MAX   = 65000
DUTY_MIN   = 0
DUTY_MAX   = 100

running = True
tach_rpm = 0
duty = 0
temp = 0
ctrl_mode = "auto"      # "auto" or "manual"
manual_duty = 50        # manual target duty

# ── GPIO init (using gpiod v2 Direction & Value enums) ───
pwm_request = gpiod.request_lines(
    f"/dev/gpiochip{PWM_CHIP}",
    consumer="pwm-fan",
    config={
        PWM_PIN: gpiod.LineSettings(
            direction=gpiod.line.Direction.OUTPUT,
            output_value=gpiod.line.Value.INACTIVE
        )
    }
)

tach_request = None
if TACH_CHIP is not None and TACH_PIN is not None:
    tach_request = gpiod.request_lines(
        f"/dev/gpiochip{TACH_CHIP}",
        consumer="pwm-fan-tach",
        config={
            TACH_PIN: gpiod.LineSettings(
                direction=gpiod.line.Direction.INPUT
            )
        }
    )

def read_temp():
    try:
        with open(TEMP_ZONE) as f:
            return int(f.read().strip())
    except Exception:
        return 0

_hdd_cache = {"val": None}

def get_hdd_temp():
    return _hdd_cache["val"]

def request_hdd_refresh():
    if not os.path.exists('/dev/sata1'):
        _hdd_cache["val"] = None
        return None
    try:
        import subprocess
        r = subprocess.run(
            ['/usr/bin/smartctl', '-A', '/dev/sata1'],
            capture_output=True, text=True, timeout=10
        )
        for line in r.stdout.split('\n'):
            if 'Temperature_Celsius' in line:
                raw = line.rsplit('-', 1)[-1].strip()
                _hdd_cache["val"] = int(raw.split()[0])
                return _hdd_cache["val"]
        _hdd_cache["val"] = None
    except Exception:
        _hdd_cache["val"] = None
    return _hdd_cache["val"]

def temp_to_duty(temp_mdeg):
    if temp_mdeg <= TEMP_MIN:
        return 0
    if temp_mdeg >= TEMP_MAX:
        return DUTY_MAX
    ratio = (temp_mdeg - TEMP_MIN) / (TEMP_MAX - TEMP_MIN)
    return int(DUTY_MIN + ratio * (DUTY_MAX - DUTY_MIN))

def read_ctrl():
    global ctrl_mode, manual_duty
    try:
        if os.path.exists(CTRL_FILE):
            with open(CTRL_FILE) as f:
                c = json.load(f)
            ctrl_mode = c.get("mode", "auto")
            manual_duty = int(c.get("duty", 50))
            manual_duty = max(0, min(100, manual_duty))
            if ctrl_mode == "auto":
                os.remove(CTRL_FILE)
    except Exception:
        pass

# ── PWM output thread ────────────────────────────────────
def pwm_loop():
    global duty, running
    period = 1.0 / PWM_FREQ
    while running:
        d = duty
        if d == 0:
            pwm_request.set_value(PWM_PIN, gpiod.line.Value.INACTIVE)
            time.sleep(1.0)
        elif d >= 100:
            pwm_request.set_value(PWM_PIN, gpiod.line.Value.ACTIVE)
            time.sleep(1.0)
        else:
            on_time = period * d / 100.0
            off_time = period - on_time
            if on_time > 0:
                pwm_request.set_value(PWM_PIN, gpiod.line.Value.ACTIVE)
                time.sleep(on_time)
            if off_time > 0 and running:
                pwm_request.set_value(PWM_PIN, gpiod.line.Value.INACTIVE)
                time.sleep(off_time)
    pwm_request.set_value(PWM_PIN, gpiod.line.Value.INACTIVE)
    pwm_request.release()

# ── TACH (optional) ──────────────────────────────────────
def tach_loop():
    global tach_rpm, running
    if tach_request is None:
        return
    while running:
        pulses = 0
        deadline = time.time() + 1.0
        last_val = tach_request.get_value(TACH_PIN)
        while time.time() < deadline:
            val = tach_request.get_value(TACH_PIN)
            if val != last_val and val == gpiod.line.Value.INACTIVE:
                pulses += 1
            last_val = val
            time.sleep(0.001)
        tach_rpm = pulses * 30

# ── Monitor loop ─────────────────────────────────────────
HDD_REFRESH_FILE = "/tmp/pwm-fan-hdd-refresh"

def monitor_loop():
    global duty, temp, ctrl_mode, manual_duty, running
    request_hdd_refresh()
    while running:
        read_ctrl()
        temp = read_temp()

        if os.path.exists(HDD_REFRESH_FILE):
            request_hdd_refresh()
            try: os.remove(HDD_REFRESH_FILE)
            except: pass

        if ctrl_mode == "manual":
            duty = manual_duty
        else:
            duty = temp_to_duty(temp)

        try:
            hdd = get_hdd_temp()
            with open(STATUS_FILE, "w") as f:
                json.dump({
                    "temp_c": round(temp / 1000.0, 1),
                    "temp_raw": temp,
                    "hdd_c": hdd,
                    "duty": duty,
                    "rpm": tach_rpm,
                    "freq": PWM_FREQ,
                    "gpio_pin": PWM_PIN,
                    "mode": ctrl_mode,
                }, f)
        except Exception:
            pass
        time.sleep(1)

# ── Signal handler ───────────────────────────────────────
def cleanup(sig=None, frame=None):
    global running
    running = False

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# ── Main ─────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"PWM Fan Driver | GPIO {PWM_CHIP}:{PWM_PIN} | {PWM_FREQ}Hz")
    threads = [
        threading.Thread(target=pwm_loop, daemon=True),
        threading.Thread(target=monitor_loop, daemon=True),
    ]
    if tach_request is not None:
        threads.append(threading.Thread(target=tach_loop, daemon=True))
        print(f"TACH on GPIO {TACH_CHIP}:{TACH_PIN}")

    for t in threads:
        t.start()

    while running:
        time.sleep(1)

    pwm_request.set_value(PWM_PIN, gpiod.line.Value.INACTIVE)
    pwm_request.release()
    if tach_request is not None:
        tach_request.release()
    print("Fan driver stopped.")
