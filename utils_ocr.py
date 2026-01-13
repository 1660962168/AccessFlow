import os
import uuid
import cv2
import requests
import threading

# 这个类现在只负责发 HTTP 请求，不加载任何 Paddle 库
class OcrDetector:
    def __init__(self):
        # 指向刚才创建的 OCR Server 地址
        self.api_url = "http://127.0.0.1:5001/ocr"
        self.is_ready = True # 假设服务是开启的
        self.lock = threading.Lock()
        
        # 简单测试一下服务是否在线（可选）
        print("[Client] OCR 客户端已就绪，连接目标: 5001端口")

    def recognize_temp_frame(self, frame_img, temp_folder):
        """
        接收内存图片(numpy array)，存为临时文件，发送给服务端，然后删除
        """
        temp_name = f"temp_ocr_{uuid.uuid4().hex}.jpg"
        temp_path = os.path.join(temp_folder, temp_name)
        
        # 确保是用绝对路径，防止两个进程的工作目录不一致导致找不到文件
        abs_temp_path = os.path.abspath(temp_path)
        
        res = None
        try:
            cv2.imwrite(abs_temp_path, frame_img)
            res = self.recognize(abs_temp_path)
        except Exception as e:
            print(f"[OCR Client Error] {e}")
        finally:
            if os.path.exists(abs_temp_path):
                try:
                    os.remove(abs_temp_path)
                except:
                    pass
        return res

    def recognize(self, image_path):
        """
        发送文件路径给 OCR Server
        """
        if not os.path.exists(image_path):
            return None

        try:
            # 传入绝对路径
            abs_path = os.path.abspath(image_path)
            
            # 发送 HTTP POST 请求
            response = requests.post(
                self.api_url, 
                json={'path': abs_path}, 
                timeout=3 # 设置超时，避免卡死主程序
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success') and result.get('data'):
                    return result['data']
            else:
                # 只有在调试时打印，避免刷屏
                # print(f"[OCR Client] Server returned {response.status_code}")
                pass
                
        except requests.exceptions.ConnectionError:
            print("[OCR Client Warning] 无法连接到 OCR 服务 (端口 5001)，请检查 ocr_server.py 是否运行。")
        except Exception as e:
            print(f"[OCR Client Error] {e}")
            
        return None