import os
import socket

import qrcode

from app import create_app

app = create_app()


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


if __name__ == "__main__":
    if app.config["APP_ENV"] == "production":
        raise SystemExit("Use a production WSGI server behind HTTPS; see README.md.")

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
        host=os.getenv("HOST", "127.0.0.1"),
        port=5000,
        debug=False,
        use_reloader=False,
    )
