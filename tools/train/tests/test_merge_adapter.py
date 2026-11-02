"""합친 폴더의 가중치 밖 파일을 원본으로 되돌리기(이슈 #223). 학습 라이브러리 없이 돈다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from merge_adapter import restore_original_files  # noqa: E402

WEIGHTS = {"model.embed_tokens.weight": "model-00001.safetensors", "lm_head.weight": "model-00002.safetensors"}


def write_folder(folder: Path, files: dict[str, str], weights: dict[str, str]) -> Path:
    folder.mkdir()
    (folder / "model.safetensors.index.json").write_text(json.dumps({"weight_map": weights}), encoding="utf-8")
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def test_restore_original_files_keeps_original_config_and_tokenizer(tmp_path):
    original = write_folder(tmp_path / "base", {
        "config.json": '{"rope_theta": 1000000}',
        "tokenizer_config.json": '{"additional_special_tokens": ["<|user|>"]}',
        "vocab.json": "{}", "merges.txt": "#merges", "LICENSE": "Apache-2.0",
    }, WEIGHTS)
    # Transformers 5로 다시 저장한 모양: RoPE 값이 다른 칸 안으로, 특수 토큰이 목록으로, 채팅 틀이 따로 있다
    merged = write_folder(tmp_path / "merged", {
        "config.json": '{"rope_parameters": {"rope_theta": 1000000}}',
        "tokenizer_config.json": '{"extra_special_tokens": ["<|user|>"]}',
        "chat_template.jinja": "{{ messages }}",
    }, WEIGHTS)

    restore_original_files(original, merged)

    for name in ("config.json", "tokenizer_config.json", "vocab.json", "merges.txt", "LICENSE"):
        assert (merged / name).read_text(encoding="utf-8") == (original / name).read_text(encoding="utf-8")
    assert not (merged / "chat_template.jinja").exists()


def test_restore_original_files_stops_when_weight_names_differ(tmp_path):
    original = write_folder(tmp_path / "base", {"config.json": "{}"}, WEIGHTS)
    merged = write_folder(tmp_path / "merged", {"config.json": "{}"}, {"model.embed_tokens.weight": "model-00001.safetensors"})

    with pytest.raises(SystemExit):
        restore_original_files(original, merged)
