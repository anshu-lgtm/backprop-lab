#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backprop Lab 一键发布脚本。

在项目目录执行一次，即可完成：
  1. 提交本地未提交的改动（如果有）
  2. 校验远端 GitHub Actions CI 内容，缺失或缩进损坏时自动修复
  3. 推送 main 到 GitHub（自动带上 Windows 网络兼容参数、自动 rebase）
  4. 校验远端 commit 并打印 CI 运行结果

用法（在项目目录执行）：
  python publish.py                          # 自动复用本机 GitHub 登录态，代码 + CI 一次完成
  python publish.py ghp_xxxxxxxxxxxx         # 显式 PAT（适合 CI/无 GUI 环境）
  set GITHUB_TOKEN=ghp_xxx && python publish.py   # 推荐：token 不进命令行历史
  python publish.py --check                  # 只检查状态，不联网写入

Windows 下也可以直接双击 publish.bat（等价于 python publish.py）。
PAT 只从命令行参数或环境变量读取，绝不写入任何文件、也不写进 git 配置。
自动读取的登录态来自 Windows 凭据管理器，同样不会落盘或回显。
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
OWNER, REPO, BRANCH = "anshu-lgtm", "backprop-lab", "main"
REPO_URL = f"https://github.com/{OWNER}/{REPO}"
CI_REMOTE_PATH = ".github/workflows/ci.yml"
CI_TEMPLATE = ROOT / "docs" / "ci.yml.example"
API_CONTENTS = (
    f"https://api.github.com/repos/{OWNER}/{REPO}/contents/"
    f"{urllib.parse.quote(CI_REMOTE_PATH, safe='/')}"
)
DEMO_URL = "https://bp-training-microscope.app.workbuddy.host/?sharecode=QQUVVFCKMQ"

# 之前踩过的坑：Windows SChannel + HTTP/2 在这个代理环境下会 502 / 握手失败
GIT_BASE = [
    "git", "-C", str(ROOT),
    "-c", "http.sslBackend=openssl",
    "-c", "http.version=HTTP/1.1",
]


def step(n, text):
    print(f"\n[{n}/4] {text}", flush=True)


