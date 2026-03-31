import bcrypt
print(bcrypt.hashpw(b'admin123', bcrypt.gensalt(10)).decode())