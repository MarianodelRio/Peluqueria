import qrcode

url = "https://wa.me/34676273800?text=Hola%2C%20quiero%20pedir%20cita%20%F0%9F%92%88"

qr = qrcode.QRCode(box_size=10, border=4)
qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(fill_color="black", back_color="white")
img.save("qr_cita.png")

print("QR generado: qr_cita.png")
