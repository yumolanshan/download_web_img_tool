import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional
from imgdl import ImageCrawler, CrawlConfig, ControlState, format_time


class DownloadApp:
    DEFAULT_URL = 'https://mikagogo.com/pc-wallpaper'
    DEFAULT_PAGES = 1
    WINDOW_TITLE = '图片下载工具（按页）'
    WINDOW_SIZE = '500x480'

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(self.WINDOW_TITLE)
        self.root.geometry(self.WINDOW_SIZE)
        self.root.resizable(False, False)

        self.main_frame = ttk.Frame(self.root, padding=20)
        self.main_frame.place(relx=0.5, rely=0.5, anchor='center')

        # 变量
        self.url_var = tk.StringVar(value=self.DEFAULT_URL)
        self.pages_var = tk.StringVar(value=str(self.DEFAULT_PAGES))
        self.start_page_var = tk.StringVar(value='')
        self.status_var = tk.StringVar(value='准备就绪')
        self.success_var = tk.StringVar(value='0')
        self.fail_var = tk.StringVar(value='0')
        self.total_var = tk.StringVar(value='0')
        self.time_var = tk.StringVar(value='00:00:00')

        # 控制标志（线程安全）
        self.control_state = ControlState.RUNNING
        self.control_lock = threading.Lock()
        self.download_thread: Optional[threading.Thread] = None
        self.crawler: Optional[ImageCrawler] = None
        self.timer_running = False
        self.start_time = 0.0
        self.timer_id = None

        self._create_widgets()
        self._center_window()
        self._setup_close_handler()

    def _setup_close_handler(self):
        """窗口关闭时等待下载线程结束"""
        def on_closing():
            if self.download_thread and self.download_thread.is_alive():
                self._set_status('正在取消下载，请稍候...')
                with self.control_lock:
                    self.control_state = ControlState.CANCELLED
                self.download_thread.join(timeout=5.0)
            self.root.destroy()
        self.root.protocol("WM_DELETE_WINDOW", on_closing)

    def _create_widgets(self):
        row = 0
        ttk.Label(self.main_frame, text='网页网站 URL：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.url_entry = ttk.Entry(self.main_frame, textvariable=self.url_var, width=40)
        self.url_entry.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Label(self.main_frame, text='下载页数：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.pages_entry = ttk.Entry(self.main_frame, textvariable=self.pages_var, width=12)
        self.pages_entry.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Label(self.main_frame, text='起始页：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.start_page_entry = ttk.Entry(self.main_frame, textvariable=self.start_page_var, width=12)
        self.start_page_entry.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Separator(self.main_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1

        ttk.Label(self.main_frame, text='发现总数：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.total_label = ttk.Label(self.main_frame, textvariable=self.total_var)
        self.total_label.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Label(self.main_frame, text='下载成功：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.success_label = ttk.Label(self.main_frame, textvariable=self.success_var, foreground='green')
        self.success_label.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Label(self.main_frame, text='下载失败：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.fail_label = ttk.Label(self.main_frame, textvariable=self.fail_var, foreground='red')
        self.fail_label.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Label(self.main_frame, text='耗时：').grid(row=row, column=0, sticky='e', pady=6, padx=5)
        self.time_label = ttk.Label(self.main_frame, textvariable=self.time_var)
        self.time_label.grid(row=row, column=1, sticky='w', pady=6, padx=5)
        row += 1

        ttk.Separator(self.main_frame, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1

        self.status_label = ttk.Label(self.main_frame, textvariable=self.status_var, wraplength=400)
        self.status_label.grid(row=row, column=0, columnspan=2, pady=6, sticky='ew')
        row += 1

        button_frame = ttk.Frame(self.main_frame)
        button_frame.grid(row=row, column=0, columnspan=2, pady=12)
        self.download_btn = ttk.Button(button_frame, text='下载', command=self._on_download_clicked)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        self.pause_btn = ttk.Button(button_frame, text='暂停', command=self._on_pause_clicked, state=tk.DISABLED)
        self.pause_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_btn = ttk.Button(button_frame, text='取消', command=self._on_cancel_clicked, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)

        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)

    def _center_window(self):
        self.root.update_idletasks()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f'{w}x{h}+{x}+{y}')

    def _set_status(self, message: str, is_error: bool = False):
        def _update():
            self.status_var.set(message)
            self.status_label.config(foreground='red' if is_error else 'black')
        self.root.after(0, _update)

    def _update_counts(self, success: int, fail: int):
        def _update():
            self.success_var.set(str(success))
            self.fail_var.set(str(fail))
        self.root.after(0, _update)

    def _update_total_found(self, total: int):
        def _update():
            self.total_var.set(str(total))
        self.root.after(0, _update)

    def _start_timer(self):
        self.start_time = time.time()
        self.timer_running = True
        self._update_timer()

    def _update_timer(self):
        if not self.timer_running:
            return
        elapsed = time.time() - self.start_time
        self.time_var.set(format_time(elapsed))
        self.timer_id = self.root.after(1000, self._update_timer)

    def _stop_timer(self):
        self.timer_running = False
        if self.timer_id:
            self.root.after_cancel(self.timer_id)
            self.timer_id = None

    def _enable_ui(self, enabled: bool, download_started: bool = False):
        """enabled: 是否允许编辑输入框；download_started: 下载是否已启动（用于控制暂停/取消按钮）"""
        def _update():
            state = 'normal' if enabled else 'disabled'
            self.url_entry.config(state=state)
            self.pages_entry.config(state=state)
            self.start_page_entry.config(state=state)
            self.download_btn.config(state=state)

            if download_started:
                with self.control_lock:
                    cur_state = self.control_state
                if cur_state == ControlState.RUNNING:
                    self.pause_btn.config(text='暂停', state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.NORMAL)
                elif cur_state == ControlState.PAUSED:
                    self.pause_btn.config(text='继续', state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.NORMAL)
                else:
                    self.pause_btn.config(state=tk.DISABLED)
                    self.cancel_btn.config(state=tk.DISABLED)
            else:
                self.pause_btn.config(state=tk.DISABLED)
                self.cancel_btn.config(state=tk.DISABLED)
        self.root.after(0, _update)

    def _control_callback(self) -> ControlState:
        with self.control_lock:
            return self.control_state

    def _on_pause_clicked(self):
        with self.control_lock:
            if self.control_state == ControlState.RUNNING:
                self.control_state = ControlState.PAUSED
                self._enable_ui(False, download_started=True)
                self._set_status('已暂停下载')
            elif self.control_state == ControlState.PAUSED:
                self.control_state = ControlState.RUNNING
                self._enable_ui(False, download_started=True)
                self._set_status('继续下载...')

    def _on_cancel_clicked(self):
        with self.control_lock:
            if self.control_state in (ControlState.RUNNING, ControlState.PAUSED):
                self.control_state = ControlState.CANCELLED
                self._enable_ui(False, download_started=False)
                self._set_status('正在取消下载...')

    def _download_task(self):
        try:
            url = self.url_var.get().strip() or self.DEFAULT_URL
            page_limit = int(self.pages_var.get())
            if page_limit < 1:
                raise ValueError('页数必须是大于 0 的整数')
            start_page_str = self.start_page_var.get().strip()
            start_page = int(start_page_str) if start_page_str else None
            if start_page is not None and start_page < 1:
                raise ValueError('起始页必须是大于等于 1 的整数')
        except ValueError as e:
            self._set_status(f'输入错误：{e}', is_error=True)
            self._enable_ui(True, download_started=False)
            return

        with self.control_lock:
            self.control_state = ControlState.RUNNING
        self._enable_ui(False, download_started=True)
        self._set_status('正在下载，请稍候...')
        self._update_counts(0, 0)
        self._update_total_found(0)
        self._stop_timer()
        self._start_timer()

        config = CrawlConfig(
            base_url=url.rstrip('/') + '/',
            convert_to_png=True
        )
        # 使用上下文管理器确保 session 关闭
        with ImageCrawler(
            config,
            progress_callback=None,
            image_result_callback=lambda s, f: self._update_counts(s, f),
            total_found_callback=self._update_total_found,
            control_callback=self._control_callback
        ) as crawler:
            self.crawler = crawler
            try:
                result = crawler.crawl_pages(page_limit, start_page=start_page)
                elapsed = time.time() - self.start_time
                status_msg = (f'下载完成：共 {result["pages_downloaded"]} 页，'
                              f'成功 {result["total_images"]} 张，'
                              f'失败 {result["failed_images"]} 张，'
                              f'耗时 {format_time(elapsed)}')
                self._set_status(status_msg)
            except InterruptedError:
                self._set_status('下载已取消')
            except Exception as e:
                elapsed = time.time() - self.start_time
                self._set_status(f'下载失败：{e} (耗时 {format_time(elapsed)})', is_error=True)
            finally:
                self._stop_timer()
                self._enable_ui(True, download_started=False)
                with self.control_lock:
                    self.control_state = ControlState.RUNNING
                self.crawler = None
                self.download_thread = None

    def _on_download_clicked(self):
        if self.download_thread and self.download_thread.is_alive():
            self._set_status('已有下载任务进行中', is_error=True)
            return
        self.download_thread = threading.Thread(target=self._download_task, daemon=True)
        self.download_thread.start()

    def run(self):
        self.root.mainloop()


def main() -> None:
    app = DownloadApp()
    app.run()


if __name__ == '__main__':
    main()