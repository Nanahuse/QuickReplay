from windows_capture_device_list import list_devices

if __name__ == "__main__":
    devices = list_devices()
    for device in devices:
        print(f"{device.id}: {device.name}")
        print(f" - Resolutions: {[f'{res.width}x{res.height}' for res in device.resolutions]}")
