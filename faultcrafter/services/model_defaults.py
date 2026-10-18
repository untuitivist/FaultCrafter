from pathlib import Path


EXPERIMENT32_COMPACT_PATH = Path(
    "outputs/deployment/experiment32_full_data_v1/compact"
)
EXPERIMENT32_MODEL_ID = "experiment32_full_data_v1"
EXPERIMENT32_MODEL_LABEL = "实验32 · 全数据发布版 · 共享主干＋设备LoRA"
EXPERIMENT32_MODEL_SCOPE = (
    "按32方法使用四台内置设备全部允许工况单独训练；不具备留出工况评测资格。"
    "工况归一化已折入设备LoRA，推理不读取源数据。"
)
