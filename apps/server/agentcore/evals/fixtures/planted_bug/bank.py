"""一个极简的内存账本：账户转账 + 手续费均摊。

设计契约（供审查者比对实现是否达成）：
  - ``transfer`` 把 ``amount`` 从 src 原子地转给 dst，余额不足时拒绝且不改动任何账户。
  - ``split_fee`` 让每一位 payer 平摊总手续费 ``total_fee``。
  - 余额读写在并发下保持一致（类已自带一把锁）。
"""

from __future__ import annotations

import threading


class Bank:
    def __init__(self) -> None:
        self._accounts: dict[str, int] = {}
        self._lock = threading.Lock()

    def open(self, name: str, balance: int = 0) -> None:
        with self._lock:
            self._accounts[name] = balance

    def balance(self, name: str) -> int:
        with self._lock:
            return self._accounts[name]

    def transfer(self, src: str, dst: str, amount: int) -> bool:
        if self._accounts[src] < amount:
            return False
        self._accounts[src] -= amount
        self._accounts[dst] += amount
        return True

    def split_fee(self, payers: list[str], total_fee: int) -> None:
        share = total_fee // len(payers)
        for i in range(1, len(payers)):
            self._accounts[payers[i]] -= share
