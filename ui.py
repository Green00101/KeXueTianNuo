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
from ocr import ocr_and_search_prices

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
        self.root = tk.Tk()
        self.root.title('科学天诺 测试版')
        self.root.geometry('800x500')
        self.root.resizable(True, True)
        
        # 配置文件路径
        self.config_file = 'wfocr_config.json'
        self.config = self.load_config()
        
        # 状态变量
        self.script_running = False
        self.result_window = None
        self.crop_coords = None
        self.current_screenshot = None
        self.last_screenshot_time = 0  # 记录上次截图时间
        
        # 图像引用保存
        self.ideal_image_ref = None
        self.current_image_ref = None
        self.canvas_image_ref = None
        
        self.setup_ui()
        self.load_ideal_image()
        
        # 预热OCR，在后台初始化以减少首次使用延迟
        self.preload_ocr()
        
    def load_config(self):
        """加载配置文件"""
        default_config = {
            'resolution_width': '',
            'resolution_height': '',
            'crop_coords': None,
            'copy_to_clipboard': False,
            'font_size': 12
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 合并默认配置，确保所有键都存在
                    for key in default_config:
                        if key not in config:
                            config[key] = default_config[key]
                    return config
            except:
                return default_config
        return default_config
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
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
        info_label_2 = ttk.Label(self.root, text="为了有更好的识别效果，请将错误与意见发到 kexuetiannuo@163.com", 
                              foreground='gray')
        info_label_2.pack(pady=1)
        
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
        # 检查分辨率是否填写
        if not self.width_var.get() or not self.height_var.get():
            messagebox.showwarning("警告", "请先填写分辨率")
            return
        
        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except ValueError:
            messagebox.showerror("错误", "分辨率必须是数字")
            return
        
        # 截图
        try:
            screenshot = pyautogui.screenshot(region=(0, 0, width, height))
            self.show_crop_dialog(screenshot)
        except Exception as e:
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
        if not self.config['crop_coords']:
            messagebox.showwarning("警告", "请先选择识别区域")
            return
        
        if self.script_running:
            messagebox.showinfo("提示", "脚本已在运行中")
            return
        
        self.script_running = True
        self.start_button.configure(text="脚本运行中...", state='disabled')
        
        # 创建结果显示窗口
        self.create_result_window()
        
        # 开始监听热键
        threading.Thread(target=self.start_hotkey_listener, daemon=True).start()
    
    def create_result_window(self):
        """创建结果显示窗口"""
        self.result_window = Toplevel(self.root)
        self.result_window.title("识别结果")
        self.result_window.geometry("1050x200")
        self.result_window.configure(bg='black')
        
        # 创建文本框
        self.result_text = tk.Text(self.result_window, 
                                  bg='black', 
                                  fg='white', 
                                  font=('Consolas', self.config['font_size']),
                                  wrap='word',
                                  padx=10,
                                  pady=10)
        
        self.result_text.pack(fill='both', expand=True)
        
        # 初始提示
        self.result_text.insert('end', "脚本已开启，按F8开始识别")
        
        # 关闭事件
        self.result_window.protocol("WM_DELETE_WINDOW", self.stop_script)
    
    def start_hotkey_listener(self):
        """开始监听热键"""
        keyboard.add_hotkey('f8', self.on_f8_pressed)
    
    def on_f8_pressed(self):
        """F8按键响应"""
        if not self.script_running:
            return
        
        # 检查时间间隔
        import time
        current_time = time.time()
        if current_time - self.last_screenshot_time < 1.0:  # 1秒间隔
            return
        self.last_screenshot_time = current_time
        
        try:
            # 截图
            width = int(self.config['resolution_width'])
            height = int(self.config['resolution_height'])
            screenshot = pyautogui.screenshot(region=(0, 0, width, height))
            
            # 裁剪
            coords = self.config['crop_coords']
            cropped = screenshot.crop(coords)
            
            # 显示当前截图
            self.update_current_screenshot(cropped)
            
            # 转换为numpy数组
            img_array = np.array(cropped)
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            
            # OCR识别
            results = ocr_and_search_prices(img_array)
            
            # 显示结果
            self.display_results(results)
            
        except Exception as e:
            error_msg = f"识别出错: {e}"
            if self.result_window and self.result_text:
                self.result_text.delete('1.0', 'end')
                self.result_text.insert('end', error_msg)
    
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
        """显示识别结果"""
        if not self.result_window or not self.result_text:
            return
        
        # 清空之前的内容，只显示当前结果
        self.result_text.delete('1.0', 'end')
        
        # 过滤出有用的结果（跳过调试信息）
        useful_results = []
        for result in results:
            if result and not result.startswith('已保存带框图片'):
                useful_results.append(result)
        
        # 显示结果
        if useful_results:
            for result in useful_results:
                self.result_text.insert('end', f"{result}\n")
        else:
            self.result_text.insert('end', "未识别到物品")
        
        # 保持固定窗口大小，不自动调整
        
        # 复制到剪切板
        if self.clipboard_var.get():
            try:
                clipboard_text = "\n".join(useful_results)
                pyperclip.copy(clipboard_text)
            except:
                pass  # 静默失败
    

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
            if self.result_window and self.result_text:
                self.result_text.configure(font=('Consolas', font_size))
        except:
            pass
    
    def stop_script(self):
        """停止脚本"""
        self.script_running = False
        keyboard.unhook_all()  # 移除所有热键监听
        
        if self.result_window:
            self.result_window.destroy()
            self.result_window = None
        
        self.start_button.configure(text="启动脚本", state='normal')
    
    def preload_ocr(self):
        """预热OCR，在后台初始化以减少首次使用延迟"""
        def init_ocr():
            try:
                # 触发OCR初始化
                from ocr import get_ocr_reader
                get_ocr_reader()
                print("OCR预热完成")
            except Exception as e:
                print(f"OCR预热失败: {e}")
        
        # 在后台线程中初始化
        threading.Thread(target=init_ocr, daemon=True).start()
    
    def on_closing(self):
        """程序关闭"""
        self.stop_script()
        self.root.destroy()
    
    def run(self):
        """运行程序"""
        self.root.mainloop()

if __name__ == "__main__":
    app = WFOCRApp()
    app.run()
