"""allow skipped in notification status

Revision ID: f900bca402e9
Revises: 07fbb1c5f2d2
Create Date: 2026-11-01 13:00:45.797831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f900bca402e9'
down_revision: Union[str, None] = '07fbb1c5f2d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('check_notification_status_valid', 'notifications', type_='check')
    op.create_check_constraint(
        'check_notification_status_valid',
        'notifications',
        "status IN ('pending', 'sent', 'failed', 'skipped')"
    )


def downgrade() -> None:
    op.drop_constraint('check_notification_status_valid', 'notifications', type_='check')
    op.create_check_constraint(
        'check_notification_status_valid',
        'notifications',
        "status IN ('pending', 'sent', 'failed')"
    )
