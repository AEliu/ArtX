DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

ACCEPT_IMAGE_HEADER = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"

SIGNING_KEY = bytes([123, 43, 78, 35, 222, 44, 197, 197])
AES_KEY = bytes([91, 99, 219, 17, 59, 122, 243, 224, 177, 67, 85, 86, 200, 249, 83, 12])
AES_IV = bytes([113, 231, 4, 5, 53, 58, 119, 139, 250, 111, 188, 48, 50, 27, 149, 146])
ENCRYPTION_MARKER = b"\x0a\x0a\x0a\x0a"
