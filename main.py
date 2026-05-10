import ok
import subprocess
import psutil
import time

from src.config import config

def is_htgame_running():
    '''判断HTGame是否正在运行'''
    process_name = "HTGame.exe"
    process_name = process_name.lower()
    for proc in psutil.process_iter(['name']):
        try:
            proc_name = proc.info['name'].lower()
            if process_name in proc_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False

def wait_for_htgame():
    '''等待HTGame启动'''
    if not is_htgame_running():
        print("游戏未启动，通过启动器启动")
        # 启动器启动游戏
        subprocess.Popen(["python", "launcher/launcher.py", "-t 1"])
        start_time = time.time()
        while not is_htgame_running() and time.time() - start_time < 60:
            print("等待游戏启动...")
            time.sleep(1)
        if not is_htgame_running():
            print("游戏启动超时")
            exit(1)

if __name__ == "__main__":
    # 如果游戏未启动，通过启动器启动并等待启动
    wait_for_htgame()

    config = config
    ok = ok.OK(config)
    ok.start()
