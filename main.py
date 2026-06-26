import sys
import time
import schedule
import re
from datetime import datetime

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QTextEdit, QSystemTrayIcon, QMenu, QComboBox, QSpinBox,
                               QDialog, QScrollArea)
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtCore import QThread, Signal

from data_manager import load_config, save_config, load_state, save_state
from spider import fetch_current_status
from notifier import send_wechat

def parse_status_info(raw_text):
    """
    提取期刊ID和当前状态，供微信推送和历史记录使用。
    返回: (ms_id, status_str, is_success)
    """
    if not raw_text:
        return None, "抓取失败或返回空值", False
        
    ms_id = None
    status = None
    
    # 匹配稿件号: 大写字母+数字，例如 T-ITS-26-06-3100, SEGAN-D-25-03438
    id_match = re.search(r'([A-Z0-9]+-(?:D-)?\d{2,4}-\d+[\w-]*)', raw_text)
    if id_match:
        ms_id = id_match.group(1)
        
    parts = [p.strip() for p in raw_text.split("|")]
    
    # 1. Editorial Manager 提取 (特征词 Action Links)
    if "Action Links" in raw_text:
        if len(parts) > 1:
            last_part = parts[-1]
            # 用连续的空格或者Tab切割
            sub_parts = [p.strip() for p in re.split(r'\s{2,}|\t+', last_part) if p.strip()]
            if sub_parts:
                status = sub_parts[-1]
                
    # 2. ScholarOne 提取
    else:
        # 在 ScholarOne 中，表格顺序通常是 Status 列在 ID 列的前面
        # 我们用查找到的 ID 所在的块，往前推一个块，通常就是核心状态
        if ms_id:
            for i, part in enumerate(parts):
                if ms_id in part and i > 0:
                    status = parts[i - 1]
                    break
                    
        # 兜底方案：如果上面没找到，根据用户观察强制取 "Contact Journal" 后的部分
        if not status:
            if "Contact Journal" in raw_text and len(parts) >= 4:
                status = parts[3]
            elif "Status" in parts:
                try:
                    idx = parts.index("Status")
                    status = parts[idx+1]
                except ValueError:
                    pass

    if ms_id and status:
        return ms_id, status, True
    
    # 提取失败 fallback
    return ms_id, raw_text, False