def git(*args, input_text=None, check=True):
    proc = subprocess.run(
        GIT_BASE + list(args),
        input=input_text,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    shown = " ".join(args)
    if "x-access-token:" in shown:
        shown = shown.split("x-access-token:", 1)[0] + "x-access-token:***@github.com/..."
    if check and proc.returncode != 0:
        print(f"  $ git {shown}")
        print(f"  {proc.stdout.strip()}")
        print(f"  {proc.stderr.strip()}")
        raise SystemExit("git 命令失败，已停止（不会改动远端）")
    return proc


def clear_stale_credentials():
    """旧 PAT 已撤销时，清掉 GCM 缓存，避免 push 一直 401；之后会弹一次浏览器登录。"""
    try:
        subprocess.run(
            ["git", "credential-manager", "erase"],
            input="protocol=https\nhost=github.com\n\n",
            text=True,
            capture_output=True,
            cwd=ROOT,
            timeout=15,
        )
        print("  已清理失效的 GitHub 凭据缓存，接下来会弹出一次浏览器登录。")
    except Exception:
        pass


def commit_local_changes():
    status = git("status", "--porcelain").stdout
    if not status.strip():
        print("  工作区干净，无需提交。")
        return
    files = [line.strip() for line in status.strip().splitlines()]
    print(f"  检测到 {len(files)} 项本地改动，自动提交：{' '.join(files[:5])}")
    git("add", "-A")
    msg = f"chore: sync local changes before publish ({datetime.now():%Y-%m-%d %H:%M})"
    git("commit", "-m", msg)
    print(f"  已提交：{msg}")


def push(token):
    if token:
        quoted = urllib.parse.quote(token, safe="")
        url = f"https://x-access-token:{quoted}@github.com/{OWNER}/{REPO}.git"
        # 禁用 credential.helper，防止 GCM 用缓存里的旧凭据覆盖 URL 中的 token
        cmd = ["-c", "credential.helper=", "push", url,
               f"HEAD:refs/heads/{BRANCH}"]
    else:
        # 直接复用 GCM 登录态，成功就是真正的一次执行、零交互
        cmd = ["push", "origin", f"HEAD:refs/heads/{BRANCH}"]

    first = git(*cmd, check=False)
    if first.returncode == 0:
        return first
    err = ((first.stderr or "") + (first.stdout or "")).lower()

    # 网页端创建 CI / 别人推送过 -> 远端有新提交，自动 rebase 后重试一次
    if "fetch first" in err or "non-fast-forward" in err or "rejected" in err:
        print("  远端有新提交，自动 fetch + rebase 后重试……")
        git("fetch", "origin", check=False)
        rebased = git("rebase", f"origin/{BRANCH}", check=False)
        if rebased.returncode != 0:
            print((rebased.stdout or "").strip()[-600:])
            print((rebased.stderr or "").strip()[-600:])
            print("  自动合并失败，请手动解决冲突后重跑（未强制覆盖任何提交）。")
            return rebased
        return git(*cmd, check=False)

    if not token and ("authentication failed" in err or "401" in err or "invalid username" in err):
        clear_stale_credentials()
        print("  用新的浏览器登录重试一次……")
        return git(*cmd, check=False)

    # 代理常见的 502 / 空响应：自动重试，避免还要手动再执行一次
    network_words = ("empty reply", "502", "timed out", "unable to access",
                     "could not resolve", "early eof", "rpc failed")
    if any(w in err for w in network_words):
        last = first
        for attempt in (1, 2):
            print(f"  网络波动，自动重试 {attempt}/2 ……")
            time.sleep(2)
            last = git(*cmd, check=False)
            if last.returncode == 0:
                return last
            new_err = ((last.stderr or "") + (last.stdout or "")).lower()
            if "fetch first" in new_err or "rejected" in new_err:
                print("  远端在此期间产生了新提交，重跑脚本即可自动 rebase 后推送。")
                return last
        return last
    return first


def explain_push_failure(proc):
    err = (proc.stderr or "") + (proc.stdout or "")
    low = err.lower()
    print(err.strip()[-1500:])
    if "authentication failed" in low or "401" in low or "invalid username" in low:
        print("\n  原因：GitHub 未接受凭据（旧 PAT 已撤销 / GCM 缓存失效）。")
        print("  解决：用新的 classic PAT（勾选 repo + workflow）重跑：")
        print(f"        set GITHUB_TOKEN=ghp_xxx && python publish.py")
    elif "502" in low or "timed out" in low or "could not resolve" in low or "unable to access" in low:
        print("\n  原因：代理网络波动。脚本已启用 openssl + HTTP/1.1，直接重跑一次即可。")
    elif "gh001" in low or "workflow" in low or "refusing to allow" in low:
        print("\n  原因：PAT 缺少 workflow 权限，无法推送 workflow 文件。")
        print("  解决：换用勾选 workflow 的 PAT，或改用网页端创建 CI。")
    elif "rejected" in low or "fetch first" in low or "conflict" in low:
        print("\n  原因：远端与本地有冲突，自动合并未成功。")
        print("  解决：手动处理冲突（git status）后重跑，脚本不会强制覆盖。")


def gcm_token():
    """复用 Windows 凭据管理器里已有的 GitHub 登录态，用于 GitHub API（不落盘、不回显）。"""
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            text=True, capture_output=True, cwd=ROOT, timeout=15,
        )
        if proc.returncode != 0:
            return None
        values = dict(
            line.split("=", 1)
            for line in proc.stdout.strip().splitlines()
            if "=" in line
        )
        return values.get("password") or None
    except Exception:
        return None


def api_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "backprop-lab-publish",
        "Content-Type": "application/json",
    }


