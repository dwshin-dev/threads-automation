import asyncio
import os
import sys
import random
from uploader import ThreadsProUploader

async def main():
    session_dir = os.path.abspath("sessions")
    print(f"Using session directory: {session_dir}")
    
    session_file = os.path.join(session_dir, "2.json")
    if not os.path.exists(session_file):
        print(f"Error: Session file {session_file} does not exist!")
        sys.exit(1)
        
    uploader = ThreadsProUploader(session_dir=session_dir, log_callback=print)
    
    random_id = random.randint(1000, 9999)
    test_content = f"자동화 최종 완성 검증 테스트 본문 #{random_id}"
    test_comment = f"자동화 최종 완성 검증 테스트 댓글 #{random_id}\n링크: https://www.coupang.com"
    test_topic = "테스트주제"
    
    # 해시태그 포맷팅 검증용 수동 태그 추가 (본문에 합쳐지는 방식 검증)
    tag_str = "태그원, 태그투"
    formatted_tags = []
    for t in tag_str.split(","):
        t_clean = t.strip()
        if t_clean:
            if not t_clean.startswith("#"):
                formatted_tags.append(f"#{t_clean}")
            else:
                formatted_tags.append(t_clean)
    if formatted_tags:
        test_content = f"{test_content}\n\n{' '.join(formatted_tags)}"
    
    print(f"Starting test run with content: '{test_content}' and topic: '{test_topic}'")
    success = await uploader.post_to_threads(
        username="3",
        headless=False,
        content=f"일본 과자 이거 믿먹해봐..\n개존맛탱 #포스트인젝션테스트_{random_id}",
        media_paths=["/Users/hwlee/thread_ing/스레드 이미지/1_뉴욕쿠키/1.jpeg"],
        comment_text=f"이거 진짜 맛있는데 꼭 한번 먹어봐!!\n▶️정보는 아래 링크에!◀️\nhttps://www.google.com/search?q=test_{random_id}",
        topic_text="간식",
        publish_delay=10
    )
    print(f"post_to_threads returned: {success}")

if __name__ == "__main__":
    asyncio.run(main())
