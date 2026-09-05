#!/usr/bin/env python3
"""
hot_standby.py — 135战法双机热备「主备选举 + 任务守门」

设计目标:
  双机(JesseHomeNAS=主 / gem12=备)都活着时, 只有主跑 135 任务并推送, 备静默跳过,
  绝不重复推送; 主宕机时, 备在下一个任务触发点自动接管, 无需人工切换。

主备规则(确定性, 无竞态):
  - JesseHomeNAS(100.69.128.20) = 固定主 (PRIMARY)
  - gem12(100.95.78.116)        = 备 (BACKUP), 仅当探测到主不可达时接管
  主只要自身能跑任务, 永远是主; 主死了才轮到备。

用法:
  python3 hot_standby.py            # 探测并打印判定 (供 agent 任务 step0 调用)
  python3 hot_standby.py --json     # JSON 输出
  python3 hot_standby.py self       # 只报本机身份, 不探测对端

输出(人类可读, agent 据此决策):
  [HOTSTANDBY] ROLE=PRIMARY  -> 本机是主, 请继续执行任务
  [HOTSTANDBY] ROLE=BACKUP-SKIP (primary healthy) -> 主健康, 回复 [SILENT] 结束
  [HOTSTANDBY] ROLE=BACKUP-TAKEOVER (primary down) -> 主宕机, 本机接管, 继续执行

退出码: 0=该跑(PRIMARY 或 TAKEOVER)  3=该跳过(BACKUP-SKIP)
"""
import datetime
import json
import os
import socket
import subprocess
import sys
import urllib.request

# 固定主备: 主=JesseHomeNAS, 备=gem12。用主机名识别本机身份。
def _my_role():
    try:
        host = socket.gethostname()
    except Exception:
        host = ''
    if 'JesseHomeNAS' in host or 'JesseHome' in host:
        return 'PRIMARY'   # 我是主
    return 'BACKUP'        # 我是备 (gem12)

# 主机的探测地址 (备用来探主)
PRIMARY_HOST = 'jesse@100.69.128.20'
SSH_OPTS = ['-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=accept-new']


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def probe_primary():
    """备机探测主机是否健康: ssh 可达 + 主机 gateway 进程存活。

    判据说明: 接管与否取决于「主机还能不能跑它的 cron 任务」。
    - 模型端点(59.35.206.146)是双机共享 infra, 探它无法区分主/备死活, 故不纳入。
    - 主机 gateway 进程存活 = 主机的 cron 调度器活着 = 主能自己跑任务, 备就该让位。
    返回 (healthy: bool, detail: str)。任一环节失败即视为主不可用, 触发接管。
    """
    # 单行命令, 避免多行 python 的引号/换行陷阱。
    # 匹配 hermes gateway 进程行(排除 pgrep 自身), 有输出即存活。
    remote_cmd = "pgrep -af hermes | grep gateway | grep -v pgrep | head -1"
    # 重试 2 次: 单次 ssh 抖动不应触发误接管(会导致双推)。
    last = 'unknown'
    for attempt in range(2):
        cmd = ['ssh'] + SSH_OPTS + [PRIMARY_HOST, remote_cmd]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            out = (p.stdout or '').strip()
            gw_ok = bool(out)
            last = f'ssh-ok gateway={"alive" if gw_ok else "DOWN"}'
            if gw_ok:
                return True, last
        except subprocess.TimeoutExpired:
            last = f'ssh 超时(30s) [attempt {attempt+1}]'
        except Exception as e:
            last = f'{type(e).__name__}: {e} [attempt {attempt+1}]'
    return False, last


def decide():
    role = _my_role()
    res = {'role': role, 'time': _now(), 'host': socket.gethostname()}
    if role == 'PRIMARY':
        res['action'] = 'RUN'
        res['reason'] = '本机是固定主, 直接执行'
        return res
    # BACKUP: 探主
    healthy, detail = probe_primary()
    if healthy:
        res['action'] = 'SKIP'
        res['reason'] = f'主健康, 备静默 ({detail})'
    else:
        res['action'] = 'RUN'
        res['reason'] = f'主宕机, 备接管 ({detail})'
    return res


def main():
    args = [a for a in sys.argv[1:]]
    as_json = '--json' in args
    self_only = 'self' in args
    if self_only:
        res = {'role': _my_role(), 'host': socket.gethostname(),
               'action': 'RUN', 'reason': 'self 模式仅报身份', 'time': _now()}
    else:
        res = decide()
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        a = res['action']
        r = res['role']
        if r == 'PRIMARY':
            print(f"[HOTSTANDBY] ROLE=PRIMARY -> 继续执行任务 ({res['reason']})")
        elif a == 'SKIP':
            print(f"[HOTSTANDBY] ROLE=BACKUP-SKIP -> 回复 [SILENT] 结束, 不执行任务 ({res['reason']})")
        else:
            print(f"[HOTSTANDBY] ROLE=BACKUP-TAKEOVER -> 继续执行任务, 本机接管 ({res['reason']})")
    # 退出码: 0=该跑, 3=该跳过
    sys.exit(0 if res['action'] == 'RUN' else 3)


if __name__ == '__main__':
    main()
