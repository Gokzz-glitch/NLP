import os
from cryptography.fernet import Fernet

def main():
    json_path = os.path.join("config", "firebase_credentials.json")
    enc_path = os.path.join("config", "firebase_credentials.enc")
    
    if not os.path.exists(json_path):
        print(f"Error: Could not find {json_path}")
        return

    # Generate a key
    key = Fernet.generate_key()
    f = Fernet(key)

    # Read plaintext
    with open(json_path, "rb") as file:
        plaintext = file.read()

    # Encrypt
    encrypted_data = f.encrypt(plaintext)

    # Write to .enc
    with open(enc_path, "wb") as file:
        file.write(encrypted_data)

    print(f"✅ Successfully encrypted payload to {enc_path}")
    print(f"🔑 FERNET_KEY={key.decode('utf-8')}")
    print(f"⚠️  Please copy the FERNET_KEY to your .env file.")
    print(f"⚠️  You MUST manually delete {json_path} for security reasons.")

if __name__ == "__main__":
    main()
