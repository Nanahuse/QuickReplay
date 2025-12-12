import cv2

if __name__ == "__main__":
    capture = cv2.VideoCapture(6)

    try:
        while True:
            ret, frame = capture.read()
            if not ret:
                break

            cv2.imshow("Webcam", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()
