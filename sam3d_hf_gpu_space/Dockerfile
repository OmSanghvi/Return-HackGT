FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    CONDA_DIR=/opt/conda \
    PATH=/opt/conda/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FORCE_CUDA=1 \
    PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121" \
    PIP_FIND_LINKS=https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git wget ca-certificates ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# The official SAM 3D Objects environment is a CUDA 12.1 / Python 3.11 conda
# environment.  A CUDA *devel* base is essential: PyTorch3D and FlashAttention
# contain CUDA extensions that must be compiled while the image is built.
RUN wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh \
    && bash /tmp/miniforge.sh -b -p "$CONDA_DIR" \
    && rm /tmp/miniforge.sh \
    && conda config --system --set channel_priority strict

WORKDIR /opt/sam3d
RUN git clone --depth 1 https://github.com/facebookresearch/sam-3d-objects.git .

RUN mamba env create -f environments/default.yml \
    && mamba run -n sam3d-objects pip install -e '.[dev]' \
    && mamba run -n sam3d-objects pip install -e '.[p3d]' \
    && mamba run -n sam3d-objects pip install -e '.[inference]' \
    && ./patching/hydra

COPY app.py /app/app.py
WORKDIR /app
EXPOSE 7860

CMD ["mamba", "run", "--no-capture-output", "-n", "sam3d-objects", "python", "app.py"]