def api(method, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        API_CONTENTS, data=data, method=method, headers=api_headers(token)
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, (json.loads(body) if body else {})


def enable_ci(token):
    if not token:
        print("  未提供 GitHub 凭据：跳过 CI 检查。")
        print("  登录 GitHub（或提供 PAT）后重跑本脚本即可自动补齐。")
        return "skipped"
    if not CI_TEMPLATE.exists():
        print(f"  缺少模板 {CI_TEMPLATE}，跳过。")
        return "failed"

    template = CI_TEMPLATE.read_bytes()
    sha = None
    try:
        status, meta = api("GET", token)
        if status == 200:
            sha = meta.get("sha")
            remote = base64.b64decode(meta.get("content", ""))
            if remote == template:
                print("  远端 ci.yml 与模板一致，无需改动。")
                return "exists"
            print("  远端 ci.yml 内容与模板不一致（网页粘贴常丢缩进），自动修正。")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  查询 CI 文件失败（HTTP {e.code}）。")
            if e.code in (401, 403):
                print("  凭据无效或缺少权限，请用勾选 repo + workflow 的新 PAT。")
            return "failed"
        print("  远端尚无 ci.yml，将自动创建。")
    except Exception as e:
        print(f"  无法访问 GitHub API：{e}")
        return "failed"

    payload = {
        "message": ("ci: fix workflow file from canonical template" if sha
                    else "ci: enable GitHub Actions test workflow"),
        "content": base64.b64encode(template).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    try:
        api("PUT", token, payload)
        print("  已写入正确的 ci.yml，本次提交会触发新的 CI 运行。")
        return "fixed" if sha else "created"
    except urllib.error.HTTPError as e:
        print(f"  写入 CI 失败（HTTP {e.code}）。")
        if e.code in (401, 403, 422):
            print("  凭据需要 contents + workflow 写权限（classic PAT 勾选 repo + workflow）。")
            print("  或打开 README 里的「一键启用 CI」链接，在网页端点一次 Create。")
        return "failed"
    except Exception as e:
        print(f"  写入 CI 失败：{e}")
        return "failed"


def verify():
    local = git("rev-parse", "HEAD").stdout.strip()
    proc = git("ls-remote", "origin", f"refs/heads/{BRANCH}", check=False)
    remote = proc.stdout.split()[0] if proc.returncode == 0 and proc.stdout.strip() else ""
    if remote and remote == local:
        print(f"  远端 main = 本地 HEAD = {local[:7]}，同步完成。")
        return True
    print(f"  本地 HEAD = {local[:7]}；远端 main = {remote[:7] if remote else '读取失败'}")
    print("  （公开仓库读取偶有延迟，稍后可用 git fetch 复核）")
    return False


def report_actions(token):
    if not token:
        return
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/runs?per_page=1"
    try:
        req = urllib.request.Request(url, headers=api_headers(token))
        with urllib.request.urlopen(req, timeout=20) as resp:
            runs = json.load(resp).get("workflow_runs", [])
        if not runs:
            print("  暂无 CI 运行记录（新推送会触发一次）。")
            return
        run = runs[0]
        print(f"  最近一次 CI: {run.get('status')} / {run.get('conclusion')}")
        print(f"  {run.get('html_url')}")
    except Exception as e:
        print(f"  CI 状态查询失败（不影响发布）：{e}")


def main():
    args = sys.argv[1:]
    dry = "--check" in args or "--dry-run" in args
    explicit_token = next((a for a in args if not a.startswith("--")), None)
    explicit_token = explicit_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    push_token = explicit_token                      # 推送用显式 PAT；否则走 GCM 登录态
    api_token = explicit_token or gcm_token()        # API 自动复用 Windows 已登录的凭据

    print("=" * 62)
    print("Backprop Lab 一键发布")
    print(f"目录: {ROOT}")
    print(f"远端: {REPO_URL}")
    print(f"推送: {'PAT' if push_token else 'GitHub 登录态（自动）'}")
    print(f"CI  : {'PAT' if explicit_token else ('GitHub 登录态（自动）' if api_token else '无凭据，跳过')}")
    print("=" * 62)

    git("fetch", "origin", "--quiet", check=False)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    ahead = git("rev-list", "--count", f"origin/{BRANCH}..HEAD", check=False).stdout.strip()
    behind = git("rev-list", "--count", f"HEAD..origin/{BRANCH}", check=False).stdout.strip()
    print(f"当前分支: {branch}；待推送 {ahead or '0'} 个提交，远端领先 {behind or '0'} 个")

    if dry:
        print("\n[--check] 仅做检查，未做任何写入或网络操作。")
        print("去掉 --check 再执行一次即真正发布。")
        return

    step(1, "提交本地改动")
    commit_local_changes()

    step(2, "检查 / 修复 GitHub Actions CI")
    ci_state = enable_ci(api_token)

    step(3, "推送到 GitHub")
    result = push(push_token)
    if result.returncode != 0:
        explain_push_failure(result)
        raise SystemExit(1)
    print("  推送成功。")

    step(4, "校验结果")
    verify()
    report_actions(api_token)

    print("\n" + "=" * 62)
    print(f"仓库   {REPO_URL}")
    print(f"CI     {REPO_URL}/actions   [{ci_state}]")
    print(f"Demo   {DEMO_URL}")
    print("=" * 62)
    if ci_state == "skipped":
        print("提示：本机还没有 GitHub 登录态，先用浏览器登录一次（或提供 PAT），再跑本脚本即可自动补齐 CI：")
        print("      set GITHUB_TOKEN=ghp_xxx && python publish.py")


if __name__ == "__main__":
    main()
