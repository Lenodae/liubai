"""Local interactive secret setup. Never echoes or prints the API key."""

import getpass
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
state = root / ".local"
state.mkdir(mode=0o700, exist_ok=True)
print("DeepSeek 密钥仅保存在第四部分本机配置，不会写入网页。")
key = getpass.getpass("请输入 DeepSeek API key（输入不可见）：").strip()
if not key:
    raise SystemExit("未填写密钥，原有配置不变。")
model = input("模型名称（回车使用 deepseek-flash）：").strip() or "deepseek-flash"
temporary = state / "deepseek.json.tmp"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump({"api_key": key, "model": model}, out)
os.replace(temporary, state / "deepseek.json")
print("已保存。回到“分析与执行”，点击载入最新数据即可使用。")
