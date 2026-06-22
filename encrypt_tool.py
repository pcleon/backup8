# -*- coding: utf-8 -*-
"""Fernet 对称加密辅助工具。

提供在本地生成对称密钥（ENCRYPTION_KEY）以及加密敏感用户名密码的功能。
支持命令行参数运行以及安全交互式模式运行（防止密码在 Bash 终端历史记录中泄露）。
"""

import getpass
import sys
from cryptography.fernet import Fernet


def generate_key() -> str:
    """生成一个新的 32 字节 Base64 编码的 Fernet 对称密钥。

    Returns:
        str: 密钥字符串。
    """
    return Fernet.generate_key().decode()


def encrypt_text(key: str, plaintext: str) -> str:
    """使用指定的 Fernet 密钥加密明文。

    Args:
        key (str): 32 字节 Base64 编码的 Fernet 密钥。
        plaintext (str): 需要加密的明文字符串。

    Returns:
        str: 加密后的密文。

    Raises:
        ValueError: 密钥格式非法或加密失败时抛出。
    """
    try:
        f = Fernet(key.strip().encode())
        ciphertext = f.encrypt(plaintext.encode()).decode()
        return ciphertext
    except Exception as e:
        raise ValueError(f"Fernet 加密失败，请检查密钥是否为合法的 32 字节 base64 格式。错误: {str(e)}")


def interactive_mode() -> None:
    """交互式安全加密模式。

    引导用户输入密钥和密码，利用 getpass 隐藏输入以防 Bash 历史记录泄露敏感信息。
    """
    print("====================================================")
    print("      MySQL自动备份系统 - 敏感配置安全加密小工具")
    print("====================================================")

    # 1. 获取密钥
    key_input = input("1. 请输入您的 Fernet 密钥 (回车将自动生成新密钥): ").strip().strip("'\"")
    if not key_input:
        key_input = generate_key()
        print("   [提示] 已自动为您生成新密钥:")
        print(f"   ENCRYPTION_KEY={key_input}")
        print("   (请将该密钥复制保存到您的 .env 文件中)")

    # 2. 验证密钥格式
    try:
        Fernet(key_input.encode())
    except Exception:
        print("\n[错误] 输入的密钥格式不正确，必须是 32 字节 Base64 编码格式！")
        sys.exit(1)

    # 3. 安全获取明文字符
    # 使用 getpass.getpass 安全输入，终端不会回显，防止旁观者窥视
    print("\n2. 请输入您需要加密的明文字符串 (如数据库密码/SSH账号等，输入过程已安全隐藏):")
    plaintext = getpass.getpass("   明文字符串: ")
    if not plaintext:
        print("[错误] 明文字符串不能为空！")
        sys.exit(1)

    # 4. 执行加密并输出
    try:
        ciphertext = encrypt_text(key_input, plaintext)
        print("\n=================== [加密结果] ===================")
        print(f"加密密文: {ciphertext}")
        print("====================================================")
        print("请将此密文直接替换填入您的 .env 配置文件中。")
    except Exception as e:
        print(f"\n[错误] 加密失败: {str(e)}")
        sys.exit(1)


def main() -> None:
    """脚本执行主入口。

    如果没有命令行参数，则自动进入交互式安全输入模式；
    若有参数，则按照命令行传参执行。
    """
    # 无命令行参数时，进入对运维友好的安全交互式模式
    if len(sys.argv) < 2:
        interactive_mode()
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "genkey":
        key = generate_key()
        print(f"生成的 ENCRYPTION_KEY: {key}")
        print("请将该密钥复制保存到您的 .env 文件中：ENCRYPTION_KEY=<密钥>")
    elif cmd == "encrypt":
        if len(sys.argv) < 4:
            print("错误: 缺少加密所需的 KEY 和明文字符串。")
            print("用法: python3 encrypt_tool.py encrypt <KEY> <明文字符串>")
            sys.exit(1)
        key = sys.argv[2]
        plaintext = sys.argv[3]
        try:
            ciphertext = encrypt_text(key, plaintext)
            print(f"原始明文: {plaintext}")
            print(f"加密密文: {ciphertext}")
            print("请将上述密文贴入您的 .env 配置文件中对应位置。")
        except Exception as e:
            print(f"执行失败: {str(e)}")
            sys.exit(1)
    else:
        print(f"未知指令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
