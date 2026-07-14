#!/bin/bash
# 현재 스크립트 파일이 위치한 디렉토리로 이동
cd "$(dirname "$0")"

# 파이썬 가상환경 활성화
source venv/bin/activate

# 3초 후 기본 브라우저로 127.0.0.1:5001 열기
(sleep 3 && open "http://127.0.0.1:5001") &

# 프로그램 실행
python app.py
