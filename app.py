import os
import sys
import json
import time
import queue
import datetime
import asyncio
import threading
import re
import pandas as pd
from flask import Flask, request, jsonify, render_template, Response
from uploader import ThreadsProUploader, rewrite_content, safe_session_name

app = Flask(__name__)

# 전역 로그 큐 및 실행 상태
log_queue = queue.Queue()
is_running = False
scheduler_thread = None

# 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
QUEUE_FILE = os.path.join(BASE_DIR, "queue.json")
SESSION_DIR = os.path.join(BASE_DIR, "sessions")

os.makedirs(SESSION_DIR, exist_ok=True)

def add_log(message):
    """실시간 스트리밍을 위한 큐 삽입 및 타임스탬프 부여"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {message}"
    log_queue.put(formatted_msg)
    print(formatted_msg, flush=True)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"headless": False, "publish_delay": 10, "openai_api_key": "", "gemini_api_key": "", "system_prompt": "", "accounts": []}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
        if "headless" not in config:
            config["headless"] = False
        if "publish_delay" not in config:
            config["publish_delay"] = 10
        return config

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_queue(q_data):
    with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
        json.dump(q_data, f, ensure_ascii=False, indent=2)

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    if request.method == 'POST':
        data = request.json
        config = load_config()
        config['headless'] = data.get('headless', False)
        config['publish_delay'] = int(data.get('publish_delay', 10))
        config['openai_api_key'] = data.get('openai_api_key', '')
        config['gemini_api_key'] = data.get('gemini_api_key', '')
        config['system_prompt'] = data.get('system_prompt', '')
        save_config(config)
        add_log("[System] 설정 정보가 성공적으로 저장되었습니다.")
        return jsonify({"status": "success", "config": config})
    else:
        return jsonify(load_config())

@app.route('/api/accounts', methods=['GET', 'POST', 'DELETE'])
def handle_accounts():
    config = load_config()
    
    if request.method == 'POST':
        data = request.json
        username = data.get("username", "").strip()
        if not username:
            return jsonify({"status": "error", "message": "계정명을 입력하세요."}), 400
            
        if username not in config['accounts']:
            config['accounts'].append(username)
            save_config(config)
            add_log(f"[System] 계정 '{username}'이 목록에 추가되었습니다.")
            return jsonify({"status": "success", "accounts": config['accounts']})
        return jsonify({"status": "error", "message": "이미 존재하는 계정입니다."}), 400
        
    elif request.method == 'DELETE':
        username = request.args.get("username", "").strip()
        if username in config['accounts']:
            config['accounts'].remove(username)
            if "account_handles" in config and username in config["account_handles"]:
                del config["account_handles"][username]
            save_config(config)
            
            # 세션 쿠키 파일 및 프로필 삭제 시도
            safe_user = safe_session_name(username)
            session_file = os.path.join(SESSION_DIR, f"{safe_user}.json")
            if os.path.exists(session_file):
                os.remove(session_file)
                
            add_log(f"[System] 계정 '{username}' 및 관련 세션 데이터가 삭제되었습니다.")
            return jsonify({"status": "success", "accounts": config['accounts']})
        return jsonify({"status": "error", "message": "계정을 찾을 수 없습니다."}), 400
        
    else:
        # 계정 목록과 각 로그인 세션 상태 반환
        account_status = []
        account_handles = config.get("account_handles", {})
        for user in config['accounts']:
            safe_user = safe_session_name(user)
            session_file = os.path.join(SESSION_DIR, f"{safe_user}.json")
            status = "로그인 완료" if os.path.exists(session_file) else "로그인 필요"
            actual = account_handles.get(user, "")
            account_status.append({"username": user, "status": status, "actual_username": actual})
        return jsonify(account_status)

@app.route('/api/accounts/rename', methods=['POST'])
def rename_account():
    data = request.json
    old_username = data.get("old_username", "").strip()
    new_username = data.get("new_username", "").strip()
    
    if not old_username or not new_username:
        return jsonify({"status": "error", "message": "닉네임이 올바르지 않습니다."}), 400
        
    config = load_config()
    if old_username not in config['accounts']:
        return jsonify({"status": "error", "message": "변경할 계정이 존재하지 않습니다."}), 404
        
    if new_username in config['accounts']:
        return jsonify({"status": "error", "message": "이미 존재하는 새로운 닉네임입니다."}), 400
        
    # config.json의 accounts 목록 업데이트
    idx = config['accounts'].index(old_username)
    config['accounts'][idx] = new_username
    
    # account_handles의 값 매핑 변경
    if "account_handles" in config:
        if old_username in config["account_handles"]:
            config["account_handles"][new_username] = config["account_handles"][old_username]
            del config["account_handles"][old_username]
            
    save_config(config)
    
    # 세션 파일 이름 변경
    safe_old = safe_session_name(old_username)
    safe_new = safe_session_name(new_username)
    old_session_file = os.path.join(SESSION_DIR, f"{safe_old}.json")
    new_session_file = os.path.join(SESSION_DIR, f"{safe_new}.json")
    
    if os.path.exists(old_session_file):
        try:
            os.rename(old_session_file, new_session_file)
            add_log(f"[System] 계정 세션 파일 명칭 변경 완료: {safe_old}.json -> {safe_new}.json")
        except Exception as e:
            add_log(f"[System] 계정 세션 파일 명칭 변경 오류: {e}")
            
    # queue.json 및 config.json 상의 매핑 데이터 일관성 유지
    queue_data = load_queue()
    updated_queue = False
    for row in queue_data:
        if row.get("account") == old_username:
            row["account"] = new_username
            updated_queue = True
    if updated_queue:
        save_queue(queue_data)
        add_log(f"[System] 예약 대기열의 계정명이 '{old_username}'에서 '{new_username}'으로 자동 업데이트되었습니다.")
        
    add_log(f"[System] 계정 명칭 변경 성공: {old_username} -> {new_username}")
    return jsonify({"status": "success"})

@app.route('/api/ai/rewrite', methods=['POST'])
def api_ai_rewrite():
    data = request.json
    content = data.get("content", "").strip()
    ai_option = data.get("ai", "OFF").strip()
    
    if not content:
        return jsonify({"status": "error", "message": "본문 내용이 없습니다."}), 400
        
    if ai_option == "OFF" or ai_option == "Free":
        return jsonify({"status": "success", "rewritten": content})
        
    config = load_config()
    api_key = None
    if ai_option == "GPT":
        api_key = config.get("openai_api_key")
    elif ai_option == "Gemini":
        api_key = config.get("gemini_api_key")
        
    if not api_key:
        return jsonify({"status": "error", "message": f"{ai_option} API 키가 설정되지 않았습니다."}), 400
        
    system_prompt = config.get("system_prompt", "")
    try:
        rewritten = rewrite_content(content, ai_option, api_key, system_prompt)
        return jsonify({"status": "success", "rewritten": rewritten})
    except Exception as e:
        return jsonify({"status": "error", "message": f"AI 변환 실패: {str(e)}"}), 500

@app.route('/api/login', methods=['POST'])
def handle_login():
    data = request.json
    username = data.get("username", "").strip()
    if not username:
        return jsonify({"status": "error", "message": "계정명이 누락되었습니다."}), 400
        
    uploader = ThreadsProUploader(session_dir=SESSION_DIR, log_callback=add_log)
    
    # 비동기 Playwright를 별도 스레드에서 구동하여 수동 로그인 팝업 활성화
    def run_login():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(uploader.run_manual_login(username))
        except Exception as e:
            add_log(f"[{username}] 로그인 창 구동 오류: {e}")
        finally:
            loop.close()
            
    threading.Thread(target=run_login, daemon=True).start()
    return jsonify({"status": "success", "message": "로그인 세션 창이 곧 표시됩니다."})

@app.route('/api/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "파일이 누락되었습니다."}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "선택된 파일이 없습니다."}), 400
        
    try:
        filename = file.filename.lower()
        if filename.endswith('.csv'):
            df = pd.read_csv(file, keep_default_na=False, encoding='utf-8-sig', lineterminator=None, quotechar='"')
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file, keep_default_na=False)
        else:
            return jsonify({"status": "error", "message": "지원하지 않는 파일 형식입니다. (CSV 또는 Excel만 가능)"}), 400
            
        headers = [str(c).strip().lower() for c in df.columns]
        
        content_col = -1
        comment_col = -1
        file_col = -1
        tag_col = -1
        topic_col = -1
        time_col = -1
        lang_col = -1
        ai_col = -1
        account_col = -1
        
        for idx, h in enumerate(headers):
            if "내용" in h or "content" in h:
                content_col = idx
            elif "댓글" in h or "comment" in h:
                comment_col = idx
            elif "파일" in h or "file" in h or "경로" in h:
                file_col = idx
            elif "태그" in h or "tag" in h:
                tag_col = idx
            elif "주제" in h or "topic" in h:
                topic_col = idx
            elif "시간" in h or "time" in h:
                time_col = idx
            elif "언어" in h or "lang" in h:
                lang_col = idx
            elif "ai" in h:
                ai_col = idx
            elif "계정" in h or "id" in h or "account" in h:
                account_col = idx
                
        if content_col == -1: content_col = 0
        if comment_col == -1 and len(headers) > 1: comment_col = 1
        if file_col == -1 and len(headers) > 2: file_col = 2
        if tag_col == -1 and len(headers) > 3: tag_col = 3
        
        has_topic = topic_col != -1
        offset = 1 if has_topic else 0
        
        if time_col == -1: time_col = 4 + offset if len(headers) > 4 + offset else -1
        if lang_col == -1: lang_col = 5 + offset if len(headers) > 5 + offset else -1
        if ai_col == -1: ai_col = 6 + offset if len(headers) > 6 + offset else -1
        if account_col == -1: account_col = 7 + offset if len(headers) > 7 + offset else -1
        
        data_rows = []
        for _, row in df.iterrows():
            row_list = list(row)
            if not row_list:
                continue
                
            content_val = str(row_list[content_col]).strip() if content_col < len(row_list) else ""
            comment_val = str(row_list[comment_col]).strip() if (comment_col != -1 and comment_col < len(row_list)) else ""
            file_val = str(row_list[file_col]).strip() if (file_col != -1 and file_col < len(row_list)) else ""
            tag_val = str(row_list[tag_col]).strip() if (tag_col != -1 and tag_col < len(row_list)) else ""
            topic_val = str(row_list[topic_col]).strip() if (topic_col != -1 and topic_col < len(row_list)) else ""
            time_val = str(row_list[time_col]).strip() if (time_col != -1 and time_col < len(row_list)) else ""
            lang_val = str(row_list[lang_col]).strip() if (lang_col != -1 and lang_col < len(row_list)) else "KO"
            
            raw_ai = str(row_list[ai_col]).strip() if (ai_col != -1 and ai_col < len(row_list)) else "OFF"
            if raw_ai in ("Free", "OFF", ""):
                raw_ai = "OFF"
                
            account_val = str(row_list[account_col]).strip() if (account_col != -1 and account_col < len(row_list)) else ""
            
            if not content_val and not comment_val and not file_val and not tag_val and not topic_val and not time_val and not account_val:
                continue
                
            # 만약 Content가 비어있고 이전 행이 존재한다면, 이는 이전 행의 댓글 줄바꿈 연장선으로 판단하여 병합
            if not content_val and data_rows:
                prev_row = data_rows[-1]
                if comment_val:
                    if prev_row["comment"]:
                        prev_row["comment"] += "\n" + comment_val
                    else:
                        prev_row["comment"] = comment_val
                # 다른 필드가 이전 행에 비어 있다면 채워주기
                if file_val and not prev_row["file"]:
                    prev_row["file"] = file_val
                if tag_val and not prev_row["tag"]:
                    prev_row["tag"] = tag_val
                if topic_val and not prev_row["topic"]:
                    prev_row["topic"] = topic_val
                if time_val and not prev_row["time"]:
                    prev_row["time"] = time_val
                if account_val and not prev_row["account"]:
                    prev_row["account"] = account_val
                continue
                
            data_rows.append({
                "content": content_val,
                "comment": comment_val,
                "file": file_val,
                "tag": tag_val,
                "topic": topic_val,
                "time": time_val,
                "lang": lang_val,
                "ai": raw_ai,
                "account": account_val,
                "status": "Pending"
            })
            
        return jsonify({"status": "success", "rows": data_rows})
    except Exception as e:
        return jsonify({"status": "error", "message": f"파일 파싱 실패: {str(e)}"}), 500

@app.route('/api/queue', methods=['GET', 'POST'])
def handle_queue():
    if request.method == 'POST':
        data = request.json  # 테이블의 전체 예약 행 리스트
        for row in data:
            if 'status' not in row:
                row['status'] = 'Pending'
        with queue_lock:
            save_queue(data)
        add_log("[System] 예약 대기열이 업데이트되었습니다.")
        return jsonify({"status": "success", "queue": data})
    else:
        with queue_lock:
            return jsonify(load_queue())

@app.route('/api/logs')
def stream_logs():
    """SSE를 활용한 실시간 로그 스트리밍 라우트"""
    def event_stream():
        # 최초 접속 시 기본 커넥션 유지용 더미
        yield "data: [System] 로그 연결 활성화\n\n"
        while True:
            try:
                # 큐에서 로그 꺼내기 (블로킹 대기)
                msg = log_queue.get(timeout=5)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                # 유휴 커넥션 유지용 킵얼라이브 전송
                yield ": keep-alive\n\n"
            except GeneratorExit:
                break
    return Response(event_stream(), mimetype="text/event-stream")

# --- 자동화 스케줄러 프로세스 ---
running_accounts = set()
running_accounts_lock = threading.Lock()
queue_lock = threading.Lock()

# 예약 시각이 지나도 실행을 허용하는 유예 시간(분).
# 같은 계정의 앞 작업 때문에 정각(분)을 놓친 예약이 영영 방치되는 문제를 막는다.
GRACE_MINUTES = 30

def parse_hhmm(value):
    """'HH:MM' 또는 'H:MM' 문자열을 자정 기준 분(minute)으로 변환. 형식이 아니면 None."""
    try:
        parts = str(value).strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (ValueError, TypeError):
        pass
    return None

def update_row_status(row, new_status):
    """queue.json을 다시 읽어 해당 행의 상태만 갱신.

    작업 시작 시점의 스냅샷을 통째로 저장하면 그 사이 사용자가 수정한
    대기열을 덮어쓰므로, 저장 직전에 파일을 다시 읽어 같은 행을 찾아
    상태만 바꾼다. (행 식별: 계정 + 시간 + 본문)
    """
    with queue_lock:
        current = load_queue()
        for r in current:
            if (r.get("account") == row.get("account")
                    and r.get("time") == row.get("time")
                    and r.get("content") == row.get("content")
                    and r.get("status") != new_status):
                r["status"] = new_status
                save_queue(current)
                return True
    return False

def scheduler_loop():
    global is_running
    add_log("[System] 백그라운드 스케줄러가 활성화되었습니다.")

    busy_log_minute = {}

    while is_running:
        try:
            now = datetime.datetime.now()
            now_str = now.strftime("%H:%M")
            now_minutes = now.hour * 60 + now.minute

            with queue_lock:
                queue_data = load_queue()
            config = load_config()

            for row in queue_data:
                if row.get("status") == "Pending":
                    row_minutes = parse_hhmm(row.get("time"))
                    if row_minutes is None:
                        continue

                    # 자정 넘김을 고려한 예약 시각 경과(분) 계산.
                    # 정각부터 GRACE_MINUTES 이내면 실행 대상 (앞 작업에 밀려 정각을 놓쳐도 실행됨)
                    elapsed = (now_minutes - row_minutes) % (24 * 60)
                    if elapsed > GRACE_MINUTES:
                        continue

                    account = row.get("account", "").strip()

                    # 동일 계정의 작업이 이미 실행 중인지 확인
                    with running_accounts_lock:
                        if account in running_accounts:
                            if busy_log_minute.get(account) != now_str:
                                add_log(f"[System] 대기: 계정 '{account}'의 이전 작업이 아직 실행 중입니다. 완료되는 대로 이어서 실행합니다.")
                                busy_log_minute[account] = now_str
                            continue
                        running_accounts.add(account)

                    try:
                        update_row_status(row, "Running")

                        content = row.get("content", "").strip()
                        comment = row.get("comment", "").strip()
                        files_str = row.get("file", "").strip()
                        ai_option = row.get("ai", "OFF")
                        tag_str = row.get("tag", "").strip()
                        topic = row.get("topic", "").strip()
                        
                        add_log(f"[System] 예약 작업 발행 시도 중... (계정: {account}, 시간: {now_str})")
                        
                        # 미디어 파일 경로 파싱 및 디렉토리/NFC/NFD 정상화 확장
                        media_paths = []
                        if files_str:
                            raw_paths = [p.strip(" '\",[]") for p in files_str.split(",") if p.strip(" '\",[]")]
                            post_index = queue_data.index(row)
                            import unicodedata
                            for r_path in raw_paths:
                                # 바탕화면(Desktop) 권한 오류를 방지하기 위해 프로그램 폴더 경로로 자동 변환
                                if "Desktop/thread_ing" in r_path:
                                    r_path = r_path.replace("Desktop/thread_ing", "thread_ing")
                                    
                                abs_path = os.path.abspath(r_path)
                                if not os.path.exists(abs_path):
                                    path_nfc = unicodedata.normalize('NFC', abs_path)
                                    path_nfd = unicodedata.normalize('NFD', abs_path)
                                    if os.path.exists(path_nfd):
                                        abs_path = path_nfd
                                    elif os.path.exists(path_nfc):
                                        abs_path = path_nfc
                                
                                if os.path.isdir(abs_path):
                                    try:
                                        subdirs = [os.path.join(abs_path, d) for d in os.listdir(abs_path) if os.path.isdir(os.path.join(abs_path, d))]
                                        prefix1 = f"{post_index}_"
                                        prefix2 = f"{post_index:02d}_"
                                        matched_subdir = None
                                        for sd in subdirs:
                                            name = os.path.basename(sd)
                                            if name.startswith(prefix1) or name.startswith(prefix2):
                                                matched_subdir = sd
                                                break
                                        
                                        source_dir = matched_subdir if matched_subdir else abs_path
                                        valid_exts = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.heic', '.mp4', '.mov', '.m4v')
                                        folder_files = []
                                        for f in os.listdir(source_dir):
                                            f_path = os.path.join(source_dir, f)
                                            if os.path.isfile(f_path) and f.lower().endswith(valid_exts):
                                                folder_files.append(f_path)
                                        folder_files.sort()
                                        media_paths.extend(folder_files)
                                    except Exception as dir_err:
                                        add_log(f"[System] 폴더 탐색 실패 ({abs_path}): {dir_err}")
                                        media_paths.append(abs_path)
                                else:
                                    media_paths.append(abs_path)
                            
                        # AI 리라이팅 적용
                        api_key = None
                        if ai_option == "GPT":
                            api_key = config.get("openai_api_key")
                        elif ai_option == "Gemini":
                            api_key = config.get("gemini_api_key")
                        system_prompt = config.get("system_prompt", "")
                        
                        final_content = rewrite_content(content, ai_option, api_key, system_prompt)
                        
                        # 해시태그 및 주제(Topic) 포맷팅 및 본문 하단 추가
                        tags_list = []
                        if tag_str:
                            for t in re.split(r'[,\s]+', tag_str):
                                t_clean = t.strip()
                                if t_clean:
                                    if not t_clean.startswith("#"):
                                        tags_list.append(f"#{t_clean}")
                                    else:
                                        tags_list.append(t_clean)
                                        
                        if topic:
                            topic_clean = topic.strip()
                            if topic_clean:
                                topic_tag = f"#{topic_clean}" if not topic_clean.startswith("#") else topic_clean
                                if topic_tag not in tags_list:
                                    tags_list.append(topic_tag)
                                    
                        if tags_list:
                            final_content = f"{final_content}\n\n{' '.join(tags_list)}"
                        
                        # Playwright 포스팅 진행
                        uploader = ThreadsProUploader(session_dir=SESSION_DIR, log_callback=add_log)
                        
                        def run_upload_task(row_ref, acc_key):
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            result_status = "Fail"
                            try:
                                success = loop.run_until_complete(
                                    uploader.post_to_threads(
                                        username=acc_key,
                                        headless=config.get("headless", False),
                                        content=final_content,
                                        media_paths=media_paths,
                                        comment_text=comment,
                                        topic_text=topic,
                                        publish_delay=config.get("publish_delay", 10)
                                    )
                                )
                                result_status = "Success" if success else "Fail"
                            except Exception as e:
                                add_log(f"[{acc_key}] 치명적인 에러 발생: {e}")
                            finally:
                                loop.close()
                                update_row_status(row_ref, result_status)
                                with running_accounts_lock:
                                    if acc_key in running_accounts:
                                        running_accounts.remove(acc_key)
                                add_log(f"[{acc_key}] 대기열 상태 업데이트 완료 ({result_status})")

                        # 개별 업로드는 백그라운드 스레드에서 구동하여 다음 대기열 체크를 막지 않게 함
                        threading.Thread(target=run_upload_task, args=(row, account), daemon=True).start()

                    except Exception as prep_err:
                        add_log(f"[System Error] 작업 준비 중 에러 발생: {prep_err}")
                        update_row_status(row, "Fail")
                        with running_accounts_lock:
                            if account in running_accounts:
                                running_accounts.remove(account)
                
                    
            time.sleep(5) # 5초 주기로 스캔
        except Exception as e:
            add_log(f"[System Error] 스케줄러 루프 에러: {e}")
            time.sleep(10)
            
    add_log("[System] 백그라운드 스케줄러가 중지되었습니다.")

@app.route('/api/start', methods=['POST'])
def handle_start():
    global is_running, scheduler_thread
    if scheduler_thread is not None and scheduler_thread.is_alive():
        is_running = True
        add_log("[System] 자동화 시작 신호 수신됨 (기존 스케줄러 활성 상태 유지).")
        return jsonify({"status": "success", "message": "자동화가 이미 구동 중입니다."})
        
    is_running = True
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()
    add_log("[System] 자동화 시작 신호 수신됨.")
    return jsonify({"status": "success", "message": "자동화가 시작되었습니다."})

@app.route('/api/stop', methods=['POST'])
def handle_stop():
    global is_running
    if is_running:
        is_running = False
        add_log("[System] 자동화 중지 신호 수신됨.")
        return jsonify({"status": "success", "message": "자동화가 중지되었습니다."})
    return jsonify({"status": "error", "message": "자동화가 구동 중이 아닙니다."}), 400

@app.route('/api/status', methods=['GET'])
def handle_status():
    global is_running
    return jsonify({"is_running": is_running})

if __name__ == "__main__":
    # Flask 서버 로컬 실행 (127.0.0.1:5001)
    app.run(host="127.0.0.1", port=5001, debug=True, use_reloader=False)
