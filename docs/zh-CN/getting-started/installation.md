# 安装

## 系统要求

- 操作系统：Windows。
- 分辨率：1920×1080 或更高，16:9 比例。
- 游戏语言：简体中文或 English。

## 使用安装包

这是大多数用户推荐的方式，安装包支持自动更新。

1. 打开 [GitHub Releases](https://github.com/BnanZ0/ok-nte/releases) 下载最新安装包。
2. 双击安装包并按向导完成安装。
3. 从桌面快捷方式或开始菜单启动 ok-nte。

也可使用 [Mirror酱](https://mirrorchyan.com/zh/projects?rid=ok-nte&channel=stable)、[百度网盘](https://pan.baidu.com/s/102Mh1djq2B1T-cIJhct9Gg?pwd=okww) 或 [夸克网盘](https://pan.quark.cn/s/418018ddf7a0) 下载。

## 从源码运行

源码运行适合二次开发和调试。完整的本地开发流程见[从源码运行](../../development/running-from-source.md)。

```bash
git clone https://github.com/BnanZ0/ok-nte.git
cd ok-nte
uv sync
python main.py
```

!!! tip
    更新代码后，请再次执行 `uv sync`，以保持依赖与项目要求一致。
