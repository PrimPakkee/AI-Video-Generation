#!/usr/bin/env python3
"""
Reset AI Reviews Script - v0.4.6.5

批量清除失败或生成中的 AI Review 记录

功能:
- 列出所有 failed/generating 状态的 AI Review
- 允许用户确认后删除这些记录
- 打印统计信息

Usage:
    python scripts/reset_ai_reviews.py                    # 列出所有 failed/generating 记录
    python scripts/reset_ai_reviews.py --delete-failed    # 删除所有 failed 记录
    python scripts/reset_ai_reviews.py --delete-all       # 删除所有 failed + generating 记录
    python scripts/reset_ai_reviews.py --yes              # 跳过确认,直接执行
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from web.db.models import Base, PromptReview
from web.config import get_database_url


def get_db_session():
    """创建数据库会话"""
    database_url = get_database_url()
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def list_reviews(db):
    """列出所有 failed/generating 状态的 review"""
    print("\n" + "=" * 80)
    print("AI Review 状态统计")
    print("=" * 80)

    # 统计各状态数量
    status_counts = {}
    for status in ['failed', 'generating', 'completed', 'stale']:
        count = db.query(PromptReview).filter(PromptReview.status == status).count()
        status_counts[status] = count

    print("\n当前数据库中的 AI Review 记录:")
    print(f"  - Completed: {status_counts['completed']}")
    print(f"  - Generating: {status_counts['generating']}")
    print(f"  - Failed: {status_counts['failed']}")
    print(f"  - Stale: {status_counts['stale']}")
    print(f"  - Total: {sum(status_counts.values())}")

    # 列出 failed 记录详情
    if status_counts['failed'] > 0:
        print(f"\n{'=' * 80}")
        print(f"Failed AI Reviews ({status_counts['failed']} records):")
        print(f"{'=' * 80}")

        failed_reviews = db.query(PromptReview).filter(
            PromptReview.status == 'failed'
        ).order_by(PromptReview.updated_at.desc()).all()

        for idx, review in enumerate(failed_reviews, 1):
            error_msg = getattr(review, 'error_message', None) or 'No error message'
            print(f"\n{idx}. Review ID: {review.id}")
            print(f"   History ID: {review.history_id}")
            print(f"   Schema: {review.review_schema_version}")
            print(f"   Updated: {review.updated_at}")
            print(f"   Error: {error_msg[:100]}...")

    # 列出 generating 记录详情
    if status_counts['generating'] > 0:
        print(f"\n{'=' * 80}")
        print(f"Generating AI Reviews ({status_counts['generating']} records):")
        print(f"{'=' * 80}")

        generating_reviews = db.query(PromptReview).filter(
            PromptReview.status == 'generating'
        ).order_by(PromptReview.updated_at.desc()).all()

        for idx, review in enumerate(generating_reviews, 1):
            print(f"\n{idx}. Review ID: {review.id}")
            print(f"   History ID: {review.history_id}")
            print(f"   Schema: {review.review_schema_version}")
            print(f"   Updated: {review.updated_at}")
            print(f"   Note: May be stuck (check if > 5 minutes old)")

    print("\n" + "=" * 80)

    return status_counts


def delete_reviews(db, delete_failed=False, delete_generating=False, confirm=True):
    """删除指定状态的 review 记录"""

    if not delete_failed and not delete_generating:
        print("⚠️  No deletion mode specified. Use --delete-failed or --delete-all")
        return

    statuses_to_delete = []
    if delete_failed:
        statuses_to_delete.append('failed')
    if delete_generating:
        statuses_to_delete.append('generating')

    # 统计要删除的记录
    reviews_to_delete = db.query(PromptReview).filter(
        PromptReview.status.in_(statuses_to_delete)
    ).all()

    count = len(reviews_to_delete)

    if count == 0:
        print(f"✅ No {'/'.join(statuses_to_delete)} reviews to delete.")
        return

    print(f"\n{'=' * 80}")
    print(f"准备删除 {count} 条记录 (status: {', '.join(statuses_to_delete)})")
    print(f"{'=' * 80}")

    # 确认
    if confirm:
        response = input(f"\n确认删除这 {count} 条记录? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("❌ 操作已取消")
            return

    # 执行删除
    print(f"\n🗑️  正在删除...")
    deleted_count = 0
    for review in reviews_to_delete:
        db.delete(review)
        deleted_count += 1

    db.commit()

    print(f"✅ 已删除 {deleted_count} 条记录")


def main():
    """主函数"""
    args = sys.argv[1:]

    # 解析参数
    delete_failed = '--delete-failed' in args or '--delete-all' in args
    delete_generating = '--delete-all' in args
    skip_confirm = '--yes' in args or '-y' in args

    # 创建数据库会话
    db = get_db_session()

    try:
        # 列出当前状态
        status_counts = list_reviews(db)

        # 执行删除操作
        if delete_failed or delete_generating:
            delete_reviews(
                db,
                delete_failed=delete_failed,
                delete_generating=delete_generating,
                confirm=not skip_confirm
            )

            # 再次列出状态
            print("\n删除后的状态:")
            list_reviews(db)
        else:
            print("\n💡 提示:")
            print("   - 删除所有 failed 记录: python scripts/reset_ai_reviews.py --delete-failed")
            print("   - 删除所有 failed + generating 记录: python scripts/reset_ai_reviews.py --delete-all")
            print("   - 跳过确认: python scripts/reset_ai_reviews.py --delete-failed --yes")

    finally:
        db.close()


if __name__ == "__main__":
    main()
