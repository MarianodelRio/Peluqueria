import os
import re
import sys

import qrcode
import yaml

# ── Load config.yaml relative to this script ──────────────────────────────
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
with open(_config_path, "r", encoding="utf-8") as _fh:
    _cfg = yaml.safe_load(_fh)

telefono_raw = (_cfg or {}).get("negocio", {}).get("telefono_contacto", "")
telefono = re.sub(r"\D", "", telefono_raw)  # keep digits only
if not telefono:
    sys.exit(
        "Error: 'negocio.telefono_contacto' está vacío o ausente en config.yaml. "
        "El QR no se puede generar."
    )

_out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_cita.png")

url = f"https://wa.me/{telefono}?text=Hola%2C%20quiero%20pedir%20cita%20%F0%9F%92%88"

qr = qrcode.QRCode(box_size=10, border=4)
qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save(_out_path)

print(f"QR generado: {_out_path} → {url}")
