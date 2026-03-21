import os
import zipfile
import subprocess

UPLOAD_DIR = "uploads"
BOTS_DIR = "bots"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BOTS_DIR, exist_ok=True)


def deploy_zip(zip_path):
    """Extract a bot zip and install dependencies if present."""

    name = os.path.splitext(os.path.basename(zip_path))[0]
    target = os.path.join(BOTS_DIR, name)

    os.makedirs(target, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(target)

    req = os.path.join(target, "requirements.txt")

    if os.path.exists(req):
        subprocess.run(["pip", "install", "-r", req])

    return target
