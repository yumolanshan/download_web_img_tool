from imgdl import ImageCrawler
import threading
import tkinter as tk
from tkinter import messagebox


def main() -> None:
    """创建一个简单的 Tkinter 下载界面，支持输入 URL、下载数量和起始页。"""

    def set_status(message: str, fg: str = 'black') -> None:
        status_label.config(text=message, fg=fg)
        root.update_idletasks()

    def download_task() -> None:
        try:
            url = url_var.get().strip() or 'https://www.4kdesk.com/'
            target_count = int(count_var.get())
            if target_count < 1:
                raise ValueError('下载数量必须是大于 0 的整数')
            start_page_value = start_page_var.get().strip()
            start_page = int(start_page_value) if start_page_value else None
            if start_page is not None and start_page < 1:
                raise ValueError('起始页必须是大于等于 1 的整数')
        except ValueError as exc:
            messagebox.showerror('输入错误', str(exc))
            set_status(f'输入错误：{exc}', 'red')
            return

        download_button.config(state='disabled')
        url_entry.config(state='disabled')
        count_entry.config(state='disabled')
        start_page_entry.config(state='disabled')
        set_status('正在下载，请稍候...', 'blue')

        try:
            crawler = ImageCrawler(base_url=url)
            result = crawler.crawl_pages(target_count=target_count, start_page=start_page)
            set_status(f'下载完成：{result["downloaded"]} 张图片', 'green')
        except Exception as exc:
            messagebox.showerror('下载失败', str(exc))
            set_status(f'下载失败：{exc}', 'red')
        finally:
            download_button.config(state='normal')
            url_entry.config(state='normal')
            count_entry.config(state='normal')
            start_page_entry.config(state='normal')

    def on_download_clicked() -> None:
        threading.Thread(target=download_task, daemon=True).start()

    root = tk.Tk()
    root.title('图片下载工具')
    root.geometry('440x260')
    root.resizable(False, False)

    url_var = tk.StringVar(value='https://www.4kdesk.com/')
    count_var = tk.StringVar(value='12')
    start_page_var = tk.StringVar(value='1')

    frame = tk.Frame(root, padx=16, pady=16, bg='lightblue')
    frame.pack(fill='both', expand=True)

    tk.Label(frame, text='图片网站 URL：', bg='lightblue').grid(row=0, column=0, sticky='e', pady=6)
    url_entry = tk.Entry(frame, textvariable=url_var, width=36)
    url_entry.grid(row=0, column=1, sticky='w', pady=6)

    tk.Label(frame, text='下载数量：', bg='lightblue').grid(row=1, column=0, sticky='e', pady=6)
    count_entry = tk.Entry(frame, textvariable=count_var, width=12)
    count_entry.grid(row=1, column=1, sticky='w', pady=6)

    tk.Label(frame, text='起始页：', bg='lightblue').grid(row=2, column=0, sticky='e', pady=6)
    start_page_entry = tk.Entry(frame, textvariable=start_page_var, width=12)
    start_page_entry.grid(row=2, column=1, sticky='w', pady=6)

    download_button = tk.Button(frame, text='开始下载', command=on_download_clicked, bg='#4CAF50', fg='white')
    download_button.grid(row=3, column=0, columnspan=2, pady=16, ipadx=20, ipady=8)

    status_label = tk.Label(frame, text='准备就绪', bg='lightblue', fg='black')
    status_label.grid(row=4, column=0, columnspan=2, pady=6)

    for i in range(2):
        frame.grid_columnconfigure(i, weight=1)

    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f'{width}x{height}+{x}+{y}')
    root.configure(bg='lightblue')

    root.mainloop()


if __name__ == '__main__':
    main()
