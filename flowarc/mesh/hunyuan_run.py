"""Runs inside the Hunyuan3D-2.1 venv: image -> untextured mesh. Usage: hunyuan_run.py REPO IMAGE OUT.glb [SEED]"""

import sys

repo, image, out = sys.argv[1:4]
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
sys.path.insert(0, f"{repo}/hy3dshape")

import torch
from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
from hy3dshape.rembg import BackgroundRemover
from PIL import Image

img = BackgroundRemover()(Image.open(image).convert("RGB"))
pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained("tencent/Hunyuan3D-2.1")
pipe(image=img, generator=torch.manual_seed(seed))[0].export(out)
