# note08

Q: `subprocess.run(..., capture_output=True, text=True)` 里的 `capture_output` 和 `text` 分别有什么作用？
A: `capture_output=True` 会捕获子进程的 `stdout` / `stderr`，这样 Python 可以读取命令输出；`text=True` 会把输出按字符串而不是字节串返回，所以后面可以直接做 `(r.stdout + r.stderr).strip()` 这类文本处理。

Q: 为什么 s08 里是“线程 + subprocess”，而不是直接只开一个进程？
A: 线程负责把“等待长命令完成”从主 agent loop 挪到后台，不阻塞后续思考；`subprocess.run(...)` 负责真正启动外部命令。这里需要共享 `self.tasks`、通知队列和锁，用线程最轻量；如果改成 Python 的多进程，还要额外处理跨进程共享状态，复杂度会明显上升。
