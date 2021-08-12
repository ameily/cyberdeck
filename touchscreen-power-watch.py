#!/usr/bin/python3

#
# Copyright (C) 2021, Adam Meily <meily.adam@gmail.com>
#

import subprocess
BACKLIGHT_POWER_FILENAME = '/sys/class/backlight/rpi_backlight/bl_power'

def toggle_touchscreen_backlight(enabled: bool) -> None:
    with open(BACKLIGHT_POWER_FILENAME, 'wb') as fp:
        fp.write(b'0\n' if enabled else b'1\n')


if __name__ == '__main__':
    watch = subprocess.Popen(['xscreensaver-command', '-watch'], stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)

    try:
        while watch.poll() is None:
            parts = watch.stdout.readline().strip().lower().split()
            if not parts:
                continue

            action = parts[0].decode()
            if action == 'unblank':
                toggle_touchscreen_backlight(True)
            elif action in ('blank', 'run'):
                toggle_touchscreen_backlight(False)
    except KeyboardInterrupt:
        watch.terminate()

    watch.wait()
