#!/usr/bin/python3

#
# Copyright (C) 2021, Adam Meily <meily.adam@gmail.com>
#


import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple
import re
import os
import sys
import socket
from enum import Enum
import psutil
import random
import time


__version__ = '0.1.0'


# HDMI monitor named, as reported by xrandr
HDMI_MONITOR_NAME = 'HDMI-1'
# Touchscreen monitor name, as reported by xrandr
TOUCHSCREEN_MONITOR_NAME = 'DSI-1'
# Touchscreen device name, as reported by xinput
TOUCHSCREEN_DEVICE_NAME = 'pointer:Goodix Capacitive TouchScreen'
# Touchscreen power control filename
BACKLIGHT_POWER_FILENAME = '/sys/class/backlight/rpi_backlight/bl_power'

#
# Keep this around for future reference since these numbers were initially working.
#
# TOUCHSCREEN_TRANSFORM_MATRIX = ['0.416666666666667', '0', '0.266666666666667', '0',
#                                 '0.307692307692308', '0.692307692307692', '0', '0', '1']

#
# xrandr --listmonitors output parser
#
# sample output (docked):
#
# Monitors: 2
#  0: +*DSI-1 800/212x480/127+512+1080  DSI-1
#  1: +HDMI-1 1920/598x1080/336+0+0  HDMI-1
#
MONITOR_PATTERN = re.compile(
    r'^\s+(\d+):'  # id
    r'\s+\S+\s+'  # primary/secondary
    r'(\d+)\/\d+x(\d+)\/\d+'  # size (width x height)
    r'\+(\d+)\+(\d+)'  # position (x, y)
    r'\s+(\S+)\s*$',  # name
    re.MULTILINE
)

CPU_TEMP_FILENAME = '/sys/class/thermal/thermal_zone0/temp'
BANNER = '''
\x1b[38;5;40m===========================================================
 _____         _                     _              _
/  __ \\       | |                   | |            | |
\x1b[38;5;41m| /  \\/ _   _ | |__    ___  _ __  __| |  ___   ___ | | __
| |    | | | || '_ \\  / _ \\| '__|/ _` | / _ \\ / __|| |/ /
| \\__/\\| |_| || |_) ||  __/| |  | (_| ||  __/| (__ |   <
\x1b[38;5;42m \\____/ \\__, ||_.__/  \\___||_|   \\__,_| \\___| \\___||_|\\_\\
         __/ |
        |___/                                        \x1b[38;5;45mv{version}
\x1b[38;5;46m===========================================================
\x1b[0m
'''.format(version=__version__)


AUDIO_DIRECTORY = os.path.join(os.path.dirname(__file__), 'audio')
MEDITATION_DIRECTORY = os.path.join(AUDIO_DIRECTORY, 'meditations')


@dataclass
class Monitor:
    '''
    An active monitor.
    '''
    id: int
    name: str
    width: int = 0
    height: int = 0
    x: int = 0
    y: int = 0


def humanize_duration(duration: int) -> str:
    if duration > 3600:
        hours = duration / 3600
        duration = duration % 3600
    else:
        hours = None

    minutes = duration / 60
    seconds = duration % 60

    if hours:
        return f'{hours}:{minutes:02}:{seconds:02}'
    return f'{minutes:02}:{seconds:02}'


class CyberdeckMode(Enum):
    docked = 'Docked'
    undocked = 'Undocked'
    terminal = 'Terminal'


