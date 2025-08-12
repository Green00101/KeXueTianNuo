import tkinter as tk
from tkinter import ttk, messagebox, filedialog, Toplevel
from PIL import Image, ImageTk
import pyautogui
import cv2
import numpy as np
import json
import os
import sys
import keyboard
import pyperclip
import threading
import requests
import time
import logging
from datetime import datetime
import csv
import re
from ocr import ocr_and_search_prices, get_ocr_reader, parse_guangzhou_price_string

def setup_logging():
    """设置日志记录"""
    # 创建日志记录器
    logger = logging.getLogger('WFOCR')
    logger.setLevel(logging.DEBUG)
    
    # 如果已经有处理器，就不要重复添加
    if logger.handlers:
        return logger
    
    # 创建文件处理器
    file_handler = logging.FileHandler('log.txt', mode='w', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 创建格式化器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器到记录器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 初始化日志记录器
logger = setup_logging()

def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容开发环境和打包后的环境"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller创建临时文件夹，并将路径存储在_MEIPASS中
        base_path = getattr(sys, '_MEIPASS')
    else:
        # 开发环境中使用当前脚本的目录
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

class WFOCRApp:
    def __init__(self):
        logger.info("=== 程序启动 ===")
        logger.info("初始化WFOCR应用程序")
        
        self.root = tk.Tk()
        self.root.title('科学天诺 测试版 2.6')
        self.root.geometry('1000x500')
        self.root.resizable(True, True)
        
        # 配置文件路径
        self.config_file = 'wfocr_config.json'
        logger.info(f"配置文件路径: {self.config_file}")
        self.config = self.load_config()
        
        # 状态变量
        self.script_running = False
        self.result_window = None
        self.result_canvas = None
        self.result_container = None
        self.result_scrollbar = None
        self.result_font = ('Consolas', self.config.get('font_size', 12))
        self.result_button_style_name = 'Result.TButton'
        self.result_status_label = None
        self.result_minimize_after_id = None
        self.status_var = tk.StringVar(value="")
        self.can_save_click = False  # 控制是否允许保存点击
        self.status_delay_timer = None  # 状态延迟显示定时器
        self.countdown_remaining = 0  # 剩余倒计时时间
        self.crop_coords = None
        self.current_screenshot = None
        self.last_screenshot_time = 0  # 记录上次截图时间
        self.price_update_timer = None  # 价格更新定时器
        self.price_file_lock = threading.Lock()  # 价格文件读写锁
        
        # 图像引用保存
        self.ideal_image_ref = None
        self.current_image_ref = None
        self.canvas_image_ref = None
        
        logger.info("设置用户界面")
        self.setup_ui()
        logger.info("加载理想截图")
        self.load_ideal_image()
        
        # 预热OCR，在后台初始化以减少首次使用延迟
        logger.info("开始预热OCR模型")
        self.preload_ocr()

        # 加载CSV原始中文名映射
        self.cn_name_map = self.load_cn_name_map()
        # 加载 中文 -> url_name 映射（用于仓库识别）
        self.cn_to_url_map = self.load_cn_to_url_map()
        
        logger.info("程序初始化完成")
        
    def load_config(self):
        """加载配置文件"""
        logger.info("开始加载配置文件")
        default_config = {
            'resolution_width': '',
            'resolution_height': '',
            'crop_coords': None,
            'copy_to_clipboard': False,
            'font_size': 12,
            'server_type': 'guangzhou',  # 默认选择广州服务器
            'color_mode': 'golden'  # 默认识别金黄色
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置，确保所有键都存在
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    logger.info(f"成功加载配置文件: {config}")
                    return config
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                return default_config
        else:
            logger.info("配置文件不存在，使用默认配置")
            return default_config
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            logger.info(f"配置文件保存成功: {self.config}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            messagebox.showerror("错误", f"保存配置失败: {e}")
    
    def setup_ui(self):
        """设置界面"""
        # 分辨率设置框架
        resolution_frame = ttk.LabelFrame(self.root, text="分辨率设置", padding=10)
        resolution_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(resolution_frame, text="你的电脑分辨率是").grid(row=0, column=0, padx=5)
        
        self.width_var = tk.StringVar(value=self.config['resolution_width'])
        self.width_entry = ttk.Entry(resolution_frame, textvariable=self.width_var, width=8)
        self.width_entry.grid(row=0, column=1, padx=5)
        
        ttk.Label(resolution_frame, text="x").grid(row=0, column=2, padx=2)
        
        self.height_var = tk.StringVar(value=self.config['resolution_height'])
        self.height_entry = ttk.Entry(resolution_frame, textvariable=self.height_var, width=8)
        self.height_entry.grid(row=0, column=3, padx=5)
        
        # 选择识别位置按钮
        ttk.Button(resolution_frame, text="选择识别位置", 
                  command=self.select_crop_area).grid(row=0, column=4, padx=10)
        
        # 新增：识别仓库按钮（位于“选择识别位置”和“数据源”之间）
        ttk.Button(resolution_frame, text="识别仓库", 
                  command=self.recognize_inventory).grid(row=0, column=5, padx=6)
        
        # 服务器选择
        ttk.Label(resolution_frame, text="数据源:").grid(row=0, column=6, padx=(20, 5))
        
        self.server_var = tk.StringVar(value=self.config['server_type'])
        
        # 广州服务器选项
        guangzhou_radio = ttk.Radiobutton(resolution_frame, text="广州服务器", 
                                         variable=self.server_var, value='guangzhou',
                                         command=self.on_server_change)
        guangzhou_radio.grid(row=0, column=7, padx=5)
        
        # WM API选项
        wm_radio = ttk.Radiobutton(resolution_frame, text="WM API", 
                                  variable=self.server_var, value='wm_api',
                                  command=self.on_server_change)
        wm_radio.grid(row=0, column=8, padx=5)
        
        # 控制按钮框架
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill='x', padx=10, pady=5)
        
        # 启动脚本按钮
        self.start_button = ttk.Button(control_frame, text="启动脚本", 
                                      command=self.start_script)
        self.start_button.pack(side='left', padx=5)
        
        # 复制到剪切板选项
        self.clipboard_var = tk.BooleanVar(value=self.config['copy_to_clipboard'])
        ttk.Checkbutton(control_frame, text="将结果复制到剪切板", 
                       variable=self.clipboard_var,
                       command=self.on_clipboard_change).pack(side='left', padx=10)
        
        # 字号选择
        ttk.Label(control_frame, text="字号:").pack(side='left', padx=(20, 5))
        self.font_size_var = tk.StringVar(value=str(self.config['font_size']))
        font_combo = ttk.Combobox(control_frame, textvariable=self.font_size_var, 
                                 values=['8', '9', '10', '11', '12', '14', '16', '18', '20'], 
                                 width=5, state='readonly')
        font_combo.pack(side='left', padx=5)
        font_combo.bind('<<ComboboxSelected>>', self.on_font_size_change)
        
        # 识别颜色选择
        ttk.Label(control_frame, text="识别颜色:").pack(side='left', padx=(20, 5))
        self.color_mode_var = tk.StringVar(value=self.config.get('color_mode', 'golden'))
        
        # 金黄色选项
        golden_radio = ttk.Radiobutton(control_frame, text="金黄色", 
                                      variable=self.color_mode_var, value='golden',
                                      command=self.on_color_mode_change)
        golden_radio.pack(side='left', padx=5)
        
        # 全部颜色选项
        all_colors_radio = ttk.Radiobutton(control_frame, text="全部颜色", 
                                          variable=self.color_mode_var, value='all_colors',
                                          command=self.on_color_mode_change)
        all_colors_radio.pack(side='left', padx=5)
        
        # 理想截图显示
        ideal_frame = ttk.LabelFrame(self.root, text="理想中的截图", padding=10)
        ideal_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.ideal_label = ttk.Label(ideal_frame)
        self.ideal_label.pack()
        
        # 当前截图显示
        current_frame = ttk.LabelFrame(self.root, text="你选择的截图", padding=10)
        current_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.current_label = ttk.Label(current_frame, text="暂无截图")
        self.current_label.pack()
        
        # 底部信息
        info_label = ttk.Label(self.root, text="由 Green00101 开发，通过识别图像实现，不包含任何对游戏数据的操作，本软件开源免费。", 
                              foreground='gray')
        info_label.pack(pady=1)
        info_label_2 = ttk.Label(self.root, text="本软件为玩家自制与官方无关，有问题的话，请将错误与意见发到 kexuetiannuo@163.com", 
                              foreground='gray')
        info_label_2.pack(pady=1)
        
        # 价格数据状态指示器
        self.price_status_label = ttk.Label(self.root, text="", foreground='blue')
        self.price_status_label.pack(pady=2)
        
        # 绑定关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def load_ideal_image(self):
        """加载理想截图"""
        try:
            image_path = get_resource_path('4.png')
            image = Image.open(image_path)
            # 调整图片大小以适应界面
            image.thumbnail((700, 500), Image.Resampling.LANCZOS)
            self.ideal_image_ref = ImageTk.PhotoImage(image)
            self.ideal_label.configure(image=self.ideal_image_ref)
        except Exception as e:
            self.ideal_label.configure(text=f"无法加载图片 4.png: {e}")
    
    def select_crop_area(self):
        """选择识别区域"""
        logger.info("开始选择识别区域")
        # 检查分辨率是否填写
        if not self.width_var.get() or not self.height_var.get():
            logger.warning("分辨率未填写，停止选择识别区域")
            messagebox.showwarning("警告", "请先填写分辨率")
            return
        
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
            logger.info(f"使用分辨率: {width}x{height}")
        except ValueError as e:
            logger.error(f"分辨率格式错误: {e}")
            messagebox.showerror("错误", "分辨率必须是数字")
            return
        
        # 截图
        try:
            logger.info(f"开始截图，区域: (0, 0, {width}, {height})")
            screenshot = pyautogui.screenshot(region=(0, 0, width, height))
            logger.info("截图成功，显示裁剪对话框")
            self.show_crop_dialog(screenshot)
        except Exception as e:
            logger.error(f"截图失败: {e}")
            messagebox.showerror("错误", f"截图失败: {e}")
    
    def show_crop_dialog(self, image):
        """显示截图裁剪对话框"""
        dialog = Toplevel(self.root)
        dialog.title("选择识别区域")
        dialog.geometry("1400x1000")
        
        # 转换图片
        display_image = image.copy()
        # 缩放图片以适应对话框
        original_size = display_image.size
        display_image.thumbnail((1200, 800), Image.Resampling.LANCZOS)
        scale_x = display_image.size[0] / original_size[0]
        scale_y = display_image.size[1] / original_size[1]
        
        self.canvas_image_ref = ImageTk.PhotoImage(display_image)
        
        # 创建画布
        canvas = tk.Canvas(dialog, width=display_image.size[0], height=display_image.size[1])
        canvas.pack(pady=10)
        canvas.create_image(0, 0, anchor='nw', image=self.canvas_image_ref)
        
        # 选择变量
        start_x = start_y = end_x = end_y = 0
        rect_id = None
        
        def on_mouse_down(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
        
        def on_mouse_drag(event):
            nonlocal rect_id, end_x, end_y
            end_x, end_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, end_x, end_y, 
                                            outline='red', width=2)
        
        def on_confirm():
            if rect_id:
                # 转换回原始坐标
                real_x1 = int(min(start_x, end_x) / scale_x)
                real_y1 = int(min(start_y, end_y) / scale_y)
                real_x2 = int(max(start_x, end_x) / scale_x)
                real_y2 = int(max(start_y, end_y) / scale_y)
                
                self.crop_coords = (real_x1, real_y1, real_x2, real_y2)
                self.config['crop_coords'] = self.crop_coords
                self.config['resolution_width'] = self.width_var.get()
                self.config['resolution_height'] = self.height_var.get()
                self.save_config()
                
                # 裁剪并显示选中的区域
                cropped_image = image.crop(self.crop_coords)
                self.update_current_screenshot(cropped_image)
                
                messagebox.showinfo("成功", "识别区域已保存")
                dialog.destroy()
            else:
                messagebox.showwarning("警告", "请先选择区域")
        
        def on_cancel():
            dialog.destroy()
        
        # 绑定鼠标事件
        canvas.bind("<Button-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        
        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="确定", command=on_confirm).pack(side='left', padx=5)
        ttk.Button(button_frame, text="取消", command=on_cancel).pack(side='left', padx=5)
        
        # 从配置中加载已保存的裁剪区域
        if self.config['crop_coords']:
            coords = self.config['crop_coords']
            # 转换到显示坐标
            display_x1 = int(coords[0] * scale_x)
            display_y1 = int(coords[1] * scale_y)
            display_x2 = int(coords[2] * scale_x)
            display_y2 = int(coords[3] * scale_y)
            rect_id = canvas.create_rectangle(display_x1, display_y1, display_x2, display_y2, 
                                            outline='red', width=2)
            start_x, start_y = display_x1, display_y1
            end_x, end_y = display_x2, display_y2
    
    def start_script(self):
        """启动脚本"""
        logger.info("=== 启动脚本 ===")
        logger.info(f"当前配置: {self.config}")
        
        if not self.config['crop_coords']:
            logger.warning("未设置识别区域，停止启动脚本")
            messagebox.showwarning("警告", "请先选择识别区域")
            return
        
        if self.script_running:
            logger.warning("脚本已在运行中")
            messagebox.showinfo("提示", "脚本已在运行中")
            return
        
        logger.info(f"选择的数据源: {self.config['server_type']}")
        
        # 如果选择了广州服务器，检查和更新price.json文件
        if self.config['server_type'] == 'guangzhou':
            logger.info("广州服务器模式，检查price.json文件")
            if not self.check_and_update_price_json():
                logger.error("无法获取价格文件，停止启动脚本")
                return  # 如果无法获取价格文件，停止启动
            self.update_price_status("🌐 使用广州服务器数据源")
            logger.info("广州服务器数据源配置完成")
        else:
            self.update_price_status("🔗 使用WM API数据源")
            logger.info("WM API数据源配置完成")
        
        self.script_running = True
        self.start_button.configure(text="脚本运行中...", state='disabled')
        
        # 创建结果显示窗口
        logger.info("创建结果显示窗口")
        self.create_result_window()
        # 显示即将最小化提示并启动14秒最小化定时
        self.show_minimize_countdown(seconds=14)
        
        # 如果是广州服务器模式，启动定时更新
        if self.config['server_type'] == 'guangzhou':
            logger.info("启动价格更新定时器")
            self.start_price_update_timer()
        
        # 开始监听热键
        logger.info("启动热键监听线程")
        threading.Thread(target=self.start_hotkey_listener, daemon=True).start()
        
        logger.info("脚本启动完成，等待F8按键")
    
    def create_result_window(self):
        """创建结果显示窗口（按钮 + 价格，可滚动）"""
        self.result_window = Toplevel(self.root)
        self.result_window.title("识别结果")
        self.result_window.geometry("980x270")
        # 允许最大化/最小化
        try:
            self.result_window.resizable(True, True)
        except Exception:
            pass

        # 置顶（避免被覆盖），不抢焦点
        try:
            self.result_window.wm_attributes('-topmost', True)
        except Exception:
            pass
        # 取消工具窗口样式，恢复标准标题栏（含最小化/最大化/关闭）
        try:
            self.result_window.wm_attributes('-toolwindow', False)
        except Exception:
            pass
        # 防止窗口激活时任务栏图标闪烁
        self.result_window.focus_set = lambda: None
        self.result_window.lift = self._safe_lift

        # 底部状态栏（必须先创建，才能正确布局在底部）
        bottom_bar = tk.Frame(self.result_window, bg='lightgray', height=30)
        bottom_bar.pack(side='bottom', fill='x')
        bottom_bar.pack_propagate(False)  # 防止高度被内容改变
        self.result_status_label = tk.Label(bottom_bar, textvariable=self.status_var, font=self.result_font, anchor='w', fg='green', bg='lightgray')
        self.result_status_label.pack(side='left', fill='x', expand=True, padx=10, pady=2)

        # 容器框架（占据剩余空间）
        outer = ttk.Frame(self.result_window)
        outer.pack(fill='both', expand=True)

        # 可滚动区域（Canvas + 内部Frame）
        self.result_canvas = tk.Canvas(outer, highlightthickness=0)
        self.result_scrollbar = ttk.Scrollbar(outer, orient='vertical', command=self.result_canvas.yview)
        self.result_canvas.configure(yscrollcommand=self.result_scrollbar.set)

        self.result_container = ttk.Frame(self.result_canvas)
        self.result_container.bind(
            "<Configure>",
            lambda e: self.result_canvas.configure(scrollregion=self.result_canvas.bbox("all"))
        )

        self.result_canvas.create_window((0, 0), window=self.result_container, anchor='nw')
        self.result_canvas.pack(side='left', fill='both', expand=True)
        self.result_scrollbar.pack(side='right', fill='y')

        # 初始化按钮样式
        self.update_result_button_style()

        # 初始提示
        tip_label = ttk.Label(self.result_container, text="脚本已开启，按F8开始识别", font=self.result_font)
        tip_label.pack(padx=12, pady=6, anchor='w')

        # 关闭事件
        self.result_window.protocol("WM_DELETE_WINDOW", self.stop_script)
    
    def start_hotkey_listener(self):
        """开始监听热键"""
        keyboard.add_hotkey('f8', self.on_f8_pressed)
    
    def on_f8_pressed(self):
        """F8按键响应"""
        logger.info("--- F8按键被按下 ---")
        
        if not self.script_running:
            logger.warning("脚本未运行，忽略F8按键")
            return
        
        # 检查时间间隔
        import time
        current_time = time.time()
        if current_time - self.last_screenshot_time < 1.0:  # 1秒间隔
            logger.info(f"按键间隔过短 ({current_time - self.last_screenshot_time:.2f}秒)，忽略此次按键")
            return
        self.last_screenshot_time = current_time
        
        try:
            # 截图
            width = int(self.config['resolution_width'])
            height = int(self.config['resolution_height'])
            logger.info(f"开始F8截图，分辨率: {width}x{height}")
            screenshot = pyautogui.screenshot(region=(0, 0, width, height))
            
            # 裁剪
            coords = self.config['crop_coords']
            logger.info(f"裁剪坐标: {coords}")
            cropped = screenshot.crop(coords)
            logger.info(f"裁剪后图片尺寸: {cropped.size}")
            
            # 显示当前截图
            self.update_current_screenshot(cropped)
            
            # 转换为numpy数组
            img_array = np.array(cropped)
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            logger.info("图片转换为numpy数组完成")
            
            # OCR识别
            logger.info(f"开始OCR识别，使用数据源: {self.config['server_type']}, 颜色模式: {self.config['color_mode']}")
            results = ocr_and_search_prices(img_array, self.config['server_type'], self.price_file_lock, self.config['color_mode'])
            logger.info(f"OCR识别完成，结果数量: {len(results) if results else 0}")
            
            # 显示结果
            self.display_results(results)
            # 识别界面弹出并在14秒后最小化（避免任务栏闪烁）
            try:
                # 先隐藏，更新内容后再展示，可减少任务栏闪亮
                self.result_window.withdraw()
                # 立刻显示但不抢焦点
                self.result_window.deiconify()
                self._safe_lift()
            except Exception:
                pass
            self.show_minimize_countdown(seconds=14)
            
            # 允许保存本次识别结果的第一次点击
            self.can_save_click = True
            
        except Exception as e:
            error_msg = f"识别出错: {e}"
            logger.error(f"F8处理过程出错: {e}")
            if self.result_window and self.result_container:
                self._clear_result_container()
                err_label = ttk.Label(self.result_container, text=error_msg, font=self.result_font)
                err_label.pack(padx=12, pady=10, anchor='w')
            else:
                logger.error("结果窗口不存在，无法显示错误信息")
    
    def update_current_screenshot(self, image):
        """更新当前截图显示"""
        try:
            display_image = image.copy()
            display_image.thumbnail((700, 500), Image.Resampling.LANCZOS)
            self.current_image_ref = ImageTk.PhotoImage(display_image)
            self.current_label.configure(image=self.current_image_ref)
        except Exception as e:
            self.current_label.configure(text=f"显示截图失败: {e}")
    
    def display_results(self, results):
        """显示识别结果（渲染为“按钮 + 价格文本”）"""
        logger.info("开始显示识别结果")
        logger.debug(f"原始结果: {results}")

        if not self.result_window or not self.result_container:
            logger.error("结果窗口不存在，无法显示结果")
            return

        # 过滤出有用的结果（跳过调试信息）
        useful_results = []
        for result in results:
            if result and not result.startswith('已保存带框图片'):
                useful_results.append(result)

        logger.info(f"过滤后的有用结果数量: {len(useful_results)}")
        logger.debug(f"有用结果内容: {useful_results}")

        # 清空区域
        self._clear_result_container()

        items = self._parse_items_from_results(useful_results)

        if items:
            logger.info("渲染识别结果为按钮")
            for idx, (name, price_text) in enumerate(items):
                row = ttk.Frame(self.result_container)
                row.pack(fill='x', padx=10, pady=6)
                # 是否使用按钮
                lower_name = name.lower()
                price_lower = str(price_text).lower()
                is_forma = ('forma' in lower_name)
                # 无匹配结果时不生成按钮，直接显示文本
                is_unrecognized = ('未识别' in price_text) or ('未收录' in price_text) or ('无匹配结果' in price_text)
                if not is_forma and not is_unrecognized:
                    btn = ttk.Button(
                        row,
                        text=name,
                        command=lambda n=name: self.on_item_button_click(n),
                        style=self.result_button_style_name
                    )
                    btn.pack(side='left')
                    lbl = ttk.Label(row, text=price_text, font=self.result_font)
                    lbl.pack(side='left', padx=12)
                else:
                    # 直接文本，不使用按钮
                    line = f"{name}：{price_text}"
                    ttk.Label(row, text=line, font=self.result_font).pack(side='left')
                logger.debug(f"行 {idx+1}: {name} -> {price_text}")
        else:
            # 当无法结构化出 items 时也要给出反馈
            if useful_results:
                logger.info("无法结构化解析，回退显示原始识别输出")
                for line in useful_results:
                    ttk.Label(self.result_container, text=str(line), font=self.result_font).pack(padx=12, pady=2, anchor='w')
            else:
                # 完全无结果时，仍显示“xxxxxx：无匹配结果”。此处不知道具体xxxxxx内容，统一提示。
                logger.info("未识别到物品，显示无匹配结果提示")
                ttk.Label(self.result_container, text="识别内容：无匹配结果", font=self.result_font).pack(padx=12, pady=10, anchor='w')

        # 复制到剪贴板（保持与原逻辑一致）
        if self.clipboard_var.get():
            try:
                clipboard_text = "\n".join(useful_results)
                pyperclip.copy(clipboard_text)
                logger.info("结果已复制到剪切板")
            except Exception as e:
                logger.warning(f"复制到剪切板失败: {e}")
                pass

    def _parse_items_from_results(self, useful_results):
        """从结果文本中提取 (物品名, 价格文本) 列表"""
        items = []
        for line in useful_results:
            text = str(line).strip()
            # 跳过分组标题行，例如：模糊搜索 'xxx'结果：/ 少一字匹配 'xxx'结果：
            if '结果：' in text:
                continue
            if '：' not in text:
                continue
            left, right = text.split('：', 1)
            name = left.strip()
            price_text = right.strip()
            # 过滤非物品名称的行
            if not name or ('模糊搜索' in name) or ('少一字匹配' in name):
                continue
            items.append((name, price_text))
        return items

    def _clear_result_container(self):
        """清空结果容器"""
        if self.result_container is None:
            return
        for child in self.result_container.winfo_children():
            child.destroy()

    def show_minimize_countdown(self, seconds=14):
        """在状态栏显示倒计时提示，并在到时最小化结果窗口"""
        # 取消已有倒计时
        self.cancel_minimize_countdown()
        if not self.result_window:
            return
        
        # 记录总倒计时时间
        self.countdown_remaining = seconds
        
        # 初始化提示
        if self.result_status_label:
            self.status_var.set(f"识别窗口将在 {seconds} 秒后最小化")

        # 每秒更新倒计时
        def tick():
            if not self.result_window:
                return
            self.countdown_remaining -= 1
            if self.countdown_remaining <= 0:
                try:
                    # 使用 withdraw 隐藏窗口，避免从最小化恢复时任务栏闪烁
                    self.result_window.withdraw()
                except Exception:
                    try:
                        self.result_window.iconify()
                    except Exception:
                        pass
                return
            # 只有当没有临时状态显示时才更新倒计时显示
            if self.status_delay_timer is None and self.result_status_label:
                self.status_var.set(f"识别窗口将在 {self.countdown_remaining} 秒后最小化")
            self.result_minimize_after_id = self.result_window.after(1000, tick)

        self.result_minimize_after_id = self.result_window.after(1000, tick)

    def cancel_minimize_countdown(self):
        """取消结果窗口最小化倒计时"""
        try:
            if self.result_window and self.result_minimize_after_id:
                self.result_window.after_cancel(self.result_minimize_after_id)
        except Exception:
            pass
        finally:
            self.result_minimize_after_id = None
    
    def cancel_status_delay(self):
        """取消状态延迟定时器"""
        try:
            if self.result_window and self.status_delay_timer:
                self.result_window.after_cancel(self.status_delay_timer)
        except Exception:
            pass
        finally:
            self.status_delay_timer = None
    
    def show_temp_status(self, message, duration=3):
        """显示临时状态信息，指定时间后恢复倒计时显示"""
        # 取消之前的临时状态
        self.cancel_status_delay()
        
        # 显示临时消息
        if self.result_status_label:
            self.status_var.set(message)
        
        # 设置定时器恢复倒计时显示
        def restore_countdown():
            self.status_delay_timer = None
            if self.result_status_label and self.countdown_remaining > 0:
                self.status_var.set(f"识别窗口将在 {self.countdown_remaining} 秒后最小化")
        
        self.status_delay_timer = self.result_window.after(duration * 1000, restore_countdown)
    
    def _safe_lift(self):
        """安全地提升窗口，避免任务栏图标闪烁"""
        try:
            if self.result_window:
                # 使用wm_attributes而不是lift()来避免焦点切换
                self.result_window.wm_attributes('-topmost', False)
                self.result_window.wm_attributes('-topmost', True)
        except Exception:
            pass

    def on_item_button_click(self, item_name, quantity: int = 1):
        """点击物品按钮后保存CSV中的原始中文名到JSON文件，记录名称和点击次数（每次F8识别后只保存第一次点击）"""
        try:
            # 对于仓库识别，允许多次保存；对于F8模式仍只统计一次。
            # 这里保留can_save_click语义：若False则依旧阻止（F8流程会置False）。
            if not self.can_save_click:
                self.show_temp_status(f"本次识别已有保存记录，点击未统计: {item_name}")
                return
            
            normalized = self._normalize_cn_text(item_name)
            original_name = self.cn_name_map.get(normalized, item_name)
            
            # 读取现有的JSON数据
            json_file = 'clicked_items.json'
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    data = {}
            else:
                data = {}
            
            # 更新点击次数（累加数量）
            add_count = max(1, int(quantity) if str(quantity).isdigit() else 1)
            if original_name in data:
                data[original_name] += add_count
            else:
                data[original_name] = add_count
            
            # 保存回JSON文件
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            count = data[original_name]
            logger.info(f"已保存点击物品: {original_name} (累计数量: {count})")
            
            # 显示保存成功信息（不显示点击次数）
            self.show_temp_status(f"已保存点击物品: {original_name} ×{add_count}")
            
            # 禁止本次识别的后续点击保存
            self.can_save_click = False
            
        except Exception as e:
            logger.error(f"保存点击物品失败: {e}")
            if self.result_status_label:
                self.status_var.set(f"保存失败: {e}")

    def on_item_button_click_unlimited(self, item_name, quantity: int = 1):
        """仓库识别场景：每次点击都累计数量到 clicked_items.json，不做一次性限制。"""
        try:
            normalized = self._normalize_cn_text(item_name)
            original_name = self.cn_name_map.get(normalized, item_name)

            json_file = 'clicked_items.json'
            if os.path.exists(json_file):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except (json.JSONDecodeError, IOError):
                    data = {}
            else:
                data = {}

            add_count = max(1, int(quantity) if str(quantity).isdigit() else 1)
            if original_name in data:
                data[original_name] += add_count
            else:
                data[original_name] = add_count

            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.show_temp_status(f"已保存点击物品: {original_name} ×{add_count}")
        except Exception as e:
            logger.error(f"保存点击物品失败: {e}")
            if self.result_status_label:
                self.status_var.set(f"保存失败: {e}")
    

    def on_clipboard_change(self):
        """复制到剪切板选项改变"""
        self.config['copy_to_clipboard'] = self.clipboard_var.get()
        self.save_config()
    
    def on_font_size_change(self, event=None):
        """字号改变"""
        try:
            font_size = int(self.font_size_var.get())
            self.config['font_size'] = font_size
            self.save_config()
            
            # 更新结果窗口字体
            self.result_font = ('Consolas', font_size)
            # 同步更新按钮样式字号
            self.update_result_button_style()
            if self.result_window and self.result_container:
                for row in self.result_container.winfo_children():
                    for w in row.winfo_children():
                        try:
                            w.configure(font=self.result_font)
                        except Exception:
                            pass
        except:
            pass

    def update_result_button_style(self):
        """根据当前字号更新ttk按钮样式，使按钮字号与价格字号一致，并放大按钮尺寸"""
        try:
            style = ttk.Style()
            # 主题兼容处理
            current_theme = style.theme_use()
            # 设置字体
            style.configure(self.result_button_style_name, font=self.result_font, padding=(10, 6))
        except Exception as e:
            logger.warning(f"更新按钮样式失败: {e}")
    
    def on_server_change(self):
        """服务器选择改变"""
        self.config['server_type'] = self.server_var.get()
        self.save_config()
    
    def on_color_mode_change(self):
        """颜色模式选择改变"""
        self.config['color_mode'] = self.color_mode_var.get()
        self.save_config()
    
    def update_price_status(self, message):
        """更新价格数据状态显示"""
        if hasattr(self, 'price_status_label'):
            current_time = time.strftime("%H:%M:%S")
            self.price_status_label.configure(text=f"{message} ({current_time})")
    
    def stop_script(self):
        """停止脚本"""
        logger.info("=== 停止脚本 ===")
        self.script_running = False
        keyboard.unhook_all()  # 移除所有热键监听
        logger.info("移除热键监听")
        
        # 停止价格更新定时器
        if self.price_update_timer:
            self.price_update_timer.cancel()
            self.price_update_timer = None
            logger.info("停止价格更新定时器")
        
        if self.result_window:
            self.result_window.destroy()
            self.result_window = None
            logger.info("关闭结果窗口")
        
        self.start_button.configure(text="启动脚本", state='normal')
        logger.info("脚本已停止")
    
    def download_price_json(self):
        """下载price.json文件"""
        logger.info("开始下载price.json文件")
        try:
            url = "url"
            logger.info(f"请求价格数据: url")
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                logger.info("价格数据请求成功")
                # 使用文件锁确保线程安全
                with self.price_file_lock:
                    return self._download_price_json_internal(response)
            else:
                logger.error(f"下载price.json失败，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"下载price.json出错: {e}")
            return False
    
    def _download_price_json_internal(self, response):
        """内部下载函数，不使用文件锁（调用者需要确保已加锁）"""
        try:
            # 先下载到临时文件
            temp_file = 'price.json.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(response.json(), f, ensure_ascii=False, indent=2)
            
            # 原子性替换：重命名临时文件为目标文件
            if os.path.exists('price.json'):
                os.remove('price.json')  # Windows需要先删除目标文件
            os.rename(temp_file, 'price.json')
            
            logger.info("price.json文件下载成功")
            # 更新状态显示
            self.update_price_status("📊 价格数据已更新")
            return True
        except Exception as e:
            logger.error(f"保存price.json文件出错: {e}")
            # 清理可能存在的临时文件
            try:
                if os.path.exists('price.json.tmp'):
                    os.remove('price.json.tmp')
            except:
                pass
            return False
    
    def check_and_update_price_json(self):
        """检查并更新price.json文件"""
        try:
            # 使用文件锁确保检查过程的原子性
            with self.price_file_lock:
                # 检查文件是否存在
                if not os.path.exists('price.json'):
                    print("price.json文件不存在，正在下载...")
                    if not self._download_with_lock():
                        messagebox.showerror("警告", "访问过于频繁，请在5分钟后下载 price.json 文件")
                        return False
                else:
                    # 检查文件是否完整（能否正常解析JSON）
                    try:
                        with open('price.json', 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if 'data' not in data:
                            print("price.json文件格式错误，重新下载...")
                            if not self._download_with_lock():
                                messagebox.showerror("警告", "访问过于频繁，请在5分钟后下载 price.json 文件")
                                return False
                    except (json.JSONDecodeError, IOError) as e:
                        print(f"price.json文件损坏，重新下载... 错误: {e}")
                        if not self._download_with_lock():
                            messagebox.showerror("警告", "访问过于频繁，请在5分钟后下载 price.json 文件")
                            return False
                    
                    # 检查文件是否过期（超过7分钟）
                    file_time = os.path.getmtime('price.json')
                    current_time = time.time()
                    if current_time - file_time > 420:  # 7分钟 = 420秒
                        print("price.json文件已过期，正在更新...")
                        self._download_with_lock()  # 这里不强制要求成功，允许使用旧数据
            
            return True
        except Exception as e:
            print(f"检查price.json文件时出错: {e}")
            messagebox.showerror("错误", f"检查价格文件时出错: {e}")
            return False
    
    def _download_with_lock(self):
        """在已有锁的情况下下载文件"""
        try:
            url = "url"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return self._download_price_json_internal(response)
            else:
                logger.error(f"下载price.json失败，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"下载price.json出错: {e}")
            return False
    
    def start_price_update_timer(self):
        """启动价格更新定时器，每7分钟更新一次"""
        def update_price():
            if self.script_running and self.config['server_type'] == 'guangzhou':
                self.download_price_json()
                # 继续设置下一次更新
                self.price_update_timer = threading.Timer(420, update_price)  # 7分钟
                self.price_update_timer.start()
        
        # 7分钟后开始第一次更新
        self.price_update_timer = threading.Timer(420, update_price)
        self.price_update_timer.start()
    
    def preload_ocr(self):
        """预热OCR，在后台初始化以减少首次使用延迟"""
        def init_ocr():
            try:
                # 触发OCR初始化
                from ocr import get_ocr_reader
                get_ocr_reader()
                logger.info("OCR预热完成")
            except Exception as e:
                logger.error(f"OCR预热失败: {e}")
                # 如果是模型文件问题，给用户更友好的提示
                if "打包环境中未找到EasyOCR模型文件" in str(e):
                    logger.error("建议解决方案：重新下载完整版程序或检查程序文件完整性")
        
        # 在后台线程中初始化
        threading.Thread(target=init_ocr, daemon=True).start()

    def load_cn_name_map(self):
        """加载CSV中原始中文名映射：去空格小写 -> 原始Chinese"""
        mapping = {}
        try:
            csv_path = get_resource_path('wfm_item_names_en_zh.csv')
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    logger.warning("CSV无表头，无法建立映射")
                    return mapping
                # 规范化表头（去BOM/空格，转小写）
                header_norm = {h.strip().lstrip('\ufeff').lower(): h for h in reader.fieldnames}
                chinese_col = header_norm.get('chinese')
                if not chinese_col:
                    logger.warning("CSV缺少Chinese列，无法建立映射")
                    return mapping
                for row in reader:
                    cn = (row.get(chinese_col) or '').strip()
                    if not cn:
                        continue
                    key = self._normalize_cn_text(cn)
                    mapping[key] = cn
            logger.info(f"加载CSV原始中文名映射完成，共{len(mapping)}条")
        except Exception as e:
            logger.error(f"加载CSV原始中文名映射失败: {e}")
        return mapping

    def load_cn_to_url_map(self):
        """加载 CSV，建立 中文(去空格小写) -> url_name 的映射"""
        mapping = {}
        try:
            csv_path = get_resource_path('wfm_item_names_en_zh.csv')
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    logger.warning("CSV无表头，无法建立url映射")
                    return mapping
                header_norm = {h.strip().lstrip('\ufeff').lower(): h for h in reader.fieldnames}
                chinese_col = header_norm.get('chinese')
                url_col = header_norm.get('url_name')
                if not chinese_col or not url_col:
                    logger.warning("CSV缺少必要列，无法建立url映射")
                    return mapping
                for row in reader:
                    cn = (row.get(chinese_col) or '').strip()
                    url = (row.get(url_col) or '').strip()
                    if not cn or not url:
                        continue
                    key = self._normalize_cn_text(cn)
                    mapping[key] = url
            logger.info(f"加载CSV中文到url映射完成，共{len(mapping)}条")
        except Exception as e:
            logger.error(f"加载CSV中文到url映射失败: {e}")
        return mapping

    def _get_price_from_local(self, url_name: str) -> str:
        """根据 url_name 从本地 price.json 读取价格字符串并格式化。
        若无数据，返回 '未收录'。始终读取广州服务器格式。
        """
        try:
            # 确保有价格文件
            self.check_and_update_price_json()
            if not os.path.exists('price.json'):
                return '未收录'
            with self.price_file_lock:
                with open('price.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
            price_str = data.get('data', {}).get(url_name)
            if not price_str:
                return '未收录'
            return parse_guangzhou_price_string(price_str)
        except Exception as e:
            logger.error(f"读取本地价格失败: {e}")
            return '未收录'

    def ensure_price_json_fresh_by_last_updated(self) -> bool:
        """检查 price.json 的 last_updated 是否超过7分钟或文件不存在，必要时下载/更新。
        返回是否可用（存在并可读取）。
        """
        try:
            with self.price_file_lock:
                need_download = False
                if not os.path.exists('price.json'):
                    need_download = True
                else:
                    try:
                        with open('price.json', 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        last_updated = data.get('last_updated')
                    except Exception:
                        last_updated = None
                    # 解析last_updated为时间戳（秒）
                    ts = None
                    if isinstance(last_updated, (int, float)):
                        ts = float(last_updated)
                    elif isinstance(last_updated, str):
                        try:
                            if last_updated.isdigit():
                                ts = float(last_updated)
                            else:
                                # ISO格式，例如 2025-08-12T14:37:09.464955
                                ts = datetime.fromisoformat(last_updated).timestamp()
                        except Exception:
                            ts = None
                    # 若json字段缺失或无法解析，则回退到文件修改时间
                    if ts is None:
                        try:
                            ts = float(os.path.getmtime('price.json'))
                        except Exception:
                            ts = 0.0
                    import time as _t
                    if _t.time() - ts > 420:  # 7分钟 = 420秒
                        need_download = True

                if need_download:
                    return self._download_with_lock()
                return True
        except Exception as e:
            logger.error(f"检查/更新价格数据出错: {e}")
            return False

    def recognize_inventory(self):
        """识别仓库：按分辨率截图->用户框选->白色提取(白->黑，非白->白)->OCR->映射->查价->展示。
        """
        # 检查分辨率
        if not self.width_var.get() or not self.height_var.get():
            messagebox.showwarning("警告", "请先填写分辨率")
            return
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except ValueError:
            messagebox.showerror("错误", "分辨率必须是数字")
            return

        # 识别前确保价格数据新鲜
        self.ensure_price_json_fresh_by_last_updated()

        # 截屏
        try:
            screenshot = pyautogui.screenshot(region=(0, 0, width, height))
        except Exception as e:
            messagebox.showerror("错误", f"截图失败: {e}")
            return

        # 弹窗让用户框选
        dialog = Toplevel(self.root)
        dialog.title("识别仓库 - 选择识别区域")
        dialog.geometry("1400x1000")

        display_image = screenshot.copy()
        original_size = display_image.size
        display_image.thumbnail((1200, 800), Image.Resampling.LANCZOS)
        scale_x = display_image.size[0] / original_size[0]
        scale_y = display_image.size[1] / original_size[1]
        self.canvas_image_ref = ImageTk.PhotoImage(display_image)
        canvas = tk.Canvas(dialog, width=display_image.size[0], height=display_image.size[1])
        canvas.pack(pady=10)
        canvas.create_image(0, 0, anchor='nw', image=self.canvas_image_ref)

        start_x = start_y = end_x = end_y = 0
        rect_id = None

        def on_mouse_down(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)

        def on_mouse_drag(event):
            nonlocal rect_id, end_x, end_y
            end_x, end_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, end_x, end_y, outline='red', width=2)

        def do_ocr_and_show(cropped_pil):
            # 显示到下方区域
            self.update_current_screenshot(cropped_pil)
            # 转BGR np
            img_bgr = cv2.cvtColor(np.array(cropped_pil), cv2.COLOR_RGB2BGR)
            # 提取接近白色的文字：低饱和高亮度
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
            mask_white = cv2.inRange(hsv, np.array([0, 0, 200]), np.array([180, 50, 255]))
            # 白色->黑，非白->白
            binary = np.where(mask_white > 0, 0, 255).astype('uint8')
            # 轻微形态学开运算，去噪点
            kernel = np.ones((2, 2), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

            # OCR
            try:
                reader = get_ocr_reader()
                ocr_result = reader.readtext(binary, detail=1)
            except Exception as e:
                messagebox.showerror("错误", f"OCR失败: {e}")
                return

            # 提取行文本与数量
            lines = []  # (name, qty)
            for (bbox, text, conf) in ocr_result:
                if not text:
                    continue
                t = text.strip()
                # 去除多余字符
                t = re.sub(r"[|,.;:，。；：]+", " ", t)
                # 解析数量
                m = re.match(r"^(\d+)\s*[xX×]\s*(.+)$", t)
                if m:
                    qty = int(m.group(1))
                    name = m.group(2).strip()
                else:
                    qty = 1
                    name = t
                if not name:
                    continue
                lines.append((name, qty))

            if not lines:
                messagebox.showinfo("提示", "未识别到有效文本")
                return

            # 合并同名数量
            agg = {}
            for name, qty in lines:
                key = self._normalize_cn_text(name)
                agg[key] = agg.get(key, 0) + qty

            # 生成用于展示的条目 (display_name, price_text, qty)
            items_to_show = []
            for key, qty in agg.items():
                # 若识别末尾是'蓝'，补'图'
                disp_cn = self.cn_name_map.get(key, None)
                norm_for_map = key
                if disp_cn is None and key.endswith('蓝'):
                    with_suffix = key + '图'
                    disp_cn = self.cn_name_map.get(with_suffix, None)
                    norm_for_map = with_suffix if disp_cn else key
                if disp_cn is None:
                    # 找不到原始展示名则用去空格小写反向恢复
                    disp_cn = key

                url = self.cn_to_url_map.get(norm_for_map, None)
                if not url and key.endswith('蓝'):
                    url = self.cn_to_url_map.get(key + '图', None)
                price_text = self._get_price_from_local(url) if url else '未收录'
                items_to_show.append((disp_cn, price_text, qty))

            # 在结果窗口展示
            if not self.result_window:
                self.create_result_window()
            self._clear_result_container()
            # 底部状态栏初始为空
            try:
                self.status_var.set("")
            except Exception:
                pass
            for name, price_text, qty in items_to_show:
                row = ttk.Frame(self.result_container)
                row.pack(fill='x', padx=10, pady=6)
                if '未收录' in str(price_text):
                    # 直接显示文本
                    line = f"{name}：{price_text}  数量×{qty}"
                    ttk.Label(row, text=line, font=self.result_font).pack(side='left')
                else:
                    btn = ttk.Button(
                        row,
                        text=name,
                        command=lambda n=name, q=qty: self.on_item_button_click_unlimited(n, q),
                        style=self.result_button_style_name
                    )
                    btn.pack(side='left')
                    info = f"{price_text}  数量×{qty}"
                    ttk.Label(row, text=info, font=self.result_font).pack(side='left', padx=12)

            # 立刻显示但不抢焦点，并启动最小化倒计时
            try:
                self.result_window.withdraw()
                self.result_window.deiconify()
                self._safe_lift()
                # 将窗口高度设为原来的3倍
                try:
                    self.result_window.geometry("1280x810")
                except Exception:
                    pass
            except Exception:
                pass
            # 仓库识别：不自动最小化
            self.cancel_minimize_countdown()
            # 允许多次保存（不限制）
            self.can_save_click = True

        def on_confirm():
            if rect_id:
                real_x1 = int(min(start_x, end_x) / scale_x)
                real_y1 = int(min(start_y, end_y) / scale_y)
                real_x2 = int(max(start_x, end_x) / scale_x)
                real_y2 = int(max(start_y, end_y) / scale_y)
                cropped = screenshot.crop((real_x1, real_y1, real_x2, real_y2))
                dialog.destroy()
                do_ocr_and_show(cropped)
            else:
                messagebox.showwarning("警告", "请先选择区域")

        def on_cancel():
            dialog.destroy()

        canvas.bind("<Button-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="确定", command=on_confirm).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side='left', padx=5)

    @staticmethod
    def _normalize_cn_text(text):
        """规范化：去空格/全角空格，转小写，去除中点分隔符"""
        if text is None:
            return ''
        t = str(text)
        t = t.replace(' ', '').replace('\u3000', '')
        t = t.replace('·', '').replace('・', '')
        return t.lower()
    
    def on_closing(self):
        """程序关闭"""
        logger.info("=== 程序关闭 ===")
        self.stop_script()
        self.root.destroy()
        logger.info("程序已完全关闭")
    
    def run(self):
        """运行程序"""
        self.root.mainloop()

if __name__ == "__main__":
    logger.info("=== 程序主入口启动 ===")
    app = WFOCRApp()
    app.run()
