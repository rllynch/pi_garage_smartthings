# pi_garage_smartthings
Monitors a garage door open/closed sensor attached to a Raspberry Pi GPIO and updates a SmartThings hub with its status. A single Raspberry Pi can monitor multiple garage door sensors.

# Usage:
1) Follow the instructions on http://www.richlynch.com/2013/07/27/pi_garage_alert_1/ to wire up the Raspberry Pi and install the dependencies.

2) Clone or make a local copy of this repository.

3) Modify the DAEMON_ARGS line in rpi_garage_smartthings1 and rpi_garage_smartthings2 with the GPIO pins used by your sensors.

4) If you only have one garage door, remove 2 from the "for IDX in" line in install.sh.

5) Copy install.sh and rpi_* to your Raspberry Pi, then run install.sh. 

6) Log into https://graph.api.smartthings.com/, and under My SmartApps, create a new SmartApp with the code in app.groovy.  Also, under My Device Types, create a New SmartDevice with the code from devicetype.groovy. Publish the device for yourself.

7) In the SmartThings iOS app, tap the "+" at the bottom to create a new Device. Under My Apps, tap on RPi Garage Connect. Select the garage doors then tap Done.

8) Back in the SmartThings iOS app under Things, the garage door sensors will show up as contact sensors. Rename the garage doors with more meaningful names by tapping them, then tapping Preferences.
