import os
from PIL import Image, ImageDraw, ImageFont
import textwrap
import sys
from multiprocessing import Pool, cpu_count

class NovelImageConverter:
    def __init__(self):
        self.possible_fonts = [
            "NanumGothicBold.ttf",    
            "malgunbd.ttf",           
            "gulim.ttc",              
            "C:/Windows/Fonts/malgunbd.ttf",
            "C:/Windows/Fonts/NanumGothicBold.ttf",
        ]
        
        self.font_path = None
        for font in self.possible_fonts:
            if os.path.exists(font):
                self.font_path = font
                break
                
        if not self.font_path:
            print("[경고] 한글 폰트를 찾을 수 없습니다.")
            sys.exit(1)
            
        self.font_size = 24
        self.line_spacing = 2.0
        self.paragraph_spacing = 3.0
        self.margin_left = 100
        self.margin_right = 100
        self.margin_top = 100
        self.margin_bottom = 150
        self.width = 1500  # 이미지 너비 증가
        self.lines_per_page = 25
        self.background_color = '#FFFEFC'

    def calculate_text_width(self, text, font):
        """주어진 텍스트의 픽셀 너비 계산"""
        return font.getlength(text)

    def process_line(self, line, font, max_width):
        """긴 줄을 적절히 분할"""
        if not line:
            return [line]
            
        text_width = self.calculate_text_width(line, font)
        available_width = max_width - self.margin_left - self.margin_right
        
        if text_width <= available_width:
            return [line]
            
        words = line.split()
        lines = []
        current_line = []
        current_width = 0
        
        for word in words:
            word_width = self.calculate_text_width(word + ' ', font)
            if current_width + word_width <= available_width:
                current_line.append(word)
                current_width += word_width
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_width = word_width
        
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines

    def process_text(self, text, font):
        """텍스트 전처리 - 원본 형식 유지"""
        lines = text.split('\n')
        processed_lines = []
        
        for line in lines:
            # 빈 줄이나 짧은 줄은 그대로 유지
            if not line.strip():
                processed_lines.append(line)
                continue
            
            # 긴 줄은 분할
            split_lines = self.process_line(line, font, self.width)
            processed_lines.extend(split_lines)
            
        return processed_lines

    def split_into_pages(self, lines):
        """줄 단위로 페이지 분할"""
        pages = []
        current_page = []
        
        for line in lines:
            if len(current_page) >= self.lines_per_page:
                pages.append('\n'.join(current_page))
                current_page = []
            current_page.append(line)
            
        if current_page:
            pages.append('\n'.join(current_page))
            
        return pages

    def create_image_from_text(self, text, output_path):
        try:
            font = ImageFont.truetype(self.font_path, self.font_size)
        except Exception as e:
            print(f"[오류] 폰트 로드 실패: {str(e)}")
            return

        # 텍스트 처리
        lines = self.process_text(text, font)
        
        # 이미지 높이 계산
        text_height = len(lines) * int(self.font_size * self.line_spacing)
        height = self.margin_top + text_height + self.margin_bottom
        height = max(height, 800)
        
        # 이미지 생성
        img = Image.new('RGB', (self.width, height), self.background_color)
        draw = ImageDraw.Draw(img)
        
        # 텍스트 그리기
        y = self.margin_top
        for line in lines:
            # 각 줄의 실제 너비 확인
            text_width = self.calculate_text_width(line, font)
            if text_width > (self.width - self.margin_left - self.margin_right):
                print(f"[경고] 줄이 너무 깁니다: {line[:50]}...")
            
            draw.text((self.margin_left, y), line, font=font, fill='black')
            y += int(self.font_size * self.line_spacing)
        
        img.save(output_path, 'JPEG', quality=95, optimize=True)

def process_file(args):
    converter, txt_path, images_folder = args
    basename = os.path.splitext(os.path.basename(txt_path))[0]
    
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(txt_path, 'r', encoding='cp949') as f:
                content = f.read()
        except UnicodeDecodeError:
            print(f"[오류] {txt_path} 파일의 인코딩을 확인할 수 없습니다.")
            return
    
    # 폰트 로드
    font = ImageFont.truetype(converter.font_path, converter.font_size)
    
    # 텍스트 처리
    processed_lines = converter.process_text(content, font)
    pages = converter.split_into_pages(processed_lines)
    
    # 이미지 생성
    for i, page_text in enumerate(pages, 1):
        image_path = os.path.join(images_folder, f'{basename}_p{i:03d}.jpg')
        converter.create_image_from_text(page_text, image_path)
    
    print(f"  > {basename} 완료 ({len(pages)} 페이지)")

def convert_novel_folder(novel_folder):
    converter = NovelImageConverter()
    
    tasks = []
    for episode_folder in os.listdir(novel_folder):
        episode_path = os.path.join(novel_folder, episode_folder)
        if not os.path.isdir(episode_path):
            continue
            
        txt_files = [f for f in os.listdir(episode_path) if f.endswith('.txt')]
        if not txt_files:
            continue
            
        images_folder = os.path.join(episode_path, 'images')
        os.makedirs(images_folder, exist_ok=True)
        
        for txt_file in txt_files:
            txt_path = os.path.join(episode_path, txt_file)
            tasks.append((converter, txt_path, images_folder))
    
    num_processes = max(1, cpu_count() - 1)
    print(f"\n[정보] {num_processes}개의 프로세스로 변환을 시작합니다...")
    
    with Pool(num_processes) as pool:
        pool.map(process_file, tasks)

def main():
    print("\n소설 텍스트 이미지 변환기")
    print("=" * 40)
    folder_path = input("\n소설 최상위 폴더 경로를 입력하세요: ").strip()
    
    if not os.path.exists(folder_path):
        print("\n[오류] 폴더를 찾을 수 없습니다!")
        return
        
    try:
        convert_novel_folder(folder_path)
        print("\n[완료] 모든 변환 작업이 끝났습니다!")
    except Exception as e:
        print(f"\n[오류] 변환 중 문제가 발생했습니다: {str(e)}")

if __name__ == "__main__":
    main()
