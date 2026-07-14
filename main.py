import os
import sys
import queue
import asyncio
import threading
import customtkinter as ctk
from tkinter import filedialog
from uploader import ThreadsUploader

# 창 디자인 테마 설정
ctk.set_appearance_mode("Dark")  # 모드: "System", "Dark", "Light"
ctk.set_default_color_theme("blue")  # 테마: "blue", "green", "dark-blue"

class ThreadsApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # 기본 윈도우 설정
        self.title("Threads Auto Uploader - 스레드 자동 업로드 툴")
        self.geometry("750x650")
        self.minsize(700, 500)
        
        # 경로 초기화
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.session_dir = os.path.join(base_dir, "threads_session")
        self.work_dir = ""
        self.excel_path = ""
        
        # 업로더 스레드 및 큐 설정
        self.uploader = None
        self.upload_thread = None
        self.log_queue = queue.Queue()
        
        self.init_ui()
        
        # 주기적으로 로그 큐를 체크하여 UI 텍스트 상자에 업데이트
        self.after(100, self.process_log_queue)

    def init_ui(self):
        # 전체 레이아웃 그리드 설정
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # 로그 영역이 가변적으로 확장되도록 설정
        
        # --- ROW 0: TITLE AREA ---
        self.title_label = ctk.CTkLabel(
            self, 
            text="Threads 자동 포스팅 툴 (Excel 및 이미지 폴더 매핑)", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.grid(row=0, column=0, padx=20, pady=(15, 10), sticky="ew")
        
        # --- ROW 1: CONFIGURATION FRAME ---
        self.config_frame = ctk.CTkFrame(self)
        self.config_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        self.config_frame.grid_columnconfigure(1, weight=1)
        
        # 1-1. 엑셀 파일 선택
        self.excel_label = ctk.CTkLabel(self.config_frame, text="엑셀 파일:", font=ctk.CTkFont(size=12, weight="bold"))
        self.excel_label.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")
        
        self.excel_path_entry = ctk.CTkEntry(
            self.config_frame, 
            placeholder_text="포스팅 본문과 매핑 폴더명이 적힌 엑셀(.xlsx) 또는 CSV 파일을 선택하세요."
        )
        self.excel_path_entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 5), sticky="ew")
        
        self.excel_select_btn = ctk.CTkButton(
            self.config_frame, 
            text="파일 선택", 
            width=90, 
            command=self.select_excel_file
        )
        self.excel_select_btn.grid(row=0, column=2, padx=10, pady=(10, 5), sticky="e")
        
        # 1-2. 작업 폴더 선택
        self.folder_label = ctk.CTkLabel(self.config_frame, text="이미지 폴더:", font=ctk.CTkFont(size=12, weight="bold"))
        self.folder_label.grid(row=1, column=0, padx=15, pady=5, sticky="w")
        
        self.folder_path_entry = ctk.CTkEntry(
            self.config_frame, 
            placeholder_text="바탕화면에 생성한 스레드 업로드용 이미지 폴더 경로를 선택하세요."
        )
        self.folder_path_entry.grid(row=1, column=1, padx=(5, 10), pady=5, sticky="ew")
        
        self.folder_select_btn = ctk.CTkButton(
            self.config_frame, 
            text="폴더 선택", 
            width=90, 
            command=self.select_folder
        )
        self.folder_select_btn.grid(row=1, column=2, padx=10, pady=5, sticky="e")
        
        # 1-3. 계정 ID 입력
        self.username_label = ctk.CTkLabel(self.config_frame, text="계정 ID:", font=ctk.CTkFont(size=12, weight="bold"))
        self.username_label.grid(row=2, column=0, padx=15, pady=(5, 10), sticky="w")
        
        self.username_entry = ctk.CTkEntry(
            self.config_frame, 
            placeholder_text="계정 ID를 입력해주세요 (세션 정보를 개별적으로 관리할 고유 ID)"
        )
        self.username_entry.grid(row=2, column=1, padx=(5, 10), pady=(5, 10), sticky="ew")
        
        # 1-4. 로그인 세션 및 설정 프레임 (가로 분할)
        self.sub_config_frame = ctk.CTkFrame(self.config_frame, fg_color="transparent")
        self.sub_config_frame.grid(row=3, column=0, columnspan=3, padx=10, pady=(5, 10), sticky="ew")
        self.sub_config_frame.grid_columnconfigure(0, weight=1)
        self.sub_config_frame.grid_columnconfigure(1, weight=1)
        
        # 2-1. 좌측: 세션 관리
        self.session_frame = ctk.CTkFrame(self.sub_config_frame)
        self.session_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        
        self.session_btn = ctk.CTkButton(
            self.session_frame, 
            text="🔑 스레드 로그인 세션 열기", 
            fg_color="#D83C54", 
            hover_color="#B82E43",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.open_session
        )
        self.session_btn.pack(padx=15, pady=12, fill="both", expand=True)
        
        # 2-2. 우측: 대기 및 실행 설정
        self.control_frame = ctk.CTkFrame(self.sub_config_frame)
        self.control_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        
        # 대기 시간 설정
        self.delay_label = ctk.CTkLabel(self.control_frame, text="간격 (분):", font=ctk.CTkFont(size=12))
        self.delay_label.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="w")
        
        self.delay_entry = ctk.CTkEntry(self.control_frame, width=60)
        self.delay_entry.insert(0, "30")  # 기본값 30분
        self.delay_entry.grid(row=0, column=1, padx=5, pady=10, sticky="w")
        
        # 브라우저 실행 모드
        self.headless_var = ctk.BooleanVar(value=True)
        self.headless_cb = ctk.CTkCheckBox(
            self.control_frame, 
            text="화면 숨김(Headless)", 
            variable=self.headless_var
        )
        self.headless_cb.grid(row=0, column=2, padx=15, pady=10, sticky="w")
        
        # --- ROW 2: ACTION BUTTONS ---
        self.action_frame = ctk.CTkFrame(self)
        self.action_frame.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.action_frame.grid_columnconfigure(1, weight=1)
        
        self.start_btn = ctk.CTkButton(
            self.action_frame, 
            text="🚀 자동 업로드 시작", 
            fg_color="#2EA44F", 
            hover_color="#22863A",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start_upload
        )
        self.start_btn.grid(row=0, column=0, padx=15, pady=12, sticky="ew")
        
        self.stop_btn = ctk.CTkButton(
            self.action_frame, 
            text="⏹️ 정지", 
            fg_color="#D73A49", 
            hover_color="#CB2431",
            font=ctk.CTkFont(size=14, weight="bold"),
            state="disabled",
            command=self.stop_upload
        )
        self.stop_btn.grid(row=0, column=1, padx=15, pady=12, sticky="ew")
        
        # --- ROW 3: LOG CONSOLE AREA ---
        self.log_frame = ctk.CTkFrame(self)
        self.log_frame.grid(row=3, column=0, padx=20, pady=(5, 15), sticky="nsew")
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)
        
        self.console_title = ctk.CTkLabel(
            self.log_frame, 
            text="💻 실시간 작업 상태 로그", 
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.console_title.grid(row=0, column=0, padx=15, pady=(10, 2), sticky="w")
        
        self.log_textbox = ctk.CTkTextbox(
            self.log_frame, 
            font=ctk.CTkFont(family="Courier" if sys.platform != "darwin" else "Menlo", size=11)
        )
        self.log_textbox.grid(row=1, column=0, padx=15, pady=(2, 12), sticky="nsew")

    # --- BUTTON EVENT HANDLERS ---
    
    def select_excel_file(self):
        """엑셀 또는 CSV 파일 선택 팝업 오픈"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if file_path:
            self.excel_path = os.path.abspath(file_path)
            self.excel_path_entry.delete(0, ctk.END)
            self.excel_path_entry.insert(0, self.excel_path)
            self.write_log(f"엑셀 파일이 지정되었습니다: {self.excel_path}")

    def select_folder(self):
        """이미지 루트 디렉토리 선택 팝업 오픈"""
        selected_dir = filedialog.askdirectory()
        if selected_dir:
            self.work_dir = os.path.abspath(selected_dir)
            self.folder_path_entry.delete(0, ctk.END)
            self.folder_path_entry.insert(0, self.work_dir)
            self.write_log(f"이미지 폴더가 설정되었습니다: {self.work_dir}")

    def write_log(self, text):
        """스레드 세이프 로그 전송"""
        self.log_queue.put(text)

    def process_log_queue(self):
        """로그 큐 비우기"""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_textbox.insert(ctk.END, f"{msg}\n")
                self.log_textbox.see(ctk.END)
                self.log_queue.task_done()
        except queue.Empty:
            pass
        self.after(100, self.process_log_queue)

    def open_session(self):
        """계정 세션을 수동으로 획득하기 위한 브라우저 구동"""
        username = self.username_entry.get().strip()
        if not username:
            self.write_log("오류: 세션을 관리할 '계정 ID'를 먼저 입력해주세요.")
            return

        self.session_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.username_entry.configure(state="disabled")
        
        def run():
            uploader = ThreadsUploader(
                user_data_dir=self.session_dir, 
                work_dir=self.work_dir, 
                username=username,
                log_callback=self.write_log
            )
            asyncio.run(uploader.open_login_session())
            self.after(0, self.restore_ui_states)

        threading.Thread(target=run, daemon=True).start()

    def restore_ui_states(self):
        self.session_btn.configure(state="normal")
        self.start_btn.configure(state="normal")
        self.username_entry.configure(state="normal")

    def start_upload(self):
        """자동 포스팅 스케줄러 실행"""
        self.work_dir = os.path.abspath(self.folder_path_entry.get().strip())
        self.excel_path = os.path.abspath(self.excel_path_entry.get().strip())
        username = self.username_entry.get().strip()
        
        # 유효성 검증
        if not self.excel_path or not os.path.exists(self.excel_path):
            self.write_log("오류: 올바른 엑셀/CSV 파일 경로를 지정해주세요.")
            return
            
        if not self.work_dir or not os.path.exists(self.work_dir):
            self.write_log("오류: 올바른 이미지 작업 폴더 경로를 선택해주세요.")
            return
            
        if not username:
            self.write_log("오류: 세션 식별을 위한 '계정 ID'를 입력해주세요.")
            return
            
        try:
            delay = float(self.delay_entry.get().strip())
            if delay <= 0:
                raise ValueError
        except ValueError:
            self.write_log("오류: 포스팅 간격(분)은 0보다 큰 숫자여야 합니다.")
            return
            
        # UI 비활성화
        self.start_btn.configure(state="disabled")
        self.session_btn.configure(state="disabled")
        self.excel_select_btn.configure(state="disabled")
        self.excel_path_entry.configure(state="disabled")
        self.folder_select_btn.configure(state="disabled")
        self.folder_path_entry.configure(state="disabled")
        self.username_entry.configure(state="disabled")
        self.delay_entry.configure(state="disabled")
        self.headless_cb.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        
        # 업로더 객체 빌드
        self.uploader = ThreadsUploader(
            user_data_dir=self.session_dir,
            work_dir=self.work_dir,
            username=username,
            log_callback=self.write_log
        )
        
        is_headless = self.headless_var.get()
        
        def run_upload():
            try:
                # 엑셀 기반 업로드 프로세스 시작
                asyncio.run(self.uploader.start_upload_process(
                    excel_path=self.excel_path,
                    delay_minutes=delay, 
                    is_headless=is_headless
                ))
            except Exception as e:
                self.write_log(f"백그라운드 포스팅 중 에러 발생: {e}")
            finally:
                self.after(0, self.on_upload_finished)
                
        self.upload_thread = threading.Thread(target=run_upload, daemon=True)
        self.upload_thread.start()

    def stop_upload(self):
        """스케줄러 강제 중단"""
        if self.uploader:
            self.uploader.stop()
            self.stop_btn.configure(state="disabled")

    def on_upload_finished(self):
        """종료 후 UI 컨트롤 상태 복구"""
        self.start_btn.configure(state="normal")
        self.session_btn.configure(state="normal")
        self.excel_select_btn.configure(state="normal")
        self.excel_path_entry.configure(state="normal")
        self.folder_select_btn.configure(state="normal")
        self.folder_path_entry.configure(state="normal")
        self.username_entry.configure(state="normal")
        self.delay_entry.configure(state="normal")
        self.headless_cb.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.write_log("자동 포스팅 프로세스가 완전히 정지되었습니다.")

if __name__ == "__main__":
    app = ThreadsApp()
    app.mainloop()
