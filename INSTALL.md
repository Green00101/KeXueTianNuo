# 科学天诺 - 安装指南

## 环境准备

### 1. 安装Python

确保你的系统已安装Python 3.7或更高版本。你可以从[Python官网](https://www.python.org/downloads/)下载并安装。

> 注意：安装时请勾选"Add Python to PATH"选项，以便在命令行中直接使用Python命令。

### 2. 验证Python安装

打开命令提示符或PowerShell，输入以下命令验证Python是否安装成功：

```bash
python --version
pip --version
```

## 安装依赖包

### 方法1：使用requirements.txt文件

1. 打开命令提示符或PowerShell
2. 导航到项目目录：
   ```bash
   cd d:\tenno\KeXueTianNuo
   ```
3. 运行以下命令安装依赖：
   ```bash
   pip install --user -r requirements.txt
   ```

### 方法2：手动安装依赖包

如果上述方法失败，可以尝试手动安装每个依赖包：

```bash
pip install --user Pillow pyautogui opencv-python numpy keyboard pyperclip easyocr pandas requests
```

## 常见问题及解决方法

### 1. 权限错误

**错误信息**：`[WinError 5] 拒绝访问。`

**解决方案**：
- 使用`--user`选项安装到用户目录
- 以管理员身份运行命令提示符

### 2. 安装时间过长

**问题**：`easyocr`安装时间较长

**解决方案**：
- 耐心等待，因为`easyocr`需要下载预训练模型
- 确保网络连接稳定

### 3. 模块未找到错误

**错误信息**：`ModuleNotFoundError: No module named 'xxx'`

**解决方案**：
- 确保已使用`--user`选项安装
- 检查Python环境变量配置
- 尝试重新安装缺失的模块

### 4. 网络问题

**错误信息**：`Connection timed out`或下载失败

**解决方案**：
- 检查网络连接
- 尝试使用国内镜像源安装：
  ```bash
  pip install --user -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```

## 运行项目

### 方法1：直接运行Python文件

1. 打开命令提示符或PowerShell
2. 导航到项目目录：
   ```bash
   cd d:\tenno\KeXueTianNuo
   ```
3. 运行主文件：
   ```bash
   python ui.py
   ```

### 方法2：使用IDE运行

如果你使用PyCharm、VS Code等IDE：
1. 打开项目文件夹
2. 确保已配置好Python解释器
3. 运行 `ui.py` 文件

## 使用步骤

1. **设置分辨率**：在主界面输入你的电脑屏幕分辨率
2. **选择识别区域**：
   - 点击"选择识别位置"按钮
   - 在弹出的窗口中，用鼠标框选游戏中物品名称的显示区域（通常是黄色文字部分）
   - 点击"确定"保存区域设置
3. **启动脚本**：点击"启动脚本"按钮
4. **开始识别**：
   - 进入Warframe游戏
   - 当你看到物品时，按 `F8` 键
   - 程序会自动识别物品并显示市场价格

## 故障排除

- **无法识别物品**：尝试调整识别区域，确保只包含物品名称的黄色文字
- **价格查询失败**：检查网络连接，或尝试使用模糊搜索功能
- **热键无响应**：确保程序窗口未被最小化，且游戏未拦截F8键
- **OCR初始化失败**：检查easyocr是否正确安装，可能需要重新安装

## 联系支持

如果遇到无法解决的问题，可以联系项目开发者获取帮助。

---

**注意**：本工具仅供辅助游戏使用，请勿用于任何违反游戏规则的行为。