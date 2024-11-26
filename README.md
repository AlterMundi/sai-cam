# sai-cam
## SaiCam implementation on RaspberriPi 3 B+

#### Install Raspberry Pi OS using Raspberry Pi Imager
https://www.raspberrypi.com/software/

Start the Imager
Select debian Lite 64bit
Configure hostname, username and password, SSH connection.

#### Login to the RPI via console:
open SSH session with username and password generated in the imager.
`ssh admin@saicam1.local`
password: `admin`


#### Install dependencies
sudo apt install python3-full
sudo apt install python3-opencv

###### campost/ folder contains main.py file thats forward images from cammera (USB or RTSP) to de SAI Firebot

### SAI cammera control and access.



## To install and run the service:

1. Create a directory for the project:
```bash
mkdir ~/camera_project
cd ~/camera_project
```

2. Copy all the above files into the directory.

3. Run the installation script:
```bash
chmod +x install.sh
./install.sh
```

This code includes:

- Configuration via YAML
- Configurable image compression
- System health monitoring
- Local storage with recycling system
- Secure SSL/TLS handling
- Logging system with rotation
- Automatic storage management
- Systemd service for automatic execution
- Automatic restart in case of failures

To monitor the service:
```bash
sudo systemctl status camera_service
sudo journalctl -u camera_service -f
```

To modify the configuration:
```bash
sudo nano /etc/camera_service/config.yaml
sudo systemctl restart camera_service
``` 
