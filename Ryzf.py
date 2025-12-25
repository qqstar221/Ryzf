import argparse
import requests
import urllib.parse
import base64
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from colorama import init, Fore
import time

init(autoreset=True)

def print_startup_art():
    startup_art = f"""{Fore.YELLOW}
    ___       ___       ___       ___   
   |   |     |   |     |   |     |   |  
       |_R__|     |__R_|    |__R_|    |__R_|  
  _______   _______   _______   _______ 
 |       | |       | |       | |       |
 |   R   | |   y   | |   z   | |   f   |
 |_______| |_______| |_______| |_______|
                                        
[ Ryzf -  Fuzz Tool v1.0 ]
{Fore.RESET}"""
    print(startup_art)
    time.sleep(0.5)  



def remove_duplicates(lst):
    """保持列表原始顺序的去重"""
    seen = set()
    result = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_arguments():
    """解析命令行参数（-u必填）"""
    parser = argparse.ArgumentParser(
        description='你也想让小大俊为你测试吗？'
    )
    parser.add_argument('-d', help='指定脚本同目录下的自定义字典文件名（不填则用内置字典）')
    parser.add_argument('-u', required=True, help='目标URL（必须含"FUZZ"替换标记，例：http://xxx/index.php?url=FUZZ）')
    parser.add_argument('-t', help='结果保存的TXT文件路径（不填则不保存）')
    parser.add_argument('-p', help='HTTP代理（格式：ip:port，例：127.0.0.1:8080）')
    parser.add_argument('-l', type=int, default=5, help='线程数（1-10，默认5）')
    parser.add_argument('-e', action='store_true', help='仅测试编码后的payload（需选择编码方式）')
    
    args = parser.parse_args()


    if not (1 <= args.l <= 10):
        print("❌ 线程数必须在1-10之间")
        sys.exit(1)
    

    if 'FUZZ' not in args.u:
        print("❌ 目标URL必须包含'FUZZ'作为替换标记")
        sys.exit(1)
    
    return args


def load_dictionary(dict_filename):
    """加载字典（内置字典固定顺序：特殊字符→小写a-z→大写A-Z）"""
    special_chars = [
        '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '-', '_', '+', '=',
        '[', ']', '{', '}', '|', '\\', ':', ';', '\'', '"', ',', '.', '/', '?',
        '<', '>', '~', '`', ' '
    ]
    lower_chars = [chr(ord('a') + i) for i in range(26)]
    upper_chars = [chr(ord('A') + i) for i in range(26)]
    
    default_chars = special_chars + lower_chars + upper_chars
    default_chars = remove_duplicates(default_chars)

    if dict_filename is None:
        print(f"✅ 内置字典顺序：特殊字符→小写a-z→大写A-Z，共{len(default_chars)}个原字符")
        return default_chars
    
    try:
        with open(dict_filename, 'r', encoding='utf-8') as f:
            raw_chars = [line.strip() for line in f if line.strip()]
        raw_chars = remove_duplicates(raw_chars)
        print(f"✅ 自定义字典（同目录）按行顺序加载，共{len(raw_chars)}个原字符")
        return raw_chars
    except FileNotFoundError:
        print(f"❌ 错误：同目录未找到字典文件{dict_filename}")
        sys.exit(1)


def get_encoding_func():
    """交互选择编码方式"""
    print("\n=== 选择编码方式 ===")
    print("1. URL编码（例：!→%21）")
    print("2. Unicode编码（例：!→\\u0021）")
    print("3. HTML编码（例：!→&#33;）")
    print("4. Base64编码（例：!→IQ==）")
    print("5. ASCII编码（例：!→33）")
    
    while True:
        choice = input("输入选择（1-5）：").strip()
        if choice == '1':
            
            return lambda x: urllib.parse.quote(x, safe=''), "URL编码"
        elif choice == '2':
            
            return lambda x: ''.join([f'\\u{ord(c):04x}' for c in x]), "Unicode编码"
        elif choice == '3':
            
            return lambda x: ''.join([f'&#{ord(c)};' for c in x]), "HTML编码"
        elif choice == '4':
            
            return lambda x: base64.b64encode(x.encode('utf-8')).decode('utf-8'), "Base64编码"
        elif choice == '5':
            
            return lambda x: str(ord(x)) if len(x) == 1 else ''.join([str(ord(c)) for c in x]), "ASCII编码"
        else:
            print("❌ 输入错误，请重新选择！")


