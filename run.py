import socket

import qrcode

from app import create_app

app = create_app()


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


if __name__ == "__main__":
    ip = get_local_ip()
    url = f"http://{ip}:5000"

    print("\n" + "=" * 60)
    print(f"Сервер: {url}")
    print("=" * 60 + "\n")

    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)

    print(f"\nОткрой на телефоне: {url}\n")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        use_reloader=False,
    )