# ================= 任务5：后台监控子线程 =================
class MonitorThread(QThread):
    # 使用 Signal 解决跨线程更新 UI 的问题
    log_signal = Signal(str)
    notify_signal = Signal(str, str) # (title, msg)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        
    def run(self):
        self.running = True
        self.log_signal.emit("后台监控线程已启动...")
        
        # 启动时立刻执行一次抓取检查
        self.check_job()
        
        # 设置定时任务 (根据用户设定的间隔轮询)
        interval = int(self.config.get("poll_interval_hours", 4))
        schedule.every(interval).hours.do(self.check_job)
        
        # 独立定时任务：准点发送每日汇报
        if self.config.get("send_mode") == "每天定时汇报发送":
            report_hour = int(self.config.get("daily_report_hour", 19))
            time_str = f"{report_hour:02d}:00"
            schedule.every().day.at(time_str).do(self.send_daily_report)
        
        # 线程挂起循环，等待被停止
        while self.running:
            schedule.run_pending()
            time.sleep(1)
            
    def send_daily_report(self):
        self.log_signal.emit("到达设定时间，准备发送每日例行汇报...")
        state = load_state()
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 防止重复发送
        if state.get("last_daily_report_date") == today_str:
            self.log_signal.emit("今日已发送过例行汇报，跳过。")
            return
            
        use_desktop = self.config.get("use_desktop_notify", False)
        send_key = self.config.get('send_key')
        
        status1 = state.get("last_status_1", "暂无")
        status2 = state.get("last_status_2", "暂无")
        
        msg = f"系统 1 当前精简状态：{status1}\n\n系统 2 当前精简状态：{status2}\n\n今天也是没有波澜的一天，放平心态，早点休息~"
        
        if use_desktop:
            self.notify_signal.emit("☕【每日例行】稿件状态无变化", msg)
        else:
            send_wechat(send_key, "☕【每日例行】稿件状态无变化", msg, log_callback=self.log_signal.emit)
            
        state["last_daily_report_date"] = today_str
        save_state(state)
            
    def stop(self):
        self.running = False
        schedule.clear()
        self.log_signal.emit("后台监控线程已停止。")
        
    def check_job(self):
        self.log_signal.emit(f"[{datetime.now().strftime('%H:%M:%S')}] 开始执行定时网页抓取...")
        
        # 重新加载配置和状态，确保拿到最新数据
        state = load_state()
        send_key = self.config.get('send_key')
        report_hour = int(self.config.get('daily_report_hour', 19))
        
        systems = [
            ("【系统 1】", self.config.get('url_1'), self.config.get('username_1'), self.config.get('password_1'), "last_status_1"),
            ("【系统 2】", self.config.get('url_2'), self.config.get('username_2'), self.config.get('password_2'), "last_status_2")
        ]
        
        changes_detected = []
        statuses = []
        
        for sys_name, url, username, password, state_key in systems:
            if not url or not username or not password:
                self.log_signal.emit(f"{sys_name} 未配置完整，跳过。")
                statuses.append(None)
                continue
                
            self.log_signal.emit(f"正在抓取 {sys_name} ({url})...")
            current_raw = fetch_current_status(url, username, password, log_callback=self.log_signal.emit)
            if not current_raw:
                self.log_signal.emit(f"{sys_name} 获取状态失败，请检查网络。")
                statuses.append(None)
                continue
                
            # 解析 ID 和精简状态
            ms_id, current_status, is_success = parse_status_info(current_raw)
            statuses.append(current_status)
            
            if is_success:
                formatted_msg = f"期刊: {sys_name[1:-1]}\nID: {ms_id}\n当前状态: **{current_status}**"
                track_id = ms_id
            else:
                formatted_msg = f"期刊: {sys_name[1:-1]}\nID: {ms_id if ms_id else '未提取到'}\n抓取结果:\n{current_status}"
                track_id = ms_id if ms_id else state_key
                
            last_status = state.get(state_key, "暂无")
            is_changed = (last_status != "暂无" and current_status != last_status)
            is_first_time = (last_status == "暂无")
            
            # --- 历史记录维护 ---
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            history = state.get("history", {})
            if track_id not in history:
                history[track_id] = []
            
            # 若状态发生了改变或初次抓取，则追加日期轨迹
            if not history[track_id] or history[track_id][-1]["status"] != current_status:
                history[track_id].append({"date": today_str, "status": current_status})
                state["history"] = history
            
            # --- 通知策略判断 ---
            send_mode = self.config.get("send_mode", "仅状态变化时发送")
            
            if is_changed:
                changes_detected.append(f"🔴 【状态更新】\n{formatted_msg}")
                state[state_key] = current_status
            elif is_first_time:
                state[state_key] = current_status
                self.log_signal.emit(f"首次运行 {sys_name}，已记录初始基准状态: {current_status}")
                if send_mode in ["查询完立即发送", "仅状态变化时发送"]:
                    changes_detected.append(f"🟢 【初始状态记录】\n{formatted_msg}")
            elif send_mode == "查询完立即发送":
                changes_detected.append(f"⚪ 【实时查询报告】\n{formatted_msg}")
                
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 统一推送变化
        use_desktop = self.config.get("use_desktop_notify", False)
        
        if changes_detected:
            msg = "\n---\n".join(changes_detected)
            if use_desktop:
                self.notify_signal.emit("🎯 稿件监控实时报告", msg)
            else:
                send_wechat(send_key, "🎯 稿件监控实时报告", msg, log_callback=self.log_signal.emit)
            save_state(state)
        else:
            self.log_signal.emit(f"所有已配置系统状态无变化 (当前模式: {self.config.get('send_mode')})，静默等待下次轮询。")
            save_state(state)


