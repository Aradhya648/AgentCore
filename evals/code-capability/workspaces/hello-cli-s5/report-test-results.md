# hello_cli 测试报告

## 测试覆盖情况

| 场景 | 测试用例 | 状态 |
|------|----------|------|
| `greet <name>` 输出含 `Hello, <name>` | `test_greet_prints_hello_name` | ✅ 通过 |
| `greet` 支持带空格的名字 | `test_greet_with_spaces_in_name` | ✅ 通过 |
| `add <a> <b>` 正确输出整数和 | `test_add_two_positive_integers` | ✅ 通过 |
| `add` 支持负数 | `test_add_negative_numbers` | ✅ 通过 |
| `run_plan` 有输出 | `test_run_plan_prints_commands` | ✅ 通过 |
| `--help` 退出码 0 | `test_help_flag_exits_zero` | ✅ 通过 |
| 无参数时显示帮助 | `test_no_args_shows_help` | ✅ 通过 |

## 运行结果

```
$ python -m pytest tests/ -q
.......                                                                  [100%]
7 passed in 0.02s
```

**退出码: 0 — 全部通过。**

## 测试文件

- `tests/__init__.py` — 使 tests 目录为 package
- `tests/test_hello_cli.py` — 7 个 pytest 测试，覆盖 greet / add / run_plan / --help

## CLI 直接验证

| 命令 | 输出 | 退出码 |
|------|------|--------|
| `python -m hello_cli --help` | 用法说明 | 0 |
| `python -m hello_cli greet World` | `Hello, World` | 0 |
| `python -m hello_cli add 3 4` | `7` | 0 |
| `python -m hello_cli run_plan` | 命令列表 | 0 |
