#!/usr/bin/env bash
# 在本机（Mac）运行此脚本，将 fastvideo 推送到 GitHub。
# 运行前请先在 GitHub 网页上创建一个空的 Public 仓库：fastvideo
# （不要勾选 README/gitignore/license，保持空仓库）
#
# 用法：
#   cd "/Users/apple/Documents/中建实习/第六周/fastvideo"
#   bash push_to_github.sh
#
# 如果你的 GitHub 用户名不是 apple，或仓库地址不同，请修改下面的 GITHUB_USER / REPO_NAME。

set -e

GITHUB_USER="apple"        # ←← 改成你的 GitHub 用户名
REPO_NAME="fastvideo"      # ←← 改成你的仓库名（如果不同）

echo "==> 1/5 清理沙盒残留的 .git（如果有）"
rm -rf .git

echo "==> 2/5 初始化 git 仓库"
git init -b main

echo "==> 3/5 暂存文件（.env / node_modules / venv / zip 等已被 .gitignore 排除）"
git add -A

echo "==> 4/5 首次提交"
git -c user.name="${GITHUB_USER}" -c user.email="${GITHUB_USER}@users.noreply.github.com" \
    commit -m "Initial commit: FastVideo AI bid video platform" || echo "（没有新变更，跳过提交）"

echo "==> 5/5 添加远程并推送"
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
git branch -M main

echo ""
echo "即将推送到 https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
echo "推送时会要求输入用户名和密码 —— 密码处请粘贴 GitHub Personal Access Token（不是账号密码）。"
echo "PAT 获取：https://github.com/settings/tokens （勾选 repo 权限）"
echo ""

git push -u origin main

echo ""
echo "完成！仓库地址：https://github.com/${GITHUB_USER}/${REPO_NAME}"
