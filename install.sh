#!/bin/bash

sudo rm -f /usr/local/sbin/rpi_garage_smartthings.py
sudo cp -f rpi_garage_smartthings.py /usr/local/sbin
sudo chown root:root /usr/local/sbin/rpi_garage_smartthings.py
sudo chmod 0755 /usr/local/sbin/rpi_garage_smartthings.py

for IDX in 1 2
do
    sudo rm -f /etc/init.d/rpi_garage_smartthings${IDX}
    sudo cp rpi_garage_smartthings${IDX} /etc/init.d/rpi_garage_smartthings${IDX}
    sudo chown root:root /etc/init.d/rpi_garage_smartthings${IDX}
    sudo chmod 0755 /etc/init.d/rpi_garage_smartthings${IDX}
    sudo update-rc.d rpi_garage_smartthings${IDX} defaults
    sudo service rpi_garage_smartthings${IDX} restart
done
