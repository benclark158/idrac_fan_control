import subprocess
import time
import signal
import sys
import os
import threading
import requests
import json
import traceback
import re

from datetime import datetime

import webserver

class Ipmi:
    __host: str
    __username: str
    __password: str

    def __init__(self, host: str | None = None, username: str | None = None, password: str | None = None):
        self.__host = host or 'idrac-37bjzg2'
        self.__username = username or 'root'
        self.__password = password or 'calvin'

    def send_ipmi_command(self, *args):
        result = subprocess.run([
            'ipmitool', 
            '-I', 'lanplus',
            '-H', f'{self.__host}',
            '-U', f'{self.__username}',
            '-P', f'{self.__password}',
            *args
        ], capture_output=True, text=True, timeout=30.0)

        return result.stdout, result.stderr, ' '.join(result.args)

    def get_temps(self) -> dict[str, int]:
        result, _, _ = self.send_ipmi_command('sdr', 'type', 'temperature')
        lines = result.split('\n')
        temps = {}

        for line in lines:
            # Split by | and strip whitespace
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue  # Skip malformed lines

            name: str = parts[0].lower().replace('temp', '').strip()
            reading = parts[4]

            if name == '':
                if 'cpu1' in temps:
                    name = 'cpu2'
                else:
                    name = 'cpu1'

            # Skip sensors without a numeric reading
            if "degrees" not in reading:
                continue

            # Extract numeric value
            try:
                value = int(reading.split(' ')[0])
            except ValueError:
                continue

            temps[name] = value
        return temps

    def set_fan_speed(self, speed: int):
        # limit speed between 0 and 100 %
        speed = min(100, max(0, speed))
        self.send_ipmi_command('raw', '0x30', '0x30', '0x02', '0xff', hex(speed))

    def disable_auto_fans(self):
        self.send_ipmi_command('raw', '0x30', '0x30', '0x01', '0x00')
        print('Disabled Automatic Fans')

    def enable_auto_fans(self):
        self.send_ipmi_command('raw', '0x30', '0x30', '0x01', '0x01')
        print('Enabled Automatic Fans')

    def get_cpu_util(self) -> int:
        result, _, _ = self.send_ipmi_command('sdr', 'get', 'CPU Usage', '0x01', '0x01')
        reading: str = [ line for line in result.split('\n') if 'Sensor Reading' in line][0]
        return int(reading.strip().split(':', 1)[1].strip().split(' ')[0])



class Line:
    @classmethod
    def fit(self, p1: tuple[float, float], p2: tuple[float, float]) -> "Line":
        pass

    def calculate(self, x: float) -> float:
        pass


class Linear(Line):
    slope: float
    intercept: float

    def __init__(self, slope: float, intercept: float):
        self.slope = slope
        self.intercept = intercept
        
    def calculate(self, x: int | float) -> float:
        return (x * self.slope) + self.intercept

    @classmethod
    def fit(cls, p1: tuple[float, float], p2: tuple[float, float]) -> "Linear":
        # y = mx + c
        x1, y1 = p1
        x2, y2 = p2

        slope = float(y2 - y1) / float(x2 - x1)
        intercept = y1 - slope * x1

        return Linear(slope=slope, intercept=intercept)
    
    def __str__(self):
        return f'y = {self.slope}*x + {self.intercept}'
    
