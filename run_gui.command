#!/bin/bash
# 현재 스크립트 파일이 위치한 디렉토리로 이동
cd "$(dirname "$0")"

# 파이썬 가상환경 활성화
source venv/bin/activate

# GUI 프로그램 실행
python main.py
