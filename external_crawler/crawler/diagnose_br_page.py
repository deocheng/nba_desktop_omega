"""
诊断 BR 球员页面 HTML 结构
检查体重数据在页面中的位置
"""
import requests
from bs4 import BeautifulSoup
import re

# 测试一个已知球员
player_id = 'abrines01'  # Alex Abrines
url = f"https://www.basketball-reference.com/players/a/{player_id}.html"

print(f"=== 诊断 BR 球员页面 ===\n")
print(f"URL: {url}\n")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    
    print(f"✅ 页面获取成功 (HTTP {response.status_code})")
    print(f"   页面大小: {len(response.text)} 字符\n")
    
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 1. 搜索 "Weight" 关键词
    print('1. 搜索 "Weight" 关键词:')
    weight_count = response.text.lower().count('weight')
    print(f"   页面中包含 'weight' 的次数: {weight_count}")
    
    if weight_count > 0:
        # 找到包含 weight 的片段
        import re
        matches = re.findall(r'.{0,50}weight.{0,50}', response.text, re.IGNORECASE)
        print(f"   样本 (前3个):")
        for i, match in enumerate(matches[:3]):
            print(f"   {i+1}. {match.strip()}")
    
    # 2. 检查 meta 标签
    print('\n2. 检查 meta 标签:')
    meta_tags = soup.find_all('li')
    for i, tag in enumerate(meta_tags[:20]):
        text = tag.get_text()
        if 'weight' in text.lower() or 'height' in text.lower():
            print(f"   找到: {text.strip()}")
    
    # 3. 检查 JSON-LD 数据
    print('\n3. 检查 JSON-LD 数据:')
    script_tags = soup.find_all('script', type='application/ld+json')
    print(f"   找到 {len(script_tags)} 个 JSON-LD 标签")
    
    for i, script in enumerate(script_tags):
        try:
            import json
            data = json.loads(script.string)
            if isinstance(data, dict):
                if 'weight' in str(data).lower():
                    print(f"   JSON-LD {i+1} 包含 weight 数据:")
                    print(f"   {json.dumps(data, indent=2)[:500]}")
        except:
            pass
    
    # 4. 保存 HTML 样本（前2000字符）
    print('\n4. HTML 样本 (前2000 字符):')
    print(response.text[:2000])
    
    # 5. 寻找球员信息表格
    print('\n5. 寻找球员信息表格:')
    tables = soup.find_all('table')
    print(f"   找到 {len(tables)} 个表格")
    
    # 寻找包含球员信息的 div
    info_divs = soup.find_all('div', class_=re.compile(r'info|player|bio'))
    print(f"   找到 {len(info_divs)} 个信息 div")
    
    for div in info_divs[:3]:
        print(f"   {div.get_text()[:200]}")
    
except Exception as e:
    print(f"❌ 错误: {e}")
