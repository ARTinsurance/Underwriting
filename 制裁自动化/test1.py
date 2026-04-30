import os
import time
import io
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from docx import Document
from docx.shared import Inches
from PIL import Image

# 1. 读取Excel
excel_file = '制裁自动化\公司名称.xlsx'
df = pd.read_excel(excel_file)
company_names = df.iloc[:, 0].dropna().tolist()

# 2. 初始化Word文档
doc = Document()
doc.add_heading('公司制裁名单查询结果', 0)

# 3. 启动Selenium
options = webdriver.ChromeOptions()
# options.add_argument('--headless')  # 如需可视化操作可注释掉本行
options.add_argument('--window-size=1280,2000')  # 设置窗口大小
driver = webdriver.Chrome(options=options)

# 获取并打印实际的内容区域大小
size = driver.get_window_size()
print(f"浏览器内容区域尺寸: 宽={size['width']}, 高={size['height']}")

for name in company_names:
    driver.get('https://search-uk-sanctions-list.service.gov.uk/')
    time.sleep(2)  # 等待页面加载

    # 缩小页面到50%
    driver.execute_script("document.body.style.zoom='50%'")

    # 输入公司名并搜索
    search_box = driver.find_element(By.ID, 'search')
    search_box.clear()
    search_box.send_keys(name)
    search_box.send_keys(Keys.RETURN)
    time.sleep(3)  # 等待结果加载

    # -- 通过坐标截图 --
    # 1. 获取整个页面的截图到内存中
    png_data = driver.get_screenshot_as_png()
    img = Image.open(io.BytesIO(png_data))

    # 2. 定义截图区域 (left, top, right, bottom)
    #    请根据你的屏幕和浏览器窗口大小调整这些坐标。
    #    (0,0) 是左上角。
    crop_box = (400, 170, 1200, 800)  # 示例坐标，请自行修改
    cropped_img = img.crop(crop_box)

    # 3. 保存裁剪后的图片
    safe_name = "".join([c if c.isalnum() else "_" for c in name])
    screenshot_path = f'{safe_name}.png'
    cropped_img.save(screenshot_path)

    # 写入Word
    doc.add_heading(name, level=1)
    doc.add_picture(screenshot_path, width=Inches(5))

    # 可选：删除临时图片
    os.remove(screenshot_path)

doc.save('UK Sanction_Search.docx')
driver.quit()
print("全部完成，结果已保存到UK Sanction_Search.docx")