class Cyberdeck:

    def __init__(self):
        self.hdmi: Optional[Monitor] = None
        self.touchscreen: Optional[Monitor] = None
        self._monitors = []
        self.mode = None
        self.remote = None

    @property
    def monitors(self) -> List[Monitor]:
        return self._monitors

    @monitors.setter
    def monitors(self, monitors) -> None:
        self._monitors = monitors
        self.hdmi = None
        self.touchscreen = None
        for monitor in monitors:
            if monitor.name == HDMI_MONITOR_NAME:
                self.hdmi = monitor
            elif monitor.name == TOUCHSCREEN_MONITOR_NAME:
                self.touchscreen = monitor

    def detect_monitors(self) -> None:
        '''
        Detect active monitors. This will load touchscreen information and, when docked, load the
        HDMI monitor information.
        '''
        monitors = []
        if not os.environ.get('DISPLAY'):
            env = os.environ.copy()
            env['DISPLAY'] = ':0.0'
        else:
            env = None

        if os.environ.get('SSH_CLIENT'):
            self.remote = os.environ['SSH_CLIENT'].split()[0].strip()

        try:
            output = subprocess.check_output(['xrandr', '--listmonitors'], env=env).decode()
        except subprocess.CalledProcessError:
            output = ''

        for match in MONITOR_PATTERN.finditer(output):
            monitor = Monitor(
                id=int(match.group(1)),
                name=match.group(6),
                width=int(match.group(2)),
                height=int(match.group(3)),
                x=int(match.group(4)),
                y=int(match.group(5))
            )
            monitors.append(monitor)
            # print('>> Monitor:', monitor.name)

        self.monitors = monitors
        if self.hdmi and self.touchscreen:
            self.mode = CyberdeckMode.docked
        elif self.touchscreen:
            self.mode = CyberdeckMode.undocked
        else:
            self.mode = CyberdeckMode.terminal

    def _get_touchscreen_transform_matrix(self) -> List[float]:
        '''
        Touchscreen transformation matrix. This is needed while docked to make sure that
        touchscreen coordinates are properly translated to only the touchscreen. Without this,
        clicking the touch screen may move the mouse click to an area on the HDMI display and the
        touchscreen is almost impossible to use. This logic was copied from:
        https://docs.google.com/spreadsheets/d/13CNQjWfzpEkHM4ZdCcUWDTdQNaFqQ6TYTwatQsYcHcQ/edit#gid=1008975224
        '''
        # Get the entire screen dimensions
        total_width = max(self.hdmi.width + self.hdmi.x,
                          self.touchscreen.x + self.touchscreen.width)
        total_height = max(self.touchscreen.height + self.hdmi.y,
                           self.touchscreen.y + self.touchscreen.height)

        return [
            self.touchscreen.width / total_width,
            0.0,
            self.touchscreen.x / total_width,
            0.0,
            self.touchscreen.height / total_height,
            self.touchscreen.y / total_height,
            0.0,
            0.0,
            1.0
        ]

    def setup_docked(self):
        '''
        Setup cyberdeck in docked mode (HDMI plugged in).
        '''
        # fix touchscreen click coordinates when HDMI is plugged in
        transform_matrix = self._get_touchscreen_transform_matrix()
        xinput = [
            'xinput', 'set-prop', TOUCHSCREEN_DEVICE_NAME,
            '--type=float', 'Coordinate Transformation Matrix'
        ] + [str(i) for i in transform_matrix]
        subprocess.check_call(xinput, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # print('run:', *xinput)

        self.terminal()

    def terminal(self) -> None:
        xterm = [
            'xterm',
            '-fa', 'Monospace Regular',  # font family
            '-fs', '11',  # font size
            '-fullscreen',  # full screen, no title bar
            '-bc',  # block cursor
            '-cr', 'green',  # green cursor
            '-dc',  # dynamic color selection
            '-bg', 'black',  # background color = black
            '-fg', 'white',  # foregrond color = white
            '-geometry', f'+{self.touchscreen.x}+{self.touchscreen.y}'  # position on touchscreen
        ]
        # print('run:', *xterm)
        subprocess.Popen(xterm, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, cwd=os.path.expanduser("~"))

    def launch_screensaver(self) -> None:
        '''
        Start a background process that monitors for xscreensaver activity. This script will turn
        off the touchscreen backlight while the screensaver is active.
        '''
        subprocess.Popen([sys.executable, __file__], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    def start(self):
        '''
        Start Cyberdeck. This should only be called once after login.
        '''
        self.launch_screensaver()
        if self.mode == 'Docked':
            self.setup_docked()

    def get_cpu_temp(self) -> Tuple[int, str]:
        '''
        Get the CPU temperature, in fahrenheit. Returns a tuple containing the core temperature and
        the ANSI escape color code for the current temperature.
        '''
        with open(CPU_TEMP_FILENAME, 'r') as fp:
            value = fp.read()

        temp = int(((float(value.strip()) / 1000.0) * 1.8) + 32)
        if temp < 110:
            color = '1;34m'
        elif temp < 130:
            color = '1;33m'
        else:
            color = '1;31m'

        return temp, color

    def get_cpu_usage(self) -> List[Tuple[int, str]]:
        '''
        Get the CPU usage for each core. Returns a list of tuples containing the core usage
        (10 == 10%) and the ANSI escape color code for the usage.
        '''
        usage = psutil.cpu_percent(interval=0.1, percpu=True)
        cpus = []
        for cpu in usage:
            if cpu < 50.0:
                color = '1;34m'
            elif cpu < 75.0:
                color = '1;33m'
            else:
                color = '1;31m'
            cpus.append((int(cpu), color))
        return cpus

    def get_memory_usage(self) -> Tuple[int, str]:
        '''
        Get memory usage. This returns a tuple containing the memory usage percantage (10 == 10%)
        and the ANSI escape color code for the usage.
        '''
        usage = int(psutil.virtual_memory().percent)
        if usage < 50.0:
            color = '1;34m'
        elif usage < 75.0:
            color = '1;33m'
        else:
            color = '1;31m'
        return usage, color

    def get_ip_address(self) -> str:
        try:
            output = subprocess.check_output(['hostname', '--all-ip-addresses'],
                                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            output = b''

        return output.decode().strip()

    def print_banner(self) -> None:
        '''
        Print the cyberdeck banner
        '''
        username = os.getlogin()
        hostname = socket.gethostname()
        temp, temp_color = self.get_cpu_temp()
        cpus = '    '.join([
            f'\x1b[{color}{cpu}%\x1b[0m' for cpu, color in self.get_cpu_usage()
        ])
        memory, memory_color = self.get_memory_usage()
        mode = self.mode.value
        if self.remote:
            mode += f' (\x1b[1;35m{self.remote}\x1b[0m)'

        ip = self.get_ip_address()
        if ip:
            ip_color = '1;35m'
        else:
            ip = 'Disconnected'
            ip_color = '1;31m'

        print(BANNER)
        print(f'Mode:      {mode}')
        print(f'Operator:  \x1b[1;33m{username}\x1b[0m @ \x1b[1;33m{hostname}\x1b[0m')
        print(f'Network:   \x1b[{ip_color}{ip}\x1b[0m')  # TODO
        for monitor in self.monitors:
            if monitor is self.hdmi:
                monitor_type = '\x1b[1;36mDesktop\x1b[0m'
            elif monitor is self.touchscreen:
                monitor_type = '\x1b[1;32mTerminal\x1b[0m'
            else:
                monitor_type = 'unknown'

            print(f'Monitor:   [{monitor.id}] {monitor_type}',
                  f'{monitor.width}x{monitor.height} +{monitor.x}.{monitor.y}')

        print(f'Temp:      \x1b[{temp_color}{temp}F\x1b[0m')
        print(f'CPU:       {cpus}')
        print(f'Memory:    \x1b[{memory_color}{memory}%\x1b[0m')
        print()

    def screensaver(self) -> None:
        '''
        Monitor xscreensaver events and turn off the touchscreen backlight while the screensaver is
        active.
        '''
        watch = subprocess.Popen(['xscreensaver-command', '-watch'], stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)

        try:
            while watch.poll() is None:
                parts = watch.stdout.readline().strip().lower().split()
                if not parts:
                    continue

                action = parts[0].decode()
                if action == 'unblank':
                    self.toggle_touchscreen_backlight(True)
                elif action in ('blank', 'run'):
                    self.toggle_touchscreen_backlight(False)
        except KeyboardInterrupt:
            watch.terminate()

        watch.wait()

    def toggle_touchscreen_backlight(self, enabled: bool) -> None:
        '''
        Toggle the touchscreen backlight.

        :param enabled: turn on the backlight
        '''
        print('toggle_touchscreen_backlight:', enabled)
        with open(BACKLIGHT_POWER_FILENAME, 'wb') as fp:
            fp.write(b'0\n' if enabled else b'1\n')

    def get_audio_duration(self, filename: str) -> int:
        try:
            output = subprocess.check_output(['ffprobe', '-i', filename, '-show_format'],
                                             stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            output = b''

        lines = output.splitlines()
        for line in lines:
            if line.startswith(b'duration='):
                return int(line.split('=')[1].strip())

        return 0

    def load_meditations(self) -> List[Tuple[str, int]]:
        meditations = []
        try:
            filenames = os.listdir(MEDITATION_DIRECTORY)
        except OSError:
            filenames = []

        for filename in filenames:
            path = os.path.join(MEDITATION_DIRECTORY, filename)
            duration = self._get_audio_duration(path)
            if duration:
                meditations.append((path, duration))

        return meditations

    def play_meditation(self, filename: str, length: int, loop: bool = False) -> None:
        print('Playing meditation:', filename, '-', humanize_duration(length))
        args = ['cvlc', filename]
        if loop:
            args.append('--loop')

        vlc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               stdin=subprocess.DEVNULL)
        try:
            while vlc.poll() is None:
                time.sleep(0.5)
        except KeyboardInterrupt:
            vlc.terminate()
            vlc.wait()

    def print_meditation_strategy(self, meditations: List[Tuple[str, int]], interval: int) -> None:
        print('Meditation Strategy:')
        offset = 0
        for path, duration in meditations:
            length = humanize_duration(offset)
            print(f'  {length} {os.path.basename(path)} ({humanize_duration(length)})')
            offset += duration + interval
        print()

    def meditate(self, duration: int = 60) -> None:
        meditations = self.load_meditations()
        selected = []
        if not meditations:
            print('error: no meditations available', file=sys.stderr)
            return

        remaining = duration
        random.shuffle(meditations)
        for path, length in meditations:
            if length < remaining:
                selected.append((path, length))
                remaining -= length

        interval = remaining / len(selected)
        self.print_meditation_strategy(selected, interval)

        for path, length in selected:
            self.play_meditation(path, length)
            time.sleep(interval)

        self.play_meditation(os.path.join(AUDIO_DIRECTORY, 'alarm.mp3'), loop=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True, dest='command')
    commands.add_parser('start')
    commands.add_parser('banner')
    commands.add_parser('screensaver')
    commands.add_parser('terminal')

    meditate = commands.add_parser('meditate')
    meditate.add_argument('-d', '--duration', action='store', default=60, type=int,
                          help='meditation session duration, in minutes')

    args = parser.parse_args()

    cyberdeck = Cyberdeck()
    cyberdeck.detect_monitors()

    if args.command == 'start':
        cyberdeck.start()
    elif args.command == 'banner':
        cyberdeck.print_banner()
    elif args.command == 'screensaver':
        cyberdeck.screensaver()
    elif args.command == 'terminal':
        cyberdeck.terminal()
    elif args.command == 'meditate':
        cyberdeck.meditate(duration=args.duration)
