#!/usr/bin/python3

#
# Copyright (C) 2021, Adam Meily <meily.adam@gmail.com>
#


import subprocess
from dataclasses import dataclass
from sys import stdin
from typing import List, Optional
import re
import os
import sys


# HDMI monitor named, as reported by xrandr
HDMI_MONITOR_NAME = 'HDMI-1'
# Touchscreen monitor name, as reported by xrandr
TOUCHSCREEN_MONITOR_NAME = 'DSI-1'
# Touchscreen device name, as reported by xinput
TOUCHSCREEN_DEVICE_NAME = 'pointer:Goodix Capacitive TouchScreen'

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


class Cyberdeck:

    def __init__(self):
        self.hdmi: Optional[Monitor] = None
        self.touchscreen: Optional[Monitor] = None
        self._monitors = []

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
        print('Detecting active monitors')
        output = subprocess.check_output(['xrandr', '--listmonitors']).decode()
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
            print('>> Monitor:', monitor.name)

        self.monitors = monitors

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
        #print('run:', *xinput)

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
        #print('run:', *xterm)
        subprocess.Popen(xterm, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, cwd=os.path.expanduser("~"))

    def launch_touchscreen_power_watch(self):
        script = os.path.join(os.path.dirname(__file__), 'touchscreen-power-watch.py')
        subprocess.Popen([sys.executable, script], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)

    def setup_undocked(self):
        pass

    def setup(self):
        self.launch_touchscreen_power_watch()
        self.detect_monitors()
        if self.hdmi and self.touchscreen:
            self.setup_docked()
        else:
            self.setup_undocked()


if __name__ == '__main__':
    cyberdeck = Cyberdeck()
    cyberdeck.setup()
