#!/usr/bin/env python3
"""
修改用户密码的工具脚本
"""
import sys
sys.path.insert(0, '.')
exec(open('services/user_manager.py').read())

def change_admin_password():
    """修改admin密码"""
    um = UserManager()

    print("=" * 60)
    print("修改Admin密码")
    print("=" * 60)

    # 方式1: 直接在脚本中指定新密码
    old_password = 'admin'
    new_password = '你的新密码'  # 在这里修改新密码

    print(f"\n当前用户名: admin")
    print(f"旧密码: {old_password}")
    print(f"新密码: {new_password}")
    print("\n⚠️  如需修改新密码，请编辑此脚本第19行")

    confirm = input("\n确认修改密码? (yes/no): ").strip().lower()

    if confirm == 'yes':
        result = um.change_password('admin', old_password, new_password)

        if result:
            print("\n✅ 密码修改成功！")
            print(f"\n新的登录凭据:")
            print(f"  用户名: admin")
            print(f"  密码: {new_password}")
            print("\n请保存此密码！")
        else:
            print("\n❌ 密码修改失败！")
            print("可能原因：")
            print("  1. 旧密码错误")
            print("  2. 用户不存在")
    else:
        print("\n取消修改")

    print("=" * 60)

if __name__ == '__main__':
    change_admin_password()
