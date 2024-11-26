import cv2
import requests
import time
import sys

# Configuration
MICROSERVICE_URL = 'https://sai.altermundi.net/firebot/upload-image'
CAPTURE_INTERVAL = 500  # in seconds

def main():
    # Initialize camera
    cap = cv2.VideoCapture(0)  # 0 is the default camera

    if not cap.isOpened():
        print("Cannot open camera")
        sys.exit()

    while True:
        try:
            # Capture frame-by-frame
            ret, frame = cap.read()

            if not ret:
                print("Can't receive frame (stream end?). Exiting ...")
                break

            # Encode frame as JPEG
            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                print("Failed to encode frame")
                continue

            # Prepare HTTP request
            files = {'image': ('image.jpg', buffer.tobytes(), 'image/jpeg')}
            response = requests.post(MICROSERVICE_URL, files=files)

            # Check response
            if response.status_code != 200:
                print(f"Failed to send image: {response.status_code}")

            # Wait for the next capture
            time.sleep(CAPTURE_INTERVAL)

        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(5)  # Wait before retrying

    # Release the camera
    cap.release()

if __name__ == '__main__':
    main()
