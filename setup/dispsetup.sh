#!/bin/sh
if ! grep -q 'Raspberry Pi' /proc/device-tree/model || (grep -q okay /proc/device-tree/soc/v3d@7ec00000/status 2> /dev/null || grep -q okay /proc/device-tree/soc/firmwarekms@7e600000/status 2> /dev/null || grep -q okay /proc/device-tree/v3dbus/v3d@7ec04000/status 2> /dev/null) ; then
if xrandr --output HDMI-1 --mode 1920x1080 --rate 60.00 --pos 0x0 --rotate normal --output DSI-1 --primary --mode FIXED_MODE --rate 60.06 --pos 512x1080 --rotate left --dryrun ; then 
xrandr --output HDMI-1 --mode 1920x1080 --rate 60.00 --pos 0x0 --rotate normal --output DSI-1 --primary --mode FIXED_MODE --rate 60.06 --pos 512x1080 --rotate left
fi
fi
if [ -e /usr/share/tssetup.sh ] ; then
. /usr/share/tssetup.sh
fi
exit 0