def fuzz_single_payload(test_payload, target_url, proxies):
    """单个payload测试：返回（状态码、字符数、响应时间、测试状态）"""
    req_url = target_url.replace('FUZZ', test_payload)
    start_time = time.time()
    
    try:
        response = requests.get(
            req_url,
            proxies=proxies,
            timeout=10,
            verify=False,
            allow_redirects=False
        )
        resp_time = round(time.time() - start_time, 2)
        return (response.status_code, len(response.text), resp_time, "成功")
    except requests.exceptions.ConnectTimeout:
        resp_time = round(time.time() - start_time, 2)
        return ("N/A", "N/A", resp_time, "失败：连接超时")
    except requests.exceptions.ConnectionError:
        resp_time = round(time.time() - start_time, 2)
        return ("N/A", "N/A", resp_time, "失败：连接拒绝")
    except Exception as e:
        resp_time = round(time.time() - start_time, 2)
        return ("N/A", "N/A", resp_time, f"失败：{str(e)[:20]}")


def main():
    print_startup_art()
    args = parse_arguments()
    
    
    proxies = None
    if args.p:
        proxies = {'http': f'http://{args.p}', 'https': f'https://{args.p}'}
        print(f"✅ 使用代理：{args.p}")
    
    
    raw_chars = load_dictionary(args.d)
    
    # 生成测试队列：-e仅测编码payload，无-e仅测原码
    test_queue = []
    test_type = "仅原码"
    if args.e:
        encode_func, test_type = get_encoding_func()
        
        test_queue = [ (char, encode_func(char)) for char in raw_chars ]
    else:
        
        test_queue = [ (char, char) for char in raw_chars ]
    print(f"✅ 测试队列总数：{len(test_queue)}（{test_type}）")
    
    # 启动
    print(f"\n✅ 小大俊正在工作！线程数：{args.l}")
    print("="*85)
    print(f"{'ID':<10} {'Response':<8} {'Chars':<6} {'Time(s)':<8} {'Payload(原码)':<15} {'Encode(测试值)':<25}")
    print("="*85)

    results = []
    with ThreadPoolExecutor(max_workers=args.l) as executor:
        futures = [
            executor.submit(fuzz_single_payload, item[1], args.u, proxies)
            for item in test_queue
        ]
        
        
        for idx, (future, (raw_char, test_payload)) in enumerate(zip(futures, test_queue), 1):
            status, chars, resp_time, stat = future.result()
            print(f"{idx:08d}: {status:<8} {chars:<6} {resp_time:<8} {raw_char:<15} {test_payload:<25}")
            results.append( (idx, status, chars, resp_time, raw_char, test_payload, stat) )

    print("="*85 + "\n✅ 报告！小大俊圆满完成任务！")

    # 保存结果
    if args.t:
        try:
            with open(args.t, 'w', encoding='utf-8') as f:
                f.write(f"=== 测试结果 ===\n")
                f.write(f"目标URL：{args.u}\n")
                f.write(f"测试类型：{test_type}\n")
                f.write(f"测试总数：{len(test_queue)}\n")
                f.write(f"线程数：{args.l}\n")
                f.write(f"代理：{args.p if args.p else '无'}\n")
                f.write("-" * 85 + "\n")
                f.write(f"{'ID':<10} {'Response':<8} {'Chars':<6} {'Time(s)':<8} {'Payload(原码)':<15} {'Encode(测试值)':<25} {'状态'}\n")
                f.write("-" * 85 + "\n")
                for res in results:
                    idx, status, chars, resp_time, raw_char, test_payload, stat = res
                    f.write(f"{idx:08d}: {status:<8} {chars:<6} {resp_time:<8} {raw_char:<15} {test_payload:<25} {stat}\n")
            print(f"✅ 结果已保存到：{args.t}")
        except Exception as e:
            print(f"❌ 保存失败：{e}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断，程序退出")
        sys.exit(0)


