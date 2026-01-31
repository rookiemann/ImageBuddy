# gpu_utils.py
import subprocess
from core import logger


def get_available_gpus():
    """Returns list like: ['CPU', 'GPU 0: ...', ...]"""
    gpus = ["CPU"]

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.strip().splitlines():
            idx, name, memory = line.split(", ")
            gpus.append(f"GPU {idx}: {name.strip()} ({memory} MiB)")
    except:
        pass

    logger.info(f"Detected devices: {gpus}")
    return gpus


def get_default_selection():
    gpus = get_available_gpus()
    # Prefer first GPU if any, else CPU
    for gpu in gpus:
        if gpu.startswith("GPU"):
            return gpu
    return "CPU"