# ================= 任务6：图形界面与系统托盘 =================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AcceptBot - 期刊状态监控助手 (双系统版)")
        self.resize(650, 550)
        
        self.config = load_config()
        self.monitor_thread = None
        
        self.init_ui()
        self.init_tray()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # 表单布局
        form_layout = QVBoxLayout()
        
        # --- 系统 1 配置 ---
        form_layout.addWidget(QLabel("<b>【系统 1】 (例如 T-ITS / ScholarOne)</b>"))
        url_layout1 = QHBoxLayout()
        url_layout1.addWidget(QLabel("期刊 URL: "))
        self.url_input1 = QLineEdit(self.config.get("url_1", "https://mc.manuscriptcentral.com/t-its"))
        url_layout1.addWidget(self.url_input1)
        form_layout.addLayout(url_layout1)
        
        user_layout1 = QHBoxLayout()
        user_layout1.addWidget(QLabel("登录账号: "))
        self.user_input1 = QLineEdit(self.config.get("username_1", ""))
        user_layout1.addWidget(self.user_input1)
        
        user_layout1.addWidget(QLabel("登录密码: "))
        self.pwd_input1 = QLineEdit(self.config.get("password_1", ""))
        self.pwd_input1.setEchoMode(QLineEdit.EchoMode.Password)
        user_layout1.addWidget(self.pwd_input1)
        form_layout.addLayout(user_layout1)
        
        # --- 系统 2 配置 ---
        form_layout.addWidget(QLabel("<b>【系统 2】 (例如 SEGAN / Editorial Manager)</b>"))
        url_layout2 = QHBoxLayout()
        url_layout2.addWidget(QLabel("期刊 URL: "))
        self.url_input2 = QLineEdit(self.config.get("url_2", "https://www.editorialmanager.com/segan/default2.aspx"))
        url_layout2.addWidget(self.url_input2)
        form_layout.addLayout(url_layout2)
        
        user_layout2 = QHBoxLayout()
        user_layout2.addWidget(QLabel("登录账号: "))
        self.user_input2 = QLineEdit(self.config.get("username_2", ""))
        user_layout2.addWidget(self.user_input2)
        
        user_layout2.addWidget(QLabel("登录密码: "))
        self.pwd_input2 = QLineEdit(self.config.get("password_2", ""))
        self.pwd_input2.setEchoMode(QLineEdit.EchoMode.Password)
        user_layout2.addWidget(self.pwd_input2)
        form_layout.addLayout(user_layout2)
        
        # --- 全局配置 ---
        form_layout.addWidget(QLabel("<b>【全局配置】</b>"))
        sk_layout = QHBoxLayout()
        sk_layout.addWidget(QLabel("Server酱 SendKey: "))
        self.sk_input = QLineEdit(self.config.get("send_key", ""))
        sk_layout.addWidget(self.sk_input)
        form_layout.addLayout(sk_layout)
        
        # 新增选项：查询时间间隔、发送模式、定时汇报时间
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("查询间隔(小时):"))
        self.interval_cb = QComboBox()
        self.interval_cb.addItems(["1", "2", "4", "6", "8", "12", "24"])
        self.interval_cb.setCurrentText(str(self.config.get("poll_interval_hours", 4)))
        settings_layout.addWidget(self.interval_cb)
        
        settings_layout.addWidget(QLabel(" 发送模式:"))
        self.send_mode_cb = QComboBox()
        self.send_mode_cb.addItems(["查询完立即发送", "仅状态变化时发送", "每天定时汇报发送"])
        self.send_mode_cb.setCurrentText(self.config.get("send_mode", "仅状态变化时发送"))
        settings_layout.addWidget(self.send_mode_cb)
        
        settings_layout.addWidget(QLabel(" 定时汇报时间(点):"))
        self.report_hour_sp = QSpinBox()
        self.report_hour_sp.setRange(0, 23)
        self.report_hour_sp.setValue(self.config.get("daily_report_hour", 19))
        settings_layout.addWidget(self.report_hour_sp)
        
        form_layout.addLayout(settings_layout)
        
        # 弹窗通知选项
        notify_layout = QHBoxLayout()
        from PySide6.QtWidgets import QCheckBox
        self.desktop_notify_cb = QCheckBox("使用桌面右下角弹窗通知 (勾选后将不再发送微信)")
        self.desktop_notify_cb.setChecked(self.config.get("use_desktop_notify", False))
        notify_layout.addWidget(self.desktop_notify_cb)
        form_layout.addLayout(notify_layout)
        
        main_layout.addLayout(form_layout)
        
        # 按钮布局
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("保存配置")
        self.btn_history = QPushButton("📜 查看历史")
        self.btn_start = QPushButton("▶ 启动监控")
        self.btn_stop = QPushButton("■ 停止监控")
        self.btn_stop.setEnabled(False)
        
        # 设置按钮样式，让启动按钮醒目一点
        self.btn_history.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn_stop.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_history)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        main_layout.addLayout(btn_layout)
        
        # 日志输出区
        main_layout.addWidget(QLabel("运行日志:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: Consolas;")
        main_layout.addWidget(self.log_text)
        
        # 绑定点击事件
        self.btn_save.clicked.connect(self.save_config_ui)
        self.btn_history.clicked.connect(self.show_history_dialog)
        self.btn_start.clicked.connect(self.start_monitor)
        self.btn_stop.clicked.connect(self.stop_monitor)
        
        self.append_log("界面初始化完成。请确认上方配置无误后，点击“启动监控”。")
        self.append_log("提示：点击窗口右上角的 [X] 会最小化到右下角托盘在后台运行。")
        
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        # 调用系统自带的电脑图标作为托盘图标
        self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        
        # 托盘右键菜单
        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        quit_action = QAction("完全退出", self)
        
        show_action.triggered.connect(self.showNormal)
        quit_action.triggered.connect(self.quit_app)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()
        
    def tray_icon_activated(self, reason):
        # 双击托盘图标恢复显示主窗口
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event: QCloseEvent):
        # 重写关闭事件：实现点击右上角 X 时不退出，而是隐藏窗口
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "AcceptBot 监控已隐藏",
            "程序仍在后台默默守护您的稿件！双击任务栏图标即可恢复窗口。",
            QSystemTrayIcon.MessageIcon.Information,
            2000 # 气泡显示毫秒数
        )
        
    def quit_app(self):
        # 真正完全退出的逻辑
        self.stop_monitor()
        QApplication.quit()
        
    def show_desktop_notification(self, title, msg):
        # 系统托盘弹窗通知
        # QSystemTrayIcon.MessageIcon.Information
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 10000)
        self.append_log(f"已在桌面右下角弹出系统通知: {title}")

    def append_log(self, msg):
        self.log_text.append(f"> {msg}")
        # 自动滚动到最底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def save_config_ui(self):
        self.config["url_1"] = self.url_input1.text().strip()
        self.config["username_1"] = self.user_input1.text().strip()
        self.config["password_1"] = self.pwd_input1.text().strip()
        self.config["url_2"] = self.url_input2.text().strip()
        self.config["username_2"] = self.user_input2.text().strip()
        self.config["password_2"] = self.pwd_input2.text().strip()
        self.config["send_key"] = self.sk_input.text().strip()
        
        # 新增选项保存
        self.config["poll_interval_hours"] = int(self.interval_cb.currentText())
        self.config["send_mode"] = self.send_mode_cb.currentText()
        self.config["daily_report_hour"] = self.report_hour_sp.value()
        self.config["use_desktop_notify"] = self.desktop_notify_cb.isChecked()
        
        save_config(self.config)
        self.append_log("配置已成功保存！")
        
    def show_history_dialog(self):
        state = load_state()
        history = state.get("history", {})
        
        dialog = QDialog(self)
        dialog.setWindowTitle("稿件状态追踪时间轴")
        dialog.resize(500, 400)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        
        if not history:
            text_edit.setText("暂无任何历史记录。等待程序自动抓取后更新...")
        else:
            display_text = ""
            for ms_id, records in history.items():
                display_text += f"<h3>📄 稿件 ID: <span style='color:#E91E63'>{ms_id}</span></h3>"
                display_text += "<ul>"
                for rec in records:
                    display_text += f"<li><b>{rec['date']}</b>: <span style='color:#1565C0'>{rec['status']}</span></li>"
                display_text += "</ul><hr>"
            text_edit.setHtml(display_text)
            
        layout.addWidget(text_edit)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()
        
    def start_monitor(self):
        self.save_config_ui() # 启动前先保存一次最新配置
        if self.monitor_thread is not None and self.monitor_thread.isRunning():
            return
            
        self.monitor_thread = MonitorThread(self.config)
        self.monitor_thread.log_signal.connect(self.append_log)
        self.monitor_thread.notify_signal.connect(self.show_desktop_notification)
        self.monitor_thread.start() # 启动子线程
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
    def stop_monitor(self):
        if self.monitor_thread is not None:
            self.monitor_thread.stop()
            self.monitor_thread.wait() # 阻塞等待线程安全结束
            self.monitor_thread = None
            
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 强制阻止：当主窗口隐藏时，整个 Qt 应用自动关闭的默认行为
    app.setQuitOnLastWindowClosed(False)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