class FanMonitor:
    __ipmi: Ipmi
    
    start_temp: int = 40
    start_fan: int = 0
    end_temp: int = 65
    end_fan: int = 60

    interval = 30

    get_cpu_util: bool = False

    def __init__(self):
        # Load from env
        host = os.environ.get('IPMI_HOST')
        username = os.environ.get('IPMI_USER')
        password = os.environ.get('IPMI_PWD')

        self.start_temp = int(os.environ.get('START_TEMP') or self.start_temp)
        self.start_fan = int(os.environ.get('START_FAN') or self.start_fan)
        self.end_temp = int(os.environ.get('END_TEMP') or self.end_temp)
        self.end_fan = int(os.environ.get('END_FAN') or self.end_fan)
        self.interval = int(os.environ.get('INTERVAL') or self.interval)

        self.get_cpu_util = str(os.environ.get('GET_CPU_UTIL', False)) in ['t', '1', 'true', 'yes']

        # IPMI
        self.__ipmi = Ipmi(host=host, username=username, password=password)

        # Register handlers
        signal.signal(signal.SIGTERM, self.cleanup())
        signal.signal(signal.SIGINT, self.cleanup())

    def cleanup(self) -> callable:
        def cl(*args, **kwargs):
            self.__ipmi.enable_auto_fans()
            sys.exit(0)
        return cl

    def __calculate_function(self) -> Line:
        # start_temp 10-70
        self.start_temp = min(70, max(10, self.start_temp))
        # end_temp start_temp-70
        self.end_temp = min(70, max(self.start_temp, self.end_temp))

        # start_fan 0-100
        self.start_fan = min(100, max(0, self.start_fan))
        # end_fan start_fan-100
        self.end_fan = min(100, max(self.start_fan, self.end_fan))

        return Linear.fit((self.start_temp, self.start_fan), (self.end_temp, self.end_fan))

    def print_table_row(self, temps: dict[str, int], target_speed: int, st: float = 0, include_headings: bool = False):
        t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cpu_usage = self.__ipmi.get_cpu_util() if self.get_cpu_util else '??'

        temp_cols = [ (key.title(), len(key) + 2, str(value)) for key, value in temps.items() ]
        external_points = [ (title, len(title) + 2, str(data.get('value'))) for title, data in webserver.thermal_data.items() ]

        columns = [
            ("Datetime", 21, t),
            *temp_cols,
            *external_points
        ]

        runtime_ms: float = (time.time() - st) * 1000

        columns.extend([
            ("Fan Speed", 10, f"{target_speed}%"),
            ("CPU Util", 10, f"{cpu_usage}%"),
            ("Loop Runtime", 14, f"{int(runtime_ms)} ms")
        ])
        
        left_pad = 2
        if include_headings:
            print('')
            print('|'.join([ f'{" " * left_pad}{name}{ " " * (length - len(name)) }' for name, length, _ in columns]))
            print("-".join([ "-" * (length + left_pad) for _, length, _ in columns]))
        print('|'.join([ f'{" " * left_pad}{value}{ " " * (length - len(value)) }' for _, length, value in columns]))

    def run(self):
        try:
            self.__unsafe_run()
        except KeyboardInterrupt as e:
            print('Keyboard interrupt')
            self.cleanup()()
        except Exception as e:
            print(f'Error: {e} with trace:')
            traceback.print_exc()
            self.cleanup()()
            raise e

    def __unsafe_run(self):
        start_time = time.time()
        self.__ipmi.disable_auto_fans()
        self.print_table_row(temps=self.__ipmi.get_temps(), target_speed='na', include_headings=True, st=start_time)
        error_count = 0

        line = self.__calculate_function()
        i = 0
        while True:
            i = i + 1
            if i >= 200:
                i = 0

            try:
                self.__loop(line=line, loop_count=i)
                error_count = 0
            except KeyboardInterrupt as e:
                raise e
            except Exception as e:
                print('Error when controlling fan speed!')

                # Exit the loop and cleanup if there are more than 10 errors in a row
                # When this is in docker it should auto heal.
                if error_count >= 5:
                    raise e
                error_count += 1

    def __cleanup_external_temps(self) -> dict[str, float | int]:
        return {
            f'external_{key}': value.get('value')
            for key, value in webserver.thermal_data.items()
            if value.get('last_seen') > time.time() - 300
        }

    def __loop(self, line: Line, loop_count: int):
        loop_start_time = time.time()
        
        temp: dict[str, float | int] = self.__ipmi.get_temps()
        temp.update(self.__cleanup_external_temps())

        cpu_temp = [ int(temp) for key, temp in temp.items() if key.lower().startswith('cpu') or key.lower().startswith('external_')]
        max_cpu_temp = max(cpu_temp)
        target_fan_speed = int(line.calculate(max_cpu_temp))

        if target_fan_speed < self.start_fan:
            target_fan_speed = self.start_fan
        if target_fan_speed > self.end_fan:
            target_fan_speed = self.end_fan

        self.print_table_row(temps=temp, target_speed=target_fan_speed, include_headings=(loop_count % 50 == 0), st=loop_start_time)
        self.__ipmi.set_fan_speed(target_fan_speed)
            
        time.sleep(self.interval - (time.time() - loop_start_time))

if __name__ == '__main__':
    if str(os.environ.get('EXTERNAL_MONITOR', 'false')).lower() in ['true', 't', '1']:
        prefix = 'external_command_'
        commands = [
            (key.removeprefix(prefix),  os.environ.get(key))
            for key in os.environ.keys()
            if key.lower().startswith(prefix)
        ]
        auth_key = os.environ.get('EXERNAL_SERVER_KEY')
        server_host = os.environ.get('EXTERNAL_SERVER_HOST', 'http://localhost:8080')
        interval = int(os.environ.get('INTERVAL', 30))

        while True:
            data = {
                key: float(
                    str(subprocess.run([cmd], capture_output=True, text=True, shell=True, timeout=30.0).stdout).removesuffix('\n')
                )
                for key, cmd in commands
            }

            print(f'Gathered data: {data}')

            requests.post(
                url=f'{server_host}/update_datepoint',
                data=json.dumps({
                    key: re.sub(r'[^0-9]', '', value)
                    for key, value in data.items()
                })
            )

            time.sleep(interval)

    elif str(os.environ.get('ENABLE_SERVER', 'false')).lower() in ['true', 't', '1']:
        monitor = FanMonitor()
        monitor_thread = threading.Thread(target=monitor.run, daemon=True)
        monitor_thread.start()
        
        # 2. Start Flask Server in the main thread
        # Note: host='0.0.0.0' allows the VM to reach this across the bridge
        print("[*] Starting Flask API on port 5000")
        webserver.app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
    else:
        fan_monitor: FanMonitor = FanMonitor()
        fan_monitor.run()

# Monitoring GPU
# nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits