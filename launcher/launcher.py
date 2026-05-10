import os
import sys

# select current directory as the working directory
# ensure import and config can be found correctly
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
os.chdir(current_dir)

from ok import OK

# See more on https://github.com/ok-oldking/ok-py/blob/master/src/config.py
global_config = {
    'custom_tasks':True,
    'debug': False,
    'use_gui': True,
    'config_folder': 'configs',
    'gui_icon': 'icons/icon.png',
    'ocr': {
        'lib': 'onnxocr',
        'auto_simplify': True,
        'params': {
            'use_openvino': True,
        }
    },
    'windows': {
        'exe': ['NTEGame.exe'], # 启动器进程名NTEGame.exe
        'interaction': ['Pynput', 'PostMessage', 'Genshin', 'PyDirect','ForegroundPostMessage'],
        'capture_method': ['WGC', 'BitBlt_RenderFull', 'BitBlt'],
        'check_hdr': False,
        'force_no_hdr': False,
        'require_bg': True
    },
    'window_size': {
        'width': 1200,
        'height': 800,
        'min_width': 600,
        'min_height': 450,
    },
    'supported_resolution': {
        'ratio': '16:9',
        'min_size': (1280, 720),
        'resize_to': [(2560, 1440), (1920, 1080), (1600, 900), (1280, 720)],
    },
    'screenshots_folder': "screenshots",
    'gui_title': 'ok-nte-launcher',
    'my_app': ['src.globals', 'Globals'],
    'onetime_tasks': [
        ["src.StartTask", "StartTask"],
    ],
}

def launch():
    '''启动器启动游戏'''
    config = global_config
    ok = OK(config)
    ok.start()

if __name__ == '__main__':
    launch()
