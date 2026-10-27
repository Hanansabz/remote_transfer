# Dropzone — Local File Transfer

A desktop app for sending a file between two computers on the same local network. Run the same app on both computers: the receiver chooses a save folder and starts listening; the sender selects a file, enters the receiver address and one-time code, then sends. The receiver approves each incoming file. The sender and receiver compare a SHA-256 checksum after transfer.

## Run

Python 3 with Tkinter is required. No third-party Python packages are used.

```powershell
python transfer_app.py
```

Start the app on both computers. On the receiving computer, choose a save folder and click **Start receiving**. Share the displayed address and six-digit code with the sender. On the sending computer, open the **Send** tab, choose a file, enter those details, and click **Send file**. Accept the incoming file on the receiving computer.

Both computers need to be on the same local network. If Windows Firewall asks about Python, allow it on the private network so the other computer can connect. Do not create an internet port-forward for this prototype.

## Current scope

Transfers are limited to 10 GB per file. The receiver asks before saving and avoids overwriting files. A one-time pairing code authenticates a transfer, and SHA-256 verifies the received bytes. The file contents are not encrypted in this first version, so use it only on a trusted local network. Internet/VPN support and encrypted transport are future improvements.
