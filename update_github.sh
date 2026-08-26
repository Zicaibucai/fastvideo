#!/usr/bin/env bash
# 在本机（Mac）运行：把当前文件夹的新版本更新推送到已有的 GitHub 仓库，
# 同时保留远程原有的提交历史。
#
# 用法：
#   cd "/Users/apple/Documents/中建实习/第六周/fastvideo"
#   bash update_github.sh
#
# 推送时若要求登录：用户名填 Zicaibucai，密码处粘贴 GitHub Personal Access Token。

set -e

REMOTE="https://github.com/Zicaibucai/fastvideo.git"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_DIR="/tmp/fastvideo_push_$$"

echo "==> 1/5 克隆远程现有仓库到临时目录 ${TMP_DIR}"
git clone "${REMOTE}" "${TMP_DIR}"

echo "==> 2/5 用本地新版本覆盖（保留 .git，忽略依赖/密钥/压缩包等）"
rsync -a --delete \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.venv' \
  --exclude='.venv-local' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.mypy_cache' \
  --exclude='.ruff_cache' \
  --exclude='dist' \
  --exclude='build' \
  --exclude='.env' \
  --exclude='*.zip' \
  --exclude='*.db' \
  --exclude='zitG1nIE' \
  --exclude='openevai_img2video/videos' \
  --exclude='openevai_img2video/frames' \
  --exclude='openevai_img2video/thumbs' \
  --exclude='backend/data' \
  "${SRC_DIR}/" "${TMP_DIR}/"

cd "${TMP_DIR}"

echo "==> 3/5 查看变更概览"
git add -A
git status --short | head -40
echo "..."
echo "变更文件数：$(git status --short | wc -l | tr -d ' ')"

echo "==> 4/5 提交"
git -c user.name="Zicaibucai" \
    -c user.email="Zicaibucai@users.noreply.github.com" \
    commit -m "Update to latest version (2026-08-20)" || {
      echo "没有检测到变更，无需推送。"
      exit 0;
    }

echo "==> 5/5 推送到 GitHub"
git push origin main

echo ""
echo "完成！查看：https://github.com/Zicaibucai/fastvideo"

# 清理本机之前那个沙盒残留的、独立初始化的 .git（可选）
echo "提示：当前源目录里有一个本地独立的 .git（与远程无关），如不需要可手动删除："
echo "  rm -rf \"${SRC_DIR}/.git\